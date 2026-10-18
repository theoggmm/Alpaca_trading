"""
Sélection du jour en direct (décision T18) : à 14 h 45 (New York), 0 à 3 stratégies de fin de journée choisies sur
leurs résultats déjà connus, si le marché est en bonne forme ; au plus 7 actions, prises en tête de leurs listes dès
que celles-ci sortent (core/selection.py). Le choix est enregistré, daté, dans research/experiments/selection/ ; le
résultat se lit dans les états des stratégies retenues (gain de chaque action retenue, frais compris).

Résultats connus : ceux des tests de la semaine du 12 octobre 2026 (amorce), puis les états de fin de séance vendus.
"""

import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from core.selection import (SelectionRules, breadth, choose_stocks, likely_reporting, market_ok, pick_strategies,
                            sector_trends)
from core.screener import market_in_uptrend
from dashboard.build import FINALS_DIR, RUNS_DIR, ROOT, live_file
from infra import sec
from infra.cache import cached
from infra.http import FetchError
from infra.trace import load_runs, latest_per_session, variant_of

PICKS_DIR = ROOT / "research" / "experiments" / "selection"
GUARD_MINUTES = 315          # 14 h 45, New York : première décision des stratégies candidates
FEAR_SYMBOL = "VIXY"
SEED_LABEL = "periode_20261012_20261016"
NEW_YORK = "America/New_York"


def candidates(every):
    """Stratégies de fin de journée gardées une nuit au plus (décision à 14 h 45 ou plus tard)."""
    return [s for s in every if s.sale_offset == 1
            and min(c.decision_minutes for c in s.criteria().values()) >= GUARD_MINUTES]


def picks_file(family, key):
    return PICKS_DIR / family / f"{key}.json"


def history(chosen, key):
    """
    Liste candidate (« stratégie|version ») -> résultats connus avant la séance key, du plus ancien au plus récent :
    amorce (tests de la semaine du 12 octobre 2026), puis états de fin de séance dont la vente est faite.
    """
    result = {}
    for strategy in chosen:
        seed = {}
        for path in sorted((RUNS_DIR / strategy.storage / "backtests").glob("b[0-9][0-9][0-9]/results.json")):
            test = json.loads(path.read_text(encoding="utf-8"))
            if test.get("label") == SEED_LABEL and test.get("top") is None:
                seed = {r["date"]: r for r in test["days"]}
        for variant in strategy.criteria():
            series = {d: (r[variant] if r.get(f"{variant}_n") else None) for d, r in seed.items()}
            for path in sorted((FINALS_DIR / strategy.storage).glob("????-??-??.json")):
                if path.stem >= key:
                    continue
                version = ((json.loads(path.read_text(encoding="utf-8")).get("portfolio") or {}).get("versions") or {}).get(variant)
                if version is None:
                    continue
                if not version.get("n"):
                    series[path.stem] = None
                elif version.get("status") == "closed":
                    series[path.stem] = version.get("net_mean_return")
            result[f"{strategy.id}|{variant}"] = sorted(series.items())
    return result


