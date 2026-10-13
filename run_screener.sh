#!/bin/sh
# Run quotidien du screener puis régénération du tableau de bord.
# À lancer au moins 1 h 15 après l'ouverture de New York (données consolidées décalées de 15 min).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
"$ROOT/.venv/bin/python" -m research.algorithms.reprise_apres_baisse.run
"$ROOT/.venv/bin/python" -m dashboard.build reprise_apres_baisse
