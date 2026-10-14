"""
Screener « reprise après baisse » : logique pure, sans réseau.

Chaque fonction publique reçoit l'instant de décision et tronque ses données
dès sa première ligne (règle 1 de CLAUDE.md) : une barre non terminée à cet
instant est inatteignable.

Données attendues (une ligne par barre) : colonnes symbol, timestamp (début de
barre, UTC), open, close (Decimal), volume (int).
"""

import json
import math
import statistics
from dataclasses import asdict, dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

from core.datation import usable_bars

DAY = timedelta(days=1)
MINUTE = timedelta(minutes=1)
NEW_YORK = "America/New_York"
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class Criteria:
    version: int
    count: int
    month_sessions: int
    up_days: int
    first_hour_minutes: int
    liquidity_sessions: int
    min_price_usd: Decimal
    min_avg_dollar_volume_usd: Decimal
    volatility_sessions: int
    max_volatility_quantile: float
    correlation_sessions: int
    max_pairwise_correlation: float

    @classmethod
    def from_file(cls, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = {f.name for f in fields(cls)}
        if set(raw) != expected:
            raise ValueError(f"Clés attendues dans {path} : {sorted(expected)}, reçues : {sorted(raw)}")
        return cls(**{f.name: f.type(raw[f.name]) for f in fields(cls)})

    @property
    def required_sessions(self):
        """Nombre de clôtures nécessaires : la plus longue fenêtre de rendements + 1."""
        return max(self.month_sessions, self.volatility_sessions, self.correlation_sessions,
                   self.liquidity_sessions, self.up_days) + 1

    def to_json(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


@dataclass(frozen=True)
class DailyStats:
    symbol: str
    last_close: Decimal
    avg_dollar_volume: Decimal
    volatility: float          # écart-type des rendements quotidiens
    return_month: float
    returns: tuple             # ((timestamp, rendement quotidien), ...) du plus ancien au plus récent
    closes: tuple              # clôtures (Decimal) du plus ancien au plus récent


def _daily_stats(symbol, bars, criteria):
    closes = list(bars["close"])
    volumes = list(bars["volume"])
    returns = tuple((ts, float(c / p - 1))
                    for ts, p, c in zip(bars["timestamp"].iloc[1:], closes[:-1], closes[1:]))
    liquidity = criteria.liquidity_sessions
    dollar_volume = sum(c * v for c, v in zip(closes[-liquidity:], volumes[-liquidity:])) / liquidity
    return DailyStats(
        symbol=symbol,
        last_close=closes[-1],
        avg_dollar_volume=dollar_volume,
        volatility=statistics.stdev(r for _, r in returns[-criteria.volatility_sessions:]),
        return_month=float(closes[-1] / closes[-1 - criteria.month_sessions] - 1),
        returns=returns,
        closes=tuple(closes),
    )


def liquid_universe(daily, decision_time, criteria):
    """
    Titres à l'historique complet, au prix et au volume échangé suffisants (critères 2 à 4).
    Retourne (statistiques par titre, entonnoir).
    """
    daily = usable_bars(daily, DAY, decision_time)

    funnel = {"avec_barres_quotidiennes": int(daily["symbol"].nunique())}
    if daily.empty:
        return [], funnel
    latest_session = daily["timestamp"].max()
    needed = criteria.required_sessions

    stats = [
        _daily_stats(symbol, bars.tail(needed), criteria)
        for symbol, bars in daily.sort_values("timestamp").groupby("symbol", sort=True)
        if len(bars) >= needed and bars["timestamp"].iloc[-1] == latest_session
    ]
    funnel["historique_complet"] = len(stats)

    stats = [s for s in stats if s.last_close >= criteria.min_price_usd]
    funnel["prix_minimum"] = len(stats)

    stats = [s for s in stats if s.avg_dollar_volume >= criteria.min_avg_dollar_volume_usd]
    funnel["volume_echange_minimum"] = len(stats)
    return stats, funnel


def daily_candidates(daily, decision_time, criteria):
    """
    Applique les critères quotidiens, dans l'ordre. Retourne (candidats, entonnoir).
    Candidats triés du plus fort repli sur un mois au plus faible.
    """
    daily = usable_bars(daily, DAY, decision_time)

    stats, funnel = liquid_universe(daily, decision_time, criteria)
    if stats:
        ceiling = np.quantile([s.volatility for s in stats], criteria.max_volatility_quantile)
        stats = [s for s in stats if s.volatility <= ceiling]
    funnel["volatilite_basse"] = len(stats)

    stats = [s for s in stats if s.return_month < 0]
    funnel["en_baisse_sur_un_mois"] = len(stats)

    stats = [s for s in stats if all(r > 0 for _, r in s.returns[-criteria.up_days:])]
    funnel["hausse_des_derniers_jours"] = len(stats)

    stats.sort(key=lambda s: (s.return_month, s.symbol))
    return stats, funnel


def first_hour_prices(minute, market_open):
    """symbole -> (prix d'ouverture de la séance, dernier prix des barres fournies)."""
    session = minute[minute["timestamp"] >= market_open].sort_values("timestamp")
    return {symbol: (bars["open"].iloc[0], bars["close"].iloc[-1])
            for symbol, bars in session.groupby("symbol", sort=True)}


def recent_closes(daily, market_open, symbols, sessions):
    """
    symbole -> [(date de la séance à New York, clôture en texte)] des `sessions` dernières séances
    terminées avant l'ouverture, de la plus ancienne à la plus récente.
    """
    daily = usable_bars(daily, DAY, market_open)

    wanted = daily[daily["symbol"].isin(list(symbols))].sort_values("timestamp")
    return {symbol: [(ts.tz_convert(NEW_YORK).date().isoformat(), str(close))
                     for ts, close in zip(bars["timestamp"].tail(sessions), bars["close"].tail(sessions))]
            for symbol, bars in wanted.groupby("symbol", sort=True)}


def last_session_prices(minute, market_close):
    """
    Dernier échange de la séance régulière, reconstitué depuis les barres minute :
    symbole -> (fin de la dernière barre terminée à la clôture, dernier prix de cette barre).
    """
    minute = usable_bars(minute, MINUTE, market_close)

    last = minute.sort_values("timestamp").groupby("symbol", sort=True).tail(1)
    return {row.symbol: ((row.timestamp + MINUTE).to_pydatetime(), row.close) for row in last.itertuples()}


def session_trades(last_trades, market_open, market_close, now):
    """Échanges faits pendant la séance régulière et connus à now : symbole -> (horodatage, prix)."""
    return {s: (ts, p) for s, (ts, p) in last_trades.items() if market_open <= ts <= min(now, market_close)}


def changes_since_open(opens, last_trades, market_open, market_close, now):
    """
    Variation depuis l'ouverture de la séance : dernier prix / premier prix de la séance - 1.
    opens       : symbole -> premier prix de la séance (Decimal).
    last_trades : symbole -> (horodatage, prix) ; seuls les échanges de la séance régulière
                  antérieurs à now servent.
    Retourne symbole -> {"change", "price", "at"}.
    """
    last_trades = session_trades(last_trades, market_open, market_close, now)

    return {symbol: {"change": float(last_trades[symbol][1] / day_open - 1),
                     "price": str(last_trades[symbol][1]), "at": last_trades[symbol][0].isoformat()}
            for symbol, day_open in opens.items() if symbol in last_trades}


def session_open_prices(minute, market_open, now):
    """symbole -> premier prix de la séance (ouverture de sa première barre minute), connu à now."""
    minute = usable_bars(minute, MINUTE, now)

    return {symbol: first for symbol, (first, _) in first_hour_prices(minute, market_open).items()}


def _correlation(a, b):
    """Corrélation des rendements quotidiens aux dates communes ; None si non calculable."""
    returns_b = dict(b)
    common = [(r, returns_b[ts]) for ts, r in a if ts in returns_b]
    if len(common) < 2:
        return None
    value = np.corrcoef(*zip(*common))[0, 1]
    return None if math.isnan(value) else float(value)


def screen(daily, minute, market_open, decision_time, criteria):
    """
    Liste les titres qui remplissent tous les critères à decision_time.
    Retourne (sélection, entonnoir). La sélection peut compter moins de criteria.count titres :
    elle n'est jamais complétée en assouplissant les critères.
    """
    daily = usable_bars(daily, DAY, decision_time)
    minute = usable_bars(minute, MINUTE, decision_time)

    if decision_time != market_open + timedelta(minutes=criteria.first_hour_minutes):
        raise ValueError("decision_time doit valoir market_open + first_hour_minutes")

    candidates, funnel = daily_candidates(daily, decision_time, criteria)
    first_hour = first_hour_prices(minute, market_open)

    rising = [(s, *first_hour[s.symbol]) for s in candidates
              if s.symbol in first_hour and first_hour[s.symbol][1] > first_hour[s.symbol][0]]
    funnel["hausse_premiere_heure"] = len(rising)

    window = criteria.correlation_sessions
    selection = []
    for stats, day_open, price in rising:
        if len(selection) == criteria.count:
            break
        correlations = [_correlation(stats.returns[-window:], kept["stats"].returns[-window:])
                        for kept in selection]
        if any(c is None or c > criteria.max_pairwise_correlation for c in correlations):
            continue
        selection.append({"stats": stats, "open": day_open, "price": price,
                          "max_correlation": max(correlations, default=None)})
    funnel["selection_diversifiee"] = len(selection)

    return [
        {
            "rank": rank,
            "symbol": item["stats"].symbol,
            "prev_close": str(item["stats"].last_close),
            "open_today": str(item["open"]),
            "price_at_decision": str(item["price"]),
            "return_month": item["stats"].return_month,
            "return_day_minus_2": item["stats"].returns[-2][1],
            "return_day_minus_1": item["stats"].returns[-1][1],
            "return_first_hour": float(item["price"] / item["open"] - 1),
            "volatility_annualized": item["stats"].volatility * math.sqrt(TRADING_DAYS_PER_YEAR),
            "avg_dollar_volume": str(item["stats"].avg_dollar_volume.quantize(Decimal("1"))),
            "max_correlation_with_previous": item["max_correlation"],
        }
        for rank, item in enumerate(selection, start=1)
    ], funnel
