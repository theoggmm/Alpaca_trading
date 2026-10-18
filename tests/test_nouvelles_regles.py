"""
Règles des trois nouvelles stratégies (décision T16) : marché qui tient / qui remonte, bascule, repli dans une
tendance. Chaque test place des barres après la décision : elles ne doivent jamais servir (datation).
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from core.closing import ClosingCriteria, market_conditions, screen_closing
from core.swing import SwingCriteria, screen_swing
from core.switch import SwitchCriteria, choose, screen_switch
from tests.synthetic import MARKET_OPEN, market

COLUMNS = ["symbol", "timestamp", "open", "close", "volume"]
CLOSING = ClosingCriteria(
    signal="fin_de_journee", version=1, count=20, liquidity_sessions=20, min_price_usd=Decimal("5"),
    min_avg_dollar_volume_usd=Decimal("20000000"), volatility_sessions=60, month_sessions=21, correlation_sessions=60,
    max_pairwise_correlation=1.0, decision_after_open_minutes=315, last_hour_minutes=60,
    min_day_gain=Decimal("0.005"), max_day_gain=Decimal("0.04"), max_below_day_high=Decimal("0.01"),
    market_symbol="SPY", market_min_day_return=Decimal("-0.002"))
FIRST = MARKET_OPEN + timedelta(minutes=315)    # 14 h 45
SECOND = MARKET_OPEN + timedelta(minutes=370)   # 15 h 40


def _spy(points, after=None):
    """Barres minute de SPY : {minute: prix}, + une barre après `after` (jamais connue à la décision)."""
    rows = [("SPY", MARKET_OPEN + timedelta(minutes=m), Decimal(p), Decimal(p), 1000) for m, p in points.items()]
    if after is not None:
        rows.append(("SPY", after + timedelta(minutes=1), Decimal("200"), Decimal("200"), 1000))
    return pd.DataFrame(rows, columns=COLUMNS)


def _stocks():
    """Une action qui passe toutes les règles « fin de journée » à 14 h 45 et à 15 h 40."""
    rows = [("CALM1", MARKET_OPEN + timedelta(minutes=m), Decimal(p), Decimal(p), 1000)
            for m, p in {0: "100", 200: "101", 300: "101.5", 314: "102", 360: "102.2", 369: "102.5"}.items()]
    return pd.DataFrame(rows, columns=COLUMNS)


def test_marche_qui_tient():
    daily, _ = market()
    # SPY à −0,1 % à 14 h 45 : le marché tient ; la barre de 14 h 46 (+100 %) n'est pas connue.
    holds = _spy({0: "100", 314: "99.9"}, after=FIRST)
    assert market_conditions(CLOSING, holds, MARKET_OPEN, FIRST) == {"marche_tient": True}
    selection, funnel = screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, CLOSING, market_minute=holds)
    assert [i["symbol"] for i in selection] == ["CALM1"] and funnel["marche_tient"] > 0
    # SPY à −0,3 % : aucune liste, même si une barre plus tardive remonte.
    falls = _spy({0: "100", 314: "99.7"}, after=FIRST)
    selection, funnel = screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, CLOSING, market_minute=falls)
    assert selection == [] and funnel["marche_tient"] == 0
    with pytest.raises(ValueError):
        screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, CLOSING)   # barres de SPY requises


def test_bascule():
    daily, _ = market()
    second = replace(CLOSING, decision_after_open_minutes=370, market_min_day_return=None,
                     market_min_last_hour_return=Decimal("0"))
    switch = SwitchCriteria(signal="bascule", version=1, first=CLOSING, second=second)
    assert switch.decisions_minutes == [315, 370]
    # Le marché tient à 14 h 45 : la liste du jour est la première ; la seconde est refusée.
    holds = _spy({0: "100", 314: "99.9", 369: "99.5"})
    assert choose(switch, holds, MARKET_OPEN, FIRST)
    selection, _, chosen = screen_switch(daily, _stocks(), MARKET_OPEN, FIRST, switch, market_minute=holds)
    assert chosen is CLOSING and [i["symbol"] for i in selection] == ["CALM1"]
    with pytest.raises(ValueError):
        screen_switch(daily, _stocks(), MARKET_OPEN, SECOND, switch, market_minute=holds)
    # Le marché ne tient pas à 14 h 45 (−0,5 %), mais remonte sur la dernière heure (14 h 40 → 15 h 40) : seconde liste.
    # La barre de 14 h 46 (après la première décision) ne change pas le choix fait à 14 h 45.
    recovers = _spy({0: "100", 300: "99.4", 314: "99.5", 315: "120", 369: "99.8"})
    assert not choose(switch, recovers, MARKET_OPEN, FIRST)
    selection, funnel, chosen = screen_switch(daily, _stocks(), MARKET_OPEN, SECOND, switch, market_minute=recovers)
    assert chosen is second and funnel["marche_remonte"] > 0
    # Le marché ne remonte pas non plus : aucune liste.
    sinks = _spy({0: "100", 300: "99.4", 314: "99.5", 369: "99.0"}, after=SECOND)
    selection, funnel, _ = screen_switch(daily, _stocks(), MARKET_OPEN, SECOND, switch, market_minute=sinks)
    assert selection == [] and funnel["marche_remonte"] == 0


SWING = SwingCriteria(
    signal="repli_tendance", version=1, count=20, liquidity_sessions=20, min_price_usd=Decimal("5"),
    min_avg_dollar_volume_usd=Decimal("20000000"), volatility_sessions=60, max_volatility_quantile=1.0,
    month_sessions=21, correlation_sessions=60, max_pairwise_correlation=1.0, decision_after_open_minutes=370,
    short_trend_sessions=20, trend_sessions=50, high_sessions=10, min_pullback=Decimal("0.03"),
    max_pullback=Decimal("0.10"))


def _trend_daily():
    """70 séances : UP monte de 50 à ~70 ; FLAT reste à 60. Une barre future (le jour même) ne doit pas servir."""
    days = pd.bdate_range(end=MARKET_OPEN.date() - timedelta(days=1), periods=70)
    rows = []
    for i, d in enumerate(days):
        ts = datetime(d.year, d.month, d.day, 4, tzinfo=timezone.utc)
        up = Decimal(str(round(50 + 0.3 * i + (0.4 if i % 2 else -0.4), 2)))
        rows += [("UP", ts, up, up, 1_000_000), ("FLAT", ts, Decimal("60"), Decimal("60") + Decimal(i % 2) / 10, 1_000_000)]
    rows.append(("UP", datetime(MARKET_OPEN.year, MARKET_OPEN.month, MARKET_OPEN.day, 4, tzinfo=timezone.utc),
                 Decimal("10"), Decimal("10"), 1_000_000))
    return pd.DataFrame(rows, columns=COLUMNS)


def test_repli_dans_une_tendance():
    daily = _trend_daily()
    high = max(daily[(daily["symbol"] == "UP") & (daily["timestamp"] < MARKET_OPEN)]["close"].tail(10))
    dip = (high * Decimal("0.95")).quantize(Decimal("0.01"))   # 5 % sous le plus haut, sous la clôture de la veille
    minute = pd.DataFrame([("UP", SECOND - timedelta(minutes=2), dip, dip, 100),
                           ("FLAT", SECOND - timedelta(minutes=2), Decimal("57"), Decimal("57"), 100),
                           ("UP", SECOND + timedelta(minutes=1), high, high, 100)], columns=COLUMNS)  # après : inconnue
    selection, funnel = screen_swing(daily, minute, MARKET_OPEN, SECOND, SWING)
    assert [i["symbol"] for i in selection] == ["UP"]           # FLAT : pas de tendance haussière
    assert funnel["tendance_haussiere"] == 1 and abs(selection[0]["pullback"] - 0.05) < 0.001
    # Un repli trop faible (1 %) : exclu.
    small = minute.assign(close=[(high * Decimal("0.99")).quantize(Decimal("0.01")), Decimal("57"), high])
    assert screen_swing(daily, small, MARKET_OPEN, SECOND, SWING)[0] == []



def test_sans_stop_ni_objectif():
    """stop_loss et take_profit None : aucune vente anticipée, chaque titre gardé jusqu'à l'heure de vente."""
    from core.portfolio import simulate
    entry_t = MARKET_OPEN + timedelta(minutes=90)
    exit_t = MARKET_OPEN + timedelta(minutes=360)
    entry = pd.DataFrame([("A", entry_t, Decimal("100"), Decimal("100"), 1)], columns=COLUMNS)
    exit_ = pd.DataFrame([("A", exit_t - timedelta(minutes=1), Decimal("101"), Decimal("101"), 1)], columns=COLUMNS)
    path = pd.DataFrame([("A", entry_t + timedelta(minutes=10), Decimal("90"), Decimal("90"), 1)], columns=COLUMNS)
    result = simulate(["A"], entry, exit_, {}, entry_t, exit_t, exit_t + timedelta(hours=1), path_bars=path,
                      stop_loss=None, take_profit=None)
    assert result["early_exits"] == {} and abs(result["mean_return"] - 0.01) < 1e-9


def test_filtres_quotidiens_fin_de_journee():
    """Hausse des N dernières séances et hausse sur la semaine : calculées sur les clôtures d'avant la décision."""
    daily, _ = market()
    holds = _spy({0: "100", 314: "99.9"})
    base = screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, CLOSING, market_minute=holds)[0]
    assert [i["symbol"] for i in base] == ["CALM1"]
    week = base[0]["return_week"]
    inside = replace(CLOSING, min_week_gain=Decimal(str(week - 0.001)), max_week_gain=Decimal(str(week + 0.001)))
    assert [i["symbol"] for i in screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, inside, market_minute=holds)[0]] == ["CALM1"]
    outside = replace(CLOSING, min_week_gain=Decimal(str(week + 0.01)))
    assert screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, outside, market_minute=holds)[0] == []
    many = replace(CLOSING, min_up_days=30)
    selection, funnel = screen_closing(daily, _stocks(), MARKET_OPEN, FIRST, many, market_minute=holds)
    assert selection == [] and "hausse_des_derniers_jours" in funnel
