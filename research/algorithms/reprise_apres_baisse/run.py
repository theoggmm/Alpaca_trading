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
from infra.trace import TraceError, committed_git_sha, load_runs, next_run_id, save_run, variant_of

FAMILY = "reprise_apres_baisse"
HERE = Path(__file__).resolve().parent
# Deux versions produites à chaque séance : variante -> fichier de critères. Depuis le 16 octobre 2026,
# les deux portent les règles « pas au sommet » et « confirmation » (décision à 10 h 45, achat à 11 h 00).
VARIANTS = {"sans_per": HERE / "criteres_sans_per.json", "per12": HERE / "criteres_per12.json"}
# Versions remplacées, pour la comparaison avant / après du test sur le passé.
ARCHIVED = {"sans_per_v1": HERE / "archive" / "criteres_v1_sans_per.json",
            "per12_v2": HERE / "archive" / "criteres_v2_per12.json"}
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
    Toutes les données sont tronquées à l'instant de décision (ouverture + première heure, + confirmation).
    """
    key = session_date.isoformat()
    decision_time = market_open + timedelta(minutes=criteria.decision_minutes)
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    candidates, _ = daily_candidates(daily, decision_time, criteria)
    minute = cached(f"{key}/minute_bars" if criteria.confirmation_minutes is None else f"{key}/minute_bars_{criteria.decision_minutes}",
                    lambda: alpaca.bars([c.symbol for c in candidates], "1Min", market_open, decision_time))
    selection, funnel = screen(daily, minute, market_open, decision_time, criteria,
                               earnings_for=lambda symbols: sec.eps(symbols, key))

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


def _report(payload, criteria, path):
    selection = payload["selection"]
    decision_time = datetime.fromisoformat(payload["decision_time"])
    print(f"[{payload['variant']}] Séance du {payload['session_date']}, décision à "
          f"{decision_time.astimezone(NEW_YORK):%H:%M} (New York) — run {payload['run_id']}, "
          f"critères version {criteria.version}, statut diagnostic, code {payload['git_sha'][:7]}")
    print("Entonnoir : " + " → ".join(f"{step} {n}" for step, n in payload["funnel"].items()))
    print(f"n = {len(selection)} titres sur {criteria.count} au plus :")
    for item in selection:
        pe = f"  PER {item['pe_ttm']}" if item.get("pe_ttm") else ""
        print(f"{item['rank']:>3}. {item['symbol']:<6} {item['name'][:40]:<40} "
              f"mois {_pct(item['return_month'])}  J-2 {_pct(item['return_day_minus_2'])}  "
              f"J-1 {_pct(item['return_day_minus_1'])}  1re heure {_pct(item['return_first_hour'])}{pe}")
    print(f"Résultats : {path}")


def run():
    now = datetime.now(timezone.utc)
    session_date = now.astimezone(NEW_YORK).date()
    key = session_date.isoformat()

    runs = [r for r in load_runs(FAMILY) if r["session_date"] == key]
    todo = {variant: Criteria.from_file(path) for variant, path in VARIANTS.items()
            if not any(variant_of(r) == variant for r in runs)}
    if not todo:
        print(f"Runs déjà produits pour la séance du {key} : {', '.join(r['run_id'] for r in runs)}.")
        return 0

    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    session = alpaca.session(session_date)
    if session is None:
        print(f"Marché fermé le {key} (calendrier Alpaca) : aucun run.")
        return 0

    market_open = datetime.combine(session_date, session[0], NEW_YORK).astimezone(timezone.utc)
    # Chaque version part dès que ses données sont disponibles (décision + 15 min). Seule la première attend
    # (lancement planifié quelques secondes trop tôt) ; une version plus tardive (confirmation, 11 h 00) qui
    # n'est pas prête est laissée au lancement suivant, sans retarder les autres.
    domains = None
    pending = []
    for i, (variant, criteria) in enumerate(sorted(todo.items(), key=lambda item: item[1].decision_minutes)):
        ready_at = market_open + timedelta(minutes=criteria.decision_minutes) + SIP_DELAY
        now = datetime.now(timezone.utc)
        if i == 0 and ready_at - MAX_WAIT <= now < ready_at:
            print(f"[{variant}] Données disponibles à {ready_at.astimezone(NEW_YORK):%H:%M:%S} (New York) : "
                  f"attente de {(ready_at - now).total_seconds():.0f} s.")
            time.sleep((ready_at - now).total_seconds())
            now = datetime.now(timezone.utc)
        if now < ready_at:
            print(f"[{variant}] Pas encore : données disponibles à {ready_at.astimezone(NEW_YORK):%H:%M} (New York), "
                  f"liste produite au prochain lancement.")
            pending.append(variant)
            continue
        payload = {"run_id": next_run_id(FAMILY), "variant": variant,
                   **produce(alpaca, criteria, session_date, market_open, now, git_sha)}
        _report(payload, criteria, save_run(FAMILY, payload))
        domains = payload["domains"]
    if domains is None:
        return 1 if pending else 0

    if "error" in domains:
        print(f"Domaines indisponibles : {domains['error']}")
    else:
        print(f"Tendance sur {criteria.month_sessions} séances par domaine (SEC), "
              f"{domains['unclassified']} titres non classés :")
        for bubble in domains["bubbles"]:
            print(f"     {bubble['domain']:<40} {_pct(bubble['mean_return'])}  n = {bubble['n']}")
    return 0


def main():
    try:
        return run()
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
