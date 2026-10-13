"""
Run quotidien du screener « reprise après baisse ».

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.run
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.screener import Criteria, daily_candidates, screen
from core.universe import eligible_symbols
from infra import nasdaq_symbols
from infra.alpaca_api import DATA_URL, AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import TraceError, committed_git_sha, load_runs, next_run_id, save_run

FAMILY = "reprise_apres_baisse"
CRITERIA_FILE = Path(__file__).resolve().parent / "criteres.json"
NEW_YORK = ZoneInfo("America/New_York")
# Offre gratuite Alpaca : les barres consolidées (SIP) des 15 dernières minutes ne sont pas servies.
SIP_DELAY = timedelta(minutes=15)
# Couvre largement les 61 séances nécessaires aux critères (jours fériés compris).
DAILY_HISTORY = timedelta(days=130)


def _pct(value):
    return f"{value * 100:+.2f} %"


def run():
    criteria = Criteria.from_file(CRITERIA_FILE)
    now = datetime.now(timezone.utc)
    session_date = now.astimezone(NEW_YORK).date()
    key = session_date.isoformat()

    done = [r for r in load_runs(FAMILY) if r["session_date"] == key]
    if done:
        print(f"Run déjà produit pour la séance du {key} : {done[0]['run_id']}.")
        return 0

    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    session = alpaca.session(session_date)
    if session is None:
        print(f"Marché fermé le {key} (calendrier Alpaca) : aucun run.")
        return 0

    market_open = datetime.combine(session_date, session[0], NEW_YORK).astimezone(timezone.utc)
    decision_time = market_open + timedelta(minutes=criteria.first_hour_minutes)
    ready_at = decision_time + SIP_DELAY
    if now < ready_at:
        print(f"Trop tôt : les données de la première heure seront disponibles à "
              f"{ready_at.astimezone(NEW_YORK):%H:%M} (New York).")
        return 1

    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    candidates, _ = daily_candidates(daily, decision_time, criteria)
    minute = cached(f"{key}/minute_bars",
                    lambda: alpaca.bars([c.symbol for c in candidates], "1Min", market_open, decision_time))
    selection, funnel = screen(daily, minute, market_open, decision_time, criteria)

    payload = {
        "run_id": next_run_id(FAMILY),
        "family": FAMILY,
        "status": "diagnostic",
        "session_date": key,
        "market_open": market_open.isoformat(),
        "decision_time": decision_time.isoformat(),
        "created_at": now.isoformat(),
        "git_sha": git_sha,
        "criteria": criteria.to_json(),
        "sources": {
            "alpaca": {"trading_api": alpaca.trading_url, "data_api": DATA_URL, "feed": "sip", "adjustment": "all"},
            "nasdaq_trader": listings_created,
        },
        "funnel": {**universe_funnel, **funnel},
        "selection": [{**item, "name": listings[item["symbol"]]["name"]} for item in selection],
    }
    path = save_run(FAMILY, payload)

    print(f"Séance du {key}, décision à {decision_time.astimezone(NEW_YORK):%H:%M} (New York) — "
          f"run {payload['run_id']}, statut diagnostic, code {git_sha[:7]}")
    print("Entonnoir : " + " → ".join(f"{step} {n}" for step, n in payload["funnel"].items()))
    print(f"n = {len(selection)} titres sur {criteria.count} demandés :")
    for item in payload["selection"]:
        print(f"{item['rank']:>3}. {item['symbol']:<6} {item['name'][:40]:<40} "
              f"mois {_pct(item['return_month'])}  J-2 {_pct(item['return_day_minus_2'])}  "
              f"J-1 {_pct(item['return_day_minus_1'])}  1re heure {_pct(item['return_first_hour'])}")
    print(f"Résultats : {path}")
    return 0


def main():
    try:
        return run()
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
