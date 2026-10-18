"""
Sélection « fin de journée » : choisie juste avant un achat en fin de séance, gardé pendant la nuit.

Décision decision_minutes après l'ouverture (achat 15 min plus tard, retard des données) : seules les barres
terminées à cet instant servent (datation structurelle, première ligne de screen_closing).

Critères, dans l'ordre :
1-4. Univers liquide (mêmes règles que la famille : historique, prix, montant échangé).
5. Marché en bonne forme (facultatif) : la veille, le repère a clôturé au-dessus de sa moyenne.
5 bis. Marché qui tient (facultatif) : le repère (SPY) n'a pas perdu plus que market_min_day_return depuis
   l'ouverture, à la décision.
5 ter. Marché qui remonte (facultatif) : le repère a gagné au moins market_min_last_hour_return sur la dernière
   heure avant la décision.
5 quater (facultatifs, quotidiens) : volatilité dans le quantile max_volatility_quantile le plus calme ; hausse
   lors de chacune des min_up_days dernières séances ; hausse sur week_sessions séances entre min_week_gain et
   max_week_gain. rank_by « semaine » classe par hausse sur la semaine au lieu de la dernière heure.
6. Journée en hausse : dernier prix / premier prix de la séance - 1 entre deux bornes.
7. Dernière heure en hausse : dernier prix > prix last_hour_minutes plus tôt.
8. Près du plus haut du jour : au plus max_below_day_high sous la plus haute clôture minute de la séance.
9. PER (facultatif) : prix à la décision / bénéfice sur 12 mois glissants sous un seuil.
10. Classement par hausse de la dernière heure, puis diversification (corrélation), comme la famille.
"""

import json
import math
from dataclasses import MISSING, asdict, dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from core.datation import usable_bars
from core.fundamentals import price_to_earnings, ttm_eps
from core.screener import (DAY, MINUTE, NEW_YORK, TRADING_DAYS_PER_YEAR, _correlation, liquid_universe,
                           market_in_uptrend)

SIGNAL = "fin_de_journee"


