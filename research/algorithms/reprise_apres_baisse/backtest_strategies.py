"""
Tests sur le passé des 10 stratégies (diagnostic) : rejoue chaque séance d'une période avec les fonctions des
listes quotidiennes (core/screener, core/opening, core/closing) et de la simulation (core/portfolio), aux heures
d'achat et de vente de chaque stratégie, stop −1,5 % / objectif +3 % compris (règle 8 : un seul module de logique).

La période est rejouée une fois, séance par séance, pour toutes les stratégies (données partagées) ; chaque test
(un mois, six mois, une année) en est une tranche : une séance donne le même résultat dans toutes les tranches.

Heures (New York) : achat au premier échange 15 min après la décision (retard des données, comme en direct),
vente à l'heure de la stratégie (avant la clôture, après l'ouverture, ou la séance suivante pour les achats de
nuit) ; vente plus tôt au stop ou à l'objectif, vérifiés sur chaque minute entre l'achat et la vente.

Lectures réduites sans changer les listes : une liste « fin de journée » ne garde que les titres en hausse de
0,5 % à 4 % sur la journée ; ce filtre est d'abord appliqué sur les minutes d'ouverture et celles d'avant la
décision, puis toute la séance n'est lue que pour les titres qui le passent. Une liste « ouverture » ne garde que
les titres en hausse dans la dernière heure de la veille ; la nuit n'est lue que pour eux.

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest_strategies
"""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd

from core.closing import ClosingCriteria, screen_closing
from core.opening import OpeningCriteria, screen_opening
from core.performance_metrics import summary
from core.portfolio import simulate
from core.screener import daily_candidates, liquid_universe, screen
from core.universe import eligible_symbols
from infra import nasdaq_symbols
from infra.alpaca_api import BAR_COLUMNS, AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import RUNS_DIR, TraceError, committed_git_sha
from research.algorithms.reprise_apres_baisse.backtest import BIASES, TESTED_AMOUNTS
from research.algorithms.reprise_apres_baisse.run import DAILY_HISTORY, FAMILY, NEW_YORK, SIP_DELAY, STRATEGIES, earnings

BENCHMARK = "SPY"
SUITE = "tests_2025"
# Une passe sur 2025, puis trois tests : le mois le plus baissier du S&P 500 (mars, −5,6 %), six mois, l'année.
YEAR = (date(2025, 1, 1), date(2025, 12, 31))
TESTS = [
    {"label": "mars_2025", "start": date(2025, 3, 1), "end": date(2025, 3, 31),
     "spy_month": "−5,57 % (mois le plus baissier de 2025 pour SPY, clôture à clôture)"},
    {"label": "janvier_juin_2025", "start": date(2025, 1, 1), "end": date(2025, 6, 30)},
    {"label": "annee_2025", "start": date(2025, 1, 1), "end": date(2025, 12, 31)},
]
TRADE_WINDOW = timedelta(minutes=5)
EXIT_WINDOW = timedelta(minutes=30)
FIRST_WINDOW = timedelta(minutes=15)   # minutes d'ouverture lues pour le premier prix (préfiltre « fin de journée »)
# Change quand le calcul change : les séances déjà rejouées (cache) sont alors refaites.
VERSION = 1
WORKERS = 4
EXTRA_BIASES = [
    "Liste « fin de journée » : un titre sans échange dans les 15 premières minutes, ou dans les 15 minutes avant "
    "la décision, est écarté (en direct il serait jugé sur ses premiers et derniers échanges) — rare pour des "
    "titres liquides.",
]


def _key(*parts):
    return "/".join(["backtest_strategies", *map(str, parts)])


def _symbols_hash(symbols):
    return hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()[:12]


def _utc(day, at):
    return datetime.combine(day, at, NEW_YORK).astimezone(timezone.utc)


def _bars(alpaca, key, symbols, start, end):
    """Barres minute de symbols entre start et end, lues une fois (cache nommé par la liste de titres)."""
    if not symbols or end <= start:
        return pd.DataFrame(columns=BAR_COLUMNS)
    return cached(f"{key}_{_symbols_hash(symbols)}", lambda: alpaca.bars(sorted(symbols), "1Min", start, end))


