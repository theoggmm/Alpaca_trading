"""
Preuve de l'invariant de datation (règle 1) pour la famille reprise_apres_baisse :
aucune barre non terminée à l'instant de décision ne peut influencer la sélection.
"""

from datetime import timedelta

import pandas as pd

from core.datation import usable_bars
from core.screener import DAY, MINUTE, screen
from tests.synthetic import CRITERIA, DECISION_TIME, MARKET_OPEN, market


def _past_only(daily, minute):
    return usable_bars(daily, DAY, DECISION_TIME), usable_bars(minute, MINUTE, DECISION_TIME)


def test_barre_terminee_a_l_instant_de_decision_utilisable_suivante_non():
    bars = pd.DataFrame({"timestamp": [DECISION_TIME - timedelta(minutes=1), DECISION_TIME]})
    kept = usable_bars(bars, MINUTE, DECISION_TIME)
    assert list(kept["timestamp"]) == [DECISION_TIME - timedelta(minutes=1)]


def test_seance_du_jour_exclue_veille_incluse():
    daily, _ = market()
    kept = usable_bars(daily, DAY, DECISION_TIME)
    assert kept["timestamp"].max() + DAY <= DECISION_TIME
    assert (daily["timestamp"] + DAY > DECISION_TIME).any()


def test_selection_identique_avec_ou_sans_donnees_futures():
    daily, minute = market()
    with_future, funnel_future = screen(daily, minute, MARKET_OPEN, DECISION_TIME, CRITERIA)
    past_daily, past_minute = _past_only(daily, minute)
    without_future, funnel_past = screen(past_daily, past_minute, MARKET_OPEN, DECISION_TIME, CRITERIA)
    assert with_future, "le marché fictif doit produire une sélection non vide"
    assert with_future == without_future
    assert funnel_future == funnel_past


def test_donnees_futures_modifiees_sans_effet():
    daily, minute = market()
    reference, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, CRITERIA)

    future_daily = daily["timestamp"] + DAY > DECISION_TIME
    future_minute = minute["timestamp"] + MINUTE > DECISION_TIME
    daily.loc[future_daily, "close"] = daily.loc[future_daily, "close"] * 100
    minute.loc[future_minute, "close"] = minute.loc[future_minute, "close"] / 100

    altered, _ = screen(daily, minute, MARKET_OPEN, DECISION_TIME, CRITERIA)
    assert altered == reference
