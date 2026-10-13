"""
Marché fictif pour les tests : séances quotidiennes jusqu'à la veille, la séance du jour,
une séance future, et des barres minute avant et après l'instant de décision.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd

from core.screener import Criteria

MARKET_OPEN = datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc)  # 9 h 30 à New York
DECISION_TIME = MARKET_OPEN + timedelta(minutes=60)
PAST_SESSIONS = 70

CRITERIA = Criteria(
    version=1, count=20, month_sessions=21, up_days=2, first_hour_minutes=60,
    liquidity_sessions=20, min_price_usd=Decimal("5"), min_avg_dollar_volume_usd=Decimal("20000000"),
    volatility_sessions=60, max_volatility_quantile=0.5, correlation_sessions=60,
    max_pairwise_correlation=0.6,
)


def _session_starts():
    days = pd.bdate_range(end=MARKET_OPEN.date() - timedelta(days=1), periods=PAST_SESSIONS)
    return [datetime(d.year, d.month, d.day, 4, tzinfo=timezone.utc) for d in days]


def _returns(rng, kind):
    if kind == "down":       # calme, en baisse sur le dernier mois, deux séances de hausse à la fin
        r = rng.normal(0, 0.005, PAST_SESSIONS - 1)
        r[-21:] += -0.006
        r[-2:] = 0.008
    elif kind == "calm":     # calme, sans tendance
        r = rng.normal(0, 0.005, PAST_SESSIONS - 1)
    else:                    # très volatil
        r = rng.normal(0, 0.04, PAST_SESSIONS - 1)
    return r


def _closes(returns, start=50.0):
    prices = start * np.cumprod(np.concatenate([[1.0], 1 + returns]))
    return [Decimal(f"{p:.4f}") for p in prices]


def market(seed=7):
    """Retourne (daily, minute) : barres passées, du jour et futures."""
    rng = np.random.default_rng(seed)
    universe = ([(f"DOWN{i}", "down", 1_000_000) for i in range(30)]
                + [(f"CALM{i}", "calm", 1_000_000) for i in range(30)]
                + [(f"WILD{i}", "wild", 1_000_000) for i in range(70)]
                + [("ILLIQ", "down", 1_000)])
    series = {symbol: (_returns(rng, kind), volume) for symbol, kind, volume in universe}
    series["TWINB"] = series["DOWN0"]  # mêmes rendements que DOWN0 : corrélation 1

    starts = _session_starts()
    daily, minute = [], []
    for symbol, (returns, volume) in series.items():
        closes = _closes(returns)
        daily += [(symbol, ts, c, c, volume) for ts, c in zip(starts, closes)]
        last = closes[-1]
        # Séance du jour et séance future : jamais terminées à l'instant de décision.
        daily.append((symbol, starts[-1] + timedelta(days=1), last, last * 3, volume))
        daily.append((symbol, starts[-1] + timedelta(days=2), last, last / 3, volume))
        # Première heure en hausse régulière, puis effondrement après la décision.
        for m in range(120):
            ts = MARKET_OPEN + timedelta(minutes=m)
            price = last * (Decimal("1.0001") ** m) if m < 60 else last / 2
            minute.append((symbol, ts, price, price, 1000))

    columns = ["symbol", "timestamp", "open", "close", "volume"]
    return pd.DataFrame(daily, columns=columns), pd.DataFrame(minute, columns=columns)
