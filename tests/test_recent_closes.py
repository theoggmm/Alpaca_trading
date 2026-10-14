"""Clôtures du dernier mois pour les graphiques : séances terminées avant l'ouverture seulement."""

from core.screener import recent_closes
from tests.synthetic import MARKET_OPEN, market


def test_dernieres_seances_avant_l_ouverture():
    daily, _ = market()
    closes = recent_closes(daily, MARKET_OPEN, {"DOWN0", "CALM1", "INCONNU"}, 22)
    assert set(closes) == {"CALM1", "DOWN0"}
    series = closes["DOWN0"]
    assert len(series) == 22
    assert series[-1][0] == "2026-10-12"            # veille ; la séance du jour et la suivante sont exclues
    assert [d for d, _ in series] == sorted(d for d, _ in series)
    last_bar = daily[(daily["symbol"] == "DOWN0") & (daily["timestamp"].dt.strftime("%Y-%m-%d") == "2026-10-12")]
    assert series[-1][1] == str(last_bar["close"].iloc[0])
