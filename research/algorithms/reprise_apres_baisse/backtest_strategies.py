"""
Tests sur le passé des 10 stratégies (diagnostic) : rejoue chaque séance d'une période avec les fonctions des
listes quotidiennes (core/screener, core/opening, core/closing) et de la simulation (core/portfolio), aux heures
d'achat et de vente de chaque stratégie, stop −1,5 % / objectif +3 % compris (règle 8 : un seul module de logique).

La période est rejouée une fois, séance par séance, pour toutes les stratégies (données partagées) ; chaque test
(un mois, six mois, une année) en est une tranche : une séance donne le même résultat dans toutes les tranches.

Heures (New York) : achat au premier échange 15 min après la décision (retard des données, comme en direct),
vente à l'heure de la stratégie (avant la clôture, après l'ouverture, ou la séance suivante pour les achats de
nuit) ; vente plus tôt au stop ou à l'objectif, vérifiés sur chaque minute entre l'achat et la vente.

Lectures réduites sans changer les listes : une liste « fin de journée » ne garde que les titres en hausse de
0,5 % à 4 % sur la journée ; ce filtre est d'abord appliqué sur les minutes d'ouverture et celles d'avant la
décision, puis toute la séance n'est lue que pour les titres qui le passent. Une liste « ouverture » ne garde que
les titres en hausse dans la dernière heure de la veille ; la nuit n'est lue que pour eux.

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest_strategies
    .venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest_strategies --year 2024 --only nuit_marche_tient,...

Stratégie gardée plusieurs séances (achats qui se chevauchent) : le capital est partagé en autant de tranches que de
séances de garde ; le rendement d'une séance d'achat compte pour une tranche dans les cumuls (« capital_slices »).
"""

import argparse
import hashlib
import json
import sys
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from core.closing import ClosingCriteria, screen_closing
from core.swing import SwingCriteria, screen_swing
from core.switch import SwitchCriteria, choose
from core.opening import OpeningCriteria, screen_opening
from core.performance_metrics import summary
from core.portfolio import simulate
from core.screener import Criteria, daily_candidates, liquid_universe, screen
from core.universe import eligible_symbols
from infra import nasdaq_symbols
from infra.alpaca_api import BAR_COLUMNS, AlpacaReader
from infra.cache import cached, read_cached
from infra.http import FetchError
from infra.trace import RUNS_DIR, TraceError, committed_git_sha
from research.algorithms.reprise_apres_baisse.backtest import BIASES, TESTED_AMOUNTS
from research.algorithms.reprise_apres_baisse.run import (DAILY_HISTORY, FAMILY, NEW_YORK, SIP_DELAY, STRATEGIES,
                                                          earnings)
from core.strategy import MAX_HOLD_SESSIONS

BENCHMARK = "SPY"
SUITE = "tests_2025"   # nom de la série de tests affichée dans l'onglet « Tests » (toutes années)
# Une passe sur 2025, puis trois tests : le mois le plus baissier du S&P 500 (mars, −5,6 %), six mois, l'année.
YEAR = (date(2025, 1, 1), date(2025, 12, 31))
TESTS = [
    {"label": "mars_2025", "start": date(2025, 3, 1), "end": date(2025, 3, 31),
     "spy_month": "−5,57 % (mois le plus baissier de 2025 pour SPY, clôture à clôture)"},
    {"label": "janvier_juin_2025", "start": date(2025, 1, 1), "end": date(2025, 6, 30)},
    {"label": "annee_2025", "start": date(2025, 1, 1), "end": date(2025, 12, 31)},
]
TRADE_WINDOW = timedelta(minutes=5)
EXIT_WINDOW = timedelta(minutes=30)
FIRST_WINDOW = timedelta(minutes=15)   # minutes d'ouverture lues pour le premier prix (préfiltre « fin de journée »)
# Change quand le calcul change : les séances déjà rejouées (cache) sont alors refaites.
VERSION = 2   # 2 : variante « stop seul » et titres de chaque liste enregistrés
WORKERS = 5
# Les 10 premières stratégies gardent leur clé de cache d'origine (critères seuls) : leurs séances déjà rejouées
# servent encore (mêmes heures, même stop et même objectif qu'alors).
OLD_KEYS = {"principale", "vente_cloture", "achat_10h30", "achat_10h30_vente_cloture", "ouverture_1h", "ouverture_2h",
            "nuit_15h_ouverture", "nuit_15h_10h30", "nuit_15h55_ouverture", "nuit_15h55_10h30"}
