"""
Sélection du jour sur le passé (diagnostic, décision T18) : chaque séance, 0 à 3 stratégies de fin de journée
(gardées une nuit au plus) choisies sur leurs résultats déjà connus (dernières 24 h, puis 3 dernières séances), si
le marché est en bonne forme à 14 h 45 ; au plus 7 actions en tout, prises en tête de leurs listes, hors actions qui
publient probablement leurs résultats pendant la nuit et hors secteurs en baisse ce jour-là (core/selection.py).

Listes, heures d'achat et de vente, prix : ceux des tests des stratégies (backtest_strategies.py), relus du cache.
Garde-fous du jour : largeur du marché à 14 h 45 (barres en cache des tests), VIXY depuis l'ouverture (lu ici).

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.selection_backtest --years 2024,2025
"""

import argparse
import json
import multiprocessing
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone

from core.performance_metrics import summary
from core.selection import (SelectionRules, breadth, choose_stocks, day_return, likely_reporting, market_ok,
                            pick_strategies, sector_trends)
from infra import sec
from infra.alpaca_api import AlpacaReader
from infra.cache import CACHE_DIR, cached
from infra.http import FetchError
from infra.trace import RUNS_DIR, TraceError, committed_git_sha
from research.algorithms.reprise_apres_baisse import backtest_strategies as bt
from research.algorithms.reprise_apres_baisse.run import FAMILY, NEW_YORK, STRATEGIES

FEAR_SYMBOL = "VIXY"          # fonds coté qui suit l'indice de peur (VIX), servi par Alpaca
GUARD_MINUTES = 315           # garde-fous lus à 14 h 45 (New York), la première décision des stratégies candidates
SELECTION_DIR = RUNS_DIR / FAMILY / "selection"
WORKERS = 5


def candidates():
    """Stratégies de fin de journée gardées une nuit au plus (décision à 14 h 45 ou plus tard)."""
    return [s for s in STRATEGIES if s.sale_offset <= 1 and s.overnight
            and min(c.decision_minutes for c in s.criteria().values()) >= GUARD_MINUTES]


