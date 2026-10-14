"""
Comptages sur l'historique : runs du screener et états de fin de séance.
"""

from collections import Counter, defaultdict

TOP_IN_DOMAIN = 20


def selection_counts(runs):
    """symbole -> nombre de runs dont la sélection le contient."""
    return dict(Counter(item["symbol"] for run in runs for item in run["selection"]))


def top_in_domain_counts(finals, top_n=TOP_IN_DOMAIN):
    """
    Pour chaque séance terminée et chaque domaine, les top_n titres à la meilleure variation
    « journée » (égalité : ordre alphabétique ; titre sans variation ou sans domaine : exclu).
    Retourne symbole -> nombre de séances où il en faisait partie.
    """
    counts = Counter()
    for final in finals:
        if "stocks" not in final:
            continue
        columns = final["stocks"]["columns"]
        by_domain = defaultdict(list)
        for row in final["stocks"]["rows"]:
            stock = dict(zip(columns, row))
            if stock["domain"] and stock["day"] is not None:
                by_domain[stock["domain"]].append(stock)
        for members in by_domain.values():
            members.sort(key=lambda s: (-s["day"], s["symbol"]))
            counts.update(s["symbol"] for s in members[:top_n])
    return dict(counts)
