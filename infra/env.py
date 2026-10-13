"""
Variables du fichier .env du dépôt, chargées par load_dotenv et jamais affichées (règle 7).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from infra.http import FetchError

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def require(name, purpose):
    """Valeur de la variable name ; lève FetchError (sans jamais afficher de valeur) si elle manque."""
    load_dotenv(ENV_FILE)
    value = os.getenv(name)
    if not value:
        raise FetchError(f"{name} doit être défini dans {ENV_FILE} ({purpose})")
    return value


def optional(name, default):
    load_dotenv(ENV_FILE)
    return os.getenv(name, default)
