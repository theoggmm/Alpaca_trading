"""
Liste du panier « Volatilité » (core/volatility.py, décision T25) pour une séance : décidée à l'ouverture avec les
seules séances terminées avant, gardée dans research/experiments/runs/volatilite/<run_id>/results.json (règle 5).
Le suivi (dashboard/volatility.py) la produit lui-même au début de chaque tour ; à la main, depuis la racine :
    .venv/bin/python -m research.algorithms.volatilite.run [AAAA-MM-JJ]
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core.universe import eligible_symbols
from core.volatility import VolatilityRules, screen_basket
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.trace import committed_git_sha, load_runs, next_run_id, save_run

FAMILY = "volatilite"
HERE = Path(__file__).resolve().parent
RULES_FILE = HERE / "regles.json"
NEW_YORK = ZoneInfo("America/New_York")
# Historique quotidien lu : 126 séances de tendance + marge (jours fériés, week-ends).
DAILY_HISTORY = timedelta(days=280)


def rules():
    return VolatilityRules.from_file(RULES_FILE)


def list_for(session_date):
    """Le run de la séance s'il existe déjà (le plus récent), sinon None."""
    runs = [r for r in load_runs(FAMILY) if r["session_date"] == session_date.isoformat()]
    return runs[-1] if runs else None


def produce(alpaca, session_date):
    """Produit et enregistre la liste de la séance (décision à l'ouverture). Retourne le payload."""
    git_sha = committed_git_sha()
    session = alpaca.session(session_date)
    if session is None:
        raise ValueError(f"Marché fermé le {session_date} (calendrier Alpaca)")
    market_open = datetime.combine(session_date, session[0], NEW_YORK).astimezone(timezone.utc)
    key = session_date.isoformat()
    config = rules()
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    eligible, _ = eligible_symbols(assets, listings)
    listed = {a["symbol"] for a in assets if a.get("exchange") == config.exchange}
    symbols = [s for s in eligible if s in listed]
    daily = cached(f"{key}/volatilite_daily",
                   lambda: alpaca.bars(symbols, "1Day", market_open - DAILY_HISTORY, market_open))

    def domains_for(names):
        return {s: p["domain"] for s, p in sec.profiles(names, key).items()}

    selection, summary = screen_basket(daily, market_open, config, domains_for)
    payload = {
        "run_id": next_run_id(FAMILY),
        "family": FAMILY,
        "variant": "panier",
        "strategy": FAMILY,
        "status": "diagnostic",
        "session_date": key,
        "market_open": market_open.isoformat(),
        "decision_time": market_open.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "criteria": config.to_json(),
        "sources": {"alpaca": {"bars": "1Day, feed sip", "assets": "exchange"},
                    "nasdaq_trader": listings_created,
                    "sec": {"tickers": sec.TICKERS_URL, "profiles": "data.sec.gov/submissions (ownerOrg)"}},
        "universe": {"exchange_symbols": len(symbols), "liquid_strict": summary["liquid"]},
        "summary": summary,
        "selection": [{**item, "rank": rank, "name": listings.get(item["symbol"], {}).get("name", "")}
                      for rank, item in enumerate(selection, start=1)],
    }
    save_run(FAMILY, payload)
    return payload


def main():
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    existing = list_for(day)
    if existing:
        print(f"Liste du {day} déjà produite : run {existing['run_id']} ({len(existing['selection'])} titres).")
        return 0
    payload = produce(AlpacaReader(), day)
    print(f"Liste du {day} : run {payload['run_id']}, {len(payload['selection'])} titres, "
          f"code {payload['git_sha'][:7]}, statut diagnostic.")
    for d, info in payload["summary"]["domains"].items():
        names = ", ".join(i["symbol"] for i in payload["selection"] if i["domain"] == d)
        print(f"  {d} : {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
