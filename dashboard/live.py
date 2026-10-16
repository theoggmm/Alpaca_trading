"""
Suivi en direct des bulles par domaine pendant la séance de New York, et état de fin de séance.

Toutes les minutes : derniers prix (toutes bourses, 15 min de retard), moyenne par domaine pour
la journée, la première heure, 2 séances, 1 semaine et 1 mois, variation depuis l'ouverture de
chaque titre de la sélection du jour, puis régénération du tableau de bord (qui se recharge seul).

Après la clôture (ou au réveil du Mac après la clôture), l'état de fin de séance est reconstitué
depuis l'historique minute d'Alpaca et gardé dans research/experiments/final/<stockage>/<date>.json.
catch_up() refait cet état pour toute séance terminée qui n'en a pas.

Toutes les stratégies de la famille (heures d'achat et de vente différentes) sont suivies ensemble : les
prix lus servent à toutes, chaque stratégie a son état en direct, ses fins de séance et son tableau de bord.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.live reprise_apres_baisse
"""

import fcntl
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from core.domains import LIVE_MEASURES, WEEK_SESSIONS, domain_trends, live_domain_trends
from core.portfolio import entry_prices, order_plan, simulate
from core.screener import (Criteria, changes_since_open, last_session_prices, liquid_universe, recent_closes,
                           session_open_prices, session_trades)
from core.strategy import criteria_from_json, load_strategies
from core.universe import eligible_symbols
from dashboard.build import CHARTS_FILE, FINALS_DIR, LIVE_FILE, SUPPLEMENTS, build, live_file
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import ROOT, TraceError, committed_git_sha, latest_per_session, load_runs, variant_of
from research.algorithms.reprise_apres_baisse import run as screener

NEW_YORK = ZoneInfo("America/New_York")
FEED = "delayed_sip"
# Offre gratuite Alpaca : les 15 dernières minutes de données consolidées ne sont pas servies.
FEED_DELAY = timedelta(minutes=15)
REFRESH_S = 60
DAILY_HISTORY = timedelta(days=130)
# Fenêtre lue pour retrouver le dernier échange de chaque titre avant la clôture.
CLOSING_WINDOW = timedelta(minutes=30)
# Fenêtre lue après l'ouverture pour connaître le premier prix de chaque titre (graphiques « depuis l'ouverture »).
OPENING_WINDOW = timedelta(minutes=5)
# Simulation d'investissement : achat dès que la liste est disponible (décision + 15 min), vente N minutes
# avant la clôture (N propre à chaque stratégie). Fenêtres lues pour trouver le premier et le dernier échange.
TRADE_WINDOW = timedelta(minutes=5)
EXIT_WINDOW = timedelta(minutes=30)
# Section « Ordres à passer » : montant réparti en actions entières sur la liste avec PER.
ORDER_PLAN_AMOUNT = Decimal("10000")
ORDER_PLAN_VARIANT = "per12"
# Repères de la simulation : tous les titres liquides à parts égales, et l'indice S&P 500 (fonds SPY).
BENCHMARK = "SPY"
# Les données minute d'Alpaca sont corrigées après coup (échanges annulés ou rectifiés) : un état de
# fin de séance calculé le soir même est provisoire ; il devient définitif, relu à neuf, 12 h après la clôture.
DEFINITIVE_AFTER = timedelta(hours=12)
SUPERSEDED_DIR = ROOT / "research" / "outputs" / "final_superseded"
EMPTY_BARS = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])


def strategies(family):
    """Stratégies de la famille : la principale, puis ses variantes d'heures."""
    return load_strategies(ROOT / "research" / "algorithms" / family, family)


def _criteria(family):
    # Univers liquide (critères 2 à 4) : identique dans les deux versions.
    return Criteria.from_file(ROOT / "research" / "algorithms" / family / "criteres_sans_per.json")


def _times(session_date, open_time, close_time):
    """(ouverture, clôture) en UTC d'une séance donnée en heure de New York."""
    return tuple(datetime.combine(session_date, t, NEW_YORK).astimezone(timezone.utc) for t in (open_time, close_time))


