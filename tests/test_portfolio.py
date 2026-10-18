"""Simulation d'investissement : achat après la première heure, vente 30 min avant la clôture."""

from datetime import timedelta
from decimal import Decimal

import pandas as pd
import pytest

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


def test_titre_sans_prix_de_vente_ecarte_sans_bloquer_les_autres():
    import pandas as pd
    from datetime import datetime, timedelta, timezone
    from core.portfolio import simulate
    entry_t = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
    exit_t = datetime(2026, 10, 15, 19, 30, tzinfo=timezone.utc)
    cols = ["symbol", "timestamp", "open", "close", "volume"]
    entry = pd.DataFrame([("AAA", entry_t, Decimal("10"), Decimal("10"), 1), ("BBB", entry_t, Decimal("20"), Decimal("20"), 1)], columns=cols)
    # BBB n'échange qu'à 15 h 30 pile : barre postérieure à l'heure de vente, inutilisable.
    exit_ = pd.DataFrame([("AAA", exit_t - timedelta(minutes=1), Decimal("11"), Decimal("11"), 1),
                          ("BBB", exit_t, Decimal("30"), Decimal("30"), 1)], columns=cols)
    result = simulate(["AAA", "BBB"], entry, exit_, {}, entry_t, exit_t, exit_t + timedelta(minutes=30))
    assert result["status"] == "closed" and result["priced"] == 1 and result["n"] == 2
    assert result["mean_return"] == 0.1


def test_vente_anticipee_stop_et_objectif():
    from datetime import datetime, timedelta, timezone
    from core.portfolio import simulate
    entry_t = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
    exit_t = datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
    cols = ["symbol", "timestamp", "open", "close", "volume"]
    entry = pd.DataFrame([(s, entry_t, Decimal("100"), Decimal("100"), 1) for s in ("DOWN", "UP", "FLAT")], columns=cols)
    exit_ = pd.DataFrame([(s, exit_t - timedelta(minutes=1), Decimal(p), Decimal(p), 1)
                          for s, p in (("DOWN", "110"), ("UP", "90"), ("FLAT", "101"))], columns=cols)
    # Trajet : DOWN tombe à 98,4 (−1,6 %) à 11 h 20 puis remonte ; UP touche 103,2 (+3,2 %) à 12 h 00 puis chute.
    path = pd.DataFrame([("DOWN", entry_t + timedelta(minutes=20), Decimal("98.4"), Decimal("98.4"), 1),
                         ("DOWN", entry_t + timedelta(minutes=10), Decimal("99"), Decimal("99"), 1),
                         ("UP", entry_t + timedelta(minutes=60), Decimal("103.2"), Decimal("103.2"), 1),
                         ("FLAT", entry_t + timedelta(minutes=60), Decimal("99"), Decimal("99"), 1)], columns=cols)
    after = exit_t + timedelta(minutes=30)
    result = simulate(["DOWN", "UP", "FLAT"], entry, exit_, {}, entry_t, exit_t, after, path_bars=path)
    assert set(result["early_exits"]) == {"DOWN", "UP"}
    assert result["early_exits"]["DOWN"]["reason"] == "stop" and result["early_exits"]["DOWN"]["price"] == "98.4"
    assert result["early_exits"]["UP"]["reason"] == "objectif"
    # Rendement : DOWN −1,6 %, UP +3,2 %, FLAT +1 % (vendu à l'heure de vente) ; le rebond de DOWN ne compte pas.
    assert result["mean_return"] == pytest.approx((-0.016 + 0.032 + 0.01) / 3)
    # Suivi des positions : deux titres vendus plus tôt, le troisième à l'heure de vente.
    positions = result["positions"]
    assert {k: v["state"] for k, v in positions.items()} == {"DOWN": "stop", "UP": "objectif", "FLAT": "sold"}
    assert positions["FLAT"]["return"] == pytest.approx(0.01) and positions["DOWN"]["price"] == "98.4"
    # Pendant la séance : FLAT encore détenu, valorisé au dernier échange connu.
    live = simulate(["DOWN", "UP", "FLAT"], entry, exit_, {"FLAT": (entry_t + timedelta(minutes=70), Decimal("100.5"))},
                    entry_t, exit_t, entry_t + timedelta(minutes=75), path_bars=path)
    assert live["positions"]["FLAT"]["state"] == "held" and live["positions"]["FLAT"]["price"] == "100.5"
    assert live["positions"]["UP"]["state"] == "objectif"
    # Sans trajet (repères) : pas de vente anticipée.
    plain = simulate(["DOWN", "UP", "FLAT"], entry, exit_, {}, entry_t, exit_t, after)
    assert plain["early_exits"] == {} and plain["mean_return"] == pytest.approx((0.1 - 0.1 + 0.01) / 3)
    # Pendant la séance, une minute pas encore terminée n'est pas connue.
    assert simulate(["DOWN"], entry, exit_, {}, entry_t, exit_t, entry_t + timedelta(minutes=20),
                    path_bars=path)["early_exits"] == {}


