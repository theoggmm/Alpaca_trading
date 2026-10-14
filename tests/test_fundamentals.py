"""Bénéfice par action sur 12 mois glissants et PER : définitions et datation."""

from datetime import date
from decimal import Decimal

from core.fundamentals import price_to_earnings, ttm_eps


def _e(start, end, val, filed):
    return {"start": start, "end": end, "val": Decimal(val), "filed": filed}


# Exercice calé sur l'année civile ; 10-K de 2025 déposé en février 2026, trimestres 2025 et 2026.
DECLARATIONS = [
    _e("2025-01-01", "2025-06-30", "2.00", "2025-08-01"),   # cumul 6 mois 2025
    _e("2025-01-01", "2025-12-31", "5.00", "2026-02-20"),   # exercice 2025
    _e("2026-01-01", "2026-03-31", "1.10", "2026-05-05"),   # T1 2026
    _e("2026-01-01", "2026-06-30", "2.40", "2026-08-04"),   # cumul 6 mois 2026
]


def test_douze_mois_glissants():
    # 5,00 (exercice 2025) + 2,40 (6 mois 2026) - 2,00 (6 mois 2025) = 5,40
    assert ttm_eps(DECLARATIONS, date(2026, 10, 14)) == Decimal("5.40")


def test_declaration_deposee_apres_la_decision_ignoree():
    # Le 4 août, le cumul 6 mois 2026 n'est pas encore connu (déposé le jour même) : seul le T1 l'est,
    # mais il manque le T1 2025 pour le compléter -> non calculable plutôt qu'approximé.
    assert ttm_eps(DECLARATIONS, date(2026, 8, 4)) is None
    assert ttm_eps(DECLARATIONS, date(2026, 8, 5)) == Decimal("5.40")


def test_exercice_complet_le_plus_recent():
    assert ttm_eps(DECLARATIONS, date(2026, 3, 1)) == Decimal("5.00")


def test_donnees_trop_anciennes():
    assert ttm_eps(DECLARATIONS[:2], date(2026, 10, 14)) is None


def test_per():
    assert price_to_earnings(Decimal("54"), Decimal("5.40")) == Decimal("10")
    assert price_to_earnings(Decimal("54"), Decimal("-1")) is None
    assert price_to_earnings(Decimal("54"), None) is None
