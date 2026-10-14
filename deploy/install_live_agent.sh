#!/bin/sh
# Installe (ou réinstalle) le démarrage automatique du suivi en direct sur ce Mac (launchd).
#
# Chaque jour de semaine à 14 h 15, heure du Mac (Paris) : c'est avant l'ouverture de New York
# (15 h 30 à Paris, 14 h 30 pendant les semaines où les changements d'heure sont décalés). Le suivi
# attend lui-même l'ouverture, ne fait rien un jour férié et s'arrête seul après la clôture.
# Mac en veille à 14 h 15 : launchd le lance au réveil. Mac éteint : rien ce jour-là.
# macOS interdit aux services d'arrière-plan l'accès au dossier Documents : launchd ouvre donc
# deploy/live_bubbles.command dans une fenêtre Terminal, qui a cet accès.
# Pendant le suivi, caffeinate empêche la mise en veille automatique (pas celle du capot fermé).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.alpaca-trading.live"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/alpaca_trading_live.log"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>Terminal</string>
    <string>$ROOT/deploy/live_bubbles.command</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
$(for day in 1 2 3 4 5; do printf '    <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>14</integer><key>Minute</key><integer>15</integer></dict>\n' "$day"; done)
  </array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Démarrage automatique installé : $PLIST"
echo "Journal : $LOG"
