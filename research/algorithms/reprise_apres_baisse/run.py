"""
Run quotidien du screener « reprise après baisse ».

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.run
"""

import json
import sys
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from core.closing import ClosingCriteria, market_moves, screen_closing
from core.domains import domain_trends
from core.fundamentals import split_adjusted
from core.opening import OpeningCriteria, screen_opening
from core.screener import Criteria, daily_candidates, liquid_universe, market_in_uptrend, screen
from core.strategy import load_strategies
from core.swing import SwingCriteria, screen_swing
from core.switch import SwitchCriteria, choose
from core.universe import eligible_symbols
from infra import nasdaq_symbols, sec
from infra.alpaca_api import DATA_URL, AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import TraceError, committed_git_sha, load_runs, next_run_id, save_run, variant_of

FAMILY = "reprise_apres_baisse"
HERE = Path(__file__).resolve().parent
# Stratégies : la principale (ce dossier) et ses variantes d'heures (strategies/<id>/), chacune avec deux listes.
STRATEGIES = load_strategies(HERE, FAMILY)
# Listes de la stratégie principale : variante -> fichier de critères (test sur le passé, tests).
VARIANTS = STRATEGIES[0].criteria_files
# Versions remplacées, pour la comparaison avant / après du test sur le passé.
ARCHIVED = {"sans_per_v1": HERE / "archive" / "criteres_v1_sans_per.json",
            "per12_v2": HERE / "archive" / "criteres_v2_per12.json"}
NEW_YORK = ZoneInfo("America/New_York")
# Offre gratuite Alpaca : les barres consolidées (SIP) des 15 dernières minutes ne sont pas servies.
SIP_DELAY = timedelta(minutes=15)
# Lancé un peu avant que les données soient disponibles, le run attend au plus ce délai au lieu d'abandonner.
MAX_WAIT = timedelta(minutes=20)
# Couvre largement les 61 séances nécessaires aux critères (jours fériés compris).
DAILY_HISTORY = timedelta(days=130)
# Liste « repli dans une tendance » : dernier prix des titres liquides lu sur les 15 minutes avant la décision.
PRICE_WINDOW = timedelta(minutes=15)


# Divisions d'actions lues depuis cette date (bien avant les plus anciens bénéfices utiles, 12 mois + 200 jours).
SPLITS_SINCE = date(2015, 1, 1)


def earnings(alpaca, key):
    """
    earnings_for des sélections : symboles -> déclarations de bénéfice (10-K / 10-Q) ramenées au nombre d'actions
    d'aujourd'hui (divisions d'actions d'Alpaca, lues une fois par jour de cache key).
    """
    def lookup(symbols):
        splits = cached(f"{key}/splits", lambda: alpaca.splits(SPLITS_SINCE, datetime.now(timezone.utc).date()))
        by_symbol = {}
        for split in splits:
            by_symbol.setdefault(split["symbol"], []).append(split)
        return {s: split_adjusted(entries, by_symbol.get(s, [])) for s, entries in sec.eps(symbols, key).items()}

    return lookup


def _pct(value):
    return f"{value * 100:+.2f} %"


def _previous_close(alpaca, session_date):
    """Clôture (UTC) de la séance précédant session_date."""
    earlier = [s for s in alpaca.sessions(session_date - timedelta(days=10), session_date) if s[0] < session_date]
    day, _, close_time = earlier[-1]
    return datetime.combine(day, close_time, NEW_YORK).astimezone(timezone.utc)


def _produce_opening(alpaca, criteria, session_date, market_open, key):
    """
    Liste « ouverture » : barres minute de la dernière heure de la veille et de la nuit (pré-ouverture
    comprise) des titres liquides, jusqu'à la décision (ouverture - retard des données).
    Retourne (décision, sélection, entonnoir, cotes Nasdaq, univers, titres liquides, quotidien).
    """
    decision_time = market_open + timedelta(minutes=criteria.decision_minutes)
    previous_close = _previous_close(alpaca, session_date)
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/premarket_daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    liquid, _ = liquid_universe(daily, decision_time, criteria)
    start = previous_close - timedelta(minutes=criteria.last_hour_minutes)
    minute = cached(f"{key}/night_bars_{decision_time.astimezone(NEW_YORK):%H%M}",
                    lambda: alpaca.bars([s.symbol for s in liquid], "1Min", start, decision_time))
    market_daily = None if criteria.market_symbol is None else cached(
        f"{key}/market_daily_bars_{criteria.market_symbol}_open",
        lambda: alpaca.bars([criteria.market_symbol], "1Day", decision_time - DAILY_HISTORY, decision_time))
    selection, funnel = screen_opening(daily, minute, market_open, previous_close, decision_time, criteria,
                                       earnings_for=earnings(alpaca, key), market_daily=market_daily)
    return decision_time, selection, funnel, listings, listings_created, universe_funnel, daily