def _latest_days(strategy, label):
    latest = None
    for path in sorted((RUNS_DIR / strategy.storage / "backtests").glob("b[0-9][0-9][0-9]/results.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("label") == label and result.get("top") is None:
            latest = result
    return {} if latest is None else {r["date"]: r for r in latest["days"]}


def _cached_prices(day, prefix):
    """Barres en cache des tests (ouverture_15min_*, avant_1445_*) : symbole -> (premier prix, dernier prix)."""
    paths = sorted((CACHE_DIR / "backtest_strategies" / day).glob(f"{prefix}_*.pkl"), key=lambda p: -p.stat().st_size)
    if not paths:
        return None
    bars = pickle.loads(paths[0].read_bytes()).sort_values("timestamp")
    return {s: (b["open"].iloc[0], b["close"].iloc[-1]) for s, b in bars.groupby("symbol")}


_CONTEXT = {}


def _init(history, lists, sessions, healthy, domains, releases, rules, filters):
    bt._share_rate_limit()
    _CONTEXT.update(history=history, lists=lists, sessions=sessions, healthy=healthy, domains=domains,
                    releases=releases, alpaca=AlpacaReader(), by_id={s.id: s for s in STRATEGIES}, rules=rules,
                    filters=filters)


def _one_day(day):
    """Choix et résultat de la séance day (dans un processus du pool)."""
    alpaca, sessions, rules = _CONTEXT["alpaca"], _CONTEXT["sessions"], _CONTEXT["rules"]
    index = {d: i for i, (d, _, _) in enumerate(sessions)}
    i = index[date.fromisoformat(day)]
    session_day, open_at, close_at = sessions[i]
    market_open, market_close = bt._utc(session_day, open_at), bt._utc(session_day, close_at)
    sale_day = sessions[i + 1][0]
    guard_time = market_open + timedelta(minutes=GUARD_MINUTES)

    # Résultats connus à 14 h 45 : séances d'achat jusqu'à la veille (ventes de nuit faites ce matin).
    history = {c: [(d, r) for d, r in results if d < day][-10:] for c, results in _CONTEXT["history"].items()}
    picks = pick_strategies(history, rules)

    # Garde-fous du jour.
    opens, late = _cached_prices(day, "ouverture_15min"), _cached_prices(day, "avant_1445")
    width = None if not opens or not late else breadth({s: v[0] for s, v in opens.items()}, {s: v[1] for s, v in late.items()})
    fear = cached(f"selection/{day}/vixy_1445", lambda: alpaca.bars([FEAR_SYMBOL], "1Min", market_open, guard_time))
    fear_rise = None if fear.empty else float(fear.sort_values("timestamp")["close"].iloc[-1] / fear.sort_values("timestamp")["open"].iloc[0] - 1)
    ok, reason = market_ok(_CONTEXT["healthy"].get(day), width, fear_rise, rules)
    if not ok:
        picks = []

    # Actions : en tête des listes retenues, hors publication probable et hors secteur en baisse.
    lists = {c: _CONTEXT["lists"][c].get(day, []) for c, _ in picks}
    symbols = sorted({s for v in lists.values() for s in v})
    releases = {s: _CONTEXT["releases"].get(s, []) for s in symbols}
    domains = _CONTEXT["domains"]
    trends = {} if not picks or not opens or not late else sector_trends(
        {s: v[0] for s, v in opens.items()}, {s: v[1] for s, v in late.items()}, domains)
    filters = _CONTEXT["filters"]
    excluded = {c: {s for s in v if ("earnings" in filters and likely_reporting(releases.get(s, []), session_day, sale_day,
                                                                                 rules.earnings_tolerance_days))
                    or ("sector" in filters and domains.get(s) in trends and trends[domains[s]] <= 0)}
                for c, v in lists.items()}
    chosen = choose_stocks(picks, lists, excluded, rules)

    # Résultat : chaque stratégie retenue, rejouée sur ses seules actions retenues (mêmes heures, mêmes barres).
    stock_returns = {}
    for c, kept in chosen.items():
        if not kept:
            continue
        sid, variant = c.split("|")
        strategy = _CONTEXT["by_id"][sid]
        later = [(bt._utc(d, o), bt._utc(d, cl)) for d, o, cl in sessions[i + 1:i + 1 + bt.MAX_HOLD_SESSIONS]]
        decisions = bt.decisions_for(alpaca, strategy.criteria(), session_day, market_open)
        full = {v: _CONTEXT["lists"][f"{sid}|{v}"].get(day, []) for v in strategy.criteria()}
        record = bt._results_for_day(alpaca, {sid: {v: (kept if v == variant else []) for v in strategy.criteria()}},
                                     {sid: decisions}, session_day, market_open, market_close, later, [strategy],
                                     fetch_lists={sid: full})[sid]
        stock_returns[c] = {s: record[variant] for s in kept} if record.get(variant) is not None else {}
    result = day_return(chosen, stock_returns)
    return day, {"date": day, "return": result, "picks": [c for c, _ in picks], "stocks": chosen,
                 "guard": {"healthy": _CONTEXT["healthy"].get(day), "breadth": width, "fear_rise": fear_rise,
                           "blocked": reason},
                 "excluded": {c: sorted(v) for c, v in excluded.items() if v}}


def run(years, rules=SelectionRules(), filters=("earnings", "sector"), variant="complete"):
    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    chosen = candidates()
    history, lists = {}, {}
    for strategy in chosen:
        for variant in strategy.criteria():
            key = f"{strategy.id}|{variant}"
            history[key], lists[key] = [], {}
            for year in years:
                for day, r in sorted(_latest_days(strategy, f"annee_{year}").items()):
                    history[key].append((day, r[variant] if r.get(f"{variant}_n") else None))
                    lists[key][day] = r.get(f"{variant}_symbols", [])
    days = sorted({d for v in lists.values() for d in v})
    if not days:
        raise ValueError(f"Aucun test des stratégies pour {years}")
    sessions = alpaca.sessions(date.fromisoformat(days[0]) - timedelta(days=10), date.fromisoformat(days[-1]) + timedelta(days=20))
    # Marché en bonne forme : la veille, SPY au-dessus de sa moyenne de 50 séances (clôtures quotidiennes).
    spy = cached(f"selection/spy_daily_{days[0]}_{days[-1]}", lambda: alpaca.bars(
        ["SPY"], "1Day", datetime.fromisoformat(days[0]).replace(tzinfo=timezone.utc) - timedelta(days=120),
        datetime.fromisoformat(days[-1]).replace(tzinfo=timezone.utc)))
    spy["d"] = spy["timestamp"].dt.tz_convert(NEW_YORK).dt.date.astype(str)
    closes = list(zip(spy["d"], spy["close"]))
    healthy = {}
    for day in days:
        before = [c for d, c in closes if d < day][-50:]
        healthy[day] = None if len(before) < 50 else before[-1] > sum(before) / 50
    print(f"{len(days)} séances, {len(history)} listes candidates ({len(chosen)} stratégies).")
    # Données SEC lues une fois ici (au plus 10 requêtes par seconde), pas dans les processus : secteur de chaque
    # action liquide des séances, publications de résultats des actions des listes.
    universe = sorted({s for day in days for s in (_cached_prices(day, "ouverture_15min") or {})})
    in_lists = sorted({s for v in lists.values() for symbols in v.values() for s in symbols})
    print(f"SEC : secteurs de {len(universe)} actions, publications de {len(in_lists)} actions…", flush=True)
    domains = {s: p.get("domain") for s, p in sec.profiles(universe, "selection").items()}
    releases = sec.earnings_releases(in_lists, "selection")
    results = {}
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=multiprocessing.get_context("spawn"), initializer=_init,
                             initargs=(history, lists, sessions, healthy, domains, releases, rules, filters)) as pool:
        for n, (day, record) in enumerate(pool.map(_one_day, days), start=1):
            results[day] = record
            if n % 20 == 0:
                print(f"  [{n}/{len(days)}] {day} : {len(record['picks'])} stratégie(s), "
                      f"{sum(len(v) for v in record['stocks'].values())} actions, {record['return'] * 100:+.2f} %", flush=True)
    rows = [results[d] for d in days]
    by_year = {str(y): {r["date"]: r["return"] for r in rows if r["date"].startswith(str(y))} for y in years}
    payload = {
        "family": FAMILY, "kind": "selection_du_jour", "status": "diagnostic", "git_sha": git_sha,
        "created_at": datetime.now(timezone.utc).isoformat(), "years": [str(y) for y in years],
        "variant": variant, "rules": rules.__dict__, "filters": list(filters), "candidates": sorted(history),
        "summaries": {y: summary(v) for y, v in by_year.items() if v},
        "days": rows,
    }
    numbers = [int(p.name[1:]) for p in SELECTION_DIR.glob("s[0-9][0-9][0-9]") if p.name[1:].isdigit()]
    path = SELECTION_DIR / f"s{max(numbers, default=0) + 1:03d}" / "results.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    for y, s in payload["summaries"].items():
        traded = [r for r in rows if r["date"].startswith(y) and r["stocks"]]
        print(f"{y}: total {s['total'] * 100:+.1f} %, {len(traded)} séances investies sur {s['n']}, "
              f"pire séance {s['worst'] * 100:+.2f} %")
    print(f"Résultats : {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Sélection du jour sur le passé (diagnostic)")
    parser.add_argument("--years", default="2024,2025", help="Années, séparées par des virgules (tests des stratégies requis)")
    parser.add_argument("--without", default="", help="Parties retirées pour comparer : breadth, fear, earnings, sector, guard")
    args = parser.parse_args()
    off = set(filter(None, args.without.split(",")))
    rules = SelectionRules(min_breadth=0.0 if off & {"breadth", "guard"} else SelectionRules.min_breadth,
                           max_fear_rise=1e9 if off & {"fear", "guard"} else SelectionRules.max_fear_rise)
    filters = tuple(f for f in ("earnings", "sector") if f not in off)
    try:
        return run([int(y) for y in args.years.split(",")], rules, filters, "sans " + ",".join(sorted(off)) if off else "complete")
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
