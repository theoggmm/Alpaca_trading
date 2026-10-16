"""
Sélection « ouverture » : choisie avant l'ouverture, à partir de la fin de la séance précédente et de la nuit.

Décision à l'ouverture moins le retard des données (9 h 15 à New York) : seules les barres terminées à cet
instant servent (datation structurelle, première ligne de screen_opening). Achat au premier échange de la
séance (9 h 30), vente N minutes après l'ouverture (fixée par la stratégie).

Critères, dans l'ordre :
1-4. Univers liquide (mêmes règles que la famille : historique, prix, montant échangé).
5. Marché en bonne forme (facultatif) : la veille, le repère a clôturé au-dessus de sa moyenne.
6. Fin de séance en hausse : dernier échange de la séance précédente > premier prix de sa dernière heure.
7. Nuit en hausse modérée : dernier échange avant la décision / clôture de la veille - 1 entre deux bornes,
   avec assez d'actions échangées en pré-ouverture pour que ce prix ait un sens.
8. PER (facultatif) : prix avant l'ouverture / bénéfice sur 12 mois glissants sous un seuil.
9. Classement par hausse de la dernière heure, puis diversification (corrélation), comme la famille.
"""

import json
import math
from dataclasses import MISSING, asdict, dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from core.datation import usable_bars
from core.fundamentals import price_to_earnings, ttm_eps
from core.screener import (DAY, MINUTE, NEW_YORK, TRADING_DAYS_PER_YEAR, _correlation, liquid_universe,
                           market_in_uptrend)

SIGNAL = "ouverture"
# Pré-ouverture : à partir de 4 h 00 à New York, soit 5 h 30 avant l'ouverture habituelle.
PREMARKET = timedelta(hours=5, minutes=30)


@dataclass(frozen=True)
class OpeningCriteria:
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
    last_hour_minutes: int
    min_overnight: Decimal
    max_overnight: Decimal
    min_premarket_volume: int
    data_delay_minutes: int
    market_symbol: str = None
    market_ma_sessions: int = None
    max_pe: Decimal = None

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
        """Minutes entre l'ouverture et la décision : négatif, la décision précède l'ouverture du retard des données."""
        return -self.data_delay_minutes

    def to_json(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


def screen_opening(daily, minute, market_open, previous_close, decision_time, criteria, earnings_for=None,
                   market_daily=None):
    """
    Liste les titres retenus à decision_time (avant l'ouverture de la séance market_open).
    minute : barres minute de la fin de la séance précédente (clôture previous_close) et de la nuit.
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

    minute = minute.sort_values("timestamp")
    last_hour = minute[(minute["timestamp"] >= previous_close - timedelta(minutes=criteria.last_hour_minutes))
                       & (minute["timestamp"] < previous_close)]
    hour = {s: (b["open"].iloc[0], b["close"].iloc[-1]) for s, b in last_hour.groupby("symbol", sort=True)}
    rising = [(s, float(hour[s.symbol][1] / hour[s.symbol][0] - 1)) for s in stats
              if s.symbol in hour and hour[s.symbol][1] > hour[s.symbol][0]]
    funnel["fin_de_seance_en_hausse"] = len(rising)

    night = minute[minute["timestamp"] >= previous_close]
    last_night = {s: b["close"].iloc[-1] for s, b in night.groupby("symbol", sort=True)}
    premarket = night[night["timestamp"] >= market_open - PREMARKET]
    volume = premarket.groupby("symbol")["volume"].sum().to_dict()
    kept = []
    for s, r_hour in rising:
        if s.symbol not in last_night or volume.get(s.symbol, 0) < criteria.min_premarket_volume:
            continue
        overnight = last_night[s.symbol] / s.last_close - 1
        if criteria.min_overnight <= overnight <= criteria.max_overnight:
            kept.append((s, r_hour, last_night[s.symbol], float(overnight)))
    funnel["nuit_en_hausse_moderee"] = len(kept)

    pe = {}
    if criteria.max_pe is not None:
        decision_date = decision_time.astimezone(ZoneInfo(NEW_YORK)).date()
        earnings = earnings_for([s.symbol for s, *_ in kept])
        pe = {s.symbol: price_to_earnings(price, ttm_eps(earnings.get(s.symbol, []), decision_date))
              for s, _, price, _ in kept}
        kept = [k for k in kept if pe[k[0].symbol] is not None and pe[k[0].symbol] < criteria.max_pe]
        funnel["per_maximum"] = len(kept)

    kept.sort(key=lambda k: (-k[1], k[0].symbol))
    window = criteria.correlation_sessions
    selection = []
    for s, r_hour, price, overnight in kept:
        if len(selection) == criteria.count:
            break
        correlations = [_correlation(s.returns[-window:], other[0].returns[-window:]) for other in selection]
        if any(c is None or c > criteria.max_pairwise_correlation for c in correlations):
            continue
        selection.append((s, r_hour, price, overnight, max(correlations, default=None)))
    funnel["selection_diversifiee"] = len(selection)

    return [
        {
            "rank": rank,
            "symbol": s.symbol,
            "prev_close": str(s.last_close),
            # Premier prix connu de la séance au moment de la décision : le dernier échange de la nuit.
            "open_today": str(price),
            "price_at_decision": str(price),
            "return_month": s.return_month,
            "return_day_minus_2": s.returns[-2][1],
            "return_day_minus_1": s.returns[-1][1],
            "return_last_hour": r_hour,
            "return_overnight": overnight,
            "premarket_volume": int(volume.get(s.symbol, 0)),
            "volatility_annualized": s.volatility * math.sqrt(TRADING_DAYS_PER_YEAR),
            "avg_dollar_volume": str(s.avg_dollar_volume.quantize(Decimal("1"))),
            "max_correlation_with_previous": corr,
            "pe_ttm": None if pe.get(s.symbol) is None else str(pe[s.symbol].quantize(Decimal("0.01"))),
        }
        for rank, (s, r_hour, price, overnight, corr) in enumerate(selection, start=1)
    ], funnel
