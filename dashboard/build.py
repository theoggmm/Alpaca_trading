"""
Génère dashboard/index.html (et index_en.html) à partir de l'historique des runs d'une famille,
des états de fin de séance (research/experiments/final/) et du dernier état du suivi en direct
(research/outputs/live/latest.json, volatil), s'il existe.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.build reprise_apres_baisse
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from core.domains import domain_trends
from core.history import TOP_IN_DOMAIN, selection_counts, top_in_domain_counts
from core.performance_metrics import cumulative, summary
from core.portfolio import TAX_RATE, after_tax
from core.screener import Criteria, liquid_universe
from infra import sec
from infra.cache import read_cached
from infra.http import FetchError
from infra.trace import ROOT, RUNS_DIR, latest_per_session, load_runs, variant_of

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
# Une page par langue, générées depuis le même gabarit.
OUTPUTS = {"fr": HERE / "index.html", "en": HERE / "index_en.html"}
LIVE_FILE = ROOT / "research" / "outputs" / "live" / "latest.json"
# Clôtures du dernier mois de tout l'univers, écrites une fois par séance par le suivi en direct.
CHARTS_FILE = HERE / "charts_data.js"
# États figés des séances passées, un fichier par séance, chargé par la page quand on choisit la séance.
SESSIONS_DIR = HERE / "sessions"
# États de fin de séance, durables (commités avec l'historique) : <famille>/<date>.json.
FINALS_DIR = ROOT / "research" / "experiments" / "final"
# Compléments d'une séance définitive (simulation recalculée après coup), à côté de l'état, jamais dedans.
SUPPLEMENTS = "supplements"


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


def _load_finals(family):
    """
    États de fin de séance, par date ; un complément (supplements/<date>.json) remplace à l'affichage la
    simulation, les ordres et « Depuis l'achat » de l'état, qui reste intact sur le disque.
    Retourne [(état, date de modification la plus récente)].
    """
    finals = []
    for path in sorted((FINALS_DIR / family).glob("*.json")):
        final = json.loads(path.read_text(encoding="utf-8"))
        mtime = path.stat().st_mtime
        extra = FINALS_DIR / family / SUPPLEMENTS / path.name
        if extra.exists():
            sup = json.loads(extra.read_text(encoding="utf-8"))
            final.update(portfolio=sup["portfolio"], order_plan=sup["order_plan"],
                         supplement={"computed_at": sup["computed_at"], "git_sha": sup["git_sha"]})
            final.setdefault("selection", {})["since_entry"] = sup["since_entry"]
            mtime = max(mtime, extra.stat().st_mtime)
        finals.append((_with_tax(final), mtime))
    return finals


def _write_session_files(finals):
    """sessions/<date>.js pour chaque état de fin de séance, réécrit seulement s'il a changé."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    for final, mtime in finals:
        target = SESSIONS_DIR / f"{final['session_date']}.js"
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
        criteria = Criteria.from_json(run["criteria"], run["run_id"])
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


def _backtest(family):
    """Dernier test sur le passé de la famille (diagnostic) : résumés, cumuls, écarts appariés. None s'il n'y en a pas."""
    paths = sorted((RUNS_DIR / family / "backtests").glob("b[0-9][0-9][0-9]/results.json"))
    if not paths:
        return None
    result = json.loads(paths[-1].read_text(encoding="utf-8"))
    return {
        "id": result["backtest_id"],
        "git_sha": result["git_sha"],
        "period": result["period"],
        "summaries": result["summaries"],
        "differences": result["differences"],
        "cumulative": {name: cumulative({d["date"]: d[name] for d in result["days"] if d[name] is not None})
                       for name in result["summaries"]},
    }


def build(family):
    runs = load_runs(family)
    _fill_domains(runs)
    _fill_month_trend(runs)
    live = _with_tax(json.loads(LIVE_FILE.read_text(encoding="utf-8"))) if LIVE_FILE.exists() else None
    if live and live["family"] != family:
        live = None
    loaded = _load_finals(family)
    finals = [final for final, _ in loaded]
    # La page n'embarque que les comptages et la colonne « ouverture → clôture » de chaque séance,
    # pas la liste complète des titres de chaque fin de séance.
    current_runs = [r for r in runs if r["session_date"] >= RULES_SINCE]
    current_finals = [f for f in finals if f["session_date"] >= RULES_SINCE]
    archived_runs = [r for r in latest_per_session(runs) if r["session_date"] < RULES_SINCE]
    archived_finals = [f for f in finals if f["session_date"] < RULES_SINCE]
    # La page n'embarque que les comptages et la colonne « ouverture → clôture » de chaque séance,
    # pas la liste complète des titres de chaque fin de séance. Comptages et résultats : règles actuelles.
    history = {
        "runs": len(current_runs),
        "finals": sum("stocks" in f for f in current_finals),
        "top_n": TOP_IN_DOMAIN,
        # Une liste par séance et par version ; comptage séparé pour chaque version.
        "in_selection": {variant: selection_counts([r for r in latest_per_session(current_runs) if variant_of(r) == variant])
                         for variant in {variant_of(r) for r in current_runs}},
        "top_in_domain": top_in_domain_counts(current_finals),
        "results": _results(current_finals),
        "backtest": _backtest(family),
        "archive": {
            "since": RULES_SINCE,
            "results": _results(archived_finals),
            "lists": [{"session_date": r["session_date"], "variant": variant_of(r), "run_id": r["run_id"],
                       "symbols": [i["symbol"] for i in r["selection"]]} for r in archived_runs],
        },
    }
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__RUNS_JSON__", _embed(runs))
            .replace("__LIVE_JSON__", _embed(live))
            .replace("__FINALS_JSON__", _embed({f["session_date"]: {"selection": f.get("selection"), "charts": f.get("charts"),
                                                                    "provisional": f.get("provisional", True)}
                                                for f in finals}))
            .replace("__HISTORY_JSON__", _embed(history)))
    _write_session_files(loaded)
    # Import tardif : dashboard.methodology lit les constantes de dashboard.live, qui importe ce module.
    from dashboard import methodology
    for lang, path in OUTPUTS.items():
        path.write_text(page.replace("__LANG__", lang).replace("__METHODOLOGY__", methodology.embedded(lang, EXPERIMENT)),
                        encoding="utf-8")
    methodology.write(EXPERIMENT)
    return OUTPUTS, len(runs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.build <famille>")
    paths, n = build(sys.argv[1])
    print(f"Tableau de bord ({n} run(s)) : {paths['fr']} · English: {paths['en']}")
