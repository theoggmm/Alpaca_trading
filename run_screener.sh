#!/bin/sh
# Run quotidien du screener, régénération du tableau de bord, puis envoi de l'historique sur GitHub.
# À lancer au moins 1 h 15 après l'ouverture de New York (données consolidées décalées de 15 min).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
FAMILY="reprise_apres_baisse"
HISTORY="research/experiments/runs/$FAMILY research/experiments/registry.csv"
cd "$ROOT"

"$PY" -m research.algorithms.$FAMILY.run
"$PY" -m dashboard.build "$FAMILY"

# Historique : seuls les fichiers de runs et le registre sont commités ; tests verts et git pull avant git push.
if [ -n "$(git status --porcelain -- $HISTORY)" ]; then
  "$PY" -m pytest -q
  git pull --ff-only -q
  RUN="$(tail -n 1 research/experiments/registry.csv | cut -d, -f1,3 | sed 's/,/, séance du /')"
  git add -- $HISTORY
  git commit -q -m "Historique $FAMILY : $RUN" -- $HISTORY
  git push -q
  echo "Historique envoyé sur GitHub : $RUN"
fi
