"""Sélection « fin de journée » : journée, dernière heure, proximité du plus haut, datation."""

from datetime import timedelta
from decimal import Decimal

import pandas as pd

from core.closing import ClosingCriteria, screen_closing
from tests.synthetic import MARKET_OPEN, market

CRITERIA = ClosingCriteria(
    signal="fin_de_journee", version=1, count=20, liquidity_sessions=20, min_price_usd=Decimal("5"),
    min_avg_dollar_volume_usd=Decimal("20000000"), volatility_sessions=60, month_sessions=21, correlation_sessions=60,
    max_pairwise_correlation=1.0, decision_after_open_minutes=315, last_hour_minutes=60,
    min_day_gain=Decimal("0.005"), max_day_gain=Decimal("0.04"), max_below_day_high=Decimal("0.01"))
DECISION = MARKET_OPEN + timedelta(minutes=315)   # 14 h 45


def _day(paths):
    """Barres minute du jour : symbole -> {minute: prix}, entre l'ouverture et la décision, + une barre après."""
    rows = []
    for symbol, points in paths.items():
        for m, price in points.items():
            rows.append((symbol, MARKET_OPEN + timedelta(minutes=m), Decimal(price), Decimal(price), 1000))
        rows.append((symbol, DECISION + timedelta(minutes=5), Decimal("1"), Decimal("1"), 1000))  # inconnue à 14 h 45
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "close", "volume"])


def test_journee_derniere_heure_plus_haut():
    daily, _ = market()
    minute = _day({
        "CALM1": {0: "100", 200: "101", 314: "102"},                # +2 %, dernière heure en hausse, au plus haut : retenu
        "CALM2": {0: "100", 200: "100.5", 314: "103"},              # +3 %, meilleure dernière heure : premier
        "CALM3": {0: "100", 200: "103", 314: "102"},                # dernière heure en baisse : exclu
        "CALM4": {0: "100", 100: "106", 200: "101", 314: "103"},    # 2,8 % sous son plus haut : exclu
        "CALM5": {0: "100", 200: "100.1", 314: "100.2"},            # journée trop calme (+0,2 %) : exclu
        "CALM6": {0: "100", 200: "103", 314: "106"},                # journée trop forte (+6 %) : exclu
    })
    selection, funnel = screen_closing(daily, minute, MARKET_OPEN, DECISION, CRITERIA)
    assert [i["symbol"] for i in selection] == ["CALM2", "CALM1"]
    assert funnel["journee_en_hausse"] == 4 and funnel["derniere_heure_en_hausse"] == 3 and funnel["pres_du_plus_haut"] == 2
    # La barre de 14 h 50 (prix 1) n'est pas connue à 14 h 45.
    assert abs(selection[1]["return_day"] - 0.02) < 1e-9