EXTRA_BIASES = [
    "Liste « fin de journée » : un titre sans échange dans les 15 premières minutes, ou dans les 15 minutes avant "
    "la décision, est écarté (en direct il serait jugé sur ses premiers et derniers échanges) — rare pour des "
    "titres liquides.",
]


def _key(*parts):
    return "/".join(["backtest_strategies", *map(str, parts)])


def _symbols_hash(symbols):
    return hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()[:12]


def _utc(day, at):
    return datetime.combine(day, at, NEW_YORK).astimezone(timezone.utc)


def _bars(alpaca, key, symbols, start, end):
    """Barres minute de symbols entre start et end, lues une fois (cache nommé par la liste de titres)."""
    if not symbols or end <= start:
        return pd.DataFrame(columns=BAR_COLUMNS)
    return cached(f"{key}_{_symbols_hash(symbols)}", lambda: alpaca.bars(sorted(symbols), "1Min", start, end))


def _concat(frames):
    frames = [f for f in frames if not f.empty]
    return (pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "timestamp"]) if frames
            else pd.DataFrame(columns=BAR_COLUMNS))


def _kind(criteria_by_variant):
    return type(next(iter(criteria_by_variant.values())))


def _lists_for_day(alpaca, daily, market_daily, day, market_open, previous_close, strategies):
    """Listes des stratégies pour la séance : {stratégie: {version: [symboles]}}, et la décision de chacune."""
    lists, decisions = {}, {}
    pe = earnings(alpaca, "backtest")
    memo = {}

    def liquid(decision, c):
        key = ("liquid", decision, c.required_sessions, c.liquidity_sessions, c.min_price_usd, c.min_avg_dollar_volume_usd)
        if key not in memo:
            memo[key] = [s.symbol for s in liquid_universe(daily, decision, c)[0]]
        return memo[key]

    def candidates(cut, c):
        key = ("candidates", cut, json.dumps({k: v for k, v in c.to_json().items() if k not in ("max_pe", "version")},
                                             sort_keys=True, default=str))
        if key not in memo:
            memo[key] = {x.symbol for x in daily_candidates(daily, cut, c)[0]}
        return memo[key]

    def market_minute(decision):
        """Barres minute de SPY de l'ouverture à la décision (règles « marché qui tient / qui remonte »)."""
        return _bars(alpaca, _key(day, f"spy_minute_{decision.astimezone(NEW_YORK):%H%M}"), [BENCHMARK], market_open, decision)

    def closing_list(c, decision):
        """Liste « fin de journée » : préfiltre « journée en hausse », puis toute la séance des titres qui le passent."""
        symbols = liquid(decision, c)
        first = _bars(alpaca, _key(day, "ouverture_15min"), symbols, market_open, market_open + FIRST_WINDOW)
        late = _bars(alpaca, _key(day, f"avant_{decision.astimezone(NEW_YORK):%H%M}"), symbols,
                     decision - FIRST_WINDOW, decision)
        opens = {s: b["open"].iloc[0] for s, b in first.sort_values("timestamp").groupby("symbol")}
        prices = {s: b["close"].iloc[-1] for s, b in late.sort_values("timestamp").groupby("symbol")}
        rising = [s for s in opens if s in prices and c.min_day_gain <= prices[s] / opens[s] - 1 <= c.max_day_gain]
        session = _bars(alpaca, _key(day, f"seance_{decision.astimezone(NEW_YORK):%H%M}"), rising, market_open, decision)
        needs_market = c.market_min_day_return is not None or c.market_min_last_hour_return is not None
        fear = (_bars(alpaca, _key(day, f"peur_{c.fear_symbol}_{decision.astimezone(NEW_YORK):%H%M}"), [c.fear_symbol],
                      market_open, decision) if c.market_max_fear_move is not None else None)
        selection, _ = screen_closing(daily, session, market_open, decision, c, earnings_for=pe, market_daily=market_daily,
                                      market_minute=market_minute(decision) if needs_market else None, fear_minute=fear)
        return [i["symbol"] for i in selection]

    kinds = {s.id: s.criteria() for s in strategies}

    # « Reprise après baisse » : candidats quotidiens, puis minutes de 9 h 30 jusqu'à la décision la plus tardive.
    rebound = {sid: c for sid, c in kinds.items() if _kind(c) is Criteria}
    if rebound:
        last = max(c.decision_minutes for cs in rebound.values() for c in cs.values())
        wanted = set()
        for cs in rebound.values():
            for c in cs.values():
                cut = market_open + timedelta(minutes=c.first_hour_minutes)
                wanted |= candidates(cut, c)
        minute = _bars(alpaca, _key(day, f"rebound_0930_{last}"), wanted, market_open,
                       market_open + timedelta(minutes=last))
        for sid, cs in rebound.items():
            for variant, c in cs.items():
                decision = market_open + timedelta(minutes=c.decision_minutes)
                selection, _ = screen(daily, minute, market_open, decision, c, earnings_for=pe, market_daily=market_daily)
                lists.setdefault(sid, {})[variant] = [i["symbol"] for i in selection]
                decisions.setdefault(sid, {})[variant] = decision

    for sid, cs in kinds.items():
        kind = _kind(cs)
        for variant, c in cs.items():
            if kind is OpeningCriteria:
                # Dernière heure de la veille de tous les titres liquides, puis la nuit des seuls titres en hausse.
                decision = market_open + timedelta(minutes=c.decision_minutes)
                symbols = liquid(decision, c)
                start = previous_close - timedelta(minutes=c.last_hour_minutes)
                hour = _bars(alpaca, _key(day, f"veille_derniere_heure_{c.last_hour_minutes}"), symbols, start, previous_close)
                rising = [s for s, b in hour.sort_values("timestamp").groupby("symbol")
                          if b["close"].iloc[-1] > b["open"].iloc[0]]
                night = _bars(alpaca, _key(day, f"nuit_{decision.astimezone(NEW_YORK):%H%M}"), rising, previous_close, decision)
                selection, _ = screen_opening(daily, _concat([hour, night]), market_open, previous_close, decision, c,
                                              earnings_for=pe, market_daily=market_daily)
                chosen = [i["symbol"] for i in selection]
            elif kind is ClosingCriteria:
                decision = market_open + timedelta(minutes=c.decision_minutes)
                chosen = closing_list(c, decision)
            elif kind is SwitchCriteria:
                # Première liste si le marché tient à la première décision (barres terminées à elle), sinon la seconde.
                first_decision = market_open + timedelta(minutes=c.first.decision_minutes)
                keep_first = choose(c, market_minute(first_decision), market_open, first_decision)
                picked = c.first if keep_first else c.second
                decision = market_open + timedelta(minutes=picked.decision_minutes)
                chosen = closing_list(picked, decision)
            elif kind is SwingCriteria:
                # Dernier prix des titres liquides avant la décision (15 dernières minutes).
                decision = market_open + timedelta(minutes=c.decision_minutes)
                symbols = liquid(decision, c)
                late = _bars(alpaca, _key(day, f"avant_{decision.astimezone(NEW_YORK):%H%M}"), symbols,
                             decision - FIRST_WINDOW, decision)
                selection, _ = screen_swing(daily, late, market_open, decision, c, earnings_for=pe, market_daily=market_daily,
                                            market_minute=market_minute(decision) if c.market_min_day_return is not None else None)
                chosen = [i["symbol"] for i in selection]
            else:
                continue
            lists.setdefault(sid, {})[variant] = chosen
            decisions.setdefault(sid, {})[variant] = decision
    return lists, decisions