def update(alpaca, family, every, key, market_open, now, trades, opens, domains, git_sha):
    """
    Pendant la séance (suivi en direct) : décide à 14 h 45 (barres servies 15 min plus tard), puis choisit les actions
    de chaque stratégie retenue dès que sa liste sort ; les actions déjà choisies ne changent plus. Écrit le fichier
    du jour. Retourne l'enregistrement, ou None avant l'heure.
    """
    guard_time = market_open + timedelta(minutes=GUARD_MINUTES)
    if now < guard_time + timedelta(minutes=15):
        return None
    path = picks_file(family, key)
    record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    rules = SelectionRules()
    chosen = candidates(every)
    if record is None:
        # Version 2 : toujours la même liste (rules.fixed) ; version 1 : choix par résultats récents.
        picks = [(c, 0.0) for c in rules.fixed] if rules.fixed else pick_strategies(history(chosen, key), rules)
        spy = cached(f"{key}/selection_spy_daily", lambda: alpaca.bars(["SPY"], "1Day", market_open - timedelta(days=120), market_open))
        healthy, _, _ = market_in_uptrend(spy, market_open, "SPY", 50)
        prices = {s: p for s, (_, p) in trades.items()}
        width = breadth(opens, prices)
        try:
            fear = cached(f"{key}/selection_vixy_1445", lambda: alpaca.bars([FEAR_SYMBOL], "1Min", market_open, guard_time))
            fear = fear.sort_values("timestamp")
            fear_rise = None if fear.empty else float(fear["close"].iloc[-1] / fear["open"].iloc[0] - 1)
        except FetchError:
            fear_rise = None
        ok, reason = market_ok(healthy, width, fear_rise, rules, weekday=market_open.astimezone(ZoneInfo(NEW_YORK)).weekday())
        record = {"session_date": key, "decided_at": now.isoformat(), "git_sha": git_sha, "status": "diagnostic",
                  "picks": [{"candidate": c, "recent": score} for c, score in picks] if ok else [],
                  "considered": [c for c, _ in picks],
                  "guard": {"healthy": healthy, "breadth": width, "fear_rise": fear_rise, "blocked": reason},
                  "trends": sector_trends(opens, prices, domains), "stocks": {}, "excluded": {}}
    # Actions : listes du jour sorties, dans l'ordre des stratégies retenues (une liste plus tardive se complète ensuite).
    by_id = {s.id: s for s in every}
    lists, waiting = {}, False
    for pick in record["picks"]:
        sid, variant = pick["candidate"].split("|")
        runs = [r for r in latest_per_session(load_runs(by_id[sid].storage))
                if r["session_date"] == key and variant_of(r) == variant]
        if runs:
            lists[pick["candidate"]] = [i["symbol"] for i in runs[-1]["selection"]]
        else:
            waiting = True
    fresh = [c for c in lists if c not in record["stocks"]]
    if fresh:
        symbols = sorted({s for c in fresh for s in lists[c]})
        try:
            releases = sec.earnings_releases(symbols, key) if "earnings" in rules.filters else {}
        except FetchError:
            releases = {}
        session_day = market_open.astimezone(ZoneInfo(NEW_YORK)).date()
        sale_day = session_day + timedelta(days=3 if session_day.weekday() == 4 else 1)
        trends = record["trends"]
        excluded = {c: sorted(s for s in lists[c] if ("earnings" in rules.filters and likely_reporting(
                                  releases.get(s, []), session_day, sale_day, rules.earnings_tolerance_days))
                              or ("sector" in rules.filters and domains.get(s) in trends and trends[domains[s]] <= 0))
                    for c in lists}
        picks = [(p["candidate"], p["recent"]) for p in record["picks"]]
        stocks = choose_stocks(picks, lists, {c: set(v) for c, v in excluded.items()}, rules)
        for c in fresh:
            record["stocks"][c] = stocks.get(c, [])
            record["excluded"][c] = excluded.get(c, [])
    record["waiting_lists"] = waiting
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return record


def outcome(family, every, record):
    """
    Résultat d'une séance de la sélection : moyenne, à parts égales, des gains après frais des actions retenues, lus
    dans l'état (en direct ou de fin de séance) de chaque stratégie retenue. Retourne {"return", "status", "stocks"}.
    """
    by_id = {s.id: s for s in every}
    values, statuses, detail = [], set(), {}
    for candidate, symbols in record.get("stocks", {}).items():
        sid, variant = candidate.split("|")
        strategy = by_id.get(sid)
        if strategy is None or not symbols:
            continue
        final = FINALS_DIR / strategy.storage / f"{record['session_date']}.json"
        state_path = final if final.exists() else live_file(strategy)
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        if state.get("session_date", record["session_date"]) != record["session_date"]:
            continue
        version = ((state.get("portfolio") or {}).get("versions") or {}).get(variant) or {}
        statuses.add(version.get("status"))
        positions = version.get("positions") or {}
        for s in symbols:
            r = (positions.get(s) or {}).get("net_return")
            p = positions.get(s) or {}
            detail[s] = {"candidate": candidate, "net_return": r, "state": p.get("state"), "entry": p.get("entry"),
                         "price": p.get("price"), "at": p.get("at"), "return": p.get("return")}
            if r is not None:
                values.append(r)
    status = "none" if not record.get("stocks") else "closed" if statuses == {"closed"} else "live"
    return {"return": sum(values) / len(values) if values else None, "status": status, "stocks": detail}
