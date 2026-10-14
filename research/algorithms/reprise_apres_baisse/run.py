"""
Run quotidien du screener « reprise après baisse ».

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.run
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.domains import domain_trends
from core.screener import Criteria, daily_candidates, liquid_universe, screen
from core.universe import eligible_symbols
from infra import nasdaq_symbols, sec
from infra.alpaca_api import DATA_URL, AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import TraceError, committed_git_sha, load_runs, next_run_id, save_run

FAMILY = "reprise_apres_baisse"
CRITERIA_FILE = Path(__file__).resolve().parent / "criteres.json"
NEW_YORK = ZoneInfo("America/New_York")
# Offre gratuite Alpaca : les barres consolidées (SIP) des 15 dernières minutes ne sont pas servies.
SIP_DELAY = timedelta(minutes=15)
# Lancé un peu avant que les données soient disponibles, le run attend au plus ce délai au lieu d'abandonner.
MAX_WAIT = timedelta(minutes=20)
# Couvre largement les 61 séances nécessaires aux critères (jours fériés compris).
DAILY_HISTORY = timedelta(days=130)


def _pct(value):
    return f"{value * 100:+.2f} %"


def produce(alpaca, criteria, session_date, market_open, now, git_sha):
    """
    Calcule le run d'une séance (sans l'enregistrer) : sélection, entonnoir, domaines, sources.
    Toutes les données sont tronquées à l'instant de décision (ouverture + première heure).
    """
    key = session_date.isoformat()
    decision_time = market_open + timedelta(minutes=criteria.first_hour_minutes)
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    candidates, _ = daily_candidates(daily, decision_time, criteria)
    minute = cached(f"{key}/minute_bars",
                    lambda: alpaca.bars([c.symbol for c in candidates], "1Min", market_open, decision_time))
    selection, funnel = screen(daily, minute, market_open, decision_time, criteria)

    # Domaines : complément de lecture, pas un critère. Une panne SEC n'empêche pas la liste, elle est enregistrée.
    liquid, _ = liquid_universe(daily, decision_time, criteria)
    try:
        profiles = sec.profiles([s.symbol for s in liquid], key)
        bubbles, unclassified = domain_trends(
            daily, decision_time, criteria, {symbol: p["domain"] for symbol, p in profiles.items()})
        domains = {"bubbles": bubbles, "unclassified": unclassified,
                   "measure": f"moyenne simple des variations sur {criteria.month_sessions} séances",
                   "universe": "titres à l'historique complet, au prix et au volume échangé suffisants"}
    except FetchError as e:
        profiles, domains = {}, {"error": str(e)}

    payload = {
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
            "sec": {"tickers": sec.TICKERS_URL, "profiles": "data.sec.gov/submissions (ownerOrg, sic)"},
        },
        "funnel": {**universe_funnel, **funnel},
        "domains": domains,
        "selection": [{**item, "name": listings[item["symbol"]]["name"],
                       "domain": profiles.get(item["symbol"], {}).get("domain"),
                       "sic_description": profiles.get(item["symbol"], {}).get("sic_description")}
                      for item in selection],
    }
    return payload


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
    ready_at = market_open + timedelta(minutes=criteria.first_hour_minutes) + SIP_DELAY
    if ready_at - MAX_WAIT <= now < ready_at:
        print(f"Données de la première heure disponibles à {ready_at.astimezone(NEW_YORK):%H:%M:%S} (New York) : "
              f"attente de {(ready_at - now).total_seconds():.0f} s.")
        time.sleep((ready_at - now).total_seconds())
        now = datetime.now(timezone.utc)
    if now < ready_at:
        print(f"Trop tôt : les données de la première heure seront disponibles à "
              f"{ready_at.astimezone(NEW_YORK):%H:%M} (New York).")
        return 1

    payload = {"run_id": next_run_id(FAMILY), **produce(alpaca, criteria, session_date, market_open, now, git_sha)}
    path = save_run(FAMILY, payload)
    selection = payload["selection"]
    decision_time = datetime.fromisoformat(payload["decision_time"])
    domains = payload["domains"]

    print(f"Séance du {key}, décision à {decision_time.astimezone(NEW_YORK):%H:%M} (New York) — "
          f"run {payload['run_id']}, statut diagnostic, code {git_sha[:7]}")
    print("Entonnoir : " + " → ".join(f"{step} {n}" for step, n in payload["funnel"].items()))
    print(f"n = {len(selection)} titres sur {criteria.count} demandés :")
    for item in payload["selection"]:
        print(f"{item['rank']:>3}. {item['symbol']:<6} {item['name'][:40]:<40} "
              f"mois {_pct(item['return_month'])}  J-2 {_pct(item['return_day_minus_2'])}  "
              f"J-1 {_pct(item['return_day_minus_1'])}  1re heure {_pct(item['return_first_hour'])}")
    if "error" in domains:
        print(f"Domaines indisponibles : {domains['error']}")
    else:
        print(f"Tendance sur {criteria.month_sessions} séances par domaine (SEC), "
              f"{domains['unclassified']} titres non classés :")
        for bubble in domains["bubbles"]:
            print(f"     {bubble['domain']:<40} {_pct(bubble['mean_return'])}  n = {bubble['n']}")
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
