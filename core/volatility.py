"""
Stratégie « Volatilité » (famille volatilite, décisions T25, T26) : des titres très volatils, peu corrélés entre eux,
achetés à l'ouverture (un montant fixe par titre, ex. 5 000 $) ; chaque titre est gardé jusqu'à ce que son propre gain
net atteigne l'objectif (ex. 200 $), puis vendu.

Liste (screen_basket), décidée à l'ouverture d'une séance avec les seules séances terminées avant (datation
structurelle, première ligne) : par domaine SEC (hors domaines exclus), les per_domain titres d'une bourse donnée
(ETF exclus en amont) qui sont
  1. très échangés : montant moyen sur liquidity_sessions séances ≥ min_dollar_volume, prix ≥ min_price ;
  2. très volatils : volatilité annualisée (volatility_sessions séances) au-dessus du quantile volatility_quantile
     des titres très échangés ;
  3. en tendance neutre ou positive : variation sur trend_sessions séances ≥ min_trend ;
  4. les moins corrélés entre eux : le jeu de per_domain titres dont la corrélation moyenne deux à deux des
     rendements quotidiens (trend_sessions séances) est la plus faible (recherche complète).
Un domaine qui n'a pas assez de titres est complété au plus proche : les règles sont relâchées pas à pas (échelle
cumulative « ladder »), chaque titre ajouté porte le pas qui l'a laissé passer.

Suivi (track_round) : montant réparti à parts égales (fractions d'action) sur les titres donnés, achat au premier
échange de chaque titre à partir de l'ouverture ; à chaque clôture de minute de séance régulière, valeur (dernier
cours connu de chaque titre) ; vente à la première minute où le gain net de frais atteint l'objectif. La stratégie
suit chaque titre seul (un titre, son montant, son objectif).
Montants en Decimal (règle des nombres d'argent de CLAUDE.md).
"""

import itertools
import json
import math
from dataclasses import dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from core.datation import usable_bars
from core.screener import DAY, MINUTE

SIGNAL = "volatilite"
# Au-delà de ce nombre de combinaisons, la recherche se limite aux 25 titres les plus échangés du domaine.
MAX_COMBINATIONS = 300000


@dataclass(frozen=True)
class VolatilityRules:
    signal: str
    version: int
    exchange: str
    excluded_domains: tuple
    per_domain: int
    min_price: Decimal
    liquidity_sessions: int
    volatility_sessions: int
    trend_sessions: int
    # Échelle : [{"label", "min_dollar_volume", "volatility_quantile", "min_trend"}], du pas strict au plus large.
    ladder: tuple
    amount_per_stock: Decimal
    target_gain: Decimal
    cost_bps: Decimal

    @classmethod
    def from_json(cls, raw, source="règles"):
        names = {f.name for f in fields(cls)}
        if set(raw) != names or raw["signal"] != SIGNAL:
            raise ValueError(f"Clés attendues dans {source} : {sorted(names)}, signal « {SIGNAL} », reçues : {sorted(raw)}")
        steps = tuple({"label": s["label"], "min_dollar_volume": Decimal(s["min_dollar_volume"]),
                       "volatility_quantile": float(s["volatility_quantile"]), "min_trend": Decimal(s["min_trend"])}
                      for s in raw["ladder"])
        return cls(signal=raw["signal"], version=int(raw["version"]), exchange=raw["exchange"],
                   excluded_domains=tuple(raw["excluded_domains"]), per_domain=int(raw["per_domain"]),
                   min_price=Decimal(raw["min_price"]), liquidity_sessions=int(raw["liquidity_sessions"]),
                   volatility_sessions=int(raw["volatility_sessions"]), trend_sessions=int(raw["trend_sessions"]),
                   ladder=steps, amount_per_stock=Decimal(raw["amount_per_stock"]), target_gain=Decimal(raw["target_gain"]),
                   cost_bps=Decimal(raw["cost_bps"]))

    @classmethod
    def from_file(cls, path):
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")), str(path))

    def to_json(self):
        def plain(v):
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, (tuple, list)):
                return [plain(x) for x in v]
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items()}
            return v
        return {f.name: plain(getattr(self, f.name)) for f in fields(self)}