def _prepare(alpaca, criteria, key, market_open):
    """Univers liquide (séances terminées avant l'ouverture) et domaines SEC : une fois par séance."""
    listings, _ = cached(f"{key}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{key}/alpaca_assets", alpaca.assets)
    symbols, _ = eligible_symbols(assets, listings)
    # Seules les séances terminées avant l'ouverture servent ; avant l'ouverture, ne rien demander
    # de plus récent que maintenant - 15 min (au-delà, l'offre gratuite refuse la requête).
    end = min(market_open, datetime.now(timezone.utc) - FEED_DELAY)
    daily = cached(f"{key}/live_daily_bars", lambda: alpaca.bars(symbols, "1Day", market_open - DAILY_HISTORY, end))
    liquid, _ = liquid_universe(daily, market_open, criteria)
    profiles = sec.profiles([s.symbol for s in liquid], key)
    names = {s.symbol: listings[s.symbol]["name"] for s in liquid}
    return daily, [s.symbol for s in liquid], {s: p["domain"] for s, p in profiles.items()}, names


def _write_chart_data(daily, market_open, symbols, criteria, key):
    """
    dashboard/charts_data.js : clôtures du dernier mois de chaque titre de l'univers, chargé une fois
    par la page (graphiques des listes par domaine). Écrit une fois par séance, pas à chaque minute.
    """
    closes = recent_closes(daily, market_open, symbols, criteria.month_sessions)
    dates = sorted({d for series in closes.values() for d, _ in series})[-(criteria.month_sessions):]
    rows = ",".join(
        f'"{s}":[' + ",".join(dict(series).get(d, "null") for d in dates) + "]" for s, series in closes.items())
    CHARTS_FILE.write_text(
        f'window.CHART_CLOSES={{"session_date":"{key}","dates":{json.dumps(dates)},"closes":{{{rows}}}}};\n',
        encoding="utf-8")


def _selection(family, key):
    """
    Listes de la séance (la plus récente de chaque version ; vide avant 16 h 45) et premier prix de
    chaque titre de ces listes.
    """
    runs = [r for r in latest_per_session(load_runs(family)) if r["session_date"] == key]
    return runs, {item["symbol"]: Decimal(item["open_today"]) for r in runs for item in r["selection"]}


def _month_trend(daily, market_open, criteria, domains):
    """Tendance sur un mois par domaine à la clôture de la veille : connue dès l'ouverture, fixe pour la séance."""
    bubbles, unclassified = domain_trends(daily, market_open, criteria, domains)
    return {"bubbles": bubbles, "unclassified": unclassified}


def _next_open(alpaca, session_date):
    """Ouverture (UTC) de la séance qui suit session_date (calendrier Alpaca)."""
    later = [s for s in alpaca.sessions(session_date, session_date + timedelta(days=10)) if s[0] > session_date]
    day, open_time, _ = later[0]
    return datetime.combine(day, open_time, NEW_YORK).astimezone(timezone.utc)


def _settled(final):
    """Toutes les listes d'un état de fin de séance sont vendues (simulation « closed ») ou vides."""
    versions = ((final.get("portfolio") or {}).get("versions") or {}).values()
    return all(v.get("status") == "closed" or not v.get("n") for v in versions)


def _trade_times(strategy, market_open, market_close, runs=(), next_open=None):
    """
    (achat des repères, vente) d'une stratégie : achat à l'heure d'achat la plus tôt des listes de la séance
    (leurs critères enregistrés), à défaut celle des critères actuels de la stratégie (décision + 15 min) ;
    vente à l'heure de la stratégie (avant la clôture ou après l'ouverture).
    """
    minutes = min(c.decision_minutes for c in strategy.criteria().values())
    default = market_open + timedelta(minutes=minutes) + FEED_DELAY
    return (min((_entry_time(r, market_open) for r in runs), default=default),
            strategy.exit_time(market_open, market_close, next_open))


