"""
Suivi en direct des bulles par domaine pendant la séance de New York, et état de fin de séance.

Toutes les minutes : derniers prix (toutes bourses, 15 min de retard), moyenne par domaine pour
la journée, la première heure, 2 séances, 1 semaine et 1 mois, variation depuis l'ouverture de
chaque titre de la sélection du jour, puis régénération du tableau de bord (qui se recharge seul).

Après la clôture (ou au réveil du Mac après la clôture), l'état de fin de séance est reconstitué
depuis l'historique minute d'Alpaca et gardé dans research/experiments/final/<famille>/<date>.json.
catch_up() refait cet état pour toute séance terminée qui n'en a pas.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.live reprise_apres_baisse
"""

import fcntl
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from core.domains import LIVE_MEASURES, WEEK_SESSIONS, live_domain_trends
from core.screener import Criteria, changes_since_open, last_session_prices, liquid_universe
from core.universe import eligible_symbols
from dashboard.build import FINALS_DIR, LIVE_FILE, build
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import ROOT, committed_git_sha, load_runs

NEW_YORK = ZoneInfo("America/New_York")
FEED = "delayed_sip"
# Offre gratuite Alpaca : les 15 dernières minutes de données consolidées ne sont pas servies.
FEED_DELAY = timedelta(minutes=15)
REFRESH_S = 60
DAILY_HISTORY = timedelta(days=130)
# Fenêtre lue pour retrouver le dernier échange de chaque titre avant la clôture.
CLOSING_WINDOW = timedelta(minutes=30)
EMPTY_BARS = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])


def _criteria(family):
    return Criteria.from_file(ROOT / "research" / "algorithms" / family / "criteres.json")


def _times(session_date, open_time, close_time):
    """(ouverture, clôture) en UTC d'une séance donnée en heure de New York."""
    return tuple(datetime.combine(session_date, t, NEW_YORK).astimezone(timezone.utc) for t in (open_time, close_time))


def _prepare(alpaca, criteria, key, market_open):
    """Univers liquide (séances terminées avant l'ouverture) et domaines SEC : une fois par séance."""
    listings, _ = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, _ = eligible_symbols(assets, listings)
    daily = cached(f"{key}/live_daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", market_open - DAILY_HISTORY, market_open))
    liquid, _ = liquid_universe(daily, market_open, criteria)
    profiles = sec.profiles([s.symbol for s in liquid], key)
    names = {s.symbol: listings[s.symbol]["name"] for s in liquid}
    return daily, [s.symbol for s in liquid], {s: p["domain"] for s, p in profiles.items()}, names


def _selection(family, key):
    """Run du screener de la séance (None s'il n'existe pas encore) et premier prix de chaque titre."""
    run = next((r for r in load_runs(family) if r["session_date"] == key), None)
    return run, {item["symbol"]: Decimal(item["open_today"]) for item in (run or {}).get("selection", [])}


def _state(family, criteria, key, market_open, market_close, now, daily, domains, names, trades, minute, run, opens):
    """État affiché par le tableau de bord, calculé avec les seules données connues à now."""
    measures, liquid, values = live_domain_trends(daily, trades, minute, market_open, market_close, now,
                                                  criteria, domains)
    used = [ts for ts, _ in trades.values() if market_open <= ts <= min(now, market_close)]
    return {
        "family": family,
        "session_date": key,
        "observed_at": now.isoformat(),
        "prices_until": max(used).isoformat() if used else None,
        "feed": FEED,
        "universe": len(liquid),
        # Une ligne par titre de l'univers ; variation absente (None) si non calculable.
        "stocks": {
            "columns": ["symbol", "name", "domain", *LIVE_MEASURES],
            "rows": [[s, names.get(s, ""), domains.get(s),
                      *(None if s not in values[m] else round(values[m][s], 6) for m in LIVE_MEASURES)]
                     for s in liquid],
        },
        "first_hour_minutes": criteria.first_hour_minutes,
        "sessions": {"two_days": criteria.up_days, "week": WEEK_SESSIONS, "month": criteria.month_sessions},
        "measures": measures,
        "selection": run and {"run_id": run["run_id"],
                              "changes": changes_since_open(opens, trades, market_open, market_close, now)},
    }


