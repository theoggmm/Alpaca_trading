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


def test_plan_d_ordres_actions_entieres_sans_depasser_la_part():
    from core.portfolio import order_plan
    plan = order_plan(["A", "B", "C"], {"A": Decimal("276.81"), "B": Decimal("39.11")}, Decimal("10000"))
    assert plan["share"] == "3333.33"
    rows = {r["symbol"]: r for r in plan["rows"]}
    assert rows["A"]["qty"] == 12 and rows["A"]["cost"] == "3321.72"    # 13 actions dépasseraient 3 333,33 $
    assert rows["B"]["qty"] == 85 and rows["B"]["cost"] == "3324.35"
    assert rows["C"]["qty"] is None                                       # pas de prix : pas de quantité
    assert plan["total_cost"] == "6646.07" and plan["cash_left"] == "3353.93"


def test_prix_d_achat_connu_seulement_apres_coup():
    from core.portfolio import entry_prices
    assert entry_prices(ENTRY_BARS, ENTRY, ENTRY) == {}
    assert entry_prices(ENTRY_BARS, ENTRY, ENTRY + timedelta(minutes=5)) == {"A": Decimal("100"), "B": Decimal("50")}


def test_frais_et_actions_entieres():
    later = EXIT + timedelta(hours=1)
    result = simulate(["A", "B"], ENTRY_BARS, EXIT_BARS, {}, ENTRY, EXIT, later)
    # A : 100 -> 110, B : 50 -> 49. Après frais de 5 pb par ordre : A 110 × 0,9995 / (100 × 1,0005) - 1, etc.
    c = Decimal("0.0005")
    net_a = Decimal("110") * (1 - c) / (Decimal("100") * (1 + c)) - 1
    net_b = Decimal("49") * (1 - c) / (Decimal("50") * (1 + c)) - 1
    assert result["net_mean_return"] == float((net_a + net_b) / 2)
    assert result["net_mean_return"] < result["mean_return"]
    # 10 000 $ -> 5 000 $ par titre : A 49 actions (5 000 / 100,05), B 99 actions (5 000 / 50,025).
    whole = 49 * (Decimal("110") * (1 - c) - Decimal("100") * (1 + c)) + 99 * (Decimal("49") * (1 - c) - Decimal("50") * (1 + c))
    assert result["whole_gains"]["10000"] == str(whole.quantize(Decimal("0.01")))


def test_apres_impot_gain_impose_perte_entiere():
    from core.portfolio import TAX_RATE, after_tax
    kept = after_tax({"10000": "100.00", "25000": "-40.00", "50000": "0.00"})
    assert kept == {"10000": str((Decimal("100") * (1 - TAX_RATE)).quantize(Decimal("0.01"))),
                    "25000": "-40.00", "50000": "0.00"}