def _entry_time(run, market_open):
    """Heure d'achat d'une liste : sa décision (première heure, + confirmation éventuelle) + retard des données."""
    return market_open + timedelta(minutes=criteria_from_json(run["criteria"], run["run_id"]).decision_minutes) + FEED_DELAY


def _entry_times(strategy, market_open, runs=()):
    """
    Heures d'achat d'une stratégie pour la séance, de la plus tôt à la plus tard : celles des listes déjà
    produites (critères enregistrés dans chaque run) et celles de ses fichiers de critères (listes à venir).
    """
    minutes = {c.decision_minutes for c in strategy.criteria().values()}
    return sorted({market_open + timedelta(minutes=m) + FEED_DELAY for m in minutes}
                  | {_entry_time(r, market_open) for r in runs})


def _entry_bars(alpaca, key, stage, traded, entry_times, now):
    """
    Barres d'achat (TRADE_WINDOW minutes) à chaque heure d'achat dont la fenêtre est terminée et servie à now,
    lues une fois chacune (cache nommé par l'heure : partagé par les stratégies) puis réunies.
    """
    frames = [cached(f"{key}/{stage}_entry_at_{at.astimezone(NEW_YORK):%H%M}",
                     lambda: alpaca.bars(traded, "1Min", at, at + TRADE_WINDOW))
              for at in entry_times if now >= at + TRADE_WINDOW + FEED_DELAY]
    return pd.concat(frames, ignore_index=True) if frames else EMPTY_BARS


def _exit_bars(alpaca, key, stage, traded, exit_time):
    """Barres de vente : EXIT_WINDOW minutes jusqu'à exit_time, lues une fois (cache nommé par l'heure de vente)."""
    return cached(f"{key}/{stage}_exit_at_{exit_time.astimezone(NEW_YORK):%H%M}",
                  lambda: alpaca.bars(traded, "1Min", exit_time - EXIT_WINDOW, exit_time))


def _path_bars(alpaca, cache_key, symbols, windows):
    """Barres minute des titres des listes sur des fenêtres (début, fin) de séance régulière, lues une fois, réunies."""
    if not symbols:
        return EMPTY_BARS
    frames = [cached(f"{cache_key}_{start.astimezone(NEW_YORK):%Y%m%d%H%M}_{end.astimezone(NEW_YORK):%Y%m%d%H%M}",
                     lambda: alpaca.bars(sorted(symbols), "1Min", start, end)) for start, end in windows if end > start]
    return pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "timestamp"]) if frames else EMPTY_BARS


def _portfolio(runs, universe, entry_bars, exit_bars, trades, market_open, entry_time, exit_time, now, path_bars=None):
    """
    Simulation par version de la liste : achat à l'heure d'achat de la version, valeur en cours ou vente, vente
    anticipée d'un titre au stop ou à l'objectif (path_bars : trajet minute des titres des listes) ; repères
    (univers liquide à parts égales, SPY) achetés à entry_time, sans vente anticipée.
    """
    def run(symbols, at, path=None):
        return simulate(symbols, entry_bars, exit_bars, trades, at, exit_time, now, path_bars=path)

    return {
        "entry_time": entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "versions": {variant_of(r): {"run_id": r["run_id"], "entry_time": _entry_time(r, market_open).isoformat(),
                                     **run([i["symbol"] for i in r["selection"]], _entry_time(r, market_open),
                                           EMPTY_BARS if path_bars is None else path_bars)}
                     for r in runs},
        "benchmarks": {"univers": run(universe, entry_time), "spy": run([BENCHMARK], entry_time)},
    }


