"""
Suivi en direct des bulles par domaine pendant la séance de New York.

Toutes les minutes : derniers prix (toutes bourses, 15 min de retard), moyenne par domaine pour
la journée, la première heure, 2 séances, 1 semaine et 1 mois, puis régénération du tableau de bord
(qui se recharge seul). S'arrête seul après la clôture. Ctrl+C pour arrêter avant.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.live reprise_apres_baisse
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from core.domains import WEEK_SESSIONS, live_domain_trends
from core.screener import Criteria, liquid_universe
from core.universe import eligible_symbols
from dashboard.build import LIVE_FILE, build
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import ROOT

NEW_YORK = ZoneInfo("America/New_York")
FEED = "delayed_sip"
FEED_DELAY = timedelta(minutes=15)
REFRESH_S = 60
DAILY_HISTORY = timedelta(days=130)


def _criteria(family):
    return Criteria.from_file(ROOT / "research" / "algorithms" / family / "criteres.json")


def _prepare(alpaca, criteria, key, market_open):
    """Univers liquide (séances terminées avant l'ouverture) et domaines SEC : une fois par séance."""
    listings, _ = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, _ = eligible_symbols(assets, listings)
    daily = cached(f"{key}/live_daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", market_open - DAILY_HISTORY, market_open))
    liquid, _ = liquid_universe(daily, market_open, criteria)
    profiles = sec.profiles([s.symbol for s in liquid], key)
    return daily, [s.symbol for s in liquid], {s: p["domain"] for s, p in profiles.items()}


def run(family):
    criteria = _criteria(family)
    alpaca = AlpacaReader()
    session_date = datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    key = session_date.isoformat()
    session = alpaca.session(session_date)
    if session is None:
        print(f"Marché fermé le {key} (calendrier Alpaca).")
        return 0
    market_open = datetime.combine(session_date, session[0], NEW_YORK).astimezone(timezone.utc)
    market_close = datetime.combine(session_date, session[1], NEW_YORK).astimezone(timezone.utc)
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    # Avec 15 min de retard, les derniers échanges de la séance arrivent jusqu'à clôture + 15 min.
    stop_at = market_close + FEED_DELAY

    if datetime.now(timezone.utc) >= stop_at:
        print(f"Séance du {key} terminée : rien à suivre.")
        return 0
    print("Préparation : univers liquide et domaines (quelques minutes la première fois)…")
    daily, symbols, domains = _prepare(alpaca, criteria, key, market_open)
    minute = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])

    while True:
        now = datetime.now(timezone.utc)
        if now >= stop_at:
            print("Clôture passée : suivi terminé.")
            return 0
        if now < market_open + FEED_DELAY:
            print(f"En attente des premiers prix (à {(market_open + FEED_DELAY).astimezone(NEW_YORK):%H:%M}, New York).")
            time.sleep(REFRESH_S)
            continue
        try:
            if minute.empty and now >= first_hour_end + FEED_DELAY:
                minute = cached(f"{key}/live_first_hour_bars",
                                lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
            trades = alpaca.latest_trades(symbols, FEED)
        except FetchError as e:
            print(f"{now.astimezone(NEW_YORK):%H:%M} — lecture impossible, nouvel essai dans {REFRESH_S} s : {e}")
            time.sleep(REFRESH_S)
            continue

        measures, universe = live_domain_trends(daily, trades, minute, market_open, market_close, now,
                                                criteria, domains)
        used = [ts for ts, _ in trades.values() if market_open <= ts <= min(now, market_close)]
        LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_FILE.write_text(json.dumps({
            "family": family,
            "session_date": key,
            "observed_at": now.isoformat(),
            "prices_until": max(used).isoformat() if used else None,
            "feed": FEED,
            "universe": universe,
            "first_hour_minutes": criteria.first_hour_minutes,
            "sessions": {"two_days": criteria.up_days, "week": WEEK_SESSIONS, "month": criteria.month_sessions},
            "measures": measures,
        }, ensure_ascii=False), encoding="utf-8")
        build(family)
        day = measures["day"]["bubbles"]
        up = sum(1 for b in day if b["mean_return"] > 0)
        print(f"{now.astimezone(NEW_YORK):%H:%M} (New York) — {len(used)} prix, journée : "
              f"{up} domaines en hausse, {len(day) - up} en baisse")
        time.sleep(REFRESH_S)


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.live <famille>")
    try:
        return run(sys.argv[1])
    except (FetchError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSuivi arrêté.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
