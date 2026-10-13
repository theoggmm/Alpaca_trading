"""Les critères de la famille reprise_apres_baisse sont appliqués tels qu'écrits."""

from dataclasses import replace
from pathlib import Path

from core.screener import Criteria, screen
from core.universe import eligible_symbols
from tests.synthetic import CRITERIA, DECISION_TIME, MARKET_OPEN, market

CRITERIA_FILE = Path(__file__).resolve().parents[1] / "research" / "algorithms" / "reprise_apres_baisse" / "criteres.json"


def test_fichier_de_criteres_lisible():
    assert Criteria.from_file(CRITERIA_FILE) == CRITERIA


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
