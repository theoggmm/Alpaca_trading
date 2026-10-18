"""
Sélection du jour : chaque séance, 0 à 3 stratégies parmi les candidates, au plus 7 actions en tout (décision T18).

1. Dernières 24 h : on garde les stratégies dont le dernier résultat connu est positif.
2. Les 2-3 derniers jours : parmi elles, celles dont la somme des 3 derniers résultats connus dépasse min_recent,
   avec au moins 2 séances positives sur 3 ; classées de la meilleure à la moins bonne.
3. Au plus max_picks stratégies ; aucune si le marché est en mauvaise forme (garde-fous du jour, plus bas).
4. Actions : dans l'ordre de la liste de chaque stratégie retenue, en écartant celles qui publient probablement leurs
   résultats pendant la garde et celles dont le secteur baisse ce jour-là ; 7 pour une stratégie, 4 + 3 pour deux,
   3 + 2 + 2 pour trois. Le montant est réparti à parts égales sur les actions retenues.

Garde-fous du jour (connus à la décision) : marché en bonne forme (repère au-dessus de sa moyenne de 50 séances),
au moins min_breadth des actions liquides en hausse depuis l'ouverture, indice de peur (VIXY) pas en hausse de plus
de max_fear_rise depuis l'ouverture.

« Résultat connu » : celui d'une séance d'achat dont la vente est faite avant la séance du jour (aucune donnée du
futur ; c'est l'appelant qui ne fournit que ces résultats).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

ALLOCATION = {1: [7], 2: [4, 3], 3: [3, 2, 2]}
QUARTER_DAYS = 91


@dataclass(frozen=True)
class SelectionRules:
    max_picks: int = 3
    max_stocks: int = 7
    recent_sessions: int = 3
    min_recent: float = 0.003          # somme des 3 derniers résultats (après frais) : +0,3 % au moins
    min_recent_positive: int = 2       # au moins 2 séances positives sur les 3
    min_breadth: float = 0.5           # au moins la moitié des actions liquides en hausse à la décision
    max_fear_rise: float = 0.03        # VIXY pas en hausse de plus de 3 % depuis l'ouverture
    earnings_tolerance_days: int = 5   # fenêtre autour d'une publication attendue


def pick_strategies(history, rules=SelectionRules()):
    """
    history : candidate -> résultats connus [(date, rendement)], du plus ancien au plus récent (rendement None :
    pas de liste ce jour-là). Retourne [(candidate, somme récente)] retenues, de la meilleure à la moins bonne.
    """
    kept = []
    for candidate, results in history.items():
        known = [r for _, r in results if r is not None]
        if not known or known[-1] <= 0:
            continue                                     # 1. les dernières 24 h
        recent = known[-rules.recent_sessions:]
        if len(recent) < rules.recent_sessions:
            continue
        positives = sum(1 for r in recent if r > 0)
        total = sum(recent)
        if total >= rules.min_recent and positives >= rules.min_recent_positive:
            kept.append((candidate, total))              # 2. les 2-3 derniers jours
    kept.sort(key=lambda k: -k[1])
    return kept[:rules.max_picks]


def market_ok(healthy, breadth, fear_rise, rules=SelectionRules()):
    """Garde-fous du jour : (vrai/faux, raison). Une mesure absente (None) ne bloque pas."""
    if healthy is False:
        return False, "marche_en_mauvaise_forme"
    if breadth is not None and breadth < rules.min_breadth:
        return False, "trop_peu_d_actions_en_hausse"
    if fear_rise is not None and fear_rise > rules.max_fear_rise:
        return False, "peur_en_hausse"
    return True, None


def breadth(open_prices, prices):
    """Part des actions (présentes dans les deux) dont le dernier prix dépasse le premier prix de la séance."""
    common = [s for s in open_prices if s in prices]
    if not common:
        return None
    return sum(1 for s in common if prices[s] > open_prices[s]) / len(common)


def sector_trends(open_prices, prices, domains):
    """Domaine -> variation moyenne depuis l'ouverture des actions de ce domaine (connues dans les deux)."""
    sums = {}
    for s, first in open_prices.items():
        if s in prices and domains.get(s):
            total, n = sums.get(domains[s], (0.0, 0))
            sums[domains[s]] = (total + float(prices[s] / first - 1), n + 1)
    return {d: total / n for d, (total, n) in sums.items()}


def likely_reporting(releases, buy_date, sale_date, tolerance_days=5):
    """
    Vrai si la société publie probablement ses résultats entre l'achat et la vente : une publication passée (8-K
    rubrique 2.02, déposée avant le jour d'achat) tombe, à un multiple de trimestre près (91, 182, 273, 364 jours),
    à moins de tolerance_days de la garde. Estimation de prudence : la date future n'est jamais connue officiellement.
    """
    for release in releases:
        day = date.fromisoformat(release["date"])
        if day >= buy_date:
            continue                                     # seules les publications déjà connues
        for quarters in (1, 2, 3, 4):
            expected = day + timedelta(days=QUARTER_DAYS * quarters)
            if buy_date - timedelta(days=tolerance_days) <= expected <= sale_date + timedelta(days=tolerance_days):
                return True
    return False


def choose_stocks(picks, lists, excluded, rules=SelectionRules()):
    """
    picks : [(candidate, score)] ; lists : candidate -> symboles dans l'ordre de la liste ; excluded : candidate ->
    symboles écartés (publication probable, secteur en baisse). Retourne candidate -> symboles retenus (au plus 7
    en tout, sans doublon : une action déjà retenue n'est pas reprise par une autre stratégie).
    """
    counts = ALLOCATION.get(len(picks), [])
    chosen, taken = {}, set()
    for (candidate, _), count in zip(picks, counts):
        symbols = [s for s in lists.get(candidate, []) if s not in excluded.get(candidate, set()) and s not in taken]
        chosen[candidate] = symbols[:count]
        taken |= set(chosen[candidate])
    return chosen


def day_return(chosen, stock_returns):
    """Rendement du jour, parts égales sur les actions retenues ; 0 si aucune (rien d'investi)."""
    values = [stock_returns[c][s] for c, symbols in chosen.items() for s in symbols
              if stock_returns.get(c, {}).get(s) is not None]
    return sum(values) / len(values) if values else 0.0
