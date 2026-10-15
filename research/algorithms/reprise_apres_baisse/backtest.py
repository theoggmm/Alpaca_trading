"""
Test sur le passé (diagnostic) : rejoue chaque séance des N derniers mois avec les fonctions du screener
quotidien et de la simulation (règle 8 : un seul module de logique).

Pour chaque séance : les deux versions actuelles (sans PER, PER < 12) et les mêmes d'avant les règles contre
l'achat au sommet (archive), chacune calculée avec les seules données connues à sa décision (10 h 45 avec
confirmation, 10 h 30 sans ; New York), achat au premier échange 15 min après la décision, vente au dernier
échange avant 15 h 30, 0,05 % de frais par ordre ; repère SPY acheté à l'heure d'achat des versions actuelles.

Biais connus, écrits dans le résultat : univers = titres actifs aujourd'hui (les titres disparus depuis
manquent, ce qui avantage le passé) ; indicateur ETF et domaines lus aujourd'hui.

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest --months 6
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.performance_metrics import paired_difference, summary
from core.portfolio import simulate
from core.screener import Criteria, daily_candidates, screen
from core.universe import eligible_symbols
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import RUNS_DIR, TraceError, committed_git_sha
from research.algorithms.reprise_apres_baisse.run import ARCHIVED, DAILY_HISTORY, FAMILY, NEW_YORK, SIP_DELAY, VARIANTS

BENCHMARK = "SPY"
# Comparaisons rapportées (écarts quotidiens appariés) : (série, référence).
COMPARISONS = [("per12", "sans_per"), ("per12", "spy"), ("sans_per", "spy"),
               ("per12", "per12_v2"), ("sans_per", "sans_per_v1")]
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
    "Plus haut de la première heure (version « pas au sommet ») : plus haute clôture minute, comme en direct.",
]


def _next_id():
    numbers = [int(p.name[1:]) for p in BACKTEST_DIR.glob("b[0-9][0-9][0-9]") if p.name[1:].isdigit()]
    return f"b{max(numbers, default=0) + 1:03d}"


def run(months):
    # Versions actuelles et versions d'avant (archive) : la comparaison montre l'effet des derniers changements.
    criteria = {variant: Criteria.from_file(path) for variant, path in {**VARIANTS, **ARCHIVED}.items()}
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
        first_hour_end = market_open + timedelta(minutes=base.first_hour_minutes)
        last_decision = market_open + timedelta(minutes=max(c.decision_minutes for c in criteria.values()))
        exit_time = market_close - EXIT_BEFORE_CLOSE
        day_key = f"backtest/{session_date}"

        candidates, _ = daily_candidates(daily, first_hour_end, base)
        wanted = [c.symbol for c in candidates]
        minute = cached(f"{day_key}/first_hour_bars", lambda: alpaca.bars(wanted, "1Min", market_open, first_hour_end))
        if last_decision > first_hour_end:   # minutes de confirmation après la première heure
            minute = pd.concat([minute, cached(f"{day_key}/confirmation_bars_{int((last_decision - market_open).total_seconds() // 60)}",
                                               lambda: alpaca.bars(wanted, "1Min", first_hour_end, last_decision))],
                               ignore_index=True)
        decisions = {variant: market_open + timedelta(minutes=c.decision_minutes) for variant, c in criteria.items()}
        lists = {variant: screen(daily, minute, market_open, decisions[variant], c,
                                 earnings_for=lambda s: sec.eps(s, "backtest"))[0]
                 for variant, c in criteria.items()}
        entries = {variant: decisions[variant] + SIP_DELAY for variant in criteria}
        # SPY acheté à l'heure d'achat des versions actuelles.
        entries["spy"] = min(entries[variant] for variant in VARIANTS)
        lists["spy"] = [{"symbol": BENCHMARK}]
        traded = sorted({i["symbol"] for items in lists.values() for i in items})
        frames = [cached(f"{day_key}/entry_bars_all_{at.astimezone(NEW_YORK):%H%M}",
                         lambda: alpaca.bars(traded, "1Min", at, at + TRADE_WINDOW)) for at in sorted(set(entries.values()))]
        entry_bars = pd.concat(frames, ignore_index=True)
        exit_bars = cached(f"{day_key}/exit_bars_all", lambda: alpaca.bars(traded, "1Min", exit_time - EXIT_WINDOW, exit_time))

        record = {"date": session_date.isoformat()}
        for name, items in lists.items():
            result = simulate([i["symbol"] for i in items], entry_bars, exit_bars, {}, entries[name], exit_time,
                              market_close)
            record[name] = 0.0 if not items else result.get("net_mean_return")
            record[f"{name}_n"] = len(items)
        days.append(record)
        print(f"  [{n}/{len(sessions)}] {record['date']} : "
              + ", ".join(f"{name} {record[f'{name}_n']} titres {_pct(record[name])}" for name in lists))

    names = [*criteria, "spy"]
    series = {name: {d["date"]: d[name] for d in days if d[name] is not None} for name in names}
    payload = {
        "backtest_id": _next_id(),
        "family": FAMILY,
        "status": "diagnostic",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "period": {"start": days[0]["date"], "end": days[-1]["date"], "sessions": len(days), "months": months},
        "rules": {"entry": "premier échange 15 min après la décision : 10 h 45, ou 11 h 00 avec confirmation (New York)",
                  "exit": "dernier échange avant 15 h 30",
                  "cost_bps_per_order": "5", "split": "parts égales, fractions d'action"},
        "criteria": {variant: c.to_json() for variant, c in criteria.items()},
        "biases": BIASES,
        "summaries": {name: summary(values) for name, values in series.items()},
        "differences": {f"{a}_vs_{b}": paired_difference(series[a], series[b]) for a, b in COMPARISONS
                        if a in series and b in series},
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
