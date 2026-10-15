"""Règles de tendance : « pas en chute » (moyenne sur 50 séances) et « marché en bonne forme » (SPY)."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.screener import market_in_uptrend, screen
from tests.synthetic import CRITERIA, DECISION_TIME, MARKET_OPEN, market

NO_KNIFE = replace(CRITERIA, count=500, max_pairwise_correlation=1.0, max_below_ma=Decimal("0.05"), ma_sessions=50)
MARKET = replace(CRITERIA, market_symbol="SPY", market_ma_sessions=50)


def _spy(trend, today=None):
    """Clôtures quotidiennes de SPY sur 70 séances (hausse ou baisse régulière), plus la séance du jour."""
    start = datetime(2026, 7, 1, 4, tzinfo=timezone.utc)
    days = pd.bdate_range(start=start.date(), end=MARKET_OPEN.date() - timedelta(days=1))
    closes = [Decimal("500") * (Decimal("1.002") if trend == "up" else Decimal("0.998")) ** i for i in range(len(days))]
    rows = [("SPY", datetime(d.year, d.month, d.day, 4, tzinfo=timezone.utc), c, c, 1000) for d, c in zip(days, closes)]
    if today is not None:   # séance du jour : jamais terminée à l'instant de décision
        rows.append(("SPY", datetime(MARKET_OPEN.year, MARKET_OPEN.month, MARKET_OPEN.day, 4, tzinfo=timezone.utc),
                     today, today, 1000))
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "close", "volume"])


def test_pas_en_chute_exclut_les_titres_trop_sous_leur_moyenne():
    daily, minute = market()
    loose = replace(NO_KNIFE, max_below_ma=None, ma_sessions=None)
    every, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, loose)
    kept, funnel = screen(daily, minute, MARKET_OPEN, DECISION_TIME, NO_KNIFE)
    assert all(i["below_ma"] <= 0.05 for i in kept)
    assert funnel["pas_en_chute"] == len(kept) < len(every)   # les données synthétiques comptent des chutes nettes
    # Une limite très large ne retire rien.
    assert len(screen(daily, minute, MARKET_OPEN, DECISION_TIME, replace(NO_KNIFE, max_below_ma=Decimal("1")))[0]) == len(every)


def test_marche_en_bonne_forme_vide_la_liste_quand_spy_est_sous_sa_moyenne():
    daily, minute = market()
    up, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, MARKET, market_daily=_spy("up"))
    down, funnel = screen(daily, minute, MARKET_OPEN, DECISION_TIME, MARKET, market_daily=_spy("down"))
    assert up == screen(daily, minute, MARKET_OPEN, DECISION_TIME, CRITERIA)[0] and up
    assert down == [] and funnel["marche_en_bonne_forme"] == 0
    with pytest.raises(ValueError):
        screen(daily, minute, MARKET_OPEN, DECISION_TIME, MARKET)


def test_marche_datation_seance_du_jour_ignoree():
    # Un effondrement de SPY pendant la séance du jour n'est pas connu à 10 h 30 : aucun effet.
    healthy, last, _ = market_in_uptrend(_spy("up", today=Decimal("1")), DECISION_TIME, "SPY", 50)
    assert healthy and last > 1
    assert market_in_uptrend(_spy("up"), DECISION_TIME, "SPY", 50)[1] == last