def _market_minute(alpaca, symbol, key, market_open, decision_time):
    """Barres minute du repère (SPY) de l'ouverture à la décision (règles « marché qui tient / qui remonte »)."""
    return cached(f"{key}/market_minute_{symbol}_{decision_time.astimezone(NEW_YORK):%H%M}",
                  lambda: alpaca.bars([symbol], "1Min", market_open, decision_time))


def _needs_market_minute(criteria):
    return criteria.market_min_day_return is not None or criteria.market_min_last_hour_return is not None


def _produce_closing(alpaca, criteria, session_date, market_open, key):
    """
    Liste « fin de journée » : barres minute de la séance du jour des titres liquides, jusqu'à la décision.
    Retourne (décision, sélection, entonnoir, cotes Nasdaq, date de l'annuaire, univers, quotidien).
    """
    decision_time = market_open + timedelta(minutes=criteria.decision_minutes)
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    liquid, _ = liquid_universe(daily, decision_time, criteria)
    minute = cached(f"{key}/day_bars_{decision_time.astimezone(NEW_YORK):%H%M}",
                    lambda: alpaca.bars([s.symbol for s in liquid], "1Min", market_open, decision_time))
    market_daily = None if criteria.market_symbol is None else cached(
        f"{key}/market_daily_bars_{criteria.market_symbol}",
        lambda: alpaca.bars([criteria.market_symbol], "1Day", decision_time - DAILY_HISTORY, decision_time))
    market_minute = (_market_minute(alpaca, criteria.market_symbol, key, market_open, decision_time)
                     if _needs_market_minute(criteria) else None)
    fear_minute = (_market_minute(alpaca, criteria.fear_symbol, key, market_open, decision_time)
                   if criteria.market_max_fear_move is not None else None)
    selection, funnel = screen_closing(daily, minute, market_open, decision_time, criteria,
                                       earnings_for=earnings(alpaca, key), market_daily=market_daily,
                                       market_minute=market_minute, fear_minute=fear_minute)
    return decision_time, selection, funnel, listings, listings_created, universe_funnel, daily


def _switch_choice(alpaca, criteria, market_open, key):
    """
    Bascule : (première liste retenue ?, variation du repère depuis l'ouverture à la première décision).
    Barres du repère terminées à la première décision seulement.
    """
    first_decision = market_open + timedelta(minutes=criteria.first.decision_minutes)
    market_minute = _market_minute(alpaca, criteria.market_symbol, key, market_open, first_decision)
    day, _ = market_moves(market_minute, market_open, first_decision, criteria.market_symbol)
    return choose(criteria, market_minute, market_open, first_decision), day


def _produce_swing(alpaca, criteria, session_date, market_open, key):
    """
    Liste « repli dans une tendance » : dernier prix des titres liquides avant la décision (15 dernières minutes).
    Retourne (décision, sélection, entonnoir, cotes Nasdaq, date de l'annuaire, univers, quotidien).
    """
    decision_time = market_open + timedelta(minutes=criteria.decision_minutes)
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    liquid, _ = liquid_universe(daily, decision_time, criteria)
    minute = cached(f"{key}/swing_prices_{decision_time.astimezone(NEW_YORK):%H%M}",
                    lambda: alpaca.bars([s.symbol for s in liquid], "1Min", decision_time - PRICE_WINDOW, decision_time))
    market_daily = None if criteria.market_symbol is None else cached(
        f"{key}/market_daily_bars_{criteria.market_symbol}",
        lambda: alpaca.bars([criteria.market_symbol], "1Day", decision_time - DAILY_HISTORY, decision_time))
    market_minute = (_market_minute(alpaca, criteria.market_symbol, key, market_open, decision_time)
                     if criteria.market_min_day_return is not None else None)
    selection, funnel = screen_swing(daily, minute, market_open, decision_time, criteria,
                                     earnings_for=earnings(alpaca, key), market_daily=market_daily,
                                     market_minute=market_minute)
    # Premier prix de la séance des titres retenus (colonne « depuis l'ouverture » du suivi), lu avant la décision.
    chosen = [i["symbol"] for i in selection]
    opening = (alpaca.bars(chosen, "1Min", market_open, market_open + PRICE_WINDOW) if chosen
               else minute.iloc[0:0])
    opens = {s: b.sort_values("timestamp")["open"].iloc[0] for s, b in opening.groupby("symbol")}
    selection = [{**i, "open_today": str(opens.get(i["symbol"], Decimal(i["prev_close"])))} for i in selection]
    return decision_time, selection, funnel, listings, listings_created, universe_funnel, daily


