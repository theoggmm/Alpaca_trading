"""
Liste complétée au plus proche (liste « Nasdaq », décision T24) : toujours `count` titres.

La sélection est d'abord faite avec les critères tels quels. S'il manque des titres, la même fonction de sélection
est rejouée avec les critères assouplis pas à pas — chaque pas relâche une règle de plus, de la moins essentielle à
la plus essentielle — et les titres nouveaux complètent la liste, dans l'ordre des pas puis du classement de chaque
pas. Un titre ajouté ainsi porte « closest_fit » : la règle relâchée qui l'a laissé passer. Aucune donnée n'est
ajoutée : chaque pas lit les mêmes barres, tronquées à la même décision (datation inchangée).
"""

from dataclasses import fields, replace
from decimal import Decimal

from core.closing import ClosingCriteria
from core.opening import OpeningCriteria
from core.screener import Criteria
from core.swing import SwingCriteria

ANY = Decimal("1")


def relaxations(criteria):
    """[(règle relâchée, critères assouplis)] cumulatifs, du premier pas au dernier (le plus large)."""
    names = {f.name for f in fields(criteria)}
    steps = []
    if isinstance(criteria, Criteria):
        if criteria.confirmation_minutes is not None:
            steps.append(("confirmation", {"confirmation_tolerance": ANY}))
        if "min_gap_below_high" in names:
            steps.append(("pas_au_sommet", {"min_gap_below_high": None}))
        if "max_below_ma" in names:
            steps.append(("pas_en_chute", {"max_below_ma": None}))
        steps.append(("volatilite_basse", {"max_volatility_quantile": 1.0}))
    elif isinstance(criteria, OpeningCriteria):
        steps += [("volume_pre_ouverture", {"min_premarket_volume": 0}),
                  ("nuit_en_hausse_moderee", {"min_overnight": -ANY, "max_overnight": ANY})]
    elif isinstance(criteria, ClosingCriteria):
        steps += [("pres_du_plus_haut", {"max_below_day_high": ANY}),
                  ("journee_en_hausse", {"min_day_gain": -ANY, "max_day_gain": ANY})]
    elif isinstance(criteria, SwingCriteria):
        steps += [("repli_net", {"min_pullback": Decimal("0"), "max_pullback": ANY}),
                  ("volatilite_basse", {"max_volatility_quantile": 1.0})]
    steps.append(("diversification", {"max_pairwise_correlation": 1.0}))
    result, changes = [], {}
    for label, change in steps:
        changes = {**changes, **change}
        result.append((label, replace(criteria, **changes)))
    return result


def loosest(criteria):
    """Les critères les plus larges de l'échelle (pour lire d'avance les données de tous les pas)."""
    return relaxations(criteria)[-1][1] if criteria.fill_to_count else criteria


def fill(screen_with, criteria):
    """
    screen_with(critères) -> (sélection, entonnoir). Retourne (sélection d'au plus criteria.count titres, complétée
    au plus proche si criteria.fill_to_count, entonnoir de la sélection stricte + « completee_au_plus_proche »).
    """
    selection, funnel = screen_with(criteria)
    if not criteria.fill_to_count or len(selection) >= criteria.count:
        return selection, funnel
    items, seen = list(selection), {i["symbol"] for i in selection}
    for label, relaxed in relaxations(criteria):
        extra, _ = screen_with(relaxed)
        for item in extra:
            if len(items) >= criteria.count:
                break
            if item["symbol"] not in seen:
                items.append({**item, "closest_fit": label})
                seen.add(item["symbol"])
        if len(items) >= criteria.count:
            break
    funnel = {**funnel, "completee_au_plus_proche": len(items)}
    return [{**item, "rank": rank} for rank, item in enumerate(items, start=1)], funnel


def restrict(daily, symbols):
    """Barres quotidiennes des seuls titres de la bourse retenue (None : toutes)."""
    return daily if symbols is None else daily[daily["symbol"].isin(symbols)]
