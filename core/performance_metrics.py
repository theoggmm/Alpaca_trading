"""
Métriques de performance : le seul module qui les calcule (règle 2 de CLAUDE.md).

Toutes les séries sont des rendements de portefeuille indexés par date de séance (« AAAA-MM-JJ » ->
rendement du jour). Une série non datée ou à dates dupliquées est refusée.
"""

import math
import statistics

TRADING_DAYS_PER_YEAR = 252


class UndatedReturnsError(ValueError):
    pass


class DuplicateDateError(ValueError):
    pass


def _checked(returns):
    """Liste [(date, rendement)] triée ; refuse une série non datée ou à dates dupliquées."""
    if not isinstance(returns, (dict, list)):
        raise UndatedReturnsError("série attendue : {date: rendement} ou [(date, rendement)]")
    pairs = list(returns.items()) if isinstance(returns, dict) else list(returns)
    if any(not isinstance(p, tuple) or len(p) != 2 or not isinstance(p[0], str) for p in pairs):
        raise UndatedReturnsError("chaque rendement doit porter sa date de séance")
    dates = [d for d, _ in pairs]
    if len(set(dates)) != len(dates):
        raise DuplicateDateError("dates dupliquées dans la série")
    return sorted(pairs)


def cumulative(returns):
    """[(date, rendement cumulé depuis le début)] : produit des (1 + rendement) - 1."""
    total, out = 1.0, []
    for date, r in _checked(returns):
        total *= 1 + r
        out.append((date, total - 1))
    return out


def sharpe(returns):
    """Ratio de Sharpe annualisé (taux sans risque 0) ; None si moins de 2 séances ou volatilité nulle."""
    values = [r for _, r in _checked(returns)]
    if len(values) < 2 or statistics.stdev(values) == 0:
        return None
    return statistics.fmean(values) / statistics.stdev(values) * math.sqrt(TRADING_DAYS_PER_YEAR)


def summary(returns):
    """
    n, moyenne quotidienne, rendement total, rendement annualisé, part des séances positives,
    meilleure et pire séance, Sharpe. Le rendement annualisé est toujours reporté avec le total
    (règle 6 : au-delà de 100 % annualisé, le résultat est suspect).
    """
    pairs = _checked(returns)
    values = [r for _, r in pairs]
    if not values:
        return {"n": 0}
    total = cumulative(pairs)[-1][1]
    annualized = (1 + total) ** (TRADING_DAYS_PER_YEAR / len(values)) - 1
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "total": total,
        "annualized": annualized,
        "suspect": annualized > 1,
        "positive_share": sum(r > 0 for r in values) / len(values),
        "best": max(values),
        "worst": min(values),
        "sharpe": sharpe(pairs),
    }


def paired_difference(a, b):
    """
    Écarts quotidiens a - b aux dates communes, leur moyenne et le t de Student apparié
    (t = moyenne / (écart-type / √n)) ; t None si moins de 2 dates ou écarts constants.
    """
    sa, sb = dict(_checked(a)), dict(_checked(b))
    diffs = [sa[d] - sb[d] for d in sorted(set(sa) & set(sb))]
    if len(diffs) < 2 or statistics.stdev(diffs) == 0:
        return {"n": len(diffs), "mean": statistics.fmean(diffs) if diffs else None, "t": None}
    return {"n": len(diffs), "mean": statistics.fmean(diffs),
            "t": statistics.fmean(diffs) / (statistics.stdev(diffs) / math.sqrt(len(diffs)))}
