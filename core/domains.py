"""
Tendance moyenne par domaine d'activité, sur l'univers liquide du screener
(historique complet, prix minimum, volume échangé : critères 2 à 4 de criteres.json).
"""

import statistics
from collections import defaultdict
from datetime import timedelta

from core.datation import usable_bars
from core.screener import DAY, MINUTE, first_hour_prices, liquid_universe

WEEK_SESSIONS = 5


def aggregate_by_domain(values, domains):
    """
    values : symbole -> variation ; domains : symbole -> domaine (absent ou vide = non classé).
    Retourne (bulles, nombre de titres non classés). Une bulle = {"domain", "n", "mean_return"},
    moyenne simple ; bulles triées de la plus forte hausse moyenne à la plus forte baisse.
    """
    by_domain = defaultdict(list)
    for symbol, value in values.items():
        if domains.get(symbol):
            by_domain[domains[symbol]].append(value)
    bubbles = [{"domain": domain, "n": len(v), "mean_return": statistics.fmean(v)} for domain, v in by_domain.items()]
    bubbles.sort(key=lambda b: (-b["mean_return"], b["domain"]))
    return bubbles, len(values) - sum(b["n"] for b in bubbles)


def domain_trends(daily, decision_time, criteria, domains):
    """
    Variation sur criteria.month_sessions séances terminées avant decision_time, moyennée par domaine.
    Retourne (bulles, nombre de titres non classés).
    """
    daily = usable_bars(daily, DAY, decision_time)

    stats, _ = liquid_universe(daily, decision_time, criteria)
    return aggregate_by_domain({s.symbol: s.return_month for s in stats}, domains)


def live_domain_trends(daily, last_trades, minute, market_open, now, criteria, domains):
    """
    Bulles en direct pendant la séance ouverte à market_open, observées à now.

    daily       : barres quotidiennes ; seules les séances terminées avant l'ouverture servent.
    last_trades : symbole -> (horodatage, prix) du dernier échange connu ; seuls ceux de la séance
                  en cours et antérieurs à now servent.
    minute      : barres minute de la séance ; seules celles terminées à la fin de la première heure servent.

    Variations « N séances, séance en cours comprise » : dernier prix / clôture d'il y a N séances - 1.
    Retourne {mesure: {"available", "bubbles", "unclassified"}} et le nombre de titres de l'univers.
    """
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    daily = usable_bars(daily, DAY, market_open)
    minute = usable_bars(minute, MINUTE, min(now, first_hour_end))
    last_trades = {s: price for s, (ts, price) in last_trades.items() if market_open <= ts <= now}

    stats, _ = liquid_universe(daily, market_open, criteria)
    sessions = {"day": 1, "two_days": criteria.up_days, "week": WEEK_SESSIONS, "month": criteria.month_sessions}
    measures = {}
    for key, n in sessions.items():
        values = {s.symbol: float(last_trades[s.symbol] / s.closes[-n] - 1) for s in stats if s.symbol in last_trades}
        bubbles, unclassified = aggregate_by_domain(values, domains)
        measures[key] = {"available": bool(values), "bubbles": bubbles, "unclassified": unclassified}

    complete = now >= first_hour_end and not minute.empty
    prices = first_hour_prices(minute, market_open) if complete else {}
    liquid = {s.symbol for s in stats}
    values = {symbol: float(last / first - 1) for symbol, (first, last) in prices.items() if symbol in liquid}
    bubbles, unclassified = aggregate_by_domain(values, domains)
    measures["first_hour"] = {"available": complete, "bubbles": bubbles, "unclassified": unclassified}
    return measures, len(stats)