def finalize(family, alpaca, criteria, session_date, open_time, close_time):
    """
    État de fin de séance reconstitué depuis l'historique minute : dernier échange de chaque titre
    avant la clôture (l'enchère de clôture n'est pas comptée). Écrit research/experiments/final/.
    """
    key = session_date.isoformat()
    market_open, market_close = _times(session_date, open_time, close_time)
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    git_sha = committed_git_sha()

    daily, symbols, domains, names = _prepare(alpaca, criteria, key, market_open)
    run, opens = _selection(family, key)
    tracked = sorted(set(symbols) | set(opens))
    minute = cached(f"{key}/live_first_hour_bars", lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
    closing = cached(f"{key}/final_closing_bars",
                     lambda: alpaca.bars(tracked, "1Min", market_close - CLOSING_WINDOW, market_close))
    trades = last_session_prices(closing, market_close)

    state = _state(family, criteria, key, market_open, market_close, market_close,
                   daily, domains, names, trades, minute, run, opens)
    state.update(final=True, computed_at=datetime.now(timezone.utc).isoformat(), git_sha=git_sha,
                 source="historique minute Alpaca (toutes bourses), dernière barre terminée à la clôture")
    path = FINALS_DIR / family / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    # Le dernier état affiché devient l'état final s'il porte sur cette séance ou une plus ancienne.
    live = json.loads(LIVE_FILE.read_text(encoding="utf-8")) if LIVE_FILE.exists() else None
    if live is None or live["session_date"] <= key:
        LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return path


def catch_up(family):
    """Produit l'état de fin de séance de chaque séance terminée sans état, depuis le premier run."""
    runs = load_runs(family)
    if not runs:
        return []
    criteria = _criteria(family)
    alpaca = AlpacaReader()
    now = datetime.now(timezone.utc)
    first = datetime.fromisoformat(runs[0]["session_date"]).date()
    done = []
    for session_date, open_time, close_time in alpaca.sessions(first, now.astimezone(NEW_YORK).date()):
        _, market_close = _times(session_date, open_time, close_time)
        if now >= market_close + FEED_DELAY and not (FINALS_DIR / family / f"{session_date}.json").exists():
            done.append(finalize(family, alpaca, criteria, session_date, open_time, close_time))
    if done:
        build(family)
    return done


def _single_instance():
    """Verrou tenu tant que le processus vit : un seul suivi à la fois. None si un autre tourne déjà."""
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = open(LIVE_FILE.parent / "tracker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def run(family):
    lock = _single_instance()
    if lock is None:
        print("Le suivi en direct tourne déjà : rien à faire.")
        return 0
    criteria = _criteria(family)
    alpaca = AlpacaReader()
    session_date = datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    key = session_date.isoformat()
    session = alpaca.session(session_date)
    if session is None:
        print(f"Marché fermé le {key} (calendrier Alpaca).")
        return 0
    market_open, market_close = _times(session_date, *session)
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    # Avec 15 min de retard, les derniers échanges de la séance arrivent jusqu'à clôture + 15 min.
    stop_at = market_close + FEED_DELAY

    print("Préparation : univers liquide et domaines (quelques minutes la première fois)…")
    daily, symbols, domains, names = _prepare(alpaca, criteria, key, market_open)
    minute = EMPTY_BARS

    while True:
        now = datetime.now(timezone.utc)
        if now >= stop_at:
            print("Clôture passée : état de fin de séance reconstitué depuis l'historique minute…")
            for path in catch_up(family):
                print(f"État de fin de séance : {path}")
            return 0
        if now < market_open + FEED_DELAY:
            print(f"En attente des premiers prix (à {(market_open + FEED_DELAY).astimezone(NEW_YORK):%H:%M}, New York).")
            time.sleep(REFRESH_S)
            continue
        # La sélection du jour existe une fois le run du screener produit (après 10 h 45, New York).
        today_run, opens = _selection(family, key)
        try:
            if minute.empty and now >= first_hour_end + FEED_DELAY:
                minute = cached(f"{key}/live_first_hour_bars",
                                lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
            trades = alpaca.latest_trades(sorted(set(symbols) | set(opens)), FEED)
        except FetchError as e:
            print(f"{now.astimezone(NEW_YORK):%H:%M} — lecture impossible, nouvel essai dans {REFRESH_S} s : {e}")
            time.sleep(REFRESH_S)
            continue

        state = _state(family, criteria, key, market_open, market_close, now,
                       daily, domains, names, trades, minute, today_run, opens)
        LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        build(family)
        day = state["measures"]["day"]["bubbles"]
        up = sum(1 for b in day if b["mean_return"] > 0)
        print(f"{now.astimezone(NEW_YORK):%H:%M} (New York) — journée : "
              f"{up} domaines en hausse, {len(day) - up} en baisse")
        time.sleep(REFRESH_S)


def main(command=run):
    if len(sys.argv) != 2:
        sys.exit(f"Usage : python -m {sys.argv[0]} <famille>")
    try:
        return command(sys.argv[1])
    except (FetchError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSuivi arrêté.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