def basket_stats(daily, decision_time, rules):
    """
    Mesures de chaque titre à decision_time (séances terminées avant seulement) : DataFrame indexé par symbole
    (price, dollar_volume, volatility, trend), et rendements quotidiens (log) des trend_sessions dernières séances.
    Seuls les titres cotés à chacune des trend_sessions + 1 dernières séances sont mesurés.
    """
    daily = usable_bars(daily, DAY, decision_time)

    closes = daily.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last").sort_index().astype(float)
    volumes = daily.pivot_table(index="timestamp", columns="symbol", values="volume", aggfunc="last").sort_index().astype(float)
    need = rules.trend_sessions + 1
    closes, volumes = closes.tail(need), volumes.reindex(closes.index).tail(need)
    full = closes.columns[closes.notna().all()]
    closes, volumes = closes[full], volumes[full]
    returns = np.log(closes).diff().iloc[1:]
    n = rules.liquidity_sessions
    stats = pd.DataFrame({
        "price": closes.iloc[-1],
        "dollar_volume": (closes.tail(n) * volumes.tail(n)).mean(),
        "volatility": returns.tail(rules.volatility_sessions).std() * math.sqrt(252),
        "trend": closes.iloc[-1] / closes.iloc[0] - 1,
    })
    return stats, returns


def ladder_floors(stats, rules):
    """Seuil de volatilité de chaque pas : quantile mesuré sur les titres très échangés du pas strict."""
    strict = rules.ladder[0]
    liquid = stats[(stats.price >= float(rules.min_price)) & (stats.dollar_volume >= float(strict["min_dollar_volume"]))]
    return {s["label"]: float(liquid.volatility.quantile(s["volatility_quantile"])) for s in rules.ladder}, len(liquid)


def candidates(stats, rules):
    """Titres qui passent le pas le plus large ; colonne « step » : premier pas qui les laisse passer."""
    floors, _ = ladder_floors(stats, rules)
    priced = stats[stats.price >= float(rules.min_price)]

    def first_step(row):
        for s in rules.ladder:
            if (row.dollar_volume >= float(s["min_dollar_volume"]) and row.volatility >= floors[s["label"]]
                    and row.trend >= float(s["min_trend"])):
                return s["label"]
        return None

    steps = priced.apply(first_step, axis=1) if not priced.empty else pd.Series(dtype=object)
    return priced.assign(step=steps)[steps.notna()] if not priced.empty else priced.assign(step=None)


def _least_correlated(corr, pool, k, fixed, by_volume):
    """Les k titres de pool qui, avec fixed, donnent la plus faible corrélation moyenne deux à deux."""
    if len(pool) <= k:
        return list(pool)
    if math.comb(len(pool), k) > MAX_COMBINATIONS:
        pool = sorted(pool, key=lambda s: -by_volume[s])[:25]

    def mean_corr(combo):
        members = list(fixed) + list(combo)
        pairs = [corr.loc[a, b] for a, b in itertools.combinations(members, 2)]
        return float(np.mean(pairs)) if pairs else 0.0
    return list(min(itertools.combinations(sorted(pool), k), key=mean_corr))


