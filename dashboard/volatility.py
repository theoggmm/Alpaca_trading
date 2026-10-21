"""
Suivi de la stratégie « Volatilité » (core/volatility.py, décision T25) et ses pages : dashboard/volatilite.html
(anglais : volatility_en.html).

Un tour : la liste du panier est décidée à l'ouverture d'une séance, le montant y est réparti à parts égales à
l'ouverture, puis le panier est gardé — sur autant de séances qu'il faut — jusqu'à la première minute où le gain net
atteint l'objectif ; tout est alors vendu. Le tour suivant commence à l'ouverture de la séance d'après, avec une
liste refaite. Chaque tour vendu est gardé dans research/experiments/final/volatilite/<date de début>.json (durable) ;
le tour en cours dans research/outputs/live/volatilite.json (volatil). Rien n'achète : simulation seulement.

Appelé à chaque passage du suivi en direct (dashboard/live.py) ; à la main, depuis la racine du dépôt :
    .venv/bin/python -m dashboard.volatility
"""

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
ROUNDS_DIR = FINALS_DIR / basket.FAMILY
NEW_YORK = ZoneInfo("America/New_York")
# Premier tour : achat à l'ouverture du 21 octobre 2026 (décision du propriétaire, T25).
FIRST_ROUND = date(2026, 10, 21)
# Offre gratuite Alpaca : les 15 dernières minutes ne sont pas servies.
FEED_DELAY = timedelta(minutes=15)


def _times(day, open_time, close_time):
    return tuple(datetime.combine(day, t, NEW_YORK).astimezone(timezone.utc) for t in (open_time, close_time))


def _next_session(alpaca, start):
    """(date, ouverture UTC, clôture UTC) de la première séance le jour start ou après."""
    for day, o, c in alpaca.sessions(start, start + timedelta(days=10)):
        if day >= start:
            return (day, *_times(day, o, c))
    raise ValueError(f"Aucune séance dans les 10 jours qui suivent le {start}")


def _bars(alpaca, run, sessions, now):
    """Barres minute du panier sur les séances du tour : séances finies en cache, séance en cours relue."""
    symbols = [i["symbol"] for i in run["selection"]]
    frames = []
    for day, start, end in sessions:
        if now >= end + FEED_DELAY:
            frames.append(cached(f"{day.isoformat()}/volatilite_minute_{run['run_id']}",
                                 lambda: alpaca.bars(symbols, "1Min", start, end)))
        elif now > start + FEED_DELAY:
            frames.append(alpaca.bars(symbols, "1Min", start, min(end, now - FEED_DELAY)))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["symbol", "timestamp", "open", "close", "volume"])


def _held(entry, until, sessions):
    """(secondes écoulées, secondes de marché ouvert) entre l'achat et until."""
    market = sum(max(0, (min(end, until) - max(start, entry)).total_seconds()) for _, start, end in sessions)
    return (until - entry).total_seconds(), market


def _round(alpaca, run, now):
    """État d'un tour connu à now (status waiting | live | sold)."""
    rules = basket.rules()
    entry_time = datetime.fromisoformat(run["market_open"])
    start_day = date.fromisoformat(run["session_date"])
    sessions = [(d, *_times(d, o, c)) for d, o, c in alpaca.sessions(start_day, now.astimezone(NEW_YORK).date())
                if d >= start_day]
    sessions = [s for s in sessions if s[1] <= now]
    symbols = [i["symbol"] for i in run["selection"]]
    state = track_round(symbols, _bars(alpaca, run, sessions, now), entry_time, [s[1:] for s in sessions], now,
                        rules.amount, rules.target_gain, rules.cost_bps)
    until = datetime.fromisoformat(state["sold_at"]) if state["sold_at"] else \
        datetime.fromisoformat(state["checked_until"]) if state["checked_until"] else entry_time
    elapsed, market = _held(entry_time, until, sessions)
    per_stock = rules.amount / len(symbols)
    stocks = []
    for item in run["selection"]:
        s = item["symbol"]
        entry, last = state["entry"].get(s), state["last"].get(s)
        stocks.append({**{k: item[k] for k in ("symbol", "name", "domain", "step", "volatility", "trend")},
                       "entry": None if entry is None else str(entry), "last": None if last is None else str(last),
                       "return": None if entry is None else float(last / entry - 1),
                       "gain": None if entry is None else str((per_stock * (last / entry - 1)).quantize(Decimal("0.01")))})
    money = lambda v: None if v is None else str(v.quantize(Decimal("0.01")))
    return {
        "run_id": run["run_id"], "session_date": run["session_date"], "entry_time": run["market_open"],
        "status": state["status"], "value": money(state["value"]), "gain": money(state["gain"]),
        "best_gain": money(state["best_gain"]), "sold_at": state["sold_at"], "sold_value": money(state["sold_value"]),
        "sold_gain": money(state["sold_gain"]), "checked_until": state["checked_until"],
        "sessions_held": state["sessions_held"], "elapsed_seconds": elapsed, "market_seconds": market,
        "amount": str(rules.amount), "target_gain": str(rules.target_gain), "n": len(symbols),
        "summary": run["summary"], "stocks": stocks,
    }


def finished_rounds():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ROUNDS_DIR.glob("*.json"))]


def update(alpaca, now=None):
    """
    Fait avancer les tours jusqu'à now : tours vendus gardés (durable), tour en cours écrit (volatil), pages
    régénérées. Retourne l'état affiché.
    """
    now = now or datetime.now(timezone.utc)
    done = finished_rounds()
    start = (datetime.fromisoformat(done[-1]["sold_at"]).astimezone(NEW_YORK).date() + timedelta(days=1)
             if done else FIRST_ROUND)
    current = None
    while current is None:
        day, market_open, _ = _next_session(alpaca, start)
        if now < market_open:
            current = {"status": "waiting", "session_date": day.isoformat(), "entry_time": market_open.isoformat()}
            break
        run = basket.list_for(day) or basket.produce(alpaca, day)
        state = _round(alpaca, run, now)
        if state["status"] != "sold":
            current = state
            break
        ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
        (ROUNDS_DIR / f"{day.isoformat()}.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n",
                                                             encoding="utf-8")
        done.append(state)
        start = datetime.fromisoformat(state["sold_at"]).astimezone(NEW_YORK).date() + timedelta(days=1)
    rules = basket.rules()
    page = {"updated": now.isoformat(), "amount": str(rules.amount), "target_gain": str(rules.target_gain),
            "per_domain": rules.per_domain, "cost_bps": str(rules.cost_bps), "current": current,
            "rounds": [{k: v for k, v in r.items() if k not in ("stocks", "summary")} for r in done]}
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
    c = page["current"]
    for r in page["rounds"]:
        print(f"Tour du {r['session_date']} : vendu {r['sold_at']} · gain net {r['sold_gain']} $ · "
              f"{r['elapsed_seconds'] / 3600:.1f} h écoulées, {r['sessions_held']} séance(s)")
    if c["status"] == "waiting":
        print(f"Prochain tour : achat à l'ouverture du {c['session_date']}.")
    else:
        print(f"Tour en cours depuis le {c['session_date']} : gain net {c['gain']} $ / {page['target_gain']} $ "
              f"(meilleur {c['best_gain']} $), {c['elapsed_seconds'] / 3600:.1f} h écoulées.")
    print(f"Pages : {PAGES['fr']} · {PAGES['en']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