def _concat(frames):
    frames = [f for f in frames if not f.empty]
    return (pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "timestamp"]) if frames
            else pd.DataFrame(columns=BAR_COLUMNS))


def _lists_for_day(alpaca, daily, market_daily, day, market_open, previous_close):
    """Listes de toutes les stratégies pour la séance : {stratégie: {version: [symboles]}}, et la décision de chacune."""
    lists, decisions = {}, {}
    pe = earnings(alpaca, "backtest")
    kinds = {s.id: s.criteria() for s in STRATEGIES}

    # « Reprise après baisse » : candidats quotidiens, puis minutes de 9 h 30 jusqu'à la décision la plus tardive.
    rebound = {sid: c for sid, c in kinds.items() if not isinstance(next(iter(c.values())), (OpeningCriteria, ClosingCriteria))}
    if rebound:
        last = max(c.decision_minutes for cs in rebound.values() for c in cs.values())
        wanted = set()
        for cs in rebound.values():
            for c in cs.values():
                cut = market_open + timedelta(minutes=c.first_hour_minutes)
                wanted |= {x.symbol for x in daily_candidates(daily, cut, c)[0]}
        minute = _bars(alpaca, _key(day, f"rebound_0930_{last}"), wanted, market_open,
                       market_open + timedelta(minutes=last))
        for sid, cs in rebound.items():
            for variant, c in cs.items():
                decision = market_open + timedelta(minutes=c.decision_minutes)
                selection, _ = screen(daily, minute, market_open, decision, c, earnings_for=pe, market_daily=market_daily)
                lists.setdefault(sid, {})[variant] = [i["symbol"] for i in selection]
                decisions.setdefault(sid, {})[variant] = decision

    # « Ouverture » : dernière heure de la veille de tous les titres liquides, puis la nuit des seuls titres en hausse.
    opening = {sid: c for sid, c in kinds.items() if isinstance(next(iter(c.values())), OpeningCriteria)}
    for sid, cs in opening.items():
        for variant, c in cs.items():
            decision = market_open + timedelta(minutes=c.decision_minutes)
            liquid = [s.symbol for s in liquid_universe(daily, decision, c)[0]]
            start = previous_close - timedelta(minutes=c.last_hour_minutes)
            hour = _bars(alpaca, _key(day, f"veille_derniere_heure_{c.last_hour_minutes}"), liquid, start, previous_close)
            rising = [s for s, b in hour.sort_values("timestamp").groupby("symbol")
                      if b["close"].iloc[-1] > b["open"].iloc[0]]
            night = _bars(alpaca, _key(day, f"nuit_{decision.astimezone(NEW_YORK):%H%M}"), rising, previous_close, decision)
            selection, _ = screen_opening(daily, _concat([hour, night]), market_open, previous_close, decision, c,
                                          earnings_for=pe, market_daily=market_daily)
            lists.setdefault(sid, {})[variant] = [i["symbol"] for i in selection]
            decisions.setdefault(sid, {})[variant] = decision

    # « Fin de journée » : préfiltre « journée en hausse » (premières minutes et minutes avant la décision), puis
    # toute la séance des seuls titres qui le passent.
    closing = {sid: c for sid, c in kinds.items() if isinstance(next(iter(c.values())), ClosingCriteria)}
    for sid, cs in closing.items():
        for variant, c in cs.items():
            decision = market_open + timedelta(minutes=c.decision_minutes)
            liquid = [s.symbol for s in liquid_universe(daily, decision, c)[0]]
            first = _bars(alpaca, _key(day, "ouverture_15min"), liquid, market_open, market_open + FIRST_WINDOW)
            late = _bars(alpaca, _key(day, f"avant_{decision.astimezone(NEW_YORK):%H%M}"), liquid,
                         decision - FIRST_WINDOW, decision)
            opens = {s: b["open"].iloc[0] for s, b in first.sort_values("timestamp").groupby("symbol")}
            prices = {s: b["close"].iloc[-1] for s, b in late.sort_values("timestamp").groupby("symbol")}
            rising = [s for s in opens if s in prices and c.min_day_gain <= prices[s] / opens[s] - 1 <= c.max_day_gain]
            session = _bars(alpaca, _key(day, f"seance_{decision.astimezone(NEW_YORK):%H%M}"), rising, market_open, decision)
            selection, _ = screen_closing(daily, session, market_open, decision, c, earnings_for=pe,
                                          market_daily=market_daily)
            lists.setdefault(sid, {})[variant] = [i["symbol"] for i in selection]
            decisions.setdefault(sid, {})[variant] = decision
    return lists, decisions


