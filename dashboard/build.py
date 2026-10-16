"""
Génère un tableau de bord par stratégie de la famille, à partir de ses runs, de ses états de fin de séance
(research/experiments/final/<stockage>/) et de son dernier état en direct (research/outputs/live/, volatil),
plus une page d'accueil qui les compare : dashboard/accueil.html (anglais : home.html).
Stratégie principale : dashboard/index.html et index_en.html ; autres : dashboard/<id>.html et <id>_en.html.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.build reprise_apres_baisse
"""

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from core.domains import domain_trends
from core.history import TOP_IN_DOMAIN, selection_counts, top_in_domain_counts
from core.performance_metrics import cumulative, summary
from core.portfolio import TAX_RATE, after_tax
from core.screener import liquid_universe
from core.strategy import criteria_from_json, load_strategies
from infra import sec
from infra.cache import read_cached
from infra.http import FetchError
from infra.trace import ROOT, RUNS_DIR, latest_per_session, load_runs, variant_of

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
HOME_TEMPLATE = HERE / "home_template.html"
# Une page par langue et par stratégie, générées depuis le même gabarit ; accueil commun.
OUTPUTS = {"fr": HERE / "index.html", "en": HERE / "index_en.html"}
HOME = {"fr": HERE / "accueil.html", "en": HERE / "home.html"}
LIVE_FILE = ROOT / "research" / "outputs" / "live" / "latest.json"
# Clôtures du dernier mois de tout l'univers, écrites une fois par séance par le suivi en direct.
CHARTS_FILE = HERE / "charts_data.js"
# États figés des séances passées, un fichier par séance, chargé par la page quand on choisit la séance.
SESSIONS_DIR = HERE / "sessions"
# États de fin de séance, durables (commités avec l'historique) : <famille>/<date>.json.
FINALS_DIR = ROOT / "research" / "experiments" / "final"
# Compléments d'une séance définitive (simulation recalculée après coup), à côté de l'état, jamais dedans.
SUPPLEMENTS = "supplements"


def strategies(family):
    return load_strategies(ROOT / "research" / "algorithms" / family, family)


def pages(strategy):
    """Pages (français, anglais) d'une stratégie."""
    if strategy.is_main:
        return OUTPUTS
    return {"fr": HERE / f"{strategy.id}.html", "en": HERE / f"{strategy.id}_en.html"}


def live_file(strategy):
    """Dernier état en direct d'une stratégie (volatil)."""
    return LIVE_FILE if strategy.is_main else LIVE_FILE.with_name(f"latest_{strategy.id}.json")


def sessions_dir(strategy):
    return SESSIONS_DIR if strategy.is_main else SESSIONS_DIR / strategy.id


def _clock(minutes):
    """Minutes depuis minuit -> « HH:MM » (heure de New York, séance habituelle 9 h 30 – 16 h 00)."""
    return f"{minutes // 60:d}:{minutes % 60:02d}"