def _results_for_day(alpaca, lists, decisions, day, market_open, market_close, later, strategies, fetch_lists=None):
    """
    Simulation de chaque liste et du repère SPY aux heures de chaque stratégie : {stratégie: enregistrement}.
    later : (ouverture, clôture) des séances suivantes (vente une ou plusieurs séances plus tard).
    fetch_lists : listes complètes dont les barres sont lues (mêmes fichiers de cache que le test d'origine) quand
    lists n'en garde qu'une partie (les premiers titres de chaque liste, --top).
    """
    records = {}
    now = datetime.now(timezone.utc)
    for strategy in strategies:
        sale_session = later[strategy.sale_offset - 1] if strategy.overnight else None
        exit_time = strategy.exit_time(market_open, market_close, sale_session)
        # Vente pas encore faite (ou pas encore servie) : la séance ne compte pas pour cette stratégie.
        if exit_time + SIP_DELAY > now:
            records[strategy.id] = {"date": day.isoformat(), "unsold": True}
            continue
        entries = {v: d + SIP_DELAY for v, d in decisions[strategy.id].items()}
        entries["spy"] = min(entries.values())
        picked = {s for symbols in (fetch_lists or lists)[strategy.id].values() for s in symbols}
        traded = picked | {BENCHMARK}
        tag = f"{strategy.id}"
        entry_bars = _concat([_bars(alpaca, _key(day, f"achat_{tag}_{at.astimezone(NEW_YORK):%H%M}"), traded, at,
                                    at + TRADE_WINDOW) for at in sorted(set(entries.values()))])
        exit_bars = _bars(alpaca, _key(day, f"vente_{tag}_{exit_time.astimezone(NEW_YORK):%Y%m%d_%H%M}"), traded,
                          exit_time - EXIT_WINDOW, exit_time)
        # Trajet minute de l'achat à la vente (séances régulières seulement : la fin de séance du jour, puis chaque
        # séance suivante jusqu'à la vente), comme le suivi en direct.
        start = min(entries.values())
        windows = [(start, min(exit_time, market_close))]
        for open_at, close_at in later[:strategy.sale_offset]:
            windows.append((open_at, min(close_at, exit_time)))
        path = _concat([_bars(alpaca, _key(day, f"trajet_{tag}_{a.astimezone(NEW_YORK):%Y%m%d%H%M}"), picked, a, b)
                        for a, b in windows if b > a])
        after = exit_time + timedelta(days=1)
        limits = {"stop_loss": strategy.stop_loss, "take_profit": strategy.take_profit}
        record = {"date": day.isoformat()}
        for name, symbols in {**lists[strategy.id], "spy": [BENCHMARK]}.items():
            result = simulate(symbols, entry_bars, exit_bars, {}, entries[name], exit_time, after,
                              amounts=TESTED_AMOUNTS, path_bars=None if name == "spy" else path,
                              **({} if name == "spy" else limits))
            empty = not symbols
            record[name] = 0.0 if empty else result.get("net_mean_return")
            record[f"{name}_n"] = len(symbols)
            record[f"{name}_gross"] = 0.0 if empty else result.get("mean_return")
            record[f"{name}_whole_gains"] = {} if empty else result.get("whole_gains", {})
            record[f"{name}_hold"] = 0.0 if empty else result.get("hold_net_mean_return", result.get("net_mean_return"))
            record[f"{name}_early"] = {} if empty else {s: e["reason"] for s, e in result.get("early_exits", {}).items()}
            record[f"{name}_symbols"] = list(symbols)
            # Variante « stop seul » : vente au stop, pas d'objectif (le titre reste jusqu'à l'heure de vente).
            if name != "spy":
                stop_only = {} if empty else simulate(symbols, entry_bars, exit_bars, {}, entries[name], exit_time, after,
                                                      amounts=TESTED_AMOUNTS, path_bars=path,
                                                      stop_loss=strategy.stop_loss, take_profit=None)
                record[f"{name}_stop_only"] = 0.0 if empty else stop_only.get("net_mean_return")
        records[strategy.id] = record
    return records


