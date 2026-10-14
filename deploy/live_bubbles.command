#!/bin/sh
# Lanceur ouvert dans une fenêtre Terminal par le démarrage automatique (launchd).
# macOS interdit aux services d'arrière-plan l'accès au dossier Documents ; Terminal l'a.
# Fermer la fenêtre (ou Ctrl+C) arrête le suivi.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/Library/Logs/alpaca_trading_live.log"

echo "$(date) — démarrage du suivi en direct" >> "$LOG"
/usr/bin/caffeinate -i "$ROOT/live_bubbles.sh" 2>&1 | tee -a "$LOG"