def _paris(minutes, day=None):
    """Même heure à Paris, pour la date donnée (aujourd'hui par défaut) : l'écart n'est pas toujours de 6 h."""
    day = day or date.today()
    moment = datetime(day.year, day.month, day.day, minutes // 60, minutes % 60, tzinfo=ZoneInfo("America/New_York"))
    return moment.astimezone(ZoneInfo("Europe/Paris")).strftime("%H:%M")


def _strategy_info(strategy):
    """Ce que la page affiche d'une stratégie : nom, description, heures d'achat et de vente (New York)."""
    open_minutes, close_minutes = 9 * 60 + 30, 16 * 60
    buy = open_minutes + min(c.decision_minutes for c in strategy.criteria().values()) + 15
    sell = (open_minutes + strategy.exit_after_open_minutes if strategy.exit_after_open_minutes is not None
            else close_minutes - strategy.exit_before_close_minutes)
    page = pages(strategy)
    return {"id": strategy.id, "name": strategy.name, "description": strategy.description, "main": strategy.is_main,
            "buy": _clock(buy), "sell": _clock(sell), "buy_paris": _paris(buy), "sell_paris": _paris(sell),
            "fr": page["fr"].name, "en": page["en"].name}


def _embed(value):
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _fill_domains(runs):
    """
    Runs produits avant l'ajout des domaines : le domaine SEC est lu à l'affichage (marqué
    domain_read_later), sans modifier le fichier du run. Si la SEC ne répond pas, rien n'est ajouté.
    """
    items = [item for run in runs for item in run["selection"] if "domain" not in item]
    if not items:
        return
    try:
        profiles = sec.profiles(sorted({item["symbol"] for item in items}), date.today().isoformat())
    except FetchError:
        return
    for item in items:
        profile = profiles.get(item["symbol"], {})
        item.update(domain=profile.get("domain"), sic_description=profile.get("sic_description"),
                    domain_read_later=True)


def _with_tax(state):
    """
    Ajoute à chaque version de la simulation le gain après impôt (actions entières, après frais), calculé
    à l'affichage depuis le gain enregistré : les états de fin de séance ne sont pas modifiés.
    """
    for row in ((state or {}).get("portfolio") or {}).get("versions", {}).values():
        if row.get("whole_gains"):
            row.update(after_tax_gains=after_tax(row["whole_gains"]), tax_rate=str(TAX_RATE))
    return state


def _load_finals(storage):
    """
    États de fin de séance, par date ; un complément (supplements/<date>.json) remplace à l'affichage la
    simulation, les ordres et « Depuis l'achat » de l'état, qui reste intact sur le disque.
    Retourne [(état, date de modification la plus récente)].
    """
    finals = []
    for path in sorted((FINALS_DIR / storage).glob("*.json")):
        final = json.loads(path.read_text(encoding="utf-8"))
        mtime = path.stat().st_mtime
        extra = FINALS_DIR / storage / SUPPLEMENTS / path.name
        if extra.exists():
            sup = json.loads(extra.read_text(encoding="utf-8"))
            final.update(portfolio=sup["portfolio"], order_plan=sup["order_plan"],
                         supplement={"computed_at": sup["computed_at"], "git_sha": sup["git_sha"]})
            final.setdefault("selection", {})["since_entry"] = sup["since_entry"]
            mtime = max(mtime, extra.stat().st_mtime)
        finals.append((_with_tax(final), mtime))
    return finals


def _write_session_files(finals, folder):
    """<dossier>/<date>.js pour chaque état de fin de séance, réécrit seulement s'il a changé."""
    folder.mkdir(parents=True, exist_ok=True)
    for final, mtime in finals:
        target = folder / f"{final['session_date']}.js"
        if target.exists() and target.stat().st_mtime >= mtime:
            continue
        state = json.dumps(final, ensure_ascii=False)
        target.write_text(f'window.SESSION_STATES=window.SESSION_STATES||{{}};'
                          f'window.SESSION_STATES["{final["session_date"]}"]={state.replace("</", "<\\/")};\n',
                          encoding="utf-8")


def _fill_month_trend(runs):
    """
    Runs produits avant l'ajout des bulles par domaine : bulles recalculées à l'affichage depuis les
    données en cache du run (mêmes barres, même instant de décision), marquées read_later, sans modifier
    le fichier du run. Données absentes du cache ou SEC injoignable : rien n'est ajouté.
    """
    for run in runs:
        daily = None if "domains" in run else read_cached(f"{run['session_date']}/daily_bars")
        if daily is None:
            continue
        criteria = criteria_from_json(run["criteria"], run["run_id"])
        decision_time = datetime.fromisoformat(run["decision_time"])
        liquid, _ = liquid_universe(daily, decision_time, criteria)
        try:
            profiles = sec.profiles([s.symbol for s in liquid], date.today().isoformat())
        except FetchError:
            continue
        bubbles, unclassified = domain_trends(daily, decision_time, criteria,
                                              {symbol: p["domain"] for symbol, p in profiles.items()})
        run["domains"] = {"bubbles": bubbles, "unclassified": unclassified, "read_later": True}


# Séances faites avec des règles remplacées (avant la décision T5 : sans « pas au sommet » ni « confirmation »,
# achat à 10 h 45) : rangées dans l'onglet Archive, hors des résultats et des comptages actuels. Rien n'est effacé.
RULES_SINCE = "2026-10-16"

# Expérience 001 (pré-enregistrée) : fenêtre de jugement.
# Suspendue (décision 001.3) : les règles sont en réglage ; repartira de zéro quand elles seront figées.
EXPERIMENT = {"id": "001", "start": "2026-10-15", "sessions": 40, "suspended": True,
              "file": "research/algorithms/reprise_apres_baisse/experiences/001_per12_vs_sans_per.md"}
SERIES = ("per12", "sans_per", "univers", "spy")


def _results(finals):
    """
    Rendement quotidien après frais de chaque série (versions de la liste, repères), depuis les états de fin
    de séance qui portent la simulation après frais. Liste vide ce jour-là : 0 (règle de l'expérience 001).
    """
    series = {name: {} for name in SERIES}
    skipped = []
    for final in finals:
        portfolio = final.get("portfolio") or {}
        rows = {**portfolio.get("versions", {}), **portfolio.get("benchmarks", {})}
        if "net_mean_return" not in str(rows):
            skipped.append(final["session_date"])
            continue
        for name, row in rows.items():
            if row.get("net_mean_return") is not None:
                series[name][final["session_date"]] = row["net_mean_return"]
            elif row.get("n") == 0:
                series[name][final["session_date"]] = 0.0
    provisional = [f["session_date"] for f in finals if f.get("provisional", True) and f["session_date"] not in skipped]
    recomputed = [f["session_date"] for f in finals if "supplement" in f]
    return {
        "series": series,
        "summaries": {name: summary(values) for name, values in series.items()},
        "cumulative": {name: cumulative(values) for name, values in series.items()},
        "skipped": skipped,
        "provisional": provisional,
        "recomputed": recomputed,
        # Une séance compte dès la clôture (positions vendues à 15 h 30) ; « pending » = encore provisoire,
        # en attente des corrections d'Alpaca de la nuit. Le verdict se calcule sur les états définitifs.
        "experiment": {**EXPERIMENT,
                       "observed": sum(1 for f in finals if f["session_date"] >= EXPERIMENT["start"]
                                       and f["session_date"] in series["per12"]),
                       "pending": sum(1 for f in finals if f["session_date"] >= EXPERIMENT["start"]
                                      and f.get("provisional", True) and f["session_date"] in series["per12"])},
    }


def _backtests(storage):
    """
    Dernier test sur le passé de chaque durée (6 mois, 1 mois…), de la plus longue à la plus courte
    (diagnostic) : résumés, cumuls, écarts appariés. Liste vide s'il n'y en a pas.
    """
    latest = {}
    for path in sorted((RUNS_DIR / storage / "backtests").glob("b[0-9][0-9][0-9]/results.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        # Une durée glissante (6 mois, 1 mois) ou une période datée (« février 2025 ») : dernier résultat de chacune.
        latest[result["period"]["months"] or result["period"]["start"]] = result
    return [{
        "id": result["backtest_id"],
        "git_sha": result["git_sha"],
        "period": result["period"],
        "max_pe": result["criteria"].get("per12", {}).get("max_pe"),
        "summaries": result["summaries"],
        "differences": result["differences"],
        "cumulative": {name: cumulative({d["date"]: d[name] for d in result["days"] if d[name] is not None})
                       for name in result["summaries"]},
    } for _, result in sorted(latest.items(), key=lambda item: (isinstance(item[0], str), item[0]), reverse=True)]


# Onglet « Tests d'un mois » : montants proposés (investis chaque séance dans chaque liste), si le test les a calculés.
MONTH_TEST_AMOUNTS = (Decimal("25000"), Decimal("2000000"))
MONTH_TEST_LISTS = ("per12", "sans_per")


def _month_tests(storage):
    """
    Tests sur le passé d'une période datée (un mois) : pour chaque montant et chaque liste, gain par séance,
    par semaine et sur la période — brut, après frais, actions entières après frais, et ce qui reste après
    impôt. Impôt d'une semaine ou du mois : sur son total (les pertes compensent les gains) ; d'une séance :
    sur elle seule. Liste vide : rien d'investi, 0.
    """
    def kept(whole):
        return after_tax({"x": str(whole)})["x"]

    def totals(rows):
        whole = sum(Decimal(r["whole"]) for r in rows)
        return {"sessions": len(rows), "gross": str(sum(Decimal(r["gross"]) for r in rows)),
                "net": str(sum(Decimal(r["net"]) for r in rows)), "whole": str(whole), "kept": kept(whole)}

    def lists_for(result, amount):
        lists = {}
        for name in MONTH_TEST_LISTS:
            days = []
            for d in result["days"]:
                empty = not d[f"{name}_n"]
                gross = Decimal(0) if empty else (amount * Decimal(str(d[f"{name}_gross"]))).quantize(Decimal("0.01"))
                net = Decimal(0) if empty else (amount * Decimal(str(d[name]))).quantize(Decimal("0.01"))
                whole = Decimal(d[f"{name}_whole_gains"].get(str(amount), "0"))
                days.append({"date": d["date"], "n": d[f"{name}_n"], "gross": str(gross), "net": str(net),
                             "whole": str(whole), "kept": kept(whole)})
            weeks = {}
            for row in days:
                weeks.setdefault(tuple(date.fromisoformat(row["date"]).isocalendar()[:2]), []).append(row)
            lists[name] = {"days": days,
                           "weeks": [{"start": rows[0]["date"], "end": rows[-1]["date"], **totals(rows)}
                                     for rows in weeks.values()],
                           "total": totals(days)}
        return lists

    tests = []
    for path in sorted((RUNS_DIR / storage / "backtests").glob("b[0-9][0-9][0-9]/results.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["period"]["months"] or "per12_gross" not in result["days"][0]:
            continue
        # Montants calculés en actions entières par ce test (un ancien test n'a pas 2 M$).
        computed = {k for d in result["days"] for n in MONTH_TEST_LISTS for k in d[f"{n}_whole_gains"]}
        empty_month = not computed
        spy = sum(Decimal(str(d["spy"])) for d in result["days"] if d["spy"] is not None)
        tests.append({"id": result["backtest_id"], "git_sha": result["git_sha"], "period": result["period"],
                      "max_pe": result["criteria"].get("per12", {}).get("max_pe"),
                      "amounts": {str(a): {"lists": lists_for(result, a),
                                           "spy_net": str((a * spy).quantize(Decimal("0.01")))}
                                  for a in MONTH_TEST_AMOUNTS if empty_month or str(a) in computed}})
    # Le plus récent test de chaque période seulement.
    latest = {t["period"]["start"]: t for t in tests}
    return [latest[k] for k in sorted(latest, reverse=True)]


def _build_strategy(strategy, infos):
    """Tableau de bord d'une stratégie ; retourne sa ligne de l'accueil."""
    runs = load_runs(strategy.storage)
    _fill_domains(runs)
    _fill_month_trend(runs)
    path = live_file(strategy)
    live = _with_tax(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
    if live and live["family"] != strategy.storage:
        live = None
    loaded = _load_finals(strategy.storage)
    finals = [final for final, _ in loaded]
    current_runs = [r for r in runs if r["session_date"] >= RULES_SINCE]
    current_finals = [f for f in finals if f["session_date"] >= RULES_SINCE]
    archived_runs = [r for r in latest_per_session(runs) if r["session_date"] < RULES_SINCE]
    archived_finals = [f for f in finals if f["session_date"] < RULES_SINCE]
    # La page n'embarque que les comptages et la colonne « ouverture → clôture » de chaque séance,
    # pas la liste complète des titres de chaque fin de séance. Comptages et résultats : règles actuelles.
    results = _results(current_finals)
    history = {
        "runs": len(current_runs),
        "finals": sum("stocks" in f for f in current_finals),
        "top_n": TOP_IN_DOMAIN,
        # Une liste par séance et par version ; comptage séparé pour chaque version.
        "in_selection": {variant: selection_counts([r for r in latest_per_session(current_runs) if variant_of(r) == variant])
                         for variant in {variant_of(r) for r in current_runs}},
        "top_in_domain": top_in_domain_counts(current_finals),
        "results": results,
        "backtests": _backtests(strategy.storage),
        "month_tests": _month_tests(strategy.storage),
        "archive": {
            "since": RULES_SINCE,
            "results": _results(archived_finals),
            "lists": [{"session_date": r["session_date"], "variant": variant_of(r), "run_id": r["run_id"],
                       "symbols": [i["symbol"] for i in r["selection"]]} for r in archived_runs],
        },
    }
    info = next(i for i in infos if i["id"] == strategy.id)
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__RUNS_JSON__", _embed(runs))
            .replace("__LIVE_JSON__", _embed(live))
            .replace("__FINALS_JSON__", _embed({f["session_date"]: {"selection": f.get("selection"), "charts": f.get("charts"),
                                                                    "provisional": f.get("provisional", True)}
                                                for f in finals}))
            .replace("__HISTORY_JSON__", _embed(history))
            .replace("__STRATEGY_JSON__", _embed(info))
            .replace("__STRATEGIES_JSON__", _embed(infos))
            .replace("__SESSIONS_DIR__", sessions_dir(strategy).relative_to(HERE).as_posix() + "/"))
    _write_session_files(loaded, sessions_dir(strategy))
    # Import tardif : dashboard.methodology lit les constantes de dashboard.live, qui importe ce module.
    from dashboard import methodology
    for lang, out in pages(strategy).items():
        out.write_text(page.replace("__LANG__", lang).replace("__METHODOLOGY__", methodology.embedded(lang, EXPERIMENT)),
                       encoding="utf-8")
    # Ligne de l'accueil : résultat du jour (en direct ou figé) et cumul depuis le début, par liste.
    today = {v: {"status": row.get("status"), "net": row.get("net_mean_return"), "n": row.get("n")}
             for v, row in ((live or {}).get("portfolio") or {}).get("versions", {}).items()}
    return {**info, "session_date": (live or {}).get("session_date"), "today": today,
            "totals": {v: results["summaries"].get(v) for v in ("per12", "sans_per", "spy")}}


def build(family):
    """Tous les tableaux de bord de la famille, puis l'accueil et la méthodologie autonome."""
    every = strategies(family)
    infos = [_strategy_info(s) for s in every]
    rows = [_build_strategy(s, infos) for s in every]
    home = HOME_TEMPLATE.read_text(encoding="utf-8").replace("__ROWS_JSON__", _embed(rows))
    for lang, out in HOME.items():
        out.write_text(home.replace("__LANG__", lang), encoding="utf-8")
    from dashboard import methodology
    methodology.write(EXPERIMENT)
    return OUTPUTS, sum(len(load_runs(s.storage)) for s in every)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.build <famille>")
    paths, n = build(sys.argv[1])
    print(f"Tableaux de bord ({n} run(s)) : accueil {HOME['fr']} · principale {paths['fr']} · English: {HOME['en']}")
