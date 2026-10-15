"""Métriques : séries datées seulement, calculs vérifiés à la main."""

import math

import pytest

from core.performance_metrics import (DuplicateDateError, UndatedReturnsError, cumulative, paired_difference,
                                      sharpe, summary)

SERIES = {"2026-10-14": 0.01, "2026-10-15": -0.005, "2026-10-16": 0.02}


def test_series_non_datees_ou_dupliquees_refusees():
    with pytest.raises(UndatedReturnsError):
        sharpe([0.01, 0.02])
    with pytest.raises(DuplicateDateError):
        sharpe([("2026-10-14", 0.01), ("2026-10-14", 0.02)])


def test_cumul_et_resume():
    assert cumulative(SERIES)[-1][1] == pytest.approx(1.01 * 0.995 * 1.02 - 1)
    s = summary(SERIES)
    assert s["n"] == 3 and s["positive_share"] == pytest.approx(2 / 3)
    assert s["total"] == pytest.approx(1.01 * 0.995 * 1.02 - 1)
    assert s["annualized"] == pytest.approx((1.01 * 0.995 * 1.02) ** (252 / 3) - 1)
    assert s["suspect"] and s["worst"] == -0.005


def test_difference_appariee():
    other = {"2026-10-14": 0.0, "2026-10-15": -0.01, "2026-10-17": 0.5}   # 17 : pas de date commune
    d = paired_difference(SERIES, other)
    assert d["n"] == 2 and d["mean"] == pytest.approx(0.0075)
    diffs = [0.01, 0.005]
    sd = (sum((x - 0.0075) ** 2 for x in diffs) / 1) ** 0.5
    assert d["t"] == pytest.approx(0.0075 / (sd / math.sqrt(2)))
