"""
Suivi en direct des bulles par domaine pendant la séance de New York, et état de fin de séance.

Toutes les minutes : derniers prix (toutes bourses, 15 min de retard), moyenne par domaine pour
la journée, la première heure, 2 séances, 1 semaine et 1 mois, variation depuis l'ouverture de
chaque titre de la sélection du jour, puis régénération du tableau de bord (qui se recharge seul).

Après la clôture (ou au réveil du Mac après la clôture), l'état de fin de séance est reconstitué
depuis l'historique minute d'Alpaca et gardé dans research/experiments/final/<famille>/<date>.json.
catch_up() refait cet état pour toute séance terminée qui n'en a pas.

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
from core.universe import eligible_symbols
from dashboard.build import CHARTS_FILE, FINALS_DIR, LIVE_FILE, SUPPLEMENTS, build
from infra import nasdaq_symbols, sec
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.http import FetchError
from infra.trace import ROOT, committed_git_sha, latest_per_session, load_runs, variant_of

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
# Simulation d'investissement (tableau du bas) : achat dès que la liste est disponible (décision + 15 min),
# vente 30 min avant la clôture. Fenêtres lues pour trouver le premier et le dernier échange.
EXIT_BEFORE_CLOSE = timedelta(minutes=30)
TRADE_WINDOW = timedelta(minutes=5)
EXIT_WINDOW = timedelta(minutes=30)
# Section « Ordres à passer » : montant réparti en actions entières sur la liste PER < 12.
ORDER_PLAN_AMOUNT = Decimal("10000")
ORDER_PLAN_VARIANT = "per12"
# Repères de la simulation : tous les titres liquides à parts égales, et l'indice S&P 500 (fonds SPY).
BENCHMARK = "SPY"
# Les données minute d'Alpaca sont corrigées après coup (échanges annulés ou rectifiés) : un état de
# fin de séance calculé le soir même est provisoire ; il devient définitif, relu à neuf, 12 h après la clôture.
DEFINITIVE_AFTER = timedelta(hours=12)
SUPERSEDED_DIR = ROOT / "research" / "outputs" / "final_superseded"
EMPTY_BARS = pd.DataFrame(columns=["symbol", "timestamp", "open", "close", "volume"])


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


def _trade_times(criteria, market_open, market_close):
    """(achat, vente) : liste disponible (décision + 15 min) et 30 min avant la clôture."""
    return (market_open + timedelta(minutes=criteria.first_hour_minutes) + FEED_DELAY,
            market_close - EXIT_BEFORE_CLOSE)


def _portfolio(runs, universe, entry_bars, exit_bars, trades, entry_time, exit_time, now):
    """
    Simulation par version de la liste (sans PER, PER < 12) : achat, valeur en cours ou vente ;
    et les mêmes règles appliquées aux repères (univers liquide à parts égales, SPY).
    """
    def run(symbols):
        return simulate(symbols, entry_bars, exit_bars, trades, entry_time, exit_time, now)

    return {
        "entry_time": entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "versions": {variant_of(r): {"run_id": r["run_id"], **run([i["symbol"] for i in r["selection"]])}
                     for r in runs},
        "benchmarks": {"univers": run(universe), "spy": run([BENCHMARK])},
    }


def _since_entry(opens, entry_bars, entry_time, trades, market_open, market_close, now):
    """
    Variation de chaque titre des listes depuis l'achat de la simulation : dernier prix / prix d'achat - 1
    (premier échange à partir de entry_time). Vide tant que le prix d'achat n'est pas connu.
    """
    prices = entry_prices(entry_bars, entry_time, now)
    return changes_since_open({s: prices[s] for s in opens if s in prices}, trades, market_open, market_close, now)


def _order_plan(runs, prices, basis):
    """
    Ordres à passer sur la liste PER < 12 : nombre entier d'actions et prix, pour ORDER_PLAN_AMOUNT.
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


