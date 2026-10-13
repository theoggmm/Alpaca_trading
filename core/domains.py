"""
Tendance moyenne par domaine d'activité, sur l'univers liquide du screener
(historique complet, prix minimum, volume échangé : critères 2 à 4 de criteres.json).
"""

import statistics
from collections import defaultdict

from core.datation import usable_bars
from core.screener import DAY, liquid_universe


def domain_trends(daily, decision_time, criteria, domains):
    """
    domains : symbole -> domaine ; un symbole absent ou sans domaine est compté comme non classé.
    Retourne (bulles, nombre de titres non classés). Une bulle = {"domain", "n", "mean_return_month"},
    moyenne simple des variations sur criteria.month_sessions séances. Bulles triées de la plus forte
    hausse moyenne à la plus forte baisse.
    """
    daily = usable_bars(daily, DAY, decision_time)

    stats, _ = liquid_universe(daily, decision_time, criteria)
    returns_by_domain = defaultdict(list)
    for s in stats:
        if domains.get(s.symbol):
            returns_by_domain[domains[s.symbol]].append(s.return_month)
    bubbles = [{"domain": domain, "n": len(returns), "mean_return_month": statistics.fmean(returns)}
               for domain, returns in returns_by_domain.items()]
    bubbles.sort(key=lambda b: (-b["mean_return_month"], b["domain"]))
    unclassified = len(stats) - sum(b["n"] for b in bubbles)
    return bubbles, unclassified
