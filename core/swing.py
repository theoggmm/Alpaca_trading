"""
Sélection « repli dans une tendance » : achat en fin de séance d'actions en tendance haussière qui viennent de
reculer, gardées quelques séances (la vente est fixée par la stratégie, au plus quelques jours).

Décision decision_minutes après l'ouverture (achat 15 min plus tard, retard des données) : seules les barres
terminées à cet instant servent (datation structurelle, premières lignes de screen_swing).

Critères, dans l'ordre :
1-4. Univers liquide (mêmes règles que la famille : historique, prix, montant échangé).
5. Marché en bonne forme (facultatif) : la veille, le repère a clôturé au-dessus de sa moyenne.
6. Volatilité basse : écart-type des rendements quotidiens dans la moitié la plus calme de l'univers liquide.
7. Tendance haussière : moyenne des short_trend_sessions dernières clôtures au-dessus de celle des
   trend_sessions dernières (la tendance de fond monte).
8. Repli : le prix à la décision est entre min_pullback et max_pullback sous la plus haute clôture des
   high_sessions dernières séances (un recul net, mais pas un effondrement).
9. En baisse aujourd'hui : prix à la décision sous la clôture de la veille (on achète la faiblesse).
9 bis (facultatifs) : baisse lors de chacune des min_down_days dernières séances ; marché qui tient (repère pas plus
   bas que market_min_day_return depuis l'ouverture, à la décision ; core/closing.market_moves).
10. PER (facultatif) : prix à la décision / bénéfice sur 12 mois glissants sous un seuil.
11. Classement du repli le plus profond au plus faible, puis diversification (corrélation), comme la famille.
"""

import json
import math
from dataclasses import MISSING, asdict, dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from core.closing import market_moves
from core.datation import usable_bars
from core.fundamentals import price_to_earnings, ttm_eps
from core.screener import (DAY, MINUTE, NEW_YORK, TRADING_DAYS_PER_YEAR, _correlation, liquid_universe,
                           market_in_uptrend)

SIGNAL = "repli_tendance"


@dataclass(frozen=True)
class SwingCriteria:
    signal: str
    version: int
    count: int
    liquidity_sessions: int
    min_price_usd: Decimal
    min_avg_dollar_volume_usd: Decimal
    volatility_sessions: int
    max_volatility_quantile: float
    month_sessions: int
    correlation_sessions: int
    max_pairwise_correlation: float
    decision_after_open_minutes: int
    short_trend_sessions: int
    trend_sessions: int
    high_sessions: int
    min_pullback: Decimal
    max_pullback: Decimal
    market_symbol: str = None
    market_ma_sessions: int = None
    max_pe: Decimal = None
    min_down_days: int = None               # 9 bis : baisse lors de chacune des N dernières séances
    market_min_day_return: Decimal = None   # 9 bis : marché qui tient à la décision (ex. -0.002)

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
        return max(self.trend_sessions, self.high_sessions, self.month_sessions, self.volatility_sessions,
                   self.correlation_sessions, self.liquidity_sessions, 2) + 1

    @property
    def decision_minutes(self):
        """Minutes entre l'ouverture et la décision."""
        return self.decision_after_open_minutes

    def to_json(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


def screen_swing(daily, minute, market_open, decision_time, criteria, earnings_for=None, market_daily=None,
                 market_minute=None):
    """
    Liste les titres retenus à decision_time (pendant la séance qui s'ouvre à market_open).
    minute : barres minute du jour avant la décision (le dernier prix de chaque titre suffit).
    Retourne (sélection, entonnoir) ; la sélection n'est jamais complétée en assouplissant les critères.
    """
    daily = usable_bars(daily, DAY, decision_time)
    minute = usable_bars(minute, MINUTE, decision_time)

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
    if criteria.market_min_day_return is not None:
        if market_minute is None:
            raise ValueError("market_minute requis par la règle « marché qui tient »")
        day, _ = market_moves(usable_bars(market_minute, MINUTE, decision_time), market_open, decision_time,
                              criteria.market_symbol)
        if day is None:
            raise ValueError(f"Barres minute de {criteria.market_symbol} manquantes avant la décision")
        stats = stats if day >= criteria.market_min_day_return else []
        funnel["marche_tient"] = len(stats)

    if stats:
        ceiling = np.quantile([s.volatility for s in stats], criteria.max_volatility_quantile)
        stats = [s for s in stats if s.volatility <= ceiling]
    funnel["volatilite_basse"] = len(stats)

    def average(closes, n):
        return sum(closes[-n:]) / n

    stats = [s for s in stats if average(s.closes, criteria.short_trend_sessions) > average(s.closes, criteria.trend_sessions)]
    funnel["tendance_haussiere"] = len(stats)

    session = minute[minute["timestamp"] >= market_open].sort_values("timestamp")
    prices = {symbol: bars["close"].iloc[-1] for symbol, bars in session.groupby("symbol", sort=True)}
    pulled = []
    for s in stats:
        price = prices.get(s.symbol)
        if price is None:
            continue
        high = max(s.closes[-criteria.high_sessions:])
        pullback = 1 - price / high
        if criteria.min_pullback <= pullback <= criteria.max_pullback:
            pulled.append((s, price, pullback, high))
    funnel["repli_net"] = len(pulled)

    kept = [k for k in pulled if k[1] < k[0].last_close]
    funnel["en_baisse_aujourd_hui"] = len(kept)
    if criteria.min_down_days:
        kept = [k for k in kept if all(r < 0 for _, r in k[0].returns[-criteria.min_down_days:])]
        funnel["baisse_des_derniers_jours"] = len(kept)

    pe = {}
    if criteria.max_pe is not None:
        decision_date = decision_time.astimezone(ZoneInfo(NEW_YORK)).date()
        earnings = earnings_for([k[0].symbol for k in kept])
        pe = {s.symbol: price_to_earnings(price, ttm_eps(earnings.get(s.symbol, []), decision_date))
              for s, price, *_ in kept}
        kept = [k for k in kept if pe[k[0].symbol] is not None and pe[k[0].symbol] < criteria.max_pe]
        funnel["per_maximum"] = len(kept)

    kept.sort(key=lambda k: (-k[2], k[0].symbol))
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
            "price_at_decision": str(price),
            "recent_high": str(high),
            "pullback": float(pullback),
            "return_day": float(price / s.last_close - 1),
            "return_month": s.return_month,
            "return_day_minus_2": s.returns[-2][1],
            "return_day_minus_1": s.returns[-1][1],
            "trend_gap": float(average(s.closes, criteria.short_trend_sessions) / average(s.closes, criteria.trend_sessions) - 1),
            "volatility_annualized": s.volatility * math.sqrt(TRADING_DAYS_PER_YEAR),
            "avg_dollar_volume": str(s.avg_dollar_volume.quantize(Decimal("1"))),
            "max_correlation_with_previous": corr,
            "pe_ttm": None if pe.get(s.symbol) is None else str(pe[s.symbol].quantize(Decimal("0.01"))),
        }
        for rank, ((s, price, pullback, high), corr) in enumerate(selection, start=1)
    ], funnel
