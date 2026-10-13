"""
Règle 7 : aucun secret dans un fichier suivi par git. Ce test ne lit jamais le fichier .env.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Formes des identifiants de clés Alpaca (paper : PK…, live : AK…, broker : CK…).
KEY_PATTERN = re.compile(r"\b[PAC]K[A-Z0-9]{16,}\b")


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout


def test_env_ignore_et_non_suivi():
    assert _git("check-ignore", ".env").strip() == ".env"
    assert _git("ls-files", ".env").strip() == ""


def test_aucune_cle_dans_les_fichiers_suivis():
    for name in _git("ls-files").splitlines():
        path = ROOT / name
        if not path.is_file() or name == "uv.lock":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert not KEY_PATTERN.search(text), f"{name} contient une chaîne qui ressemble à une clé Alpaca"
