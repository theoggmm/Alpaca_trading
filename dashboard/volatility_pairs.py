"""
Suivi de la stratégie « Volatilité — 2 actions » (décision T29, test T28) et ses pages : dashboard/volatilite_2.html
(anglais : volatility_2_en.html).

Chaque séance, depuis le 23 octobre 2026 : parmi les 39 actions de la liste Volatilité (run r001), les 2 les plus
volatiles sur les 20 dernières séances (core/volatility.rank_by_volatility) sont achetées 5 000 $ chacune au cours
d'ouverture de la minute 9 h 31 ; chacune est vendue dès que son gain net atteint 200 $, sinon 3 h 30 après l'achat si
elle est positive, sinon à la clôture du jour (core/volatility.exit_with_deadline, variante C). Rien n'est gardé la
nuit : chaque jour est indépendant. Jours terminés gardés dans research/experiments/final/volatilite/paires/<date>.json
(durable) ; état en cours dans research/outputs/live/volatilite_paires.json (volatil). Rien n'achète : simulation.

Appelé à chaque passage du suivi en direct (dashboard/live.py) ; à la main, depuis la racine du dépôt :
    .venv/bin/python -m dashboard.volatility_pairs
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core.volatility import exit_with_deadline, net_gain, rank_by_volatility
from dashboard.build import FINALS_DIR, VOLATILITY_PAIRS_LIVE, _embed
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import TraceError
from research.algorithms.volatilite import run as basket

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "volatility_pairs_template.html"
PAGES = {"fr": HERE / "volatilite_2.html", "en": HERE / "volatility_2_en.html"}
DAYS_DIR = FINALS_DIR / basket.FAMILY / "paires"
NEW_YORK = ZoneInfo("America/New_York")
FIRST_DAY = date(2026, 10, 23)
LIST_DAY = date(2026, 10, 21)            # liste des 39 (run r001)
PICKS = 2
AMOUNT, TARGET, COST_BPS = Decimal("5000"), Decimal("200"), Decimal("5")
BUY_AFTER_OPEN = timedelta(minutes=1)    # cours d'ouverture de la minute 9 h 31
DEADLINE = timedelta(hours=3, minutes=30)
VOLATILITY_SESSIONS = 20
DAILY_HISTORY = timedelta(days=60)
FEED_DELAY = timedelta(minutes=15)
EMPTY_BARS = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])


def _sessions(alpaca, now):
    """
    [(date, ouverture UTC, clôture UTC)] des séances depuis la dernière avant FIRST_DAY (repère de la clôture de la
    veille) jusqu'à la prochaine (incluse).
    """
    found = []
    for day, o, c in alpaca.sessions(FIRST_DAY - timedelta(days=10), now.astimezone(NEW_YORK).date() + timedelta(days=10)):
        times = tuple(datetime.combine(day, t, NEW_YORK).astimezone(timezone.utc) for t in (o, c))
        found.append((day, *times))
        if times[0] > now:
            break
    before = [s for s in found if s[0] < FIRST_DAY]
    return before[-1:] + [s for s in found if s[0] >= FIRST_DAY]


def _picks(alpaca, day, market_open, listing, now):
    """
    Les 2 actions du jour : classement connu dès la clôture de la veille (séances terminées avant l'ouverture).
    Avant l'ouverture, lu sans cache (rien de plus récent que maintenant - 15 min) ; ensuite, gardé en cache.
    """
    symbols = sorted(listing)
    if now < market_open:
        daily = alpaca.bars(symbols, "1Day", market_open - DAILY_HISTORY, now - FEED_DELAY)
    else:
        daily = cached(f"{day.isoformat()}/volatilite_paires_daily",
                       lambda: alpaca.bars(symbols, "1Day", market_open - DAILY_HISTORY, market_open))
    return rank_by_volatility(daily, market_open, symbols, VOLATILITY_SESSIONS)[:PICKS]


def _bars(alpaca, symbols, day, start, end, now):
    if now <= start + FEED_DELAY:
        return EMPTY_BARS
    if now >= end + FEED_DELAY:
        return cached(f"{day.isoformat()}/volatilite_paires_minute_{'_'.join(sorted(symbols))}",
                      lambda: alpaca.bars(sorted(symbols), "1Min", start, end))
    return alpaca.bars(sorted(symbols), "1Min", start, min(end, now - FEED_DELAY))


def _position(symbol, volatility, bars, market_open, market_close, listing):
    """Une action du jour : achat à 9 h 31, vente selon la règle (variante C), ou état en cours."""
    item = listing[symbol]
    base = {"symbol": symbol, "name": item["name"], "domain": item["domain"],
            "volatility_20": round(volatility * (252 ** 0.5), 4), "status": "waiting"}
    mine = bars[(bars["symbol"] == symbol) & (bars["timestamp"] >= market_open + BUY_AFTER_OPEN)
                & (bars["timestamp"] < market_close)].sort_values("timestamp")
    if mine.empty:
        return base
    buy_at = mine["timestamp"].iloc[0]
    entry = mine["open"].iloc[0]
    path = [(t + timedelta(minutes=1), c) for t, c in zip(mine["timestamp"], mine["close"])]
    sale = exit_with_deadline(path, entry, AMOUNT, TARGET, COST_BPS, buy_at + DEADLINE, market_close, "cloture")
    last_at, last = path[-1]
    money = lambda v: str(v.quantize(Decimal("0.01")))
    position = {**base, "buy_at": buy_at.isoformat(), "entry": str(entry)}
    if sale:
        return {**position, "status": "sold", "exit_at": sale["exit_at"].isoformat(), "price": str(sale["price"]),
                "gain": money(sale["gain"]), "reason": sale["reason"],
                "held_seconds": (sale["exit_at"] - buy_at).total_seconds()}
    gain = net_gain(AMOUNT / entry * last, AMOUNT, COST_BPS)
    return {**position, "status": "live", "price": str(last), "gain": money(gain), "checked_at": last_at.isoformat(),
            "held_seconds": (last_at - buy_at).total_seconds(), "deadline": (buy_at + DEADLINE).isoformat()}


def update(alpaca, now=None):
    """Jours recalculés jusqu'à now, jours terminés gardés (durable), état écrit (volatil), pages régénérées."""
    now = now or datetime.now(timezone.utc)
    first = basket.list_for(LIST_DAY)
    listing = {i["symbol"]: i for i in first["selection"]}
    days = []
    every = _sessions(alpaca, now)
    for (_, _, prev_close), (day, market_open, market_close) in zip(every, every[1:]):
        # Prochaine séance : la paire n'est connue qu'une fois la veille terminée (données servies 15 min après).
        if now < prev_close + FEED_DELAY:
            days.append({"day": day.isoformat(), "market_open": market_open.isoformat(),
                         "market_close": market_close.isoformat(), "positions": [], "gain": None, "done": False})
            continue
        saved = DAYS_DIR / f"{day.isoformat()}.json"
        if saved.exists():
            days.append(json.loads(saved.read_text(encoding="utf-8")))
            continue
        picks = _picks(alpaca, day, market_open, listing, now)
        bars = _bars(alpaca, [s for s, _ in picks], day, market_open, market_close, now)
        positions = [_position(s, v, bars, market_open, market_close, listing) for s, v in picks]
        gains = [Decimal(p["gain"]) for p in positions if p.get("gain") is not None]
        record = {"day": day.isoformat(), "market_open": market_open.isoformat(), "market_close": market_close.isoformat(),
                  "positions": positions, "gain": str(sum(gains, Decimal(0))) if gains else None,
                  "done": all(p["status"] == "sold" for p in positions) and now >= market_close + FEED_DELAY}
        if record["done"]:
            DAYS_DIR.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        days.append(record)
    page = {"updated": now.isoformat(), "amount": str(AMOUNT), "target_gain": str(TARGET), "cost_bps": str(COST_BPS),
            "days": days}
    VOLATILITY_PAIRS_LIVE.parent.mkdir(parents=True, exist_ok=True)
    VOLATILITY_PAIRS_LIVE.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8").replace("__STATE_JSON__", _embed(page))
    for lang, out in PAGES.items():
        out.write_text(template.replace("__LANG__", lang), encoding="utf-8")
    return page


def main():
    try:
        page = update(AlpacaReader())
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    for d in page["days"]:
        picks = ", ".join(f"{p['symbol']} ({p['status']}{'' if p.get('gain') is None else ' ' + p['gain'] + ' $'})"
                          for p in d["positions"])
        print(f"{d['day']} : {picks} — total {d['gain']} $")
    print(f"Pages : {PAGES['fr']} · {PAGES['en']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
