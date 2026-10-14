"""Les critères de la famille reprise_apres_baisse sont appliqués tels qu'écrits."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from core.screener import Criteria, screen
from core.universe import eligible_symbols
from tests.synthetic import CRITERIA, DECISION_TIME, MARKET_OPEN, market

FAMILY_DIR = Path(__file__).resolve().parents[1] / "research" / "algorithms" / "reprise_apres_baisse"


def test_fichiers_de_criteres_des_deux_versions():
    assert Criteria.from_file(FAMILY_DIR / "criteres_sans_per.json") == CRITERIA
    # Version 2 = critères de la version 1 + PER sur 12 mois glissants < 12.
    assert Criteria.from_file(FAMILY_DIR / "criteres_per12.json") == replace(CRITERIA, version=2, max_pe=Decimal("12"))


def test_seuls_les_titres_en_baisse_puis_en_hausse_sont_retenus():
    daily, minute = market()
    selection, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, CRITERIA)
    for item in selection:
        assert item["return_month"] < 0
        assert item["return_day_minus_2"] > 0 and item["return_day_minus_1"] > 0
        assert item["return_first_hour"] > 0
    assert all(item["symbol"].startswith(("DOWN", "TWIN")) for item in selection)
    assert [i["return_month"] for i in selection] == sorted(i["return_month"] for i in selection)


def test_titre_peu_liquide_exclu():
    daily, minute = market()
    selection, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, replace(CRITERIA, count=100))
    assert "ILLIQ" not in {i["symbol"] for i in selection}


def test_titres_trop_correles_jamais_ensemble():
    daily, minute = market()
    selection, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, replace(CRITERIA, count=100))
    symbols = {i["symbol"] for i in selection}
    assert not {"DOWN0", "TWINB"} <= symbols
    assert all(i["max_correlation_with_previous"] is None
               or i["max_correlation_with_previous"] <= CRITERIA.max_pairwise_correlation for i in selection)


def test_selection_jamais_completee_artificiellement():
    daily, minute = market()
    selection, funnel = screen(daily, minute, MARKET_OPEN, DECISION_TIME, replace(CRITERIA, count=100))
    assert len(selection) == funnel["selection_diversifiee"] < 100


def test_etf_et_titres_de_test_exclus():
    assets = [{"symbol": s, "class": "us_equity", "status": "active", "tradable": True}
              for s in ("AAPL", "SPY", "ZTEST", "OTCX")]
    listings = {
        "AAPL": {"name": "Apple", "etf": False, "test_issue": False},
        "SPY": {"name": "SPDR S&P 500", "etf": True, "test_issue": False},
        "ZTEST": {"name": "Test", "etf": False, "test_issue": True},
    }
    symbols, funnel = eligible_symbols(assets, listings)
    assert symbols == ["AAPL"]
    assert funnel == {"actifs_negociables": 4, "cotes_sur_une_bourse_us": 3, "hors_etf_et_titres_de_test": 1}


def test_per_maximum_exclut_les_titres_sans_benefice_ou_trop_chers():
    daily, minute = market()
    eps = {"filed": "2026-10-01", "start": "2025-10-01", "end": "2026-09-30"}  # exercice récent, déposé avant
    asked = []

    def earnings_for(symbols):
        asked.extend(symbols)
        # DOWN0..DOWN9 : bénéfice élevé (PER bas) ; DOWN10..DOWN19 : bénéfice faible (PER haut) ; autres : rien.
        return {s: [{**eps, "val": Decimal("10") if int(s[4:]) < 10 else Decimal("0.5")}]
                for s in symbols if s.startswith("DOWN")}

    selection, funnel = screen(daily, minute, MARKET_OPEN, DECISION_TIME, replace(CRITERIA, max_pe=Decimal("12")),
                               earnings_for=earnings_for)
    assert asked, "les bénéfices ne sont demandés que pour les titres en hausse sur la première heure"
    assert funnel["per_maximum"] <= funnel["hausse_premiere_heure"]
    assert selection and all(item["symbol"].startswith("DOWN") and int(item["symbol"][4:]) < 10 for item in selection)
    assert all(Decimal(item["pe_ttm"]) < 12 for item in selection)
