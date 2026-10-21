"""
Suivi de la stratégie « Volatilité » (core/volatility.py, décisions T25, T26) et ses pages : dashboard/volatilite.html
(anglais : volatility_en.html).

Une vague par séance (T27) : à chaque ouverture, chaque action de la liste fixe — celle du premier jour, la même
pour toutes les vagues — est achetée de zéro pour un montant fixe (5 000 $), même si une vague précédente la détient
encore. Dans une vague, chaque action est gardée seule — sur autant de séances qu'il faut — jusqu'à la première
minute de séance où son gain net atteint l'objectif (200 $), puis vendue ; rien ne se vend la nuit (un objectif
franchi pendant la fermeture est vendu à la première minute de l'ouverture). Les vagues tournent côte à côte jusqu'à
ce que toutes leurs actions aient atteint l'objectif. Tout est recalculé depuis les barres minute à chaque passage ;
les ventes sont gardées dans research/experiments/final/volatilite/ventes.json (durable), l'état en cours dans
research/outputs/live/volatilite.json (volatil). Rien n'achète : simulation seulement.

Appelé à chaque passage du suivi en direct (dashboard/live.py) ; à la main, depuis la racine du dépôt :
    .venv/bin/python -m dashboard.volatility
"""

import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core.volatility import track_round
from dashboard.build import FINALS_DIR, VOLATILITY_LIVE, _embed
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import TraceError
from research.algorithms.volatilite import run as basket

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "volatility_template.html"
PAGES = {"fr": HERE / "volatilite.html", "en": HERE / "volatility_en.html"}
SALES_FILE = FINALS_DIR / basket.FAMILY / "ventes.json"
NEW_YORK = ZoneInfo("America/New_York")
# Premiers achats : ouverture du 21 octobre 2026 (décision du propriétaire, T25). Sa liste sert à toutes les vagues (T27).
FIRST_SESSION = date(2026, 10, 21)
# Offre gratuite Alpaca : les 15 dernières minutes ne sont pas servies.
FEED_DELAY = timedelta(minutes=15)
EMPTY_BARS = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])


def _sessions(alpaca, now):
    """[(date, ouverture UTC, clôture UTC)] des séances depuis FIRST_SESSION, plus la prochaine si elle n'a pas ouvert."""
    today = now.astimezone(NEW_YORK).date()
    found = []
    for day, o, c in alpaca.sessions(FIRST_SESSION, today + timedelta(days=10)):
        times = tuple(datetime.combine(day, t, NEW_YORK).astimezone(timezone.utc) for t in (o, c))
        found.append((day, *times))
        if times[0] > now:
            break
    return found


def _bars(alpaca, symbols, session, now):
    """Barres minute des titres pendant une séance : séance finie en cache, séance en cours relue."""
    day, start, end = session
    if not symbols or now <= start + FEED_DELAY:
        return EMPTY_BARS
    if now >= end + FEED_DELAY:
        tag = hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()[:12]
        return cached(f"{day.isoformat()}/volatilite_minute_{tag}", lambda: alpaca.bars(sorted(symbols), "1Min", start, end))
    return alpaca.bars(sorted(symbols), "1Min", start, min(end, now - FEED_DELAY))


def _held(entry, until, sessions):
    """(secondes écoulées, secondes de marché ouvert) entre l'achat et until."""
    market = sum(max(0, (min(end, until) - max(start, entry)).total_seconds()) for _, start, end in sessions)
    return (until - entry).total_seconds(), market