_CONTEXT = {}


def _init(daily_key, spy_key, sessions, criteria_hash, only):
    """Au démarrage de chaque processus : cours quotidiens relus du cache disque, lecteur Alpaca propre."""
    _share_rate_limit()
    _CONTEXT.update(daily=read_cached(daily_key), market_daily=read_cached(spy_key), sessions=sessions,
                    criteria_hash=criteria_hash, alpaca=AlpacaReader(),
                    strategies=[s for s in STRATEGIES if only is None or s.id in only])


def _one_day(i):
    """Résultats de toutes les stratégies pour la séance d'indice i (dans un processus du pool)."""
    alpaca, sessions = _CONTEXT["alpaca"], _CONTEXT["sessions"]
    day, open_at, close_at = sessions[i]
    market_open, market_close = _utc(day, open_at), _utc(day, close_at)
    previous_close = _utc(sessions[i - 1][0], sessions[i - 1][2])
    later = [(_utc(d, o), _utc(d, c)) for d, o, c in sessions[i + 1:i + 1 + MAX_HOLD_SESSIONS]]
    strategies = _CONTEXT["strategies"]

    def compute():
        # Seulement l'historique utile à cette séance (plus rapide ; chaque règle retronque à sa décision).
        def window(bars):
            return bars[(bars["timestamp"] >= market_open - DAILY_HISTORY) & (bars["timestamp"] < market_close)]
        lists, decisions = _lists_for_day(alpaca, window(_CONTEXT["daily"]), window(_CONTEXT["market_daily"]), day,
                                          market_open, previous_close, strategies)
        return _results_for_day(alpaca, lists, decisions, day, market_open, market_close, later, strategies)

    # Une vente encore à venir : résultat recalculé au prochain lancement (pas de cache définitif).
    pending = later[MAX_HOLD_SESSIONS - 1][1] + SIP_DELAY > datetime.now(timezone.utc) if len(later) == MAX_HOLD_SESSIONS else True
    suffix = f"_partiel_{datetime.now(timezone.utc):%Y%m%d%H%M}" if pending else ""
    return day, cached(_key(day, f"resultats_v{VERSION}_{_CONTEXT['criteria_hash']}{suffix}"), compute)


