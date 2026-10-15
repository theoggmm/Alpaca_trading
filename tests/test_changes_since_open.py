"""Variation depuis l'ouverture des titres de la sélection : définition et datation."""

from datetime import timedelta
from decimal import Decimal

from dataclasses import replace

from core.screener import changes_since_open
from tests.synthetic import CRITERIA, MARKET_OPEN

CLOSE = MARKET_OPEN + timedelta(hours=6, minutes=30)
NOW = MARKET_OPEN + timedelta(hours=2)
OPENS = {"AAA": Decimal("100"), "BBB": Decimal("50"), "CCC": Decimal("20")}


def test_dernier_prix_sur_premier_prix_de_la_seance():
    at = MARKET_OPEN + timedelta(minutes=100)
    changes = changes_since_open(OPENS, {"AAA": (at, Decimal("102")), "BBB": (at, Decimal("49"))},
                                 MARKET_OPEN, CLOSE, NOW)
    assert changes["AAA"] == {"change": 0.02, "price": "102", "at": at.isoformat()}
    assert changes["BBB"]["change"] == -0.02
    assert "CCC" not in changes  # aucun échange connu : pas de valeur inventée


def test_echanges_hors_seance_ou_futurs_ignores():
    trades = {
        "AAA": (MARKET_OPEN - timedelta(minutes=1), Decimal("150")),   # pré-ouverture
        "BBB": (NOW + timedelta(minutes=1), Decimal("80")),            # postérieur à l'observation
        "CCC": (CLOSE + timedelta(seconds=1), Decimal("30")),          # après la clôture
    }
    assert changes_since_open(OPENS, trades, MARKET_OPEN, CLOSE, CLOSE + timedelta(minutes=10)) == {
        "BBB": {"change": 0.6, "price": "80", "at": (NOW + timedelta(minutes=1)).isoformat()}}
    assert changes_since_open(OPENS, trades, MARKET_OPEN, CLOSE, NOW) == {}


def test_premier_prix_de_la_seance_connu_a_l_instant_d_observation():
    import pandas as pd
    from core.screener import session_open_prices
    bars = pd.DataFrame([("AAA", MARKET_OPEN, Decimal("10"), Decimal("10.2"), 100),
                         ("AAA", MARKET_OPEN + timedelta(minutes=1), Decimal("10.3"), Decimal("10.4"), 100),
                         ("BBB", MARKET_OPEN + timedelta(minutes=3), Decimal("20"), Decimal("20.1"), 100)],
                        columns=["symbol", "timestamp", "open", "close", "volume"])
    assert session_open_prices(bars, MARKET_OPEN, MARKET_OPEN + timedelta(minutes=2)) == {"AAA": Decimal("10")}
    assert session_open_prices(bars, MARKET_OPEN, NOW) == {"AAA": Decimal("10"), "BBB": Decimal("20")}


def test_variation_depuis_l_achat_de_la_simulation():
    import pandas as pd
    from dashboard.live import _since_entry
    base = {"run_id": "r1", "variant": "per12", "criteria": CRITERIA.to_json(),
            "selection": [{"symbol": "AAA"}, {"symbol": "BBB"}, {"symbol": "CCC"}]}
    confirmed = {"run_id": "r2", "variant": "per12_confirmation",
                 "criteria": replace(CRITERIA, confirmation_minutes=15).to_json(), "selection": [{"symbol": "AAA"}]}
    at = MARKET_OPEN + timedelta(minutes=75)        # achat de la liste à 10 h 45 (décision 10 h 30 + 15 min)
    later = MARKET_OPEN + timedelta(minutes=90)     # achat de la liste avec confirmation à 11 h 00
    bars = pd.DataFrame([("AAA", at, Decimal("100"), Decimal("101"), 100),
                         ("BBB", at + timedelta(minutes=1), Decimal("50"), Decimal("50"), 100),
                         ("AAA", later, Decimal("102"), Decimal("102"), 100)],
                        columns=["symbol", "timestamp", "open", "close", "volume"])
    seen = later + timedelta(minutes=30)
    trades = {"AAA": (seen, Decimal("103")), "BBB": (seen, Decimal("49"))}
    since = _since_entry([base, confirmed], bars, trades, MARKET_OPEN, CLOSE, seen + timedelta(minutes=1))
    # Chaque version part de son propre prix d'achat : 100 à 10 h 45, 102 à 11 h 00.
    assert since["per12"]["AAA"]["change"] == 0.03 and since["per12"]["BBB"]["change"] == -0.02
    assert "CCC" not in since["per12"]
    assert since["per12_confirmation"]["AAA"]["change"] == float(Decimal("103") / Decimal("102") - 1)
    # Avant la fin de la barre d'achat de 11 h 00 : rien n'est inventé pour la version avec confirmation.
    assert _since_entry([confirmed], bars, trades, MARKET_OPEN, CLOSE, later) == {"per12_confirmation": {}}