def positions(alpaca, now):
    """
    Toutes les positions depuis FIRST_SESSION, connues à now, et la prochaine séance (None si une séance est ouverte).
    Une position : {symbol, name, domain, step, run_id, session_date, entry_time, status, entry, last, value, gain,
    best_gain, sold_at, sold_gain, sessions_held, elapsed_seconds, market_seconds}.
    """
    rules = basket.rules()
    every = _sessions(alpaca, now)
    started = [s for s in every if s[1] <= now]
    upcoming = next((s for s in every if s[1] > now), None)
    fixed = (basket.list_for(FIRST_SESSION) or basket.produce(alpaca, FIRST_SESSION)) if started else None
    lists = {day: fixed for day, _, _ in started}
    symbols = sorted({i["symbol"] for i in fixed["selection"]}) if fixed else []
    bars = [_bars(alpaca, symbols, s, now) for s in started]
    bars = [b for b in bars if not b.empty]
    bars = pd.concat(bars, ignore_index=True) if bars else EMPTY_BARS
    by_symbol = {s: g for s, g in bars.groupby("symbol", sort=True)}

    result = []
    money = lambda v: None if v is None else str(v.quantize(Decimal("0.01")))
    for day, market_open, _ in started:
        # Une vague : toute la liste achetée de zéro à cette ouverture, indépendamment des vagues précédentes.
        for item in lists[day]["selection"]:
            s = item["symbol"]
            windows = [(o, c) for d, o, c in started if o >= market_open]
            state = track_round([s], by_symbol.get(s, EMPTY_BARS), market_open, windows, now,
                                rules.amount_per_stock, rules.target_gain, rules.cost_bps)
            until = (datetime.fromisoformat(state["sold_at"]) if state["sold_at"] else
                     datetime.fromisoformat(state["checked_until"]) if state["checked_until"] else market_open)
            elapsed, market = _held(market_open, until, [x for x in started if x[1] >= market_open])
            entry, last = state["entry"].get(s), state["last"].get(s)
            position = {
                **{k: item[k] for k in ("symbol", "name", "domain", "step")},
                "run_id": lists[day]["run_id"], "session_date": day.isoformat(), "entry_time": market_open.isoformat(),
                "status": state["status"], "entry": None if entry is None else str(entry),
                "last": None if last is None else str(last),
                "return": None if entry is None else float(last / entry - 1),
                "value": money(state["value"]), "gain": money(state["gain"]), "best_gain": money(state["best_gain"]),
                "sold_at": state["sold_at"], "sold_gain": money(state["sold_gain"]),
                "sessions_held": state["sessions_held"], "elapsed_seconds": elapsed, "market_seconds": market,
            }
            result.append(position)
    return result, upcoming, lists


def update(alpaca, now=None):
    """Positions recalculées jusqu'à now, ventes gardées (durable), état écrit (volatil), pages régénérées."""
    now = now or datetime.now(timezone.utc)
    rules = basket.rules()
    every, upcoming, lists = positions(alpaca, now)
    sold = [p for p in every if p["status"] == "sold"]
    SALES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SALES_FILE.write_text(json.dumps(sold, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    latest = lists[max(lists)] if lists else None
    page = {"updated": now.isoformat(), "amount_per_stock": str(rules.amount_per_stock),
            "target_gain": str(rules.target_gain), "per_domain": rules.per_domain, "cost_bps": str(rules.cost_bps),
            "next_open": None if upcoming is None else upcoming[1].isoformat(),
            "latest_list": None if latest is None else {"session_date": latest["session_date"], "run_id": latest["run_id"],
                                                        "n": len(latest["selection"])},
            "open": [p for p in every if p["status"] != "sold"], "sold": sold}
    VOLATILITY_LIVE.parent.mkdir(parents=True, exist_ok=True)
    VOLATILITY_LIVE.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    render(page)
    return page


def render(page):
    template = TEMPLATE.read_text(encoding="utf-8").replace("__STATE_JSON__", _embed(page))
    for lang, out in PAGES.items():
        out.write_text(template.replace("__LANG__", lang), encoding="utf-8")


def main():
    try:
        page = update(AlpacaReader())
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    for p in page["sold"]:
        print(f"{p['symbol']} acheté le {p['session_date']} : vendu {p['sold_at']}, gain net {p['sold_gain']} $, "
              f"{p['elapsed_seconds'] / 3600:.1f} h, {p['sessions_held']} séance(s)")
    gains = [Decimal(p["gain"]) for p in page["open"] if p["gain"] is not None]
    print(f"Détenus : {len(page['open'])} titres ({len(page['open']) * Decimal(page['amount_per_stock'])} $), "
          f"gain net en cours {sum(gains, Decimal(0))} $ ; vendus : {len(page['sold'])}.")
    print(f"Pages : {PAGES['fr']} · {PAGES['en']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