def run(year=None, only=None, first=None, last=None):
    """
    Rejoue l'année (2025 par défaut, avec ses trois tranches), ou les séances du first au last, pour toutes les
    stratégies ou celles de only.
    """
    if first is not None:
        period, tests = (first, last), [{"label": f"periode_{first:%Y%m%d}_{last:%Y%m%d}", "start": first, "end": last}]
    else:
        period, tests = (YEAR, TESTS) if year is None else (
            (date(year, 1, 1), date(year, 12, 31)),
            [{"label": f"janvier_juin_{year}", "start": date(year, 1, 1), "end": date(year, 6, 30)},
             {"label": f"annee_{year}", "start": date(year, 1, 1), "end": date(year, 12, 31)}])
    chosen = [s for s in STRATEGIES if only is None or s.id in only]
    if not chosen:
        raise ValueError(f"Aucune stratégie parmi {only}")
    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    # Clé des résultats par séance : critères ET heures de vente, stop et objectif de chaque stratégie retenue.
    criteria_hash = hashlib.sha1(json.dumps({s.id: {"criteria": {v: c.to_json() for v, c in s.criteria().items()},
                                                    "exit": [s.sale_offset, s.exit_before_close_minutes,
                                                             s.exit_after_open_minutes, s.exit_next_open_minutes,
                                                             str(s.stop_loss), str(s.take_profit)]}
                                             if s.id not in OLD_KEYS else {v: c.to_json() for v, c in s.criteria().items()}
                                             for s in chosen}, sort_keys=True, default=str).encode()).hexdigest()[:10]
    sessions = alpaca.sessions(period[0] - timedelta(days=10), period[1] + timedelta(days=20))
    days = [i for i, s in enumerate(sessions) if period[0] <= s[0] <= period[1]]
    print(f"{len(days)} séances du {sessions[days[0]][0]} au {sessions[days[-1]][0]} · {len(chosen)} stratégies.")

    today = datetime.now(timezone.utc).astimezone(NEW_YORK).date()
    listings, _ = cached(f"{today}/nasdaq_listings", nasdaq_symbols.listings)
    assets = cached(f"{today}/alpaca_assets", alpaca.assets)
    symbols, _ = eligible_symbols(assets, listings)
    first_open = _utc(*sessions[days[0]][:2])
    last_close = min(_utc(sessions[days[-1] + MAX_HOLD_SESSIONS][0], sessions[days[-1] + MAX_HOLD_SESSIONS][2]),
                     datetime.now(timezone.utc) - SIP_DELAY - timedelta(minutes=5))   # offre gratuite : rien des 15 dernières minutes
    print("Lecture des cours quotidiens (une fois)…")
    daily_key = _key(f"daily_bars_{first_open:%Y%m%d}_{last_close:%Y%m%d}")
    spy_key = _key(f"spy_daily_{first_open:%Y%m%d}_{last_close:%Y%m%d}")
    cached(daily_key, lambda: alpaca.bars(symbols, "1Day", first_open - DAILY_HISTORY, last_close))
    cached(spy_key, lambda: alpaca.bars([BENCHMARK], "1Day", first_open - DAILY_HISTORY, last_close))

    # Divisions d'actions lues une fois avant les fils (cache partagé).
    earnings(alpaca, "backtest")([])

    # Plusieurs séances en parallèle, dans des processus séparés (le calcul occupe un cœur chacun) qui héritent des
    # cours quotidiens déjà lus ; chaque séance a ses propres fichiers de cache.
    results = {}
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=multiprocessing.get_context("spawn"), initializer=_init,
                             initargs=(daily_key, spy_key, sessions, criteria_hash, only)) as pool:
        for n, (day, records) in enumerate(pool.map(_one_day, days), start=1):
            results[day] = records
            print(f"  [{n}/{len(days)}] {day} : " + " · ".join(
                f"{sid} {r['per12_n']}/{r['sans_per_n']} {_pct(r['per12'])}" if not r.get("unsold") else f"{sid} pas encore vendu"
                for sid, r in records.items()), flush=True)
    by_strategy = {s.id: [results[day][s.id] for day in sorted(results)] for s in chosen}

    written = []
    for strategy in chosen:
        written += _write_tests(strategy, by_strategy[strategy.id], tests, git_sha)
    print(f"{len(written)} résultats écrits.")
    return 0


