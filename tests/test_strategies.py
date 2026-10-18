"""Stratégies : chargement, stockage sous la famille, heures de vente, sortes de critères."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.opening import OpeningCriteria
from core.screener import Criteria
from core.strategy import load_strategies

FAMILY_DIR = Path(__file__).resolve().parents[1] / "research" / "algorithms" / "reprise_apres_baisse"
OPEN = datetime(2026, 10, 16, 13, 30, tzinfo=timezone.utc)
CLOSE = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)


def test_strategies_de_la_famille():
    every = {s.id: s for s in load_strategies(FAMILY_DIR, "reprise_apres_baisse")}
    # Ordre voulu par le propriétaire (accueil, menu « Stratégie »).
    assert list(every) == ["principale", "vente_cloture", "achat_10h30", "achat_10h30_vente_cloture", "ouverture_1h",
                           "ouverture_2h", "nuit_15h_ouverture", "nuit_15h_10h30", "nuit_15h55_ouverture", "nuit_15h55_10h30"]
    assert list(every)[0] == "principale" and every["principale"].storage == "reprise_apres_baisse"
    assert every["ouverture_1h"].storage == "reprise_apres_baisse/strategies/ouverture_1h"
    for s in every.values():
        assert set(s.criteria_files) == {"sans_per", "per12"}
    # Heures de vente : avant la clôture, ou après l'ouverture.
    assert every["principale"].exit_time(OPEN, CLOSE) == datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
    assert every["vente_cloture"].exit_time(OPEN, CLOSE) == datetime(2026, 10, 16, 19, 55, tzinfo=timezone.utc)
    assert every["ouverture_1h"].exit_time(OPEN, CLOSE) == datetime(2026, 10, 16, 14, 30, tzinfo=timezone.utc)
    assert every["ouverture_2h"].exit_time(OPEN, CLOSE) == datetime(2026, 10, 16, 15, 30, tzinfo=timezone.utc)
    # Décisions : 10 h 45 (principale), 10 h 15 (achat 10 h 30), 9 h 15 (ouverture : avant l'ouverture).
    decisions = {k: min(c.decision_minutes for c in s.criteria().values()) for k, s in every.items()}
    assert decisions == {"principale": 75, "achat_10h30": 45, "ouverture_1h": -15, "ouverture_2h": -15,
                         "vente_cloture": 75, "nuit_15h_10h30": 315, "nuit_15h_ouverture": 315,
                         "nuit_15h55_ouverture": 370, "achat_10h30_vente_cloture": 45, "nuit_15h55_10h30": 370}
    # De nuit : achat en fin de séance, vente la séance suivante (« à l'ouverture » = fin de la première minute).
    monday = datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)
    assert every["nuit_15h_10h30"].exit_time(OPEN, CLOSE, (monday, monday + timedelta(hours=6, minutes=30))) == datetime(2026, 10, 19, 14, 30, tzinfo=timezone.utc)
    assert every["nuit_15h55_ouverture"].exit_time(OPEN, CLOSE, (monday, monday + timedelta(hours=6, minutes=30))) == datetime(2026, 10, 19, 13, 31, tzinfo=timezone.utc)
    assert every["nuit_15h_ouverture"].overnight and not every["principale"].overnight
    assert every["achat_10h30_vente_cloture"].exit_time(OPEN, CLOSE) == datetime(2026, 10, 16, 19, 55, tzinfo=timezone.utc)
    assert every["nuit_15h55_10h30"].exit_time(OPEN, CLOSE, (monday, monday + timedelta(hours=6, minutes=30))) == datetime(2026, 10, 19, 14, 30, tzinfo=timezone.utc)
    assert isinstance(every["ouverture_1h"].criteria()["per12"], OpeningCriteria)
    assert isinstance(every["achat_10h30"].criteria()["per12"], Criteria)


def test_cache_de_vente_distingue_le_jour(monkeypatch):
    """Vente de nuit à 10 h 30 le lendemain et vente à 10 h 30 le jour même : deux lectures distinctes."""
    from dashboard import live
    keys = []
    monkeypatch.setattr(live, "cached", lambda key, fetch: keys.append(key) or live.EMPTY_BARS)
    same_day = datetime(2026, 10, 16, 14, 30, tzinfo=timezone.utc)
    next_day = datetime(2026, 10, 19, 14, 30, tzinfo=timezone.utc)
    live._exit_bars(None, "2026-10-16", "live", ["AAA"], same_day)
    live._exit_bars(None, "2026-10-16", "live", ["AAA"], next_day)
    assert len(set(keys)) == 2
