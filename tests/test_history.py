"""Comptages sur l'historique : sélection du screener et top par domaine."""

from core.history import selection_counts, top_in_domain_counts

COLUMNS = ["symbol", "name", "domain", "day", "first_hour", "two_days", "week", "month"]


def _final(rows):
    return {"stocks": {"columns": COLUMNS, "rows": [[s, "", d, day, None, None, None, None] for s, d, day in rows]}}


def test_fois_dans_la_selection():
    runs = [{"selection": [{"symbol": "A"}, {"symbol": "B"}]}, {"selection": [{"symbol": "A"}]}]
    assert selection_counts(runs) == {"A": 2, "B": 1}


def test_top_n_par_domaine_et_par_seance():
    day1 = _final([("A", "Tech", 0.03), ("B", "Tech", 0.01), ("C", "Tech", -0.02),
                   ("D", "Fin", -0.05), ("E", None, 0.09), ("F", "Fin", None)])
    day2 = _final([("A", "Tech", -0.01), ("C", "Tech", 0.04), ("B", "Tech", 0.04)])
    counts = top_in_domain_counts([day1, day2, {"session_date": "sans titres"}], top_n=2)
    # Jour 1 : Tech -> A, B ; Fin -> D (F sans variation, E sans domaine). Jour 2 : B et C à égalité, devant A.
    assert counts == {"A": 1, "B": 2, "C": 1, "D": 1}
