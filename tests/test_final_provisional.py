"""État de fin de séance : provisoire le soir même, définitif 12 h après la clôture."""

from datetime import datetime, timedelta, timezone

from dashboard.live import DEFINITIVE_AFTER, is_definitive

CLOSE = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc)


def test_provisoire_puis_definitif():
    assert DEFINITIVE_AFTER == timedelta(hours=12)
    assert not is_definitive(CLOSE + timedelta(minutes=15), CLOSE)
    assert not is_definitive(CLOSE + timedelta(hours=11, minutes=59), CLOSE)
    assert is_definitive(CLOSE + timedelta(hours=12), CLOSE)
