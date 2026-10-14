"""
Tendance moyenne par domaine d'activité, sur l'univers liquide du screener
(historique complet, prix minimum, volume échangé : critères 2 à 4, identiques dans les deux versions).
"""

import statistics
from collections import defaultdict
from datetime import timedelta

from core.datation import usable_bars
from core.screener import DAY, MINUTE, first_hour_prices, liquid_universe, session_trades

WEEK_SESSIONS = 5
# Mesures en direct, dans l'ordre d'affichage.
LIVE_MEASURES = ("day", "first_hour", "two_days", "week", "month")


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


def live_domain_trends(daily, last_trades, minute, market_open, market_close, now, criteria, domains):
    """
    Bulles en direct pendant la séance [market_open, market_close], observées à now.

    daily       : barres quotidiennes ; seules les séances terminées avant l'ouverture servent.
    last_trades : symbole -> (horodatage, prix) du dernier échange connu ; seuls ceux faits pendant
                  la séance régulière et avant now servent (hors pré-ouverture et après-clôture).
    minute      : barres minute de la séance ; seules celles terminées à la fin de la première heure servent.

    Variations « N séances, séance en cours comprise » : dernier prix / clôture d'il y a N séances - 1.
    Retourne :
      - {mesure: {"available", "bubbles", "unclassified"}} ;
      - les symboles de l'univers liquide ;
      - {mesure: {symbole: variation}}, la variation de chaque titre (absente si non calculable).
    """
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    daily = usable_bars(daily, DAY, market_open)
    minute = usable_bars(minute, MINUTE, min(now, first_hour_end))
    last_trades = {s: price for s, (_, price) in session_trades(last_trades, market_open, market_close, now).items()}

    stats, _ = liquid_universe(daily, market_open, criteria)
    liquid = [s.symbol for s in stats]
    sessions = {"day": 1, "two_days": criteria.up_days, "week": WEEK_SESSIONS, "month": criteria.month_sessions}
    values = {key: {s.symbol: float(last_trades[s.symbol] / s.closes[-n] - 1) for s in stats if s.symbol in last_trades}
              for key, n in sessions.items()}

    complete = now >= first_hour_end and not minute.empty
    prices = first_hour_prices(minute, market_open) if complete else {}
    values["first_hour"] = {symbol: float(last / first - 1) for symbol, (first, last) in prices.items()
                            if symbol in set(liquid)}

    measures = {}
    for key, by_symbol in values.items():
        bubbles, unclassified = aggregate_by_domain(by_symbol, domains)
        measures[key] = {"available": complete if key == "first_hour" else bool(by_symbol),
                         "bubbles": bubbles, "unclassified": unclassified}
    return measures, liquid, values