def _since_entry(runs, entry_bars, trades, market_open, market_close, now, portfolio=None):
    """
    Par version : variation de chaque titre de sa liste depuis l'achat de la simulation, dernier prix / prix
    d'achat - 1 (premier échange à partir de l'heure d'achat de la version). Un titre vendu plus tôt (stop ou
    objectif, portfolio) garde sa variation à la vente, marquée « early ». Vide tant que l'achat n'est pas connu.
    """
    result = {}
    for r in runs:
        prices = entry_prices(entry_bars, _entry_time(r, market_open), now)
        symbols = {i["symbol"] for i in r["selection"]}
        changes = changes_since_open({s: prices[s] for s in symbols if s in prices}, trades,
                                     market_open, market_close, now)
        early = (((portfolio or {}).get("versions") or {}).get(variant_of(r)) or {}).get("early_exits", {})
        for s, e in early.items():
            changes[s] = {"change": e["return"], "price": e["price"], "at": e["at"], "early": e["reason"]}
        result[variant_of(r)] = changes
    return result


def _order_plan(runs, prices, basis):
    """
    Ordres à passer sur la liste avec PER : nombre entier d'actions et prix, pour ORDER_PLAN_AMOUNT.
    basis « live » : dernier prix connu ; « entry » : premier échange à l'heure d'achat (séance passée).
    """
    run = next((r for r in runs if variant_of(r) == ORDER_PLAN_VARIANT), None)
    if run is None:
        return None
    names = {item["symbol"]: item["name"] for item in run["selection"]}
    plan = order_plan(list(names), prices, ORDER_PLAN_AMOUNT)
    for row in plan["rows"]:
        row["name"] = names[row["symbol"]]
    return {"run_id": run["run_id"], "variant": ORDER_PLAN_VARIANT, "amount": str(ORDER_PLAN_AMOUNT),
            "basis": basis, **plan}


def _state(storage, criteria, key, market_open, market_close, now, daily, domains, names, trades, minute, opening,
           runs, opens):
    """
    État affiché par le tableau de bord, calculé avec les seules données connues à now.
    opening : barres minute du début de séance, d'où le premier prix de chaque titre.
    """
    measures, liquid, values = live_domain_trends(daily, trades, minute, market_open, market_close, now,
                                                  criteria, domains)
    in_session = session_trades(trades, market_open, market_close, now)
    day_opens = session_open_prices(opening, market_open, now)
    return {
        "family": storage,
        "session_date": key,
        "observed_at": now.isoformat(),
        "prices_until": max(ts for ts, _ in in_session.values()).isoformat() if in_session else None,
        "feed": FEED,
        "universe": len(liquid),
        # Une ligne par titre de l'univers ; variation absente (None) si non calculable ;
        # price = dernier prix de la séance, open = premier prix de la séance (texte), pour le graphique.
        "stocks": {
            "columns": ["symbol", "name", "domain", *LIVE_MEASURES, "price", "open"],
            "rows": [[s, names.get(s, ""), domains.get(s),
                      *(None if s not in values[m] else round(values[m][s], 6) for m in LIVE_MEASURES),
                      str(in_session[s][1]) if s in in_session else None,
                      str(day_opens[s]) if s in day_opens else None]
                     for s in liquid],
        },
        "first_hour_minutes": criteria.first_hour_minutes,
        "sessions": {"two_days": criteria.up_days, "week": WEEK_SESSIONS, "month": criteria.month_sessions},
        "measures": measures,
        "selection": {"run_ids": [r["run_id"] for r in runs],
                      "changes": changes_since_open(opens, trades, market_open, market_close, now)},
        # Graphiques de la sélection : les month_sessions dernières clôtures ; avec le prix du jour, la
        # variation affichée sur le graphique est exactement celle de la colonne « 1 mois ».
        "charts": recent_closes(daily, market_open, opens, criteria.month_sessions),
    }


def is_definitive(now, market_close):
    """Un état de fin de séance n'est définitif que calculé au moins DEFINITIVE_AFTER après la clôture."""
    return now >= market_close + DEFINITIVE_AFTER


