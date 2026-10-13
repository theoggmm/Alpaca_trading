"""
Génère dashboard/index.html à partir de l'historique des runs d'une famille et du dernier état
du suivi en direct (research/outputs/live/latest.json, volatil), s'il existe.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.build reprise_apres_baisse
"""

import json
import sys
from datetime import date
from pathlib import Path

from infra import sec
from infra.http import FetchError
from infra.trace import ROOT, load_runs

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
# Une page par langue, générées depuis le même gabarit.
OUTPUTS = {"fr": HERE / "index.html", "en": HERE / "index_en.html"}
LIVE_FILE = ROOT / "research" / "outputs" / "live" / "latest.json"


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


def build(family):
    runs = load_runs(family)
    _fill_domains(runs)
    live = json.loads(LIVE_FILE.read_text(encoding="utf-8")) if LIVE_FILE.exists() else None
    if live and live["family"] != family:
        live = None
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__RUNS_JSON__", _embed(runs))
            .replace("__LIVE_JSON__", _embed(live)))
    for lang, path in OUTPUTS.items():
        path.write_text(page.replace("__LANG__", lang), encoding="utf-8")
    return OUTPUTS, len(runs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.build <famille>")
    paths, n = build(sys.argv[1])
    print(f"Tableau de bord ({n} run(s)) : {paths['fr']} · English: {paths['en']}")
