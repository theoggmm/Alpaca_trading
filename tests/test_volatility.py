"""
Stratégie « Volatilité » (core/volatility.py, T25) : liste par domaine, complétée au plus proche, datation, et suivi
du panier jusqu'à l'objectif (vente à la première minute qui l'atteint, sur une ou plusieurs séances).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from core.volatility import VolatilityRules, net_gain, screen_basket, track_round

ROOT = Path(__file__).resolve().parents[1]
RULES = VolatilityRules.from_file(ROOT / "research" / "algorithms" / "volatilite" / "regles.json")
DECISION = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)
OPEN_2 = DECISION + timedelta(days=1)


def _daily(spec, sessions=140, seed=1):
    """spec : symbole -> (volatilité quotidienne, tendance totale, volume) ; barres quotidiennes avant DECISION."""
    rng = np.random.default_rng(seed)
    rows = []
    days = [DECISION - timedelta(days=sessions - i) for i in range(sessions)]
    for symbol, (vol, trend, volume) in spec.items():
        steps = rng.normal(0, vol, sessions)
        steps += (np.log(1 + trend) - steps[-126:].sum()) / 126 * (np.arange(sessions) >= sessions - 126)
        prices = 20 * np.exp(np.cumsum(steps))
        rows += [(symbol, d.replace(hour=4), Decimal(str(round(p, 4))), Decimal(str(round(p, 4))), volume)
                 for d, p in zip(days, prices)]
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "close", "volume"])


def test_liste_par_domaine_complete_au_plus_proche():
    # Domaine A : 6 titres stricts (très volatils, très échangés) ; domaine B : 2 stricts + 1 moins échangé (~30 M$).
    spec = {f"A{i}": (0.06, 0.2, 10_000_000) for i in range(6)}
    spec |= {"B0": (0.06, 0.1, 10_000_000), "B1": (0.06, 0.0, 10_000_000), "B2": (0.06, 0.1, 1_400_000)}
    spec |= {f"C{i}": (0.01, 0.0, 10_000_000) for i in range(60)}      # calmes : fixent les seuils de volatilité
    spec |= {"D0": (0.06, -0.5, 10_000_000), "X0": (0.06, 0.3, 10_000_000)}   # D0 en chute ; X0 domaine exclu
    daily = _daily(spec)
    domains = {s: s[0] for s in spec} | {"X0": "Crypto Assets"}
    picked, summary = screen_basket(daily, DECISION, RULES, lambda names: {s: domains[s] for s in names})
    by_domain = {}
    for item in picked:
        by_domain.setdefault(item["domain"], []).append(item)
    assert len(by_domain["A"]) == 5 and all(i["step"] == "strict" for i in by_domain["A"])
    assert {i["symbol"] for i in by_domain["B"]} == {"B0", "B1", "B2"}
    assert next(i for i in by_domain["B"] if i["symbol"] == "B2")["step"] == "volume_20M"
    assert "D" not in by_domain and "Crypto Assets" not in by_domain


def test_datation_la_liste_ignore_les_seances_futures():
    spec = {f"A{i}": (0.06, 0.2, 10_000_000) for i in range(6)} | {f"C{i}": (0.01, 0.0, 10_000_000) for i in range(20)}
    daily = _daily(spec)
    future = daily[daily["timestamp"] >= daily["timestamp"].max()].assign(
        timestamp=lambda d: d["timestamp"] + timedelta(days=2), close=Decimal("1"))
    domains = lambda names: {s: s[0] for s in names}
    assert screen_basket(daily, DECISION, RULES, domains) == screen_basket(
        pd.concat([daily, future], ignore_index=True), DECISION, RULES, domains)


def _minutes(paths, start):
    """paths : symbole -> [cours de clôture minute] à partir de start ; ouverture de la 1re barre = 1er cours."""
    rows = []
    for symbol, closes in paths.items():
        for k, c in enumerate(closes):
            rows.append((symbol, start + timedelta(minutes=k), Decimal(str(closes[0] if k == 0 else closes[k - 1])),
                         Decimal(str(c)), 100))
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "close", "volume"])


def test_vente_a_la_premiere_minute_qui_atteint_l_objectif():
    # 2 titres à 100 $ : 2 500 $ chacun ; +5 % sur les deux à la 3e minute = +250 $ brut, ~+245 $ net.
    bars = _minutes({"AAA": [100, 101, 105, 110], "BBB": [100, 100, 105, 90]}, DECISION)
    session = [(DECISION, DECISION + timedelta(hours=6, minutes=30))]
    r = track_round(["AAA", "BBB"], bars, DECISION, session, DECISION + timedelta(hours=7),
                    Decimal("5000"), Decimal("200"), Decimal("5"))
    assert r["status"] == "sold"
    assert r["sold_at"] == (DECISION + timedelta(minutes=3)).isoformat()
    assert r["sold_gain"] == net_gain(Decimal("5250"), Decimal("5000"), Decimal("5")) >= Decimal("200")
    assert r["sessions_held"] == 1


def test_panier_garde_sur_plusieurs_seances_et_rien_de_futur():
    day1 = _minutes({"AAA": [100, 101, 102], "BBB": [100, 99, 101]}, DECISION)
    day2 = _minutes({"AAA": [106, 107], "BBB": [104, 104]}, OPEN_2)
    bars = pd.concat([day1, day2], ignore_index=True)
    sessions = [(DECISION, DECISION + timedelta(hours=6, minutes=30)), (OPEN_2, OPEN_2 + timedelta(hours=6, minutes=30))]
    args = (Decimal("5000"), Decimal("200"), Decimal("5"))
    # Le premier soir : objectif pas atteint, le panier reste.
    evening = track_round(["AAA", "BBB"], bars, DECISION, sessions[:1], DECISION + timedelta(hours=8), *args)
    assert evening["status"] == "live" and evening["sold_at"] is None
    # Le lendemain : la hausse de la nuit est vendue à la première minute de la séance (5 % sur le panier).
    later = track_round(["AAA", "BBB"], bars, DECISION, sessions, OPEN_2 + timedelta(hours=1), *args)
    assert later["status"] == "sold" and later["sold_at"] == (OPEN_2 + timedelta(minutes=1)).isoformat()
    assert later["sessions_held"] == 2


def test_une_vague_par_seance_avec_la_meme_liste(monkeypatch):
    # AAA atteint +200 $ (sur 5 000 $) le 1er jour, BBB jamais : le 2e jour, une nouvelle vague rachète les deux de
    # zéro (liste du premier jour), la vague du 1er jour garde BBB.
    from datetime import date, time
    from dashboard import volatility

    day1, day2 = date(2026, 10, 21), date(2026, 10, 22)
    open1, open2 = DECISION, OPEN_2
    bars = pd.concat([_minutes({"AAA": [100, 102, 105], "BBB": [100, 99, 98]}, open1),
                      _minutes({"AAA": [104, 104], "BBB": [99, 99]}, open2)], ignore_index=True)

    class Reader:
        def sessions(self, start, end):
            return [(d, time(9, 30), time(16, 0)) for d in (day1, day2) if start <= d <= end]

        def bars(self, symbols, timeframe, start, end):
            return bars[bars["symbol"].isin(symbols) & (bars["timestamp"] >= start) & (bars["timestamp"] < end)]

    item = lambda s: {"symbol": s, "name": s, "domain": "D", "step": "strict"}
    first = {"run_id": "r1", "session_date": day1.isoformat(), "selection": [item("AAA"), item("BBB")]}
    monkeypatch.setattr(volatility.basket, "list_for", lambda d: first if d == day1 else None)
    monkeypatch.setattr(volatility, "cached", lambda key, fetch, **_: fetch())
    every, upcoming, _ = volatility.positions(Reader(), open2 + timedelta(hours=1))
    assert [(p["symbol"], p["session_date"], p["status"]) for p in every] == [
        ("AAA", "2026-10-21", "sold"), ("BBB", "2026-10-21", "live"),
        ("AAA", "2026-10-22", "live"), ("BBB", "2026-10-22", "live")]
    assert every[0]["sold_at"] == (open1 + timedelta(minutes=3)).isoformat()
    assert every[0]["elapsed_seconds"] == 180 and upcoming is None


def test_objectif_franchi_la_nuit_puis_reperdu_pas_de_vente():
    # Après la clôture, AAA passe à 110 (+10 %, au-delà de +200 $) ; à l'ouverture suivante elle est retombée à 102 :
    # rien n'est vendu (seules les minutes de séance régulière comptent).
    close1 = DECISION + timedelta(hours=6, minutes=30)
    bars = pd.concat([_minutes({"AAA": [100, 101]}, DECISION), _minutes({"AAA": [110, 110]}, close1 + timedelta(hours=1)),
                      _minutes({"AAA": [102, 102]}, OPEN_2)], ignore_index=True)
    sessions = [(DECISION, close1), (OPEN_2, OPEN_2 + timedelta(hours=6, minutes=30))]
    r = track_round(["AAA"], bars, DECISION, sessions, OPEN_2 + timedelta(hours=1),
                    Decimal("5000"), Decimal("200"), Decimal("5"))
    assert r["status"] == "live" and r["sold_at"] is None and r["last"]["AAA"] == Decimal("102")


def test_vente_a_l_echeance_selon_le_signe():
    from core.volatility import exit_with_deadline
    t0 = DECISION
    minute = lambda k: t0 + timedelta(minutes=k)
    args = (Decimal("100"), Decimal("5000"), Decimal("200"), Decimal("5"), minute(210), minute(390))
    # Objectif avant l'échéance : vendu à +5 %.
    up = [(minute(1), Decimal("101")), (minute(2), Decimal("105"))]
    assert exit_with_deadline(up, *args, "objectif")["reason"] == "objectif"
    # À l'échéance, +1 % (positif) : vendu tout de suite.
    pos = [(minute(k), Decimal("100.5")) for k in range(1, 210)] + [(minute(210), Decimal("101"))]
    r = exit_with_deadline(pos, *args, "objectif")
    assert r["reason"] == "positif_echeance" and r["exit_at"] == minute(210)
    # À l'échéance, −2 % : A garde (None), B vend au retour à 0, C vend à la clôture.
    neg = [(minute(k), Decimal("98")) for k in range(1, 300)] + [(minute(300), Decimal("100.2"))] + \
          [(minute(k), Decimal("99")) for k in range(301, 391)]
    assert exit_with_deadline(neg, *args, "objectif") is None
    assert exit_with_deadline(neg, *args, "retour_a_zero")["exit_at"] == minute(300)
    assert exit_with_deadline(neg, *args, "cloture")["exit_at"] == minute(390)


def test_deux_actions_les_plus_volatiles_sans_donnee_future():
    from core.volatility import rank_by_volatility
    spec = {"CALME": (0.01, 0.0, 1_000_000), "VIF": (0.05, 0.0, 1_000_000), "MOYEN": (0.03, 0.0, 1_000_000)}
    daily = _daily(spec, sessions=40)
    ranked = rank_by_volatility(daily, DECISION, list(spec))
    assert [s for s, _ in ranked] == ["VIF", "MOYEN", "CALME"]
    # Une séance future folle ne change rien.
    future = daily[daily["symbol"] == "CALME"].tail(1).assign(timestamp=lambda d: d["timestamp"] + timedelta(days=2),
                                                               close=Decimal("1000"))
    assert rank_by_volatility(pd.concat([daily, future], ignore_index=True), DECISION, list(spec)) == ranked


def test_journee_deux_actions_vente_selon_la_regle():
    from dashboard.volatility_pairs import _position
    close = DECISION + timedelta(hours=6, minutes=30)
    listing = {"AAA": {"name": "A", "domain": "D"}, "BBB": {"name": "B", "domain": "D"}}
    bars = pd.concat([_minutes({"AAA": [100] + [101] * 30 + [106]}, DECISION),           # +5 % : objectif
                      _minutes({"BBB": [100] * 2 + [99] * 389}, DECISION)], ignore_index=True)  # négative : clôture
    a = _position("AAA", 0.03, bars, DECISION, close, listing)
    b = _position("BBB", 0.03, bars, DECISION, close, listing)
    assert a["status"] == "sold" and a["reason"] == "objectif"
    assert b["status"] == "sold" and b["reason"] == "cloture"
    assert datetime.fromisoformat(a["buy_at"]) == DECISION + timedelta(minutes=1)      # achat à 9 h 31
