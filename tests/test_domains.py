"""Tendance par domaine : moyenne simple sur l'univers liquide, sans donnée future."""

import statistics

from core.domains import domain_trends
from core.screener import DAY, liquid_universe
from tests.synthetic import CRITERIA, DECISION_TIME, market

DOMAINS = {f"{prefix}{i}": name for prefix, name in (("DOWN", "Baisse"), ("CALM", "Calme"), ("WILD", "Agité"))
           for i in range(70)}


def test_moyenne_par_domaine_et_titres_non_classes():
    daily, _ = market()
    bubbles, unclassified = domain_trends(daily, DECISION_TIME, CRITERIA, DOMAINS)
    liquid, _ = liquid_universe(daily, DECISION_TIME, CRITERIA)

    for bubble in bubbles:
        returns = [s.return_month for s in liquid if DOMAINS.get(s.symbol) == bubble["domain"]]
        assert bubble["n"] == len(returns)
        assert bubble["mean_return"] == statistics.fmean(returns)
    assert unclassified == sum(1 for s in liquid if s.symbol not in DOMAINS)  # TWINB
    assert unclassified == 1
    assert {b["domain"]: b["mean_return"] < 0 for b in bubbles}["Baisse"]
    assert [b["mean_return"] for b in bubbles] == sorted((b["mean_return"] for b in bubbles), reverse=True)


def test_donnees_futures_sans_effet_sur_les_domaines():
    daily, _ = market()
    reference = domain_trends(daily, DECISION_TIME, CRITERIA, DOMAINS)
    future = daily["timestamp"] + DAY > DECISION_TIME
    daily.loc[future, "close"] = daily.loc[future, "close"] * 100
    assert domain_trends(daily, DECISION_TIME, CRITERIA, DOMAINS) == reference