def _write_tests(strategy, all_rows, tests, git_sha, top=None):
    """Un fichier de résultats par tranche (test) ; top : seuls les `top` premiers titres de chaque liste."""
    written = []
    folder = RUNS_DIR / strategy.storage / "backtests"
    # Achats qui se chevauchent (garde de plusieurs séances) : une tranche du capital par séance d'achat.
    slices = max(strategy.sale_offset, 1) if strategy.exit_after_sessions else 1
    for test in tests:
        rows = [r for r in all_rows if test["start"].isoformat() <= r["date"] <= test["end"].isoformat()
                and not r.get("unsold")]
        if not rows:
            print(f"{strategy.id:26} {test['label']:18} aucune séance vendue")
            continue
        names = [*strategy.criteria(), "spy"]
        series = {name: {r["date"]: r[name] / slices for r in rows if r[name] is not None} for name in names}
        holds = {f"{name}_sans_regle": {r["date"]: r[f"{name}_hold"] / slices for r in rows
                                         if r[f"{name}_hold"] is not None}
                 for name in strategy.criteria()}
        holds.update({f"{name}_stop_seul": {r["date"]: r[f"{name}_stop_only"] / slices for r in rows
                                             if r.get(f"{name}_stop_only") is not None}
                      for name in strategy.criteria()})
        numbers = [int(p.name[1:]) for p in folder.glob("b[0-9][0-9][0-9]") if p.name[1:].isdigit()]
        payload = {
            "backtest_id": f"b{max(numbers, default=0) + 1:03d}",
            "family": FAMILY, "strategy": strategy.id, "suite": SUITE,
            "label": test["label"] + ("" if top is None else f"_top{top}"), "top": top,
            "status": "diagnostic",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": git_sha,
            "period": {"start": rows[0]["date"], "end": rows[-1]["date"], "sessions": len(rows), "months": None},
            "spy_month": test.get("spy_month"),
            "capital_slices": slices,
            "rules": {"entry": "premier échange 15 min après la décision de chaque liste (New York)",
                      "exit": f"heure de vente de la stratégie {strategy.id}, "
                              + ("pas de stop" if strategy.stop_loss is None else f"stop −{strategy.stop_loss * 100} %") + " / "
                              + ("pas d'objectif" if strategy.take_profit is None else f"objectif +{strategy.take_profit * 100} %"),
                      "cost_bps_per_order": "5", "split": "parts égales, fractions d'action"},
            "criteria": {v: c.to_json() for v, c in strategy.criteria().items()},
            "biases": BIASES + EXTRA_BIASES,
            "summaries": {name: summary(values) for name, values in {**series, **holds}.items()},
            "days": rows,
        }
        path = folder / payload["backtest_id"] / "results.json"
        path.parent.mkdir(parents=True, exist_ok=False)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        written.append(path)
        s = payload["summaries"]
        print(f"{strategy.id:26} {payload['label']:24} " + "  ".join(
            f"{name} {_pct(s[name].get('total'))}" for name in ("per12", "sans_per", "spy") if s.get(name, {}).get("n")))
    return written


