#!/bin/sh
# Retire le démarrage automatique du suivi en direct. Le fichier de réglage est archivé, pas supprimé.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.alpaca-trading.live"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ARCHIVE="$(dirname "$ROOT")/Alpaca_trading_archive/$(date +%Y-%m-%d)"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ -f "$PLIST" ]; then
  mkdir -p "$ARCHIVE"
  mv "$PLIST" "$ARCHIVE/"
  echo "Démarrage automatique retiré ; réglage archivé dans $ARCHIVE"
else
  echo "Aucun démarrage automatique installé."
fi
