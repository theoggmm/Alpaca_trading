"""
Bénéfice par action sur 12 mois glissants et PER, à partir des déclarations déposées à la SEC.

Une déclaration = {"start", "end", "val", "filed"} (dates ISO, val en Decimal) : bénéfice dilué par
action sur la période [start, end], déposé le jour filed. Seules les déclarations déposées avant le jour
de décision sont utilisables (règle 1 de CLAUDE.md).
"""

from datetime import date, timedelta

ANNUAL_DAYS = range(350, 381)       # un exercice
QUARTER_DAYS = range(80, 101)       # un trimestre
SAME_DAY_TOLERANCE = 7              # fins de période décalées d'un exercice à l'autre (semaines de 52/53)
MAX_STALENESS = timedelta(days=200)  # au-delà, le dernier bénéfice publié est trop ancien


def _periods(entries, decision_date):
    """{(début, fin): valeur} des déclarations déposées avant decision_date ; la plus récente l'emporte."""
    usable = sorted((e for e in entries if date.fromisoformat(e["filed"]) < decision_date), key=lambda e: e["filed"])
    return {(date.fromisoformat(e["start"]), date.fromisoformat(e["end"])): e["val"] for e in usable}


def _near(a, b):
    return abs((a - b).days) <= SAME_DAY_TOLERANCE


def ttm_eps(entries, decision_date):
    """
    Bénéfice dilué par action des 12 derniers mois connus à decision_date, ou None si non calculable.
    - Dernière période = un exercice : sa valeur.
    - Sinon : exercice précédent + cumul de l'exercice en cours - cumul de même durée un an plus tôt.
    """
    periods = _periods(entries, decision_date)
    if not periods:
        return None
    latest_end = max(end for _, end in periods)
    if decision_date - latest_end > MAX_STALENESS:
        return None

    for (start, end), value in periods.items():
        if end == latest_end and (end - start).days in ANNUAL_DAYS:
            return value

    to_date = [(start, value) for (start, end), value in periods.items()
               if end == latest_end and (end - start).days not in ANNUAL_DAYS]
    if not to_date:
        return None
    start, current = min(to_date)  # cumul le plus long : depuis le début de l'exercice
    length = (latest_end - start).days
    previous_year = [value for (s, e), value in periods.items()
                     if (e - s).days in ANNUAL_DAYS and _near(e, start - timedelta(days=1))]
    same_period_last_year = [value for (s, e), value in periods.items()
                             if _near(e, latest_end - timedelta(days=365)) and abs((e - s).days - length) <= SAME_DAY_TOLERANCE]
    if not previous_year or not same_period_last_year:
        return None
    return previous_year[0] + current - same_period_last_year[0]


def price_to_earnings(price, eps):
    """PER = prix / bénéfice par action ; None si le bénéfice est absent, nul ou négatif."""
    if eps is None or eps <= 0:
        return None
    return price / eps
