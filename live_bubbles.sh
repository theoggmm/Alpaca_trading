#!/bin/sh
# Suivi en direct des bulles par domaine pendant la séance de New York (Ctrl+C pour arrêter).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -u -m dashboard.live reprise_apres_baisse