def screen_basket(daily, decision_time, rules, domains_for):
    """
    Liste du panier à decision_time. domains_for(symboles) -> {symbole: domaine SEC} (titre absent : non classé,
    écarté). Retourne (titres [{symbol, domain, step, price, dollar_volume, volatility, trend, corr_with_others}],
    résumé {floors, liquid, domains: {domaine: {strict, mean_corr}}}).
    """
    daily = usable_bars(daily, DAY, decision_time)

    stats, returns = basket_stats(daily, decision_time, rules)
    floors, liquid = ladder_floors(stats, rules)
    pool = candidates(stats, rules)
    domains = domains_for(sorted(pool.index))
    pool = pool.assign(domain=[domains.get(s) for s in pool.index])
    pool = pool[pool.domain.notna() & ~pool.domain.isin(rules.excluded_domains)]
    corr = returns[list(pool.index)].corr()
    order = [s["label"] for s in rules.ladder]
    by_volume = pool.dollar_volume.to_dict()

    chosen_all, summary = [], {"floors": floors, "liquid": liquid, "domains": {}}
    for domain, group in sorted(pool.groupby("domain"), key=lambda g: g[0]):
        chosen = []
        for label in order:
            room = rules.per_domain - len(chosen)
            if room <= 0:
                break
            step_pool = [s for s in group.index if group.loc[s, "step"] == label]
            chosen += _least_correlated(corr, step_pool, min(room, len(step_pool)), chosen, by_volume)
        pairs = [corr.loc[a, b] for a, b in itertools.combinations(chosen, 2)]
        summary["domains"][domain] = {"strict": int((group.step == order[0]).sum()),
                                      "mean_corr": float(np.mean(pairs)) if pairs else None}
        for s in sorted(chosen, key=lambda s: (order.index(group.loc[s, "step"]), -group.loc[s, "dollar_volume"])):
            row = group.loc[s]
            others = [corr.loc[s, o] for o in chosen if o != s]
            chosen_all.append({
                "symbol": s, "domain": domain, "step": row.step, "price": round(float(row.price), 4),
                "dollar_volume": round(float(row.dollar_volume)), "volatility": round(float(row.volatility), 4),
                "trend": round(float(row.trend), 4),
                "corr_with_others": round(float(np.mean(others)), 4) if others else None,
            })
    cross = [corr.loc[a["symbol"], b["symbol"]] for a, b in itertools.combinations(chosen_all, 2)]
    summary["mean_corr"] = float(np.mean(cross)) if cross else None
    summary["share_negative"] = float(np.mean([x < 0 for x in cross])) if cross else None
    return chosen_all, summary


def net_gain(value, amount, cost_bps):
    """Gain net de frais : valeur - montant, moins le coût d'achat (sur le montant) et de vente (sur la valeur)."""
    cost = cost_bps / Decimal("10000")
    return value - amount - cost * amount - cost * value


def track_round(symbols, bars, entry_time, sessions, now, amount, target_gain, cost_bps):
    """
    Suivi d'un tour du panier, connu à now.
    bars     : barres minute des titres à partir de entry_time (plusieurs séances possibles).
    sessions : [(ouverture, clôture)] UTC des séances depuis l'achat ; seules les minutes de séance régulière comptent.
    Retourne {"status": "waiting" | "live" | "sold", "entry", "shares", "last", "value", "gain", "best_gain",
              "sold_at", "sold_value", "sold_gain", "sessions_held", "checked_until"} ; montants en Decimal.
    """
    bars = usable_bars(bars, MINUTE, now)

    bars = bars[(bars["timestamp"] >= entry_time) & bars["symbol"].isin(list(symbols))]
    in_session = pd.Series(False, index=bars.index)
    for start, end in sessions:
        in_session |= (bars["timestamp"] >= start) & (bars["timestamp"] < end)
    bars = bars[in_session].sort_values("timestamp")
    entry = {s: g["open"].iloc[0] for s, g in bars.groupby("symbol", sort=True)}
    result = {"status": "waiting", "entry": entry, "shares": {}, "last": {}, "value": None, "gain": None,
              "best_gain": None, "sold_at": None, "sold_value": None, "sold_gain": None, "sessions_held": 0,
              "checked_until": None}
    if not entry:
        return result

    per_stock = amount / len(symbols)
    # Titre sans échange encore : sa part reste en liquide (valeur = montant alloué) jusqu'à son premier échange.
    shares = {s: per_stock / entry[s] for s in entry}
    closes = bars.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last").sort_index()
    last = dict(entry)
    best, sold = None, None
    cash = per_stock * (len(symbols) - len(entry))
    for at, row in closes.iterrows():
        for s, price in row.items():
            if price is not None and not (isinstance(price, float) and math.isnan(price)):
                last[s] = price
        value = cash + sum(shares[s] * last[s] for s in shares)
        gain = net_gain(value, amount, cost_bps)
        best = gain if best is None or gain > best else best
        if gain >= target_gain:
            sold = (at, value, gain)
            break
    value = cash + sum(shares[s] * last[s] for s in shares)
    until = sold[0] if sold else closes.index[-1]
    result.update({
        "status": "sold" if sold else "live", "shares": shares, "last": last, "value": value,
        "gain": net_gain(value, amount, cost_bps), "best_gain": best,
        "sessions_held": sum(1 for start, _ in sessions if start <= until),
        "checked_until": (until + timedelta(minutes=1)).isoformat(),
    })
    if sold:
        result.update({"sold_at": (sold[0] + timedelta(minutes=1)).isoformat(), "sold_value": sold[1],
                       "sold_gain": sold[2]})
    return result