OVERRIDES_FILE = HERE / "overrides.json"


def market_health_ignored(key):
    """Vrai si le propriétaire a suspendu la règle « marché en bonne forme » pour la séance key (overrides.json)."""
    if not OVERRIDES_FILE.exists():
        return False
    return key in json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")).get("ignore_market_health", [])


def without_market_health(criteria):
    """Mêmes critères sans la règle « marché en bonne forme » (bascule : dans ses deux listes)."""
    if isinstance(criteria, SwitchCriteria):
        return replace(criteria, first=without_market_health(criteria.first), second=without_market_health(criteria.second))
    return replace(criteria, market_ma_sessions=None) if getattr(criteria, "market_ma_sessions", None) else criteria


def produce(alpaca, criteria, session_date, market_open, now, git_sha):
    """
    Calcule le run d'une séance (sans l'enregistrer) : sélection, entonnoir, domaines, sources.
    Toutes les données sont tronquées à l'instant de décision (ouverture + première heure, + confirmation).
    """
    key = session_date.isoformat()
    if market_health_ignored(key) and without_market_health(criteria) != criteria:
        # Règle suspendue ce jour-là par le propriétaire (décision T22) : la liste le dit dans son run.
        payload = produce(alpaca, without_market_health(criteria), session_date, market_open, now, git_sha)
        if payload is not None:
            # La règle aurait-elle bloqué ? Repère et moyenne lus à la décision (clôtures quotidiennes d'avant).
            decision_time = datetime.fromisoformat(payload["decision_time"])
            spy = cached(f"{key}/market_daily_bars_SPY_health",
                         lambda: alpaca.bars(["SPY"], "1Day", decision_time - DAILY_HISTORY, decision_time))
            healthy, last, average = market_in_uptrend(spy, decision_time, "SPY", 50)
            payload["override"] = {"ignore_market_health": True, "criteria": criteria.to_json(),
                                   "market_healthy": bool(healthy), "market_close": str(last),
                                   "market_average": str(average.quantize(Decimal("0.01"))),
                                   "note": "règle « marché en bonne forme » suspendue ce jour-là par le propriétaire"}
        return payload
    if isinstance(criteria, SwitchCriteria):
        # Bascule : liste de la première décision si le marché tient, sinon (plus tard) celle de la seconde.
        first, day = _switch_choice(alpaca, criteria, market_open, key)
        chosen = criteria.first if first else criteria.second
        if now < market_open + timedelta(minutes=chosen.decision_minutes) + SIP_DELAY:
            return None   # le marché n'a pas tenu : la seconde liste n'est pas encore prête
        payload = produce(alpaca, chosen, session_date, market_open, now, git_sha)
        payload["switch"] = {"criteria": criteria.to_json(), "chosen": "first" if first else "second",
                             "market_day_return_at_first": None if day is None else float(day)}
        return payload
    if isinstance(criteria, (OpeningCriteria, ClosingCriteria, SwingCriteria)):
        special = {OpeningCriteria: _produce_opening, ClosingCriteria: _produce_closing,
                   SwingCriteria: _produce_swing}[type(criteria)]
        decision_time, selection, funnel, listings, listings_created, universe_funnel, daily = special(
            alpaca, criteria, session_date, market_open, key)
        return _payload(alpaca, criteria, key, market_open, decision_time, now, git_sha, daily, listings,
                        listings_created, universe_funnel, funnel, selection)
    decision_time = market_open + timedelta(minutes=criteria.decision_minutes)
    listings, listings_created = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, universe_funnel = eligible_symbols(assets, listings)
    daily = cached(f"{key}/daily_bars",
                   lambda: alpaca.bars(symbols, "1Day", decision_time - DAILY_HISTORY, decision_time))
    candidates, _ = daily_candidates(daily, decision_time, criteria)
    minute = cached(f"{key}/minute_bars" if criteria.confirmation_minutes is None
                    else f"{key}/minute_bars_{criteria.first_hour_minutes}_{criteria.decision_minutes}",
                    lambda: alpaca.bars([c.symbol for c in candidates], "1Min", market_open, decision_time))
    # Règle « marché en bonne forme » : clôtures quotidiennes du repère (SPY), lues à part (c'est un ETF, hors univers).
    market_daily = None if criteria.market_symbol is None else cached(
        f"{key}/market_daily_bars_{criteria.market_symbol}",
        lambda: alpaca.bars([criteria.market_symbol], "1Day", decision_time - DAILY_HISTORY, decision_time))
    selection, funnel = screen(daily, minute, market_open, decision_time, criteria,
                               earnings_for=earnings(alpaca, key), market_daily=market_daily)
    return _payload(alpaca, criteria, key, market_open, decision_time, now, git_sha, daily, listings,
                    listings_created, universe_funnel, funnel, selection)