def _results_for_day(alpaca, lists, decisions, day, market_open, market_close, next_open, next_close):
    """Simulation de chaque liste et du repère SPY aux heures de chaque stratégie : {stratégie: enregistrement}."""
    records = {}
    for strategy in STRATEGIES:
        exit_time = strategy.exit_time(market_open, market_close, next_open)
        entries = {v: d + SIP_DELAY for v, d in decisions[strategy.id].items()}
        entries["spy"] = min(entries.values())
        picked = {s for symbols in lists[strategy.id].values() for s in symbols}
        traded = picked | {BENCHMARK}
        tag = f"{strategy.id}"
        entry_bars = _concat([_bars(alpaca, _key(day, f"achat_{tag}_{at.astimezone(NEW_YORK):%H%M}"), traded, at,
                                    at + TRADE_WINDOW) for at in sorted(set(entries.values()))])
        exit_bars = _bars(alpaca, _key(day, f"vente_{tag}_{exit_time.astimezone(NEW_YORK):%Y%m%d_%H%M}"), traded,
                          exit_time - EXIT_WINDOW, exit_time)
        # Trajet minute de l'achat à la vente (séances régulières seulement ; achat de nuit : la fin de séance du
        # jour, puis la séance suivante jusqu'à la vente), comme le suivi en direct.
        start = min(entries.values())
        windows = [(start, min(exit_time, market_close))]
        if strategy.overnight:
            windows.append((next_open, exit_time))
        path = _concat([_bars(alpaca, _key(day, f"trajet_{tag}_{a.astimezone(NEW_YORK):%Y%m%d%H%M}"), picked, a, b)
                        for a, b in windows])
        after = exit_time + timedelta(days=1)
        record = {"date": day.isoformat()}
        for name, symbols in {**lists[strategy.id], "spy": [BENCHMARK]}.items():
            result = simulate(symbols, entry_bars, exit_bars, {}, entries[name], exit_time, after,
                              amounts=TESTED_AMOUNTS, path_bars=None if name == "spy" else path)
            empty = not symbols
            record[name] = 0.0 if empty else result.get("net_mean_return")
            record[f"{name}_n"] = len(symbols)
            record[f"{name}_gross"] = 0.0 if empty else result.get("mean_return")
            record[f"{name}_whole_gains"] = {} if empty else result.get("whole_gains", {})
            record[f"{name}_hold"] = 0.0 if empty else result.get("hold_net_mean_return", result.get("net_mean_return"))
            record[f"{name}_early"] = {} if empty else {s: e["reason"] for s, e in result.get("early_exits", {}).items()}
        records[strategy.id] = record
    return records