# Règle de vente « 2 actions » (T28) : objectif, sinon vente à l'échéance si positif ; si négatif à l'échéance :
IF_NEGATIVE = ("objectif", "retour_a_zero", "cloture")   # A garder jusqu'à l'objectif · B jusqu'à 0 $ net · C clôture du jour


def exit_with_deadline(path, entry_price, amount, target_gain, cost_bps, deadline, day_close, if_negative):
    """
    Vente d'une action achetée amount au prix entry_price.
    path       : [(fin de minute, cours de clôture)] des minutes de séance régulière après l'achat, dans l'ordre
                 (plusieurs séances possibles ; rien la nuit : un saut d'ouverture compte à la première minute).
    deadline   : échéance (ex. achat + 3 h 30) ; à la première minute qui la passe, vente si le gain net est > 0.
    day_close  : clôture de la séance d'achat (variante « cloture »).
    if_negative: ce qui se passe si le gain est ≤ 0 à l'échéance (IF_NEGATIVE).
    Retourne {"exit_at", "price", "gain", "reason": objectif | positif_echeance | retour_a_zero | cloture}, ou None
    si l'action est encore détenue à la fin du trajet. Montants en Decimal.
    """
    if if_negative not in IF_NEGATIVE:
        raise ValueError(f"if_negative doit valoir l'un de {IF_NEGATIVE}")
    shares = amount / entry_price
    past_deadline = False
    for at, price in path:
        gain = net_gain(shares * price, amount, cost_bps)
        sale = None
        if gain >= target_gain:
            sale = "objectif"
        elif not past_deadline and at >= deadline:
            past_deadline = True
            if gain > 0:
                sale = "positif_echeance"
        elif past_deadline and if_negative == "retour_a_zero" and gain >= 0:
            sale = "retour_a_zero"
        if sale is None and past_deadline and if_negative == "cloture" and at >= day_close:
            sale = "cloture"
        if sale:
            return {"exit_at": at, "price": price, "gain": gain, "reason": sale}
    return None


def rank_by_volatility(daily, decision_time, symbols, sessions=20):
    """
    Choix « 2 actions » (méthode M7 du test T28) : symboles classés de la plus forte à la plus faible volatilité des
    rendements quotidiens (log) sur les sessions dernières séances terminées avant decision_time. [(symbole, écart-type)].
    """
    daily = usable_bars(daily, DAY, decision_time)

    closes = daily.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last").sort_index().astype(float)
    scored = []
    for s in symbols:
        if s not in closes:
            continue
        series = closes[s].dropna()
        if len(series) < sessions + 2:
            continue
        scored.append((s, float(np.log(series.tail(sessions + 1)).diff().std())))
    return sorted(scored, key=lambda x: (-x[1], x[0]))