BASE_TESTS = {"annee_2025": TESTS,
              "annee_2024": [{"label": "janvier_juin_2024", "start": date(2024, 1, 1), "end": date(2024, 6, 30)},
                             {"label": "annee_2024", "start": date(2024, 1, 1), "end": date(2024, 12, 31)}],
              "periode_20261012_20261016": [{"label": "periode_20261012_20261016", "start": date(2026, 10, 12),
                                             "end": date(2026, 10, 16)}],
              **{f"annee_{y}": [{"label": f"janvier_juin_{y}", "start": date(y, 1, 1), "end": date(y, 6, 30)},
                                {"label": f"annee_{y}", "start": date(y, 1, 1), "end": date(y, 12, 31)}]
                 for y in (2021, 2022, 2023)}}


def decisions_for(alpaca, criteria, day, market_open):
    """Heure de décision de chaque liste ce jour-là (bascule : selon le marché à la première décision, barres en cache)."""
    decisions = {}
    for variant, c in criteria.items():
        if isinstance(c, SwitchCriteria):
            first_decision = market_open + timedelta(minutes=c.first.decision_minutes)
            spy = _bars(alpaca, _key(day, f"spy_minute_{first_decision.astimezone(NEW_YORK):%H%M}"), [BENCHMARK],
                        market_open, first_decision)
            c = c.first if choose(c, spy, market_open, first_decision) else c.second
        decisions[variant] = market_open + timedelta(minutes=c.decision_minutes)
    return decisions


def _share_rate_limit():
    """Les processus du pool se partagent la limite d'Alpaca (~200 requêtes par minute) : chacun va WORKERS fois moins vite."""
    from infra import alpaca_api
    alpaca_api.MIN_INTERVAL_S = alpaca_api.MIN_INTERVAL_S * WORKERS


