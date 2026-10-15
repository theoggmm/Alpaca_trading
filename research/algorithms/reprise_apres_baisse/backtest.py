"""
Test sur le passé (diagnostic) : rejoue chaque séance des N derniers mois avec les fonctions du screener
quotidien et de la simulation (règle 8 : un seul module de logique).

Pour chaque séance : liste « sans PER » et liste « PER < 12 » calculées avec les seules données connues à
10 h 30 (New York), achat au premier échange à partir de 10 h 45, vente au dernier échange avant 15 h 30,
0,05 % de frais par ordre ; repère SPY selon les mêmes règles.

Biais connus, écrits dans le résultat : univers = titres actifs aujourd'hui (les titres disparus depuis
manquent, ce qui avantage le passé) ; indicateur ETF et domaines lus aujourd'hui.

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest --months 6
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.performance_metrics import paired_difference, summary
from core.portfolio import simulate
from core.screener import Criteria, daily_candidates, screen
from core.universe import eligible_symbols
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import RUNS_DIR, TraceError, committed_git_sha
from research.algorithms.reprise_apres_baisse.run import DAILY_HISTORY, FAMILY, NEW_YORK, SIP_DELAY, VARIANTS

BENCHMARK = "SPY"
TRADE_WINDOW = timedelta(minutes=5)
EXIT_BEFORE_CLOSE = timedelta(minutes=30)
EXIT_WINDOW = timedelta(minutes=30)
BACKTEST_DIR = RUNS_DIR / FAMILY / "backtests"
BIASES = [
    "Univers = titres actifs aujourd'hui chez Alpaca : les titres disparus depuis (faillites, rachats) "
    "sont absents, ce qui embellit le passé (biais du survivant).",
    "Indicateur ETF (Nasdaq Trader) lu aujourd'hui, appliqué au passé.",
    "Bénéfices (PER) : seules les déclarations déposées à la SEC avant chaque jour de décision servent.",
    "Repère univers liquide non calculé (trop coûteux sur le passé) : seul SPY sert de repère.",
]


def _next_id():
    numbers = [int(p.name[1:]) for p in BACKTEST_DIR.glob("b[0-9][0-9][0-9]") if p.name[1:].isdigit()]
    return f"b{max(numbers, default=0) + 1:03d}"


def run(months):
    criteria = {variant: Criteria.from_file(path) for variant, path in VARIANTS.items()}
    base = criteria["sans_per"]
    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    today = datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    start = today - timedelta(days=round(months * 30.44))
    sessions = [s for s in alpaca.sessions(start, today) if s[0] < today]
    print(f"{len(sessions)} séances du {sessions[0][0]} au {sessions[-1][0]}.")

    key = f"backtest/{sessions[0][0]}_{sessions[-1][0]}"
    listings, _ = cached(f"{today}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{today}/alpaca_assets", alpaca.assets)
    symbols, _ = eligible_symbols(assets, listings)
    first_open = datetime.combine(sessions[0][0], sessions[0][1], NEW_YORK).astimezone(timezone.utc)
    last_close = datetime.combine(sessions[-1][0], sessions[-1][2], NEW_YORK).astimezone(timezone.utc)
    print("Lecture des cours quotidiens (une fois)…")
    daily = cached(f"{key}/daily_bars", lambda: alpaca.bars(symbols, "1Day", first_open - DAILY_HISTORY, last_close))

    days = []
    for n, (session_date, open_time, close_time) in enumerate(sessions, start=1):
        market_open = datetime.combine(session_date, open_time, NEW_YORK).astimezone(timezone.utc)
        market_close = datetime.combine(session_date, close_time, NEW_YORK).astimezone(timezone.utc)
        decision_time = market_open + timedelta(minutes=base.first_hour_minutes)
        entry_time, exit_time = decision_time + SIP_DELAY, market_close - EXIT_BEFORE_CLOSE
        day_key = f"backtest/{session_date}"

        candidates, _ = daily_candidates(daily, decision_time, base)
        minute = cached(f"{day_key}/first_hour_bars",
                        lambda: alpaca.bars([c.symbol for c in candidates], "1Min", market_open, decision_time))
        lists = {variant: screen(daily, minute, market_open, decision_time, c,
                                 earnings_for=lambda s: sec.eps(s, "backtest"))[0]
                 for variant, c in criteria.items()}
        traded = sorted({i["symbol"] for items in lists.values() for i in items} | {BENCHMARK})
        entry_bars = cached(f"{day_key}/entry_bars", lambda: alpaca.bars(traded, "1Min", entry_time, entry_time + TRADE_WINDOW))
        exit_bars = cached(f"{day_key}/exit_bars", lambda: alpaca.bars(traded, "1Min", exit_time - EXIT_WINDOW, exit_time))

        record = {"date": session_date.isoformat()}
        for name, items in [*lists.items(), ("spy", [{"symbol": BENCHMARK}])]:
            result = simulate([i["symbol"] for i in items], entry_bars, exit_bars, {}, entry_time, exit_time,
                              market_close)
            record[name] = 0.0 if not items else result.get("net_mean_return")
            record[f"{name}_n"] = len(items)
        days.append(record)
        print(f"  [{n}/{len(sessions)}] {record['date']} : sans PER {record['sans_per_n']} titres "
              f"{_pct(record['sans_per'])}, PER < 12 {record['per12_n']} titres {_pct(record['per12'])}, "
              f"SPY {_pct(record['spy'])}")

    series = {name: {d["date"]: d[name] for d in days if d[name] is not None} for name in ("per12", "sans_per", "spy")}
    payload = {
        "backtest_id": _next_id(),
        "family": FAMILY,
        "status": "diagnostic",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "period": {"start": days[0]["date"], "end": days[-1]["date"], "sessions": len(days), "months": months},
        "rules": {"entry": "premier échange à partir de 10 h 45 (New York)", "exit": "dernier échange avant 15 h 30",
                  "cost_bps_per_order": "5", "split": "parts égales, fractions d'action"},
        "criteria": {variant: c.to_json() for variant, c in criteria.items()},
        "biases": BIASES,
        "summaries": {name: summary(values) for name, values in series.items()},
        "differences": {"per12_vs_sans_per": paired_difference(series["per12"], series["sans_per"]),
                        "per12_vs_spy": paired_difference(series["per12"], series["spy"]),
                        "sans_per_vs_spy": paired_difference(series["sans_per"], series["spy"])},
        "days": days,
    }
    path = BACKTEST_DIR / payload["backtest_id"] / "results.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    for name, s in payload["summaries"].items():
        if s.get("n"):
            print(f"{name:<9} n={s['n']:<4} moyenne/séance {_pct(s['mean'])}  total {_pct(s['total'])}  "
                  f"annualisé {_pct(s['annualized'])}{' SUSPECT' if s['suspect'] else ''}  positives {_pct(s['positive_share'])}")
    print(f"Résultats : {path}")
    return 0


def _pct(value):
    return "—" if value is None else f"{value * 100:+.2f} %"


def main():
    parser = argparse.ArgumentParser(description="Test sur le passé du screener reprise_apres_baisse (diagnostic)")
    parser.add_argument("--months", type=int, default=6, help="Nombre de mois rejoués (défaut : 6)")
    args = parser.parse_args()
    try:
        return run(args.months)
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
