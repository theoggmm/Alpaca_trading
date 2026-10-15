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
from core.screener import Criteria, liquid_universe
from infra import sec
from infra.cache import read_cached
from infra.http import FetchError
from infra.trace import ROOT, latest_per_session, load_runs, variant_of

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


def _write_session_files(family):
    """sessions/<date>.js pour chaque état de fin de séance, réécrit seulement s'il a changé."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    for source in (FINALS_DIR / family).glob("*.json"):
        target = SESSIONS_DIR / f"{source.stem}.js"
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            continue
        state = source.read_text(encoding="utf-8").strip()
        target.write_text(f'window.SESSION_STATES=window.SESSION_STATES||{{}};'
                          f'window.SESSION_STATES["{source.stem}"]={state.replace("</", "<\\/")};\n', encoding="utf-8")


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


def build(family):
    runs = load_runs(family)
    _fill_domains(runs)
    _fill_month_trend(runs)
    live = json.loads(LIVE_FILE.read_text(encoding="utf-8")) if LIVE_FILE.exists() else None
    if live and live["family"] != family:
        live = None
    finals = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((FINALS_DIR / family).glob("*.json"))]
    # La page n'embarque que les comptages et la colonne « ouverture → clôture » de chaque séance,
    # pas la liste complète des titres de chaque fin de séance.
    history = {
        "runs": len(runs),
        "finals": sum("stocks" in f for f in finals),
        "top_n": TOP_IN_DOMAIN,
        # Une liste par séance et par version ; comptage séparé pour chaque version.
        "in_selection": {variant: selection_counts([r for r in latest_per_session(runs) if variant_of(r) == variant])
                         for variant in {variant_of(r) for r in runs}},
        "top_in_domain": top_in_domain_counts(finals),
    }
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__RUNS_JSON__", _embed(runs))
            .replace("__LIVE_JSON__", _embed(live))
            .replace("__FINALS_JSON__", _embed({f["session_date"]: {"selection": f.get("selection"), "charts": f.get("charts"),
                                                                    "provisional": f.get("provisional", True)}
                                                for f in finals}))
            .replace("__HISTORY_JSON__", _embed(history)))
    _write_session_files(family)
    for lang, path in OUTPUTS.items():
        path.write_text(page.replace("__LANG__", lang), encoding="utf-8")
    return OUTPUTS, len(runs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.build <famille>")
    paths, n = build(sys.argv[1])
    print(f"Tableau de bord ({n} run(s)) : {paths['fr']} · English: {paths['en']}")