def _payload(alpaca, criteria, key, market_open, decision_time, now, git_sha, daily, listings, listings_created,
             universe_funnel, funnel, selection):
    """Contenu du run : critères, sources, entonnoir, domaines (complément de lecture), sélection."""
    # Domaines : complément de lecture, pas un critère. Une panne SEC n'empêche pas la liste, elle est enregistrée.
    liquid, _ = liquid_universe(daily, decision_time, criteria)
    try:
        profiles = sec.profiles([s.symbol for s in liquid], key)
        bubbles, unclassified = domain_trends(
            daily, decision_time, criteria, {symbol: p["domain"] for symbol, p in profiles.items()})
        domains = {"bubbles": bubbles, "unclassified": unclassified,
                   "measure": f"moyenne simple des variations sur {criteria.month_sessions} séances",
                   "universe": "titres à l'historique complet, au prix et au volume échangé suffisants"}
    except FetchError as e:
        profiles, domains = {}, {"error": str(e)}

    payload = {
        "family": FAMILY,
        "status": "diagnostic",
        "session_date": key,
        "market_open": market_open.isoformat(),
        "decision_time": decision_time.isoformat(),
        "created_at": now.isoformat(),
        "git_sha": git_sha,
        "criteria": criteria.to_json(),
        "sources": {
            "alpaca": {"trading_api": alpaca.trading_url, "data_api": DATA_URL, "feed": "sip", "adjustment": "all"},
            "nasdaq_trader": listings_created,
            "sec": {"tickers": sec.TICKERS_URL, "profiles": "data.sec.gov/submissions (ownerOrg, sic)"},
        },
        "funnel": {**universe_funnel, **funnel},
        "domains": domains,
        "selection": [{**item, "name": listings[item["symbol"]]["name"],
                       "domain": profiles.get(item["symbol"], {}).get("domain"),
                       "sic_description": profiles.get(item["symbol"], {}).get("sic_description")}
                      for item in selection],
    }
    return payload


