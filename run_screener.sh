#!/bin/sh
# Rattrapage des états de fin de séance manquants, run quotidien du screener, régénération du
# tableau de bord, puis envoi de l'historique sur GitHub.
# À lancer au moins 1 h 15 après l'ouverture de New York (données consolidées décalées de 15 min).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
FAMILY="reprise_apres_baisse"
HISTORY="research/experiments/runs/$FAMILY research/experiments/final/$FAMILY research/experiments/runs/volatilite research/experiments/final/volatilite research/experiments/registry.csv"
cd "$ROOT"

# Un échec du rattrapage n'empêche pas la liste du jour ; il sera retenté au prochain lancement.
"$PY" -m dashboard.final "$FAMILY" || echo "Rattrapage des fins de séance impossible, nouvel essai au prochain lancement."
# Code 1 = au moins une liste pas encore prête (données de l'après-midi) ou une erreur de lecture : ce qui est déjà
# produit (runs, fins de séance, Volatilité) est quand même commité et envoyé ; le reste au prochain lancement.
"$PY" -m research.algorithms.$FAMILY.run || echo "Listes incomplètes (pas encore prêtes ou erreur) : la suite continue, nouvel essai au prochain lancement."
# Stratégie « Volatilité » (panier gardé jusqu'à l'objectif) : liste du tour et tours vendus.
"$PY" -m dashboard.volatility || echo "Stratégie Volatilité non mise à jour, nouvel essai au prochain passage."
"$PY" -m dashboard.volatility_pairs || echo "Stratégie Volatilité 2 actions non mise à jour, nouvel essai au prochain passage."
"$PY" -m dashboard.build "$FAMILY"

# Historique : seuls les runs, les fins de séance et le registre sont commités ; tests verts et git pull avant git push.
if [ -n "$(git status --porcelain -- $HISTORY)" ]; then
  "$PY" -m pytest -q
  git pull --ff-only -q
  git add -- $HISTORY
  CHANGED="$(git diff --cached --name-only -- $HISTORY | sed -n 's#.*/\(r[0-9]*\)/results.json#run \1#p; s#.*/final/.*/\(.*\)\.json#fin de séance \1#p' | paste -sd, - | sed 's/,/, /g')"
  git commit -q -m "Historique $FAMILY : $CHANGED" -- $HISTORY
  git push -q
  echo "Historique envoyé sur GitHub : $CHANGED"
fi