@dataclass(frozen=True)
class ClosingCriteria:
    signal: str
    version: int
    count: int
    liquidity_sessions: int
    min_price_usd: Decimal
    min_avg_dollar_volume_usd: Decimal
    volatility_sessions: int
    month_sessions: int
    correlation_sessions: int
    max_pairwise_correlation: float
    decision_after_open_minutes: int
    last_hour_minutes: int
    min_day_gain: Decimal
    max_day_gain: Decimal
    max_below_day_high: Decimal
    market_symbol: str = None
    market_ma_sessions: int = None
    max_pe: Decimal = None
    market_min_day_return: Decimal = None        # 5 bis : repère depuis l'ouverture, à la décision (ex. -0.002)
    market_min_last_hour_return: Decimal = None  # 5 ter : repère sur la dernière heure avant la décision (ex. 0)
    max_volatility_quantile: float = None        # 5 quater : les plus calmes de l'univers liquide (ex. 0.5)
    min_up_days: int = None                      # 5 quater : hausse lors de chacune des N dernières séances
    week_sessions: int = 5
    min_week_gain: Decimal = None                # 5 quater : hausse sur week_sessions séances, bornes
    max_week_gain: Decimal = None
    rank_by: str = "derniere_heure"              # ou « semaine »

    @classmethod
    def from_json(cls, raw, source="critères"):
        raw = {k: v for k, v in raw.items() if v is not None}
        required = {f.name for f in fields(cls) if f.default is MISSING}
        allowed = {f.name for f in fields(cls)}
        if not required <= set(raw) <= allowed or raw["signal"] != SIGNAL:
            raise ValueError(f"Clés attendues dans {source} : {sorted(required)} (+ facultatives "
                             f"{sorted(allowed - required)}), signal « {SIGNAL} », reçues : {sorted(raw)}")
        return cls(**{name: next(f.type for f in fields(cls) if f.name == name)(value) for name, value in raw.items()})

    @classmethod
    def from_file(cls, path):
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")), str(path))

    @property
    def required_sessions(self):
        return max(self.month_sessions, self.volatility_sessions, self.correlation_sessions,
                   self.liquidity_sessions, 2) + 1

    @property
    def decision_minutes(self):
        """Minutes entre l'ouverture et la décision."""
        return self.decision_after_open_minutes

    def to_json(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


def market_moves(market_minute, market_open, decision_time, symbol, last_hour_minutes=60):
    """
    Variation du repère connue à decision_time : (depuis l'ouverture, sur la dernière heure), chacune None si
    les barres manquent. Dernier prix = clôture de la dernière barre minute terminée.
    """
    market_minute = usable_bars(market_minute, MINUTE, decision_time)

    bars = market_minute[(market_minute["symbol"] == symbol) & (market_minute["timestamp"] >= market_open)]
    bars = bars.sort_values("timestamp")
    if bars.empty:
        return None, None
    price = bars["close"].iloc[-1]
    before = bars[bars["timestamp"] < decision_time - timedelta(minutes=last_hour_minutes)]
    return price / bars["open"].iloc[0] - 1, None if before.empty else price / before["close"].iloc[-1] - 1


def market_conditions(criteria, market_minute, market_open, decision_time):
    """
    Conditions de marché du jour (5 bis, 5 ter) : {"marche_tient": bool, "marche_remonte": bool} pour celles que
    les critères fixent ; ValueError si les barres du repère manquent.
    """
    wanted = {"marche_tient": criteria.market_min_day_return, "marche_remonte": criteria.market_min_last_hour_return}
    wanted = {k: v for k, v in wanted.items() if v is not None}
    if not wanted:
        return {}
    if market_minute is None:
        raise ValueError("market_minute requis par les règles « marché qui tient / qui remonte »")
    day, hour = market_moves(market_minute, market_open, decision_time, criteria.market_symbol)
    moves = {"marche_tient": day, "marche_remonte": hour}
    if any(moves[k] is None for k in wanted):
        raise ValueError(f"Barres minute de {criteria.market_symbol} manquantes avant la décision")
    return {k: moves[k] >= v for k, v in wanted.items()}


def screen_closing(daily, minute, market_open, decision_time, criteria, earnings_for=None, market_daily=None,
                   market_minute=None):
    """
    Liste les titres retenus à decision_time (pendant la séance qui s'ouvre à market_open).
    minute : barres minute de la séance du jour. market_minute : barres minute du repère (SPY) depuis l'ouverture,
    requises par les règles 5 bis / 5 ter. Retourne (sélection, entonnoir) ; la sélection n'est jamais
    complétée en assouplissant les critères.
    """
    daily = usable_bars(daily, DAY, decision_time)
    minute = usable_bars(minute, MINUTE, decision_time)
    if market_minute is not None:
        market_minute = usable_bars(market_minute, MINUTE, decision_time)

    if decision_time != market_open + timedelta(minutes=criteria.decision_minutes):
        raise ValueError("decision_time doit valoir market_open + decision_minutes")

    stats, funnel = liquid_universe(daily, decision_time, criteria)
    if criteria.market_ma_sessions is not None:
        if market_daily is None:
            raise ValueError("market_daily requis par la règle « marché en bonne forme »")
        healthy, _, _ = market_in_uptrend(market_daily, decision_time, criteria.market_symbol,
                                          criteria.market_ma_sessions)
        stats = stats if healthy else []
        funnel["marche_en_bonne_forme"] = len(stats)
    for step, ok in market_conditions(criteria, market_minute, market_open, decision_time).items():
        stats = stats if ok else []
        funnel[step] = len(stats)
    if criteria.max_volatility_quantile is not None:
        if stats:
            ceiling = np.quantile([s.volatility for s in stats], criteria.max_volatility_quantile)
            stats = [s for s in stats if s.volatility <= ceiling]
        funnel["volatilite_basse"] = len(stats)
    if criteria.min_up_days:
        stats = [s for s in stats if all(r > 0 for _, r in s.returns[-criteria.min_up_days:])]
        funnel["hausse_des_derniers_jours"] = len(stats)

    def week(s):
        return s.closes[-1] / s.closes[-1 - criteria.week_sessions] - 1

    if criteria.min_week_gain is not None or criteria.max_week_gain is not None:
        low = criteria.min_week_gain if criteria.min_week_gain is not None else Decimal("-1")
        high = criteria.max_week_gain if criteria.max_week_gain is not None else Decimal("1e9")
        stats = [s for s in stats if low <= week(s) <= high]
        funnel["hausse_de_la_semaine"] = len(stats)

    session = minute[minute["timestamp"] >= market_open].sort_values("timestamp")
    by_symbol = {s: b for s, b in session.groupby("symbol", sort=True)}
    hour_start = decision_time - timedelta(minutes=criteria.last_hour_minutes)

    rising, last_hour, near_high = [], [], []
    for s in stats:
        bars = by_symbol.get(s.symbol)
        if bars is None:
            continue
        first, price = bars["open"].iloc[0], bars["close"].iloc[-1]
        day = price / first - 1
        if criteria.min_day_gain <= day <= criteria.max_day_gain:
            rising.append((s, bars, price, day))
    funnel["journee_en_hausse"] = len(rising)

    for s, bars, price, day in rising:
        before = bars[bars["timestamp"] < hour_start]
        if before.empty:
            continue
        r_hour = price / before["close"].iloc[-1] - 1
        if r_hour > 0:
            last_hour.append((s, bars, price, day, r_hour))
    funnel["derniere_heure_en_hausse"] = len(last_hour)

    for s, bars, price, day, r_hour in last_hour:
        below_high = 1 - price / bars["close"].max()
        if below_high <= criteria.max_below_day_high:
            near_high.append((s, price, float(day), float(r_hour), float(below_high)))
    funnel["pres_du_plus_haut"] = len(near_high)

    kept = near_high
    pe = {}
    if criteria.max_pe is not None:
        decision_date = decision_time.astimezone(ZoneInfo(NEW_YORK)).date()
        earnings = earnings_for([k[0].symbol for k in kept])
        pe = {s.symbol: price_to_earnings(price, ttm_eps(earnings.get(s.symbol, []), decision_date))
              for s, price, *_ in kept}
        kept = [k for k in kept if pe[k[0].symbol] is not None and pe[k[0].symbol] < criteria.max_pe]
        funnel["per_maximum"] = len(kept)

    if criteria.rank_by == "semaine":
        kept.sort(key=lambda k: (-week(k[0]), k[0].symbol))
    else:
        kept.sort(key=lambda k: (-k[3], k[0].symbol))
    window = criteria.correlation_sessions
    selection = []
    for item in kept:
        if len(selection) == criteria.count:
            break
        s = item[0]
        correlations = [_correlation(s.returns[-window:], other[0].returns[-window:]) for other, _ in selection]
        if any(c is None or c > criteria.max_pairwise_correlation for c in correlations):
            continue
        selection.append((item, max(correlations, default=None)))
    funnel["selection_diversifiee"] = len(selection)

    return [
        {
            "rank": rank,
            "symbol": s.symbol,
            "prev_close": str(s.last_close),
            "open_today": str(by_symbol[s.symbol]["open"].iloc[0]),
            "price_at_decision": str(price),
            "return_month": s.return_month,
            "return_day_minus_2": s.returns[-2][1],
            "return_day_minus_1": s.returns[-1][1],
            "return_day": day,
            "return_last_hour": r_hour,
            "below_day_high": below_high,
            "return_week": float(week(s)),
            "volatility_annualized": s.volatility * math.sqrt(TRADING_DAYS_PER_YEAR),
            "avg_dollar_volume": str(s.avg_dollar_volume.quantize(Decimal("1"))),
            "max_correlation_with_previous": corr,
            "pe_ttm": None if pe.get(s.symbol) is None else str(pe[s.symbol].quantize(Decimal("0.01"))),
        }
        for rank, ((s, price, day, r_hour, below_high), corr) in enumerate(selection, start=1)
    ], funnel
