"""
Génère dashboard/index.html à partir de l'historique des runs d'une famille et du dernier état
du suivi en direct (research/outputs/live/latest.json, volatil), s'il existe.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.build reprise_apres_baisse
"""

import json
import sys
from pathlib import Path

from infra.trace import ROOT, load_runs

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUTPUT = HERE / "index.html"
LIVE_FILE = ROOT / "research" / "outputs" / "live" / "latest.json"


def _embed(value):
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def build(family):
    runs = load_runs(family)
    live = json.loads(LIVE_FILE.read_text(encoding="utf-8")) if LIVE_FILE.exists() else None
    if live and live["family"] != family:
        live = None
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__RUNS_JSON__", _embed(runs))
            .replace("__LIVE_JSON__", _embed(live)))
    OUTPUT.write_text(page, encoding="utf-8")
    return OUTPUT, len(runs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.build <famille>")
    path, n = build(sys.argv[1])
    print(f"Tableau de bord : {path} ({n} run(s))")
