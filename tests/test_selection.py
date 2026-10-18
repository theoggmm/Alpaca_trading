"""Sélection du jour : filtres 24 h et 2-3 jours, garde-fous, publications de résultats, 7 actions au plus."""

from datetime import date
from decimal import Decimal

from core.selection import (SelectionRules, breadth, choose_stocks, day_return, likely_reporting, market_ok,
                            pick_strategies, sector_trends)


def test_choix_des_strategies():
    history = {
        "A": [("d1", 0.002), ("d2", 0.003), ("d3", 0.004)],    # tout positif : retenue
        "B": [("d1", 0.010), ("d2", 0.010), ("d3", -0.001)],   # dernières 24 h négatives : écartée
        "C": [("d1", -0.004), ("d2", 0.001), ("d3", 0.001)],   # somme trop faible : écartée
        "D": [("d1", 0.006), ("d2", -0.001), ("d3", 0.005)],   # 2 sur 3 positives, somme 1 % : retenue, première
        "E": [("d1", None), ("d2", None), ("d3", 0.004)],      # pas assez de résultats : écartée
    }
    assert [c for c, _ in pick_strategies(history)] == ["D", "A"]
    assert pick_strategies({k: v for k, v in history.items() if k in "BCE"}) == []     # zéro, c'est permis


def test_garde_fous_et_largeur():
    assert market_ok(False, 0.9, 0.0) == (False, "marche_en_mauvaise_forme")
    assert market_ok(True, 0.4, 0.0)[0] is False and market_ok(True, 0.6, 0.05)[0] is False
    assert market_ok(True, 0.6, 0.01) == (True, None) and market_ok(True, None, None) == (True, None)
    opens = {"A": Decimal("10"), "B": Decimal("10"), "C": Decimal("10")}
    assert breadth(opens, {"A": Decimal("11"), "B": Decimal("9"), "C": Decimal("10.5")}) == 2 / 3
    trends = sector_trends(opens, {"A": Decimal("11"), "B": Decimal("9"), "C": Decimal("10.5")},
                           {"A": "Tech", "B": "Tech", "C": "Energy"})
    assert abs(trends["Tech"]) < 1e-12 and abs(trends["Energy"] - 0.05) < 1e-12


def test_publications_probables():
    releases = [{"date": "2025-07-24"}, {"date": "2025-10-23"}]   # deux publications passées
    # Achat le 21 janvier 2026, vente le 22 : 2025-10-23 + 91 jours = 22 janvier 2026, dans la fenêtre.
    assert likely_reporting(releases, date(2026, 1, 21), date(2026, 1, 22))
    # Achat le 2 décembre : aucune publication attendue autour.
    assert not likely_reporting(releases, date(2025, 12, 2), date(2025, 12, 3))
    # Une publication postérieure à l'achat n'est pas connue : elle ne compte pas.
    assert not likely_reporting([{"date": "2025-12-03"}], date(2025, 12, 2), date(2025, 12, 3))


def test_sept_actions_au_plus():
    lists = {"A": ["X1", "X2", "X3", "X4", "X5"], "B": ["X2", "Y1", "Y2", "Y3", "Y4"], "C": ["Z1", "Z2", "Z3"]}
    chosen = choose_stocks([("A", 1), ("B", 1), ("C", 1)], lists, {"A": {"X1"}})
    assert chosen == {"A": ["X2", "X3", "X4"], "B": ["Y1", "Y2"], "C": ["Z1", "Z2"]}
    assert sum(len(v) for v in chosen.values()) == 7
    assert choose_stocks([("C", 1)], lists, {}) == {"C": ["Z1", "Z2", "Z3"]}   # moins de 7 si la liste est courte
    assert day_return(chosen, {"A": {"X2": 0.01, "X3": 0.0, "X4": 0.02}, "B": {"Y1": -0.01, "Y2": 0.0},
                               "C": {"Z1": 0.01, "Z2": 0.0}}) == 0.03 / 7
    assert day_return({}, {}) == 0.0
    assert SelectionRules().max_stocks == 7
