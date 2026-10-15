"""Règles contre l'achat au sommet : « pas au sommet » (version 4) et « confirmation » (version 3)."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from core.screener import Criteria, screen
from tests.synthetic import CRITERIA, DECISION_TIME, MARKET_OPEN, market

FAMILY_DIR = Path(__file__).resolve().parents[1] / "research" / "algorithms" / "reprise_apres_baisse"
PER12 = replace(CRITERIA, version=2, max_pe=Decimal("12"))
NOT_AT_TOP = replace(CRITERIA, min_gap_below_high=Decimal("0.002"))
CONFIRM = replace(CRITERIA, confirmation_minutes=15)
CONFIRM_TIME = MARKET_OPEN + timedelta(minutes=75)


def _set(minute, symbol, minutes, factor):
    """Multiplie le prix de symbol sur les minutes données (barres commençant à l'ouverture + m)."""
    rows = (minute["symbol"] == symbol) & minute["timestamp"].isin([MARKET_OPEN + timedelta(minutes=m) for m in minutes])
    minute.loc[rows, ["open", "close"]] = minute.loc[rows, ["open", "close"]].map(lambda p: p * factor)
    return minute


def test_versions_3_et_4_archivees():
    # Retirées le 15 octobre 2026 avant tout run (une liste par règle) ; gardées pour la trace.
    assert Criteria.from_file(FAMILY_DIR / "archive" / "criteres_v3_per12_confirmation.json") == replace(
        PER12, version=3, confirmation_minutes=15)
    assert Criteria.from_file(FAMILY_DIR / "archive" / "criteres_v4_per12_pas_au_sommet.json") == replace(
        PER12, version=4, min_gap_below_high=Decimal("0.002"))


def test_les_deux_regles_ensemble():
    daily, minute = market()
    both = replace(CRITERIA, min_gap_below_high=Decimal("0.002"), confirmation_minutes=15)
    # DOWN1 : redescendu de son plus haut à 10 h 30 (pas au sommet), puis tenu jusqu'à 10 h 45 (confirmé).
    minute = _set(minute, "DOWN1", [30], Decimal("1.0162"))
    minute = _set(minute, "DOWN1", [59], Decimal("0.995"))
    minute = _set(minute, "DOWN1", range(60, 75), Decimal("2.02"))
    selection, funnel = screen(daily, minute, MARKET_OPEN, CONFIRM_TIME, both)
    assert [i["symbol"] for i in selection] == ["DOWN1"]
    assert funnel["pas_au_sommet"] == 1 and funnel["confirmation"] == 1


def test_pas_au_sommet_exclut_le_titre_a_son_plus_haut():
    daily, minute = market()
    # Hausse régulière : chaque titre finit la première heure à son plus haut, donc exclu...
    assert screen(daily, minute, MARKET_OPEN, DECISION_TIME, NOT_AT_TOP)[0] == []
    # ...sauf DOWN1, monté plus haut à 10 h 00 puis redescendu : 1 % sous son plus haut à 10 h 30.
    minute = _set(minute, "DOWN1", [30], Decimal("1.0162"))
    minute = _set(minute, "DOWN1", [59], Decimal("0.995"))
    selection, funnel = screen(daily, minute, MARKET_OPEN, DECISION_TIME, NOT_AT_TOP)
    assert [i["symbol"] for i in selection] == ["DOWN1"] and selection[0]["gap_below_high"] >= 0.002
    assert funnel["pas_au_sommet"] == 1


def test_confirmation_exclut_le_titre_qui_redescend():
    daily, minute = market()
    # Les données synthétiques s'effondrent après 10 h 30 : aucun titre n'est confirmé à 10 h 45.
    assert screen(daily, minute, MARKET_OPEN, CONFIRM_TIME, CONFIRM)[0] == []
    # DOWN2 reste au-dessus de son prix de 10 h 30 jusqu'à 10 h 45 : confirmé.
    minute = _set(minute, "DOWN2", range(60, 75), Decimal("2.02"))
    selection, funnel = screen(daily, minute, MARKET_OPEN, CONFIRM_TIME, CONFIRM)
    assert [i["symbol"] for i in selection] == ["DOWN2"] and selection[0]["return_confirmation"] >= 0
    assert funnel["confirmation"] == 1
    # La hausse de la première heure reste mesurée à 10 h 30, pas à 10 h 45.
    reference, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, replace(CRITERIA, count=500, max_pairwise_correlation=1.0))
    assert selection[0]["return_first_hour"] == next(i for i in reference if i["symbol"] == "DOWN2")["return_first_hour"]


def test_confirmation_datation():
    daily, minute = market()
    minute = _set(minute, "DOWN2", range(60, 75), Decimal("2.02"))
    before, _ = screen(daily, minute, MARKET_OPEN, CONFIRM_TIME, CONFIRM)
    # Données postérieures à 10 h 45 modifiées : aucun effet.
    minute = _set(minute, "DOWN2", range(75, 120), Decimal("100"))
    assert screen(daily, minute, MARKET_OPEN, CONFIRM_TIME, CONFIRM)[0] == before
    # La décision ne peut pas être prise à 10 h 30 avec une règle de confirmation.
    with pytest.raises(ValueError):
        screen(daily, minute, MARKET_OPEN, DECISION_TIME, CONFIRM)