def finalize(strategy, alpaca, criteria, session_date, open_time, close_time, next_open=None):
    """
    État de fin de séance d'une stratégie, reconstitué depuis l'historique minute : dernier échange de chaque
    titre avant la clôture (l'enchère de clôture n'est pas comptée). Écrit research/experiments/final/<stockage>/.
    Provisoire s'il est calculé moins de DEFINITIVE_AFTER après la clôture ; l'état définitif relit
    les barres minute à neuf (cache distinct), pour intégrer les corrections d'Alpaca.
    criteria : critères de l'univers liquide (communs aux stratégies).
    Stratégie de nuit (vente la séance suivante, ouverture next_open) : tant que la vente n'est pas connue,
    la simulation reste « en cours », valorisée à la clôture ; refaite après la vente ; définitive 12 h après.
    """
    key = session_date.isoformat()
    market_open, market_close = _times(session_date, open_time, close_time)
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    git_sha = committed_git_sha()
    now = datetime.now(timezone.utc)
    if strategy.overnight and next_open is None:
        next_open = _next_open(alpaca, session_date)
    settle = max(market_close, strategy.exit_time(market_open, market_close, next_open))
    stage = "definitive" if is_definitive(now, settle) else "provisional"

    daily, symbols, domains, names = _prepare(alpaca, criteria, key, market_open)
    runs, opens = _selection(strategy.storage, key)
    # Les listes sont tirées de l'univers liquide : mêmes titres lus pour toutes les stratégies (caches partagés).
    tracked = sorted(set(symbols) | set(opens))
    minute = cached(f"{key}/{stage}_first_hour_bars", lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
    closing = cached(f"{key}/{stage}_closing_bars",
                     lambda: alpaca.bars(tracked, "1Min", market_close - CLOSING_WINDOW, market_close))
    trades = last_session_prices(closing, market_close)
    entry_time, exit_time = _trade_times(strategy, market_open, market_close, runs, next_open)
    traded = sorted(set(symbols) | set(opens) | {BENCHMARK})
    entry_bars = _entry_bars(alpaca, key, stage, traded, _entry_times(strategy, market_open, runs), market_close)
    # Vente connue seulement une fois servie (de nuit : le lendemain matin) ; sinon valeur à la clôture.
    sold = now >= exit_time + FEED_DELAY
    exit_bars = _exit_bars(alpaca, key, stage, traded, exit_time) if sold else EMPTY_BARS
    observed = exit_time if sold else market_close
    # Trajet minute des titres des listes pour les ventes anticipées : de l'achat à la vente (ou à la clôture),
    # plus, de nuit, de l'ouverture suivante à la vente une fois celle-ci connue.
    windows = [(min((_entry_time(r, market_open) for r in runs), default=entry_time), min(exit_time, market_close))]
    if strategy.overnight and sold:
        windows.append((next_open, exit_time))
    path_bars = _path_bars(alpaca, f"{key}/{stage}_path_{strategy.id}", set(opens), windows)

    state = _state(strategy.storage, criteria, key, market_open, market_close, market_close,
                   daily, domains, names, trades, minute, minute, runs, opens)
    state["portfolio"] = _portfolio(runs, symbols, entry_bars, exit_bars, trades, market_open, entry_time, exit_time,
                                    observed, path_bars)
    state["month_trend"] = _month_trend(daily, market_open, criteria, domains)
    state["order_plan"] = (_order_plan(runs, entry_prices(entry_bars, entry_time, market_close), "entry")
                           if strategy.is_main else None)
    state["selection"]["since_entry"] = _since_entry(runs, entry_bars, trades, market_open, market_close, market_close,
                                                     state["portfolio"])
    state.update(final=True, provisional=stage == "provisional", computed_at=now.isoformat(), git_sha=git_sha,
                 source="historique minute Alpaca (toutes bourses), dernière barre terminée à la clôture")
    path = FINALS_DIR / strategy.storage / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():  # archive avant remplacement
        previous = (SUPERSEDED_DIR / strategy.storage /
                    f"{key}_{json.loads(path.read_text(encoding='utf-8'))['computed_at']}.json")
        previous.parent.mkdir(parents=True, exist_ok=True)
        path.rename(previous)
    path.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    # Le dernier état affiché devient l'état final s'il porte sur cette séance ou une plus ancienne.
    live_path = live_file(strategy)
    live = json.loads(live_path.read_text(encoding="utf-8")) if live_path.exists() else None
    if live is None or live["session_date"] <= key:
        if strategy.is_main:
            _write_chart_data(daily, market_open, symbols, criteria, key)
        live_path.parent.mkdir(parents=True, exist_ok=True)
        live_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return path


def catch_up(family):
    """
    Pour chaque stratégie : produit l'état de fin de séance de chaque séance terminée qui n'en a pas ; refait
    l'état d'une stratégie de nuit dès que sa vente du lendemain est connue ; remplace par l'état définitif tout
    état provisoire DEFINITIVE_AFTER après la clôture (ou après la vente, de nuit). Depuis le premier run.
    """
    criteria = _criteria(family)
    alpaca = None
    now = datetime.now(timezone.utc)
    today = now.astimezone(NEW_YORK).date()
    done = []
    for strategy in strategies(family):
        runs = load_runs(strategy.storage)
        if not runs:
            continue
        alpaca = alpaca or AlpacaReader()
        first = datetime.fromisoformat(runs[0]["session_date"]).date()
        calendar = alpaca.sessions(first, today + timedelta(days=10))
        for i, (session_date, open_time, close_time) in enumerate(calendar):
            if session_date > today or i + 1 >= len(calendar):
                break
            market_open, market_close = _times(session_date, open_time, close_time)
            next_open = _times(*calendar[i + 1])[0]
            exit_time = strategy.exit_time(market_open, market_close, next_open)
            path = FINALS_DIR / strategy.storage / f"{session_date}.json"
            final = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            missing = final is None and now >= market_close + FEED_DELAY
            unsold = strategy.overnight and final is not None and not _settled(final) and now >= exit_time + FEED_DELAY
            provisional = final is not None and final.get("provisional", True) and is_definitive(now, max(market_close, exit_time))
            if missing or unsold or provisional:
                done.append(finalize(strategy, alpaca, criteria, session_date, open_time, close_time, next_open))
    if done:
        build(family)
    return done


def supplement(family):
    """
    Séances définitives dont l'état de fin de séance a été produit avant l'ajout des frais, des actions
    entières et des repères (13 et 14 octobre 2026) : simulation, ordres et colonne « Depuis l'achat »
    recalculés avec le code actuel, mêmes règles (achat à partir de 10 h 45, vente avant 15 h 30).
    Écrits à part dans final/<famille>/supplements/<date>.json : l'état définitif n'est jamais modifié.
    Statut diagnostic : calculé après lecture de la séance. Un complément existant n'est jamais réécrit.
    """
    criteria = _criteria(family)
    main = strategies(family)[0]
    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    done = []
    for path in sorted((FINALS_DIR / family).glob("*.json")):
        final = json.loads(path.read_text(encoding="utf-8"))
        target = FINALS_DIR / family / SUPPLEMENTS / path.name
        if final.get("provisional", True) or "net_mean_return" in json.dumps(final.get("portfolio")) or target.exists():
            continue
        session_date = datetime.fromisoformat(final["session_date"]).date()
        open_time, close_time = alpaca.session(session_date)
        key = session_date.isoformat()
        market_open, market_close = _times(session_date, open_time, close_time)
        daily, symbols, domains, names = _prepare(alpaca, criteria, key, market_open)
        runs, opens = _selection(family, key)
        entry_time, exit_time = _trade_times(main, market_open, market_close, runs)
        traded = sorted(set(symbols) | set(opens) | {BENCHMARK})
        entry_bars = _entry_bars(alpaca, key, "supplement", traded, _entry_times(main, market_open, runs), market_close)
        exit_bars = _exit_bars(alpaca, key, "supplement", traded, exit_time)
        closing = cached(f"{key}/supplement_closing_bars",
                         lambda: alpaca.bars(sorted(opens), "1Min", market_close - CLOSING_WINDOW, market_close))
        trades = last_session_prices(closing, market_close)
        payload = {
            "session_date": key,
            "status": "diagnostic",
            "reason": "état définitif produit avant l'ajout des frais, des actions entières et des repères ; "
                      "simulation recalculée après coup avec le code actuel",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": git_sha,
            "portfolio": _portfolio(runs, symbols, entry_bars, exit_bars, trades, market_open, entry_time, exit_time,
                                    market_close),
            "order_plan": _order_plan(runs, entry_prices(entry_bars, entry_time, market_close), "entry"),
            "since_entry": _since_entry(runs, entry_bars, trades, market_open, market_close, market_close),
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        done.append(target)
    if done:
        build(family)
    return done


def _missing_lists(every, key, market_open, now):
    """Vrai si une liste de la séance est prête (décision + retard des données) mais pas encore produite."""
    for strategy in every:
        done = {variant_of(r) for r in load_runs(strategy.storage) if r["session_date"] == key}
        for variant, criteria in strategy.criteria().items():
            ready = market_open + timedelta(minutes=criteria.decision_minutes) + FEED_DELAY
            if now >= ready and variant not in done:
                return True
    return False


def _single_instance():
    """Verrou tenu tant que le processus vit : un seul suivi à la fois. None si un autre tourne déjà."""
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = open(LIVE_FILE.parent / "tracker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def run(family):
    lock = _single_instance()
    if lock is None:
        print("Le suivi en direct tourne déjà : rien à faire.")
        return 0
    criteria = _criteria(family)
    every = strategies(family)
    alpaca = AlpacaReader()
    session_date = datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    key = session_date.isoformat()
    session = alpaca.session(session_date)
    if session is None:
        print(f"Marché fermé le {key} (calendrier Alpaca).")
        return 0
    market_open, market_close = _times(session_date, *session)
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    # Avec 15 min de retard, les derniers échanges de la séance arrivent jusqu'à clôture + 15 min.
    stop_at = market_close + FEED_DELAY

    print("Préparation : univers liquide et domaines (quelques minutes la première fois)…")
    daily, symbols, domains, names = _prepare(alpaca, criteria, key, market_open)
    _write_chart_data(daily, market_open, symbols, criteria, key)
    month_trend = _month_trend(daily, market_open, criteria, domains)
    minute = EMPTY_BARS
    opening = EMPTY_BARS
    # Prix d'achat et de vente de tous les titres liquides et du SPY (les listes en font partie), lus une fois
    # par heure d'achat et par heure de vente, partagés par les stratégies qui ont la même heure.
    traded = sorted(set(symbols) | {BENCHMARK})
    next_open = _next_open(alpaca, session_date)
    plans = {s.id: _trade_times(s, market_open, market_close, next_open=next_open) for s in every}
    # Ventes de nuit de la veille, ce matin : l'état de la veille est refait dès qu'elles sont servies.
    overnight_sales = sorted({market_open + timedelta(minutes=max(s.exit_next_open_minutes, 1)) + FEED_DELAY
                              for s in every if s.overnight})
    entry_times = sorted({at for s in every for at in _entry_times(s, market_open)})
    exits = {}
    path_frames, path_symbols, path_until = [], set(), None

    while True:
        now = datetime.now(timezone.utc)
        if now >= stop_at:
            print("Clôture passée : états de fin de séance reconstitués depuis l'historique minute…")
            for path in catch_up(family):
                print(f"État de fin de séance : {path}")
            return 0
        if now < market_open + FEED_DELAY:
            print(f"En attente des premiers prix (à {(market_open + FEED_DELAY).astimezone(NEW_YORK):%H:%M}, New York).")
            time.sleep(REFRESH_S)
            continue
        # Listes prêtes et pas encore produites : le suivi les produit lui-même (une liste « ouverture » sort à
        # 9 h 30, avant la tâche planifiée). La tâche planifiée commite et envoie l'historique ensuite.
        if _missing_lists(every, key, market_open, now):
            try:
                screener.run(wait=False)
            except (FetchError, TraceError, ValueError) as e:
                print(f"{now.astimezone(NEW_YORK):%H:%M} — listes non produites, nouvel essai dans {REFRESH_S} s : {e}")
        while overnight_sales and now >= overnight_sales[0]:
            overnight_sales.pop(0)
            try:
                for path in catch_up(family):
                    print(f"{now.astimezone(NEW_YORK):%H:%M} — vente de nuit connue, état refait : {path}")
            except (FetchError, TraceError, ValueError) as e:
                print(f"{now.astimezone(NEW_YORK):%H:%M} — état de la veille non refait : {e}")
        selections = {s.id: _selection(s.storage, key) for s in every}
        opens_all = {sym for _, opens in selections.values() for sym in opens}
        try:
            if minute.empty and now >= first_hour_end + FEED_DELAY:
                minute = cached(f"{key}/live_first_hour_bars",
                                lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
            if opening.empty and now >= market_open + OPENING_WINDOW + FEED_DELAY:
                opening = cached(f"{key}/opening_bars",
                                 lambda: alpaca.bars(symbols, "1Min", market_open, market_open + OPENING_WINDOW))
            entry_bars = _entry_bars(alpaca, key, "live", traded, entry_times, now)
            for _, exit_time in plans.values():
                if exit_time not in exits and now >= exit_time + FEED_DELAY:
                    exits[exit_time] = _exit_bars(alpaca, key, "live", traded, exit_time)
            trades = alpaca.latest_trades(sorted(set(traded) | opens_all), FEED)
            # Trajet minute des titres des listes (ventes anticipées) : nouveaux titres depuis le premier achat,
            # puis, pour tous, les minutes servies depuis la lecture précédente.
            served = (now - FEED_DELAY).replace(second=0, microsecond=0)
            first_entry = min(entry_times)
            new = opens_all - path_symbols
            if new and served > first_entry:
                path_frames.append(alpaca.bars(sorted(new), "1Min", first_entry, served))
                path_symbols |= new
                path_until = path_until or served
            if path_symbols and path_until and served > path_until:
                path_frames.append(alpaca.bars(sorted(path_symbols), "1Min", path_until, served))
                path_until = served
            path_bars = (pd.concat(path_frames, ignore_index=True).drop_duplicates(["symbol", "timestamp"])
                         if path_frames else EMPTY_BARS)
        except FetchError as e:
            print(f"{now.astimezone(NEW_YORK):%H:%M} — lecture impossible, nouvel essai dans {REFRESH_S} s : {e}")
            time.sleep(REFRESH_S)
            continue

        last_prices = {s: price for s, (_, price) in session_trades(trades, market_open, market_close, now).items()}
        for strategy in every:
            today_runs, opens = selections[strategy.id]
            entry_time, exit_time = _trade_times(strategy, market_open, market_close, today_runs, next_open)
            # Premier prix de chaque titre : la première heure entière dès qu'elle est lue, sinon les 5 premières minutes.
            state = _state(strategy.storage, criteria, key, market_open, market_close, now, daily, domains, names,
                           trades, minute, minute if not minute.empty else opening, today_runs, opens)
            state["portfolio"] = _portfolio(today_runs, symbols, entry_bars, exits.get(exit_time, EMPTY_BARS), trades,
                                            market_open, entry_time, exit_time, now, path_bars)
            state["month_trend"] = month_trend
            state["order_plan"] = _order_plan(today_runs, last_prices, "live") if strategy.is_main else None
            state["selection"]["since_entry"] = _since_entry(today_runs, entry_bars, trades, market_open, market_close, now,
                                                             state["portfolio"])
            path = live_file(strategy)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        build(family)
        day = state["measures"]["day"]["bubbles"]
        up = sum(1 for b in day if b["mean_return"] > 0)
        print(f"{now.astimezone(NEW_YORK):%H:%M} (New York) — journée : "
              f"{up} domaines en hausse, {len(day) - up} en baisse · {len(every)} stratégies suivies")
        time.sleep(REFRESH_S)


def main(command=run):
    if len(sys.argv) != 2:
        sys.exit(f"Usage : python -m {sys.argv[0]} <famille>")
    try:
        return command(sys.argv[1])
    except (FetchError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSuivi arrêté.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
