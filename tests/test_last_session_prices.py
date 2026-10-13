"""Dernier échange de la séance reconstitué depuis les barres minute : rien après la clôture."""

from datetime import timedelta
from decimal import Decimal

import pandas as pd

from core.screener import last_session_prices
from tests.synthetic import MARKET_OPEN

CLOSE = MARKET_OPEN + timedelta(hours=6, minutes=30)


def _bars(rows):
    return pd.DataFrame([(s, CLOSE + timedelta(minutes=m), Decimal(p), Decimal(p), 100) for s, m, p in rows],
                        columns=["symbol", "timestamp", "open", "close", "volume"])


def test_derniere_barre_terminee_a_la_cloture():
    bars = _bars([
        ("AAA", -3, "10"), ("AAA", -1, "11"),   # barre 15 h 59 - 16 h 00 : la dernière de la séance
        ("AAA", 0, "50"),                       # barre 16 h 00 - 16 h 01 : après la clôture
        ("BBB", -20, "7"),                      # dernier échange 20 min avant la clôture
        ("CCC", 2, "9"),                        # seulement après la clôture : absent
    ])
    prices = last_session_prices(bars, CLOSE)
    assert prices == {"AAA": (CLOSE, Decimal("11")), "BBB": (CLOSE - timedelta(minutes=19), Decimal("7"))}
