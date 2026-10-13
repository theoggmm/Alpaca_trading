"""Bulles en direct : définitions des mesures et invariant de datation."""

import statistics
from datetime import timedelta
from decimal import Decimal

import pandas as pd

from core.domains import WEEK_SESSIONS, live_domain_trends
from core.screener import liquid_universe
from tests.synthetic import CRITERIA, DECISION_TIME, MARKET_OPEN, market
from tests.test_domains import DOMAINS

NOW = MARKET_OPEN + timedelta(minutes=90)
EMPTY_MINUTE = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])


def _trades(daily, at, factor):
    liquid, _ = liquid_universe(daily, MARKET_OPEN, CRITERIA)
    return {s.symbol: (at, s.closes[-1] * factor) for s in liquid}


def test_mesures_dernier_prix_sur_cloture_d_il_y_a_n_seances():
    daily, minute = market()
    trades = _trades(daily, MARKET_OPEN + timedelta(minutes=75), Decimal("1.01"))
    measures, universe = live_domain_trends(daily, trades, minute, MARKET_OPEN, NOW, CRITERIA, DOMAINS)
    liquid, _ = liquid_universe(daily, MARKET_OPEN, CRITERIA)
    assert universe == len(liquid)

    sessions = {"day": 1, "two_days": CRITERIA.up_days, "week": WEEK_SESSIONS, "month": CRITERIA.month_sessions}
    for key, n in sessions.items():
        for bubble in measures[key]["bubbles"]:
            expected = [float(trades[s.symbol][1] / s.closes[-n] - 1) for s in liquid
                        if DOMAINS.get(s.symbol) == bubble["domain"]]
            assert bubble["mean_return"] == statistics.fmean(expected)
    assert all(b["mean_return"] > 0 for b in measures["day"]["bubbles"])  # +1 % sur la veille partout


def test_premiere_heure_seulement_une_fois_terminee():
    daily, minute = market()
    trades = _trades(daily, MARKET_OPEN + timedelta(minutes=20), Decimal("1"))
    early, _ = live_domain_trends(daily, trades, minute, MARKET_OPEN, MARKET_OPEN + timedelta(minutes=30),
                                  CRITERIA, DOMAINS)
    assert not early["first_hour"]["available"] and early["first_hour"]["bubbles"] == []
    later, _ = live_domain_trends(daily, trades, minute, MARKET_OPEN, NOW, CRITERIA, DOMAINS)
    assert later["first_hour"]["available"] and all(b["mean_return"] > 0 for b in later["first_hour"]["bubbles"])
    no_bars, _ = live_domain_trends(daily, trades, EMPTY_MINUTE, MARKET_OPEN, NOW, CRITERIA, DOMAINS)
    assert not no_bars["first_hour"]["available"]


def test_aucune_donnee_posterieure_a_l_observation():
    daily, minute = market()
    trades = _trades(daily, MARKET_OPEN + timedelta(minutes=75), Decimal("1.01"))
    reference = live_domain_trends(daily, trades, minute, MARKET_OPEN, NOW, CRITERIA, DOMAINS)

    # Échanges postérieurs à l'observation ou antérieurs à l'ouverture : ignorés.
    late = {s: (NOW + timedelta(minutes=1), p * 10) for s, (_, p) in trades.items()}
    early = {s: (MARKET_OPEN - timedelta(minutes=1), p * 10) for s, (_, p) in trades.items()}
    ignored, _ = live_domain_trends(daily, late, minute, MARKET_OPEN, NOW, CRITERIA, DOMAINS)
    assert all(not ignored[k]["available"] for k in ("day", "two_days", "week", "month"))
    assert live_domain_trends(daily, early, minute, MARKET_OPEN, NOW, CRITERIA, DOMAINS)[0]["day"]["bubbles"] == []

    # Barres quotidiennes non terminées à l'ouverture et minutes après la première heure : sans effet.
    future_daily = daily["timestamp"] + timedelta(days=1) > MARKET_OPEN
    daily.loc[future_daily, "close"] = daily.loc[future_daily, "close"] * 100
    after_first_hour = minute["timestamp"] >= DECISION_TIME
    minute.loc[after_first_hour, "close"] = minute.loc[after_first_hour, "close"] * 100
    assert live_domain_trends(daily, trades, minute, MARKET_OPEN, NOW, CRITERIA, DOMAINS) == reference