def test_comparaison_sans_stop_ni_objectif():
    """Le même calcul sans la règle : chaque titre gardé jusqu'à l'heure de vente (DOWN 110, UP 90, FLAT 101)."""
    from datetime import datetime, timedelta, timezone
    from core.portfolio import simulate
    entry_t = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
    exit_t = datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
    cols = ["symbol", "timestamp", "open", "close", "volume"]
    entry = pd.DataFrame([(s, entry_t, Decimal("100"), Decimal("100"), 1) for s in ("DOWN", "UP", "FLAT")], columns=cols)
    exit_ = pd.DataFrame([(s, exit_t - timedelta(minutes=1), Decimal(p), Decimal(p), 1)
                          for s, p in (("DOWN", "110"), ("UP", "90"), ("FLAT", "101"))], columns=cols)
    path = pd.DataFrame([("DOWN", entry_t + timedelta(minutes=20), Decimal("98.4"), Decimal("98.4"), 1),
                         ("UP", entry_t + timedelta(minutes=60), Decimal("103.2"), Decimal("103.2"), 1)], columns=cols)
    result = simulate(["DOWN", "UP", "FLAT"], entry, exit_, {}, entry_t, exit_t, exit_t + timedelta(minutes=30),
                      path_bars=path)
    assert result["hold_mean_return"] == pytest.approx((0.1 - 0.1 + 0.01) / 3)
    assert result["mean_return"] == pytest.approx((-0.016 + 0.032 + 0.01) / 3)   # la règle, inchangée
    assert result["hold_net_mean_return"] < result["hold_mean_return"]          # frais déduits
    positions = result["positions"]
    assert positions["DOWN"]["hold_net_return"] > 0.09 and positions["UP"]["hold_net_return"] < -0.09
    assert positions["FLAT"]["hold_net_return"] == pytest.approx(positions["FLAT"]["net_return"])
    # Repères (sans trajet) : pas de comparaison.
    assert "hold_mean_return" not in simulate(["FLAT"], entry, exit_, {}, entry_t, exit_t, exit_t + timedelta(minutes=30))


def test_apres_heure_de_vente_avant_les_prix_de_vente():
    """Entre l'heure de vente et l'arrivée des barres de vente : dernier échange connu, pas seulement les stops."""
    from datetime import datetime, timedelta, timezone
    from core.portfolio import simulate
    entry_t = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
    exit_t = datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
    cols = ["symbol", "timestamp", "open", "close", "volume"]
    entry = pd.DataFrame([(s, entry_t, Decimal("100"), Decimal("100"), 1) for s in ("DOWN", "FLAT")], columns=cols)
    path = pd.DataFrame([("DOWN", entry_t + timedelta(minutes=20), Decimal("98.4"), Decimal("98.4"), 1)], columns=cols)
    no_exit = pd.DataFrame(columns=cols)
    trades = {"FLAT": (exit_t - timedelta(minutes=2), Decimal("101")), "DOWN": (exit_t - timedelta(minutes=2), Decimal("99"))}
    result = simulate(["DOWN", "FLAT"], entry, no_exit, trades, entry_t, exit_t, exit_t + timedelta(minutes=5), path_bars=path)
    assert result["status"] == "closed" and result["priced"] == 2
    assert result["mean_return"] == pytest.approx((-0.016 + 0.01) / 2)
    assert result["hold_mean_return"] == pytest.approx((-0.01 + 0.01) / 2)


def test_stop_seul_sans_objectif():
    """take_profit=None : UP (touche +3,2 %) reste jusqu'à la vente (90) ; DOWN est vendu au stop."""
    from datetime import datetime, timedelta, timezone
    from core.portfolio import simulate
    entry_t = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
    exit_t = datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
    cols = ["symbol", "timestamp", "open", "close", "volume"]
    entry = pd.DataFrame([(s, entry_t, Decimal("100"), Decimal("100"), 1) for s in ("DOWN", "UP")], columns=cols)
    exit_ = pd.DataFrame([(s, exit_t - timedelta(minutes=1), Decimal(p), Decimal(p), 1)
                          for s, p in (("DOWN", "110"), ("UP", "90"))], columns=cols)
    path = pd.DataFrame([("DOWN", entry_t + timedelta(minutes=20), Decimal("98.4"), Decimal("98.4"), 1),
                         ("UP", entry_t + timedelta(minutes=60), Decimal("103.2"), Decimal("103.2"), 1)], columns=cols)
    result = simulate(["DOWN", "UP"], entry, exit_, {}, entry_t, exit_t, exit_t + timedelta(minutes=30),
                      path_bars=path, take_profit=None)
    assert set(result["early_exits"]) == {"DOWN"}
    assert result["mean_return"] == pytest.approx((-0.016 - 0.10) / 2)
