"""
Génère dashboard/index.html à partir de l'historique des runs d'une famille.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.build reprise_apres_baisse
"""

import json
import sys
from pathlib import Path

from infra.trace import load_runs

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUTPUT = HERE / "index.html"
PLACEHOLDER = "__RUNS_JSON__"


def build(family):
    runs = load_runs(family)
    data = json.dumps(runs, ensure_ascii=False).replace("</", "<\\/")
    OUTPUT.write_text(TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, data), encoding="utf-8")
    return OUTPUT, len(runs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m dashboard.build <famille>")
    path, n = build(sys.argv[1])
    print(f"Tableau de bord : {path} ({n} run(s))")