def _init_top(top):
    _share_rate_limit()
    _CONTEXT.update(alpaca=AlpacaReader(), top=top, by_id={s.id: s for s in STRATEGIES})


def _top_job(job):
    """
    Rejoue un test déjà fait en ne gardant que les `top` premiers titres de chaque liste (ordre de la liste,
    connu à la décision) : mêmes listes, mêmes heures, mêmes barres (cache du test d'origine).
    """
    sid, path = job
    strategy, top, alpaca = _CONTEXT["by_id"][sid], _CONTEXT["top"], _CONTEXT["alpaca"]
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    dates = [date.fromisoformat(r["date"]) for r in result["days"]]
    sessions = alpaca.sessions(dates[0] - timedelta(days=10), dates[-1] + timedelta(days=20))
    index = {s[0]: i for i, s in enumerate(sessions)}
    criteria = strategy.criteria()
    rows = []
    for row in result["days"]:
        day = date.fromisoformat(row["date"])
        i = index[day]
        market_open, market_close = _utc(day, sessions[i][1]), _utc(day, sessions[i][2])
        later = [(_utc(d, o), _utc(d, c)) for d, o, c in sessions[i + 1:i + 1 + MAX_HOLD_SESSIONS]]
        decisions = decisions_for(alpaca, criteria, day, market_open)
        full = {v: row.get(f"{v}_symbols", []) for v in criteria}
        records = _results_for_day(alpaca, {sid: {v: symbols[:top] for v, symbols in full.items()}}, {sid: decisions},
                                   day, market_open, market_close, later, [strategy], fetch_lists={sid: full})
        rows.append(records[sid])
    return sid, result["label"], rows


def run_top(top, only=None):
    """Pour chaque stratégie et chaque test d'origine (2025, 2024, semaine) : le même test avec les `top` premiers titres."""
    git_sha = committed_git_sha()
    jobs = []
    for strategy in STRATEGIES:
        if only is not None and strategy.id not in only:
            continue
        latest = {}
        for path in sorted((RUNS_DIR / strategy.storage / "backtests").glob("b[0-9][0-9][0-9]/results.json")):
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("top") is None and result.get("label") in BASE_TESTS:
                latest[result["label"]] = path
        jobs += [(strategy.id, str(path)) for path in latest.values()]
    print(f"{len(jobs)} tests rejoués avec les {top} premiers titres de chaque liste.")
    written = []
    by_id = {s.id: s for s in STRATEGIES}
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=multiprocessing.get_context("spawn"), initializer=_init_top,
                             initargs=(top,)) as pool:
        for sid, label, rows in pool.map(_top_job, jobs):
            written += _write_tests(by_id[sid], rows, BASE_TESTS[label], git_sha, top)
    print(f"{len(written)} résultats écrits.")
    return 0


def _pct(value):
    return "—" if value is None else f"{value * 100:+.2f} %"


def main():
    parser = argparse.ArgumentParser(description="Tests sur le passé des stratégies (diagnostic)")
    parser.add_argument("--year", type=int, help="Année rejouée (défaut : 2025 et ses trois tranches)")
    parser.add_argument("--only", help="Identifiants des stratégies, séparés par des virgules (défaut : toutes)")
    parser.add_argument("--start", type=date.fromisoformat, help="Première séance (AAAA-MM-JJ), avec --end")
    parser.add_argument("--end", type=date.fromisoformat, help="Dernière séance (AAAA-MM-JJ)")
    parser.add_argument("--top", type=int, help="Rejouer les tests déjà faits avec les N premiers titres de chaque liste")
    args = parser.parse_args()
    try:
        if args.top:
            return run_top(args.top, None if args.only is None else set(args.only.split(",")))
        return run(args.year, None if args.only is None else set(args.only.split(",")), args.start, args.end)
    except (FetchError, TraceError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