def _state(family, criteria, key, market_open, market_close, now, daily, domains, names, trades, minute, opening,
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
        "family": family,
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


def finalize(family, alpaca, criteria, session_date, open_time, close_time):
    """
    État de fin de séance reconstitué depuis l'historique minute : dernier échange de chaque titre
    avant la clôture (l'enchère de clôture n'est pas comptée). Écrit research/experiments/final/.
    Provisoire s'il est calculé moins de DEFINITIVE_AFTER après la clôture ; l'état définitif relit
    les barres minute à neuf (cache distinct), pour intégrer les corrections d'Alpaca.
    """
    key = session_date.isoformat()
    market_open, market_close = _times(session_date, open_time, close_time)
    first_hour_end = market_open + timedelta(minutes=criteria.first_hour_minutes)
    git_sha = committed_git_sha()
    now = datetime.now(timezone.utc)
    stage = "definitive" if is_definitive(now, market_close) else "provisional"

    daily, symbols, domains, names = _prepare(alpaca, criteria, key, market_open)
    runs, opens = _selection(family, key)
    tracked = sorted(set(symbols) | set(opens))
    minute = cached(f"{key}/{stage}_first_hour_bars", lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
    closing = cached(f"{key}/{stage}_closing_bars",
                     lambda: alpaca.bars(tracked, "1Min", market_close - CLOSING_WINDOW, market_close))
    trades = last_session_prices(closing, market_close)
    entry_time, exit_time = _trade_times(criteria, market_open, market_close)
    traded = sorted(set(symbols) | set(opens) | {BENCHMARK})
    entry_bars = cached(f"{key}/{stage}_entry_bars_all",
                        lambda: alpaca.bars(traded, "1Min", entry_time, entry_time + TRADE_WINDOW))
    exit_bars = cached(f"{key}/{stage}_exit_bars_all",
                       lambda: alpaca.bars(traded, "1Min", exit_time - EXIT_WINDOW, exit_time))

    state = _state(family, criteria, key, market_open, market_close, market_close,
                   daily, domains, names, trades, minute, minute, runs, opens)
    state["portfolio"] = _portfolio(runs, symbols, entry_bars, exit_bars, trades, entry_time, exit_time, market_close)
    state["month_trend"] = _month_trend(daily, market_open, criteria, domains)
    state["order_plan"] = _order_plan(runs, entry_prices(entry_bars, entry_time, market_close), "entry")
    state["selection"]["since_entry"] = _since_entry(opens, entry_bars, entry_time, trades, market_open, market_close,
                                                     market_close)
    state.update(final=True, provisional=stage == "provisional", computed_at=now.isoformat(), git_sha=git_sha,
                 source="historique minute Alpaca (toutes bourses), dernière barre terminée à la clôture")
    path = FINALS_DIR / family / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():  # archive avant remplacement
        previous = SUPERSEDED_DIR / family / f"{key}_{json.loads(path.read_text(encoding='utf-8'))['computed_at']}.json"
        previous.parent.mkdir(parents=True, exist_ok=True)
        path.rename(previous)
    path.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    # Le dernier état affiché devient l'état final s'il porte sur cette séance ou une plus ancienne.
    live = json.loads(LIVE_FILE.read_text(encoding="utf-8")) if LIVE_FILE.exists() else None
    if live is None or live["session_date"] <= key:
        _write_chart_data(daily, market_open, symbols, criteria, key)
        LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return path


def catch_up(family):
    """
    Produit l'état de fin de séance de chaque séance terminée qui n'en a pas, et remplace par l'état
    définitif tout état provisoire dès que DEFINITIVE_AFTER est passé. Depuis le premier run.
    """
    runs = load_runs(family)
    if not runs:
        return []
    criteria = _criteria(family)
    alpaca = AlpacaReader()
    now = datetime.now(timezone.utc)
    first = datetime.fromisoformat(runs[0]["session_date"]).date()
    done = []
    for session_date, open_time, close_time in alpaca.sessions(first, now.astimezone(NEW_YORK).date()):
        _, market_close = _times(session_date, open_time, close_time)
        path = FINALS_DIR / family / f"{session_date}.json"
        missing = now >= market_close + FEED_DELAY and not path.exists()
        provisional = path.exists() and json.loads(path.read_text(encoding="utf-8")).get("provisional", True)
        if missing or (provisional and is_definitive(now, market_close)):
            done.append(finalize(family, alpaca, criteria, session_date, open_time, close_time))
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
        entry_time, exit_time = _trade_times(criteria, market_open, market_close)
        traded = sorted(set(symbols) | set(opens) | {BENCHMARK})
        entry_bars = cached(f"{key}/supplement_entry_bars_all",
                            lambda: alpaca.bars(traded, "1Min", entry_time, entry_time + TRADE_WINDOW))
        exit_bars = cached(f"{key}/supplement_exit_bars_all",
                           lambda: alpaca.bars(traded, "1Min", exit_time - EXIT_WINDOW, exit_time))
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
            "portfolio": _portfolio(runs, symbols, entry_bars, exit_bars, trades, entry_time, exit_time, market_close),
            "order_plan": _order_plan(runs, entry_prices(entry_bars, entry_time, market_close), "entry"),
            "since_entry": _since_entry(opens, entry_bars, entry_time, trades, market_open, market_close, market_close),
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        done.append(target)
    if done:
        build(family)
    return done


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
    entry_time, exit_time = _trade_times(criteria, market_open, market_close)
    # Prix d'achat et de vente de tous les titres liquides et du SPY (les listes en font partie) : lus une fois.
    traded = sorted(set(symbols) | {BENCHMARK})
    entry_bars, exit_bars = EMPTY_BARS, EMPTY_BARS

    while True:
        now = datetime.now(timezone.utc)
        if now >= stop_at:
            print("Clôture passée : état de fin de séance reconstitué depuis l'historique minute…")
            for path in catch_up(family):
                print(f"État de fin de séance : {path}")
            return 0
        if now < market_open + FEED_DELAY:
            print(f"En attente des premiers prix (à {(market_open + FEED_DELAY).astimezone(NEW_YORK):%H:%M}, New York).")
            time.sleep(REFRESH_S)
            continue
        # La sélection du jour existe une fois le run du screener produit (après 10 h 45, New York).
        today_runs, opens = _selection(family, key)
        try:
            if minute.empty and now >= first_hour_end + FEED_DELAY:
                minute = cached(f"{key}/live_first_hour_bars",
                                lambda: alpaca.bars(symbols, "1Min", market_open, first_hour_end))
            if opening.empty and now >= market_open + OPENING_WINDOW + FEED_DELAY:
                opening = cached(f"{key}/opening_bars",
                                 lambda: alpaca.bars(symbols, "1Min", market_open, market_open + OPENING_WINDOW))
            if entry_bars.empty and now >= entry_time + TRADE_WINDOW + FEED_DELAY:
                entry_bars = cached(f"{key}/live_entry_bars_all",
                                    lambda: alpaca.bars(traded, "1Min", entry_time, entry_time + TRADE_WINDOW))
            if exit_bars.empty and now >= exit_time + FEED_DELAY:
                exit_bars = cached(f"{key}/live_exit_bars_all",
                                   lambda: alpaca.bars(traded, "1Min", exit_time - EXIT_WINDOW, exit_time))
            trades = alpaca.latest_trades(sorted(set(traded) | set(opens)), FEED)
        except FetchError as e:
            print(f"{now.astimezone(NEW_YORK):%H:%M} — lecture impossible, nouvel essai dans {REFRESH_S} s : {e}")
            time.sleep(REFRESH_S)
            continue

        # Premier prix de chaque titre : la première heure entière dès qu'elle est lue, sinon les 5 premières minutes.
        state = _state(family, criteria, key, market_open, market_close, now, daily, domains, names, trades,
                       minute, minute if not minute.empty else opening, today_runs, opens)
        state["portfolio"] = _portfolio(today_runs, symbols, entry_bars, exit_bars, trades, entry_time, exit_time, now)
        state["month_trend"] = month_trend
        last_prices = {s: price for s, (_, price) in session_trades(trades, market_open, market_close, now).items()}
        state["order_plan"] = _order_plan(today_runs, last_prices, "live")
        state["selection"]["since_entry"] = _since_entry(opens, entry_bars, entry_time, trades, market_open, market_close,
                                                         now)
        LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        build(family)
        day = state["measures"]["day"]["bubbles"]
        up = sum(1 for b in day if b["mean_return"] > 0)
        print(f"{now.astimezone(NEW_YORK):%H:%M} (New York) — journée : "
              f"{up} domaines en hausse, {len(day) - up} en baisse")
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
