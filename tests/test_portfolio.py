"""Simulation d'investissement : achat après la première heure, vente 30 min avant la clôture."""

from datetime import timedelta
from decimal import Decimal

import pandas as pd

from core.portfolio import simulate
from tests.synthetic import MARKET_OPEN

ENTRY = MARKET_OPEN + timedelta(minutes=75)     # 10 h 45 (New York)
EXIT = MARKET_OPEN + timedelta(hours=6)          # 15 h 30 (New York)
COLUMNS = ["symbol", "timestamp", "open", "close", "volume"]


def _bars(rows):
    return pd.DataFrame([(s, ts, Decimal(o), Decimal(c), 100) for s, ts, o, c in rows], columns=COLUMNS)


ENTRY_BARS = _bars([("A", ENTRY, "100", "101"), ("B", ENTRY + timedelta(minutes=1), "50", "50")])
EXIT_BARS = _bars([("A", EXIT - timedelta(minutes=1), "109", "110"), ("B", EXIT - timedelta(minutes=2), "49", "49"),
                   ("A", EXIT, "500", "500")])   # barre de 15 h 30 : après la vente, ignorée


def test_en_attente_avant_l_achat():
    result = simulate(["A", "B"], ENTRY_BARS, EXIT_BARS, {}, ENTRY, EXIT, ENTRY + timedelta(seconds=30))
    assert result["status"] == "waiting" and result["gains"] == {}


def test_en_direct_entre_l_achat_et_la_vente():
    now = ENTRY + timedelta(hours=2)
    trades = {"A": (now - timedelta(minutes=1), Decimal("105")), "B": (now, Decimal("51")),
              "C": (now, Decimal("999"))}  # C n'est pas dans la liste
    result = simulate(["A", "B"], ENTRY_BARS, EXIT_BARS, trades, ENTRY, EXIT, now)
    # A : +5 %, B : +2 % -> moyenne +3,5 % ; 10 000 $ -> +350 $
    assert result["status"] == "live" and result["priced"] == 2
    assert result["gains"]["10000"] == "350.00" and result["gains"]["1000000"] == "35000.00"


def test_vente_figee_trente_minutes_avant_la_cloture():
    later = EXIT + timedelta(hours=1)
    trades = {"A": (later, Decimal("1")), "B": (later, Decimal("1"))}   # échanges après la vente : ignorés
    result = simulate(["A", "B"], ENTRY_BARS, EXIT_BARS, trades, ENTRY, EXIT, later)
    # A : 110 / 100 = +10 %, B : 49 / 50 = -2 % -> moyenne +4 % ; 25 000 $ -> +1 000 $
    assert result["status"] == "closed"
    assert result["gains"]["25000"] == "1000.00"


def test_titre_sans_prix_d_achat_exclu_de_la_repartition():
    bars = ENTRY_BARS[ENTRY_BARS["symbol"] == "A"]
    result = simulate(["A", "B"], bars, EXIT_BARS, {}, ENTRY, EXIT, EXIT + timedelta(hours=1))
    assert result["n"] == 2 and result["priced"] == 1 and result["gains"]["10000"] == "1000.00"
