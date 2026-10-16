"""Sélection « ouverture » : fin de séance de la veille, nuit, datation à 9 h 15."""

from datetime import timedelta
from decimal import Decimal

import pandas as pd

from core.opening import OpeningCriteria, screen_opening
from tests.synthetic import MARKET_OPEN, market

CRITERIA = OpeningCriteria(
    signal="ouverture", version=1, count=20, liquidity_sessions=20, min_price_usd=Decimal("5"),
    min_avg_dollar_volume_usd=Decimal("20000000"), volatility_sessions=60, month_sessions=21, correlation_sessions=60,
    max_pairwise_correlation=1.0, last_hour_minutes=60, min_overnight=Decimal("0.005"), max_overnight=Decimal("0.03"),
    min_premarket_volume=5000, data_delay_minutes=15)
DECISION = MARKET_OPEN - timedelta(minutes=15)
PREVIOUS_CLOSE = MARKET_OPEN - timedelta(hours=17, minutes=30)  # 16 h 00 la veille


def _night(daily, moves):
    """Barres de la dernière heure de la veille et de la nuit : symbole -> (hausse dernière heure, hausse nuit)."""
    last = daily[daily["timestamp"] < MARKET_OPEN - timedelta(hours=10)].sort_values("timestamp").groupby("symbol").last()
    rows = []
    for symbol, (hour, night) in moves.items():
        close = last.loc[symbol, "close"]
        start = close / (1 + hour)
        rows.append((symbol, PREVIOUS_CLOSE - timedelta(minutes=60), start, start, 100))
        rows.append((symbol, PREVIOUS_CLOSE - timedelta(minutes=1), close, close, 100))
        price = close * (1 + night)
        rows.append((symbol, MARKET_OPEN - timedelta(minutes=60), price, price, 10000))   # pré-ouverture 8 h 30
        rows.append((symbol, DECISION + timedelta(minutes=5), price * 3, price * 3, 10000))  # après 9 h 15 : invisible
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "close", "volume"])


def test_fin_de_veille_et_nuit():
    daily, _ = market()
    moves = {"CALM1": (Decimal("0.01"), Decimal("0.01")),    # retenu
             "CALM2": (Decimal("0.02"), Decimal("0.02")),    # retenu, meilleure dernière heure : premier
             "CALM3": (Decimal("-0.01"), Decimal("0.01")),   # veille en baisse : exclu
             "CALM4": (Decimal("0.01"), Decimal("0.05")),    # nuit trop forte : exclu
             "CALM5": (Decimal("0.01"), Decimal("0.001"))}   # nuit trop faible : exclu
    selection, funnel = screen_opening(daily, _night(daily, moves), MARKET_OPEN, PREVIOUS_CLOSE, DECISION, CRITERIA)
    assert [i["symbol"] for i in selection] == ["CALM2", "CALM1"]
    assert funnel["fin_de_seance_en_hausse"] == 4 and funnel["nuit_en_hausse_moderee"] == 2
    # La barre de 9 h 20 (prix triplé) n'est pas connue à 9 h 15 : la nuit est mesurée à 8 h 30.
    assert abs(selection[1]["return_overnight"] - 0.01) < 1e-6


def test_pre_ouverture_trop_calme_exclue():
    daily, _ = market()
    bars = _night(daily, {"CALM1": (Decimal("0.01"), Decimal("0.01"))})
    bars.loc[bars["timestamp"] >= MARKET_OPEN - timedelta(hours=5, minutes=30), "volume"] = 10
    assert screen_opening(daily, bars, MARKET_OPEN, PREVIOUS_CLOSE, DECISION, CRITERIA)[0] == []