def _report(payload, criteria, path):
    selection = payload["selection"]
    decision_time = datetime.fromisoformat(payload["decision_time"])
    label = payload["variant"] if payload["strategy"] == "principale" else f"{payload['strategy']}/{payload['variant']}"
    print(f"[{label}] Séance du {payload['session_date']}, décision à "
          f"{decision_time.astimezone(NEW_YORK):%H:%M} (New York) — run {payload['run_id']}, "
          f"critères version {criteria.version}, statut diagnostic, code {payload['git_sha'][:7]}")
    print("Entonnoir : " + " → ".join(f"{step} {n}" for step, n in payload["funnel"].items()))
    # Bascule : nombre de titres de ses listes (le même dans les deux).
    count = getattr(criteria, "count", None) or criteria.first.count
    print(f"n = {len(selection)} titres sur {count} au plus :")
    for item in selection:
        pe = f"  PER {item['pe_ttm']}" if item.get("pe_ttm") else ""
        # Liste « reprise » : première heure ; liste « ouverture » : dernière heure de la veille et nuit.
        signal = (f"1re heure {_pct(item['return_first_hour'])}" if "return_first_hour" in item else
                  f"repli {_pct(-item['pullback'])}  journée {_pct(item['return_day'])}" if "pullback" in item else
                  f"fin de veille {_pct(item['return_last_hour'])}  nuit {_pct(item['return_overnight'])}"
                  if "return_overnight" in item else
                  f"journée {_pct(item['return_day'])}  dernière heure {_pct(item['return_last_hour'])}")
        print(f"{item['rank']:>3}. {item['symbol']:<6} {item['name'][:40]:<40} "
              f"mois {_pct(item['return_month'])}  J-2 {_pct(item['return_day_minus_2'])}  "
              f"J-1 {_pct(item['return_day_minus_1'])}  {signal}{pe}")
    print(f"Résultats : {path}")


def run(wait=True):
    """
    Produit les listes de la séance encore manquantes, dans toutes les stratégies. wait : la première liste
    attend ses données si le lancement est un peu en avance (tâche planifiée) ; le suivi en direct passe False.
    """
    now = datetime.now(timezone.utc)
    session_date = now.astimezone(NEW_YORK).date()
    key = session_date.isoformat()

    # Listes à produire : (stratégie, version, critères) qui n'ont pas encore de run pour la séance.
    todo = []
    for strategy in STRATEGIES:
        done = {variant_of(r) for r in load_runs(strategy.storage) if r["session_date"] == key}
        todo += [(strategy, variant, c) for variant, c in strategy.criteria().items() if variant not in done]
    if not todo:
        print(f"Runs déjà produits pour la séance du {key}, dans toutes les stratégies.")
        return 0

    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    session = alpaca.session(session_date)
    if session is None:
        print(f"Marché fermé le {key} (calendrier Alpaca) : aucun run.")
        return 0

    market_open = datetime.combine(session_date, session[0], NEW_YORK).astimezone(timezone.utc)
    # Chaque liste part dès que ses données sont disponibles (décision + 15 min). Seule la première attend
    # (lancement planifié quelques secondes trop tôt) ; une liste plus tardive qui n'est pas prête est
    # laissée au lancement suivant, sans retarder les autres.
    domains = None
    pending = []
    for i, (strategy, variant, criteria) in enumerate(sorted(todo, key=lambda item: item[2].decision_minutes)):
        label = variant if strategy.is_main else f"{strategy.id}/{variant}"
        ready_at = market_open + timedelta(minutes=criteria.decision_minutes) + SIP_DELAY
        now = datetime.now(timezone.utc)
        if wait and i == 0 and ready_at - MAX_WAIT <= now < ready_at:
            print(f"[{label}] Données disponibles à {ready_at.astimezone(NEW_YORK):%H:%M:%S} (New York) : "
                  f"attente de {(ready_at - now).total_seconds():.0f} s.")
            time.sleep((ready_at - now).total_seconds())
            now = datetime.now(timezone.utc)
        if now < ready_at:
            print(f"[{label}] Pas encore : données disponibles à {ready_at.astimezone(NEW_YORK):%H:%M} (New York), "
                  f"liste produite au prochain lancement.")
            pending.append(label)
            continue
        produced = produce(alpaca, criteria, session_date, market_open, now, git_sha)
        if produced is None:
            print(f"[{label}] Bascule : le marché n'a pas tenu à la première décision, seconde liste au prochain lancement.")
            pending.append(label)
            continue
        payload = {"run_id": next_run_id(strategy.storage), "variant": variant, "strategy": strategy.id, **produced}
        _report(payload, criteria, save_run(strategy.storage, payload))
        domains = payload["domains"]
    if domains is None:
        return 1 if pending else 0

    if "error" in domains:
        print(f"Domaines indisponibles : {domains['error']}")
    else:
        print(f"Tendance sur {domains.get('measure', '')} par domaine (SEC), "
              f"{domains['unclassified']} titres non classés :")
        for bubble in domains["bubbles"]:
            print(f"     {bubble['domain']:<40} {_pct(bubble['mean_return'])}  n = {bubble['n']}")
    return 0


def main():
    try:
        return run()
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