def run():
    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    criteria_hash = hashlib.sha1(json.dumps({s.id: {v: c.to_json() for v, c in s.criteria().items()}
                                             for s in STRATEGIES}, sort_keys=True, default=str).encode()).hexdigest()[:10]
    sessions = alpaca.sessions(YEAR[0] - timedelta(days=10), YEAR[1] + timedelta(days=10))
    days = [i for i, s in enumerate(sessions) if YEAR[0] <= s[0] <= YEAR[1]]
    print(f"{len(days)} séances du {sessions[days[0]][0]} au {sessions[days[-1]][0]} · {len(STRATEGIES)} stratégies.")

    today = datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    listings, _ = cached(f"{today}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{today}/alpaca_assets", alpaca.assets)
    symbols, _ = eligible_symbols(assets, listings)
    first_open = _utc(*sessions[days[0]][:2])
    last_close = _utc(sessions[days[-1] + 1][0], sessions[days[-1] + 1][2])
    print("Lecture des cours quotidiens (une fois)…")
    daily = cached(_key(f"daily_bars_{first_open:%Y%m%d}_{last_close:%Y%m%d}"), lambda: alpaca.bars(symbols, "1Day", first_open - DAILY_HISTORY, last_close))
    market_daily = cached(_key(f"spy_daily_{first_open:%Y%m%d}_{last_close:%Y%m%d}"),
                          lambda: alpaca.bars([BENCHMARK], "1Day", first_open - DAILY_HISTORY, last_close))

    # Divisions d'actions lues une fois avant les fils (cache partagé).
    earnings(alpaca, "backtest")([])

    def one_day(i):
        day, open_at, close_at = sessions[i]
        market_open, market_close = _utc(day, open_at), _utc(day, close_at)
        previous_close = _utc(sessions[i - 1][0], sessions[i - 1][2])
        next_open = _utc(sessions[i + 1][0], sessions[i + 1][1])
        next_close = _utc(sessions[i + 1][0], sessions[i + 1][2])

        def compute():
            # Seulement l'historique utile à cette séance (plus rapide ; chaque règle retronque à sa décision).
            window = lambda bars: bars[(bars["timestamp"] >= market_open - DAILY_HISTORY) & (bars["timestamp"] < market_close)]
            lists, decisions = _lists_for_day(alpaca, window(daily), window(market_daily), day, market_open, previous_close)
            return _results_for_day(alpaca, lists, decisions, day, market_open, market_close, next_open, next_close)

        return day, cached(_key(day, f"resultats_v{VERSION}_{criteria_hash}"), compute)

    # Plusieurs séances en parallèle (l'attente est surtout réseau) ; chaque séance a ses propres fichiers de cache.
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for n, (day, records) in enumerate(pool.map(one_day, days), start=1):
            results[day] = records
            print(f"  [{n}/{len(days)}] {day} : " + " · ".join(
                f"{sid} {r['per12_n']}/{r['sans_per_n']} {_pct(r['per12'])}" for sid, r in records.items()), flush=True)
    by_strategy = {s.id: [results[day][s.id] for day in sorted(results)] for s in STRATEGIES}

    written = []
    for strategy in STRATEGIES:
        folder = RUNS_DIR / strategy.storage / "backtests"
        for test in TESTS:
            rows = [r for r in by_strategy[strategy.id] if test["start"].isoformat() <= r["date"] <= test["end"].isoformat()]
            names = [*strategy.criteria(), "spy"]
            series = {name: {r["date"]: r[name] for r in rows if r[name] is not None} for name in names}
            holds = {f"{name}_sans_regle": {r["date"]: r[f"{name}_hold"] for r in rows if r[f"{name}_hold"] is not None}
                     for name in strategy.criteria()}
            numbers = [int(p.name[1:]) for p in folder.glob("b[0-9][0-9][0-9]") if p.name[1:].isdigit()]
            payload = {
                "backtest_id": f"b{max(numbers, default=0) + 1:03d}",
                "family": FAMILY, "strategy": strategy.id, "suite": SUITE, "label": test["label"],
                "status": "diagnostic",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "git_sha": git_sha,
                "period": {"start": rows[0]["date"], "end": rows[-1]["date"], "sessions": len(rows), "months": None},
                "spy_month": test.get("spy_month"),
                "rules": {"entry": "premier échange 15 min après la décision de chaque liste (New York)",
                          "exit": f"heure de vente de la stratégie {strategy.id}, stop −1,5 % / objectif +3 %",
                          "cost_bps_per_order": "5", "split": "parts égales, fractions d'action"},
                "criteria": {v: c.to_json() for v, c in strategy.criteria().items()},
                "biases": BIASES + EXTRA_BIASES,
                "summaries": {name: summary(values) for name, values in {**series, **holds}.items()},
                "days": rows,
            }
            path = folder / payload["backtest_id"] / "results.json"
            path.parent.mkdir(parents=True, exist_ok=False)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
            written.append(path)
            s = payload["summaries"]
            print(f"{strategy.id:26} {test['label']:18} " + "  ".join(
                f"{name} {_pct(s[name].get('total'))}" for name in ("per12", "sans_per", "spy") if s.get(name, {}).get("n")))
    print(f"{len(written)} résultats écrits.")
    return 0


def _pct(value):
    return "—" if value is None else f"{value * 100:+.2f} %"


def main():
    try:
        return run()
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
