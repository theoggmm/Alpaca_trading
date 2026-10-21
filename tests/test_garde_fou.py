"""
Garde-fou anti-secrets (deploy/hooks/pre-commit, règle 7) : rejoué dans un dépôt git temporaire.
Les fausses clés sont assemblées à l'exécution : aucune n'est écrite telle quelle dans ce fichier.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "deploy" / "hooks" / "pre-commit"


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(HOOK.parent, tmp_path / "deploy" / "hooks")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "core.hooksPath", "deploy/hooks"], check=True)
    return tmp_path


def commit(repo, files, env=None):
    """Écrit les fichiers, les prépare et tente un commit : (réussi ?, messages d'erreur)."""
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    result = subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com",
                             "commit", "-q", "-m", "essai"], capture_output=True, text=True,
                            env={**os.environ, **(env or {})})
    return result.returncode == 0, result.stderr


def test_fichier_propre_accepte(repo):
    ok, _ = commit(repo, {"notes.txt": "une liste de 7 actions\n", ".env.example": "ALPACA_API_KEY=\n"})
    assert ok


def test_cle_alpaca_refusee_sans_etre_affichee(repo):
    fake = "P" + "K" + "ABCDEFGHJ" * 2           # 20 caractères, forme d'un identifiant de clé paper
    ok, err = commit(repo, {"config.py": f'KEY_ID = "{fake}"\n'})
    assert not ok and "config.py" in err and "clé Alpaca" in err
    assert fake not in err                         # la valeur n'est jamais affichée


def test_fichier_env_refuse(repo):
    ok, err = commit(repo, {".env": "ALPACA_PAPER=true\n"})
    assert not ok and ".env" in err


def test_secret_en_clair_refuse(repo):
    line = "API" + "_KEY = '" + "x7Q2" * 6 + "'\n"
    ok, err = commit(repo, {"reglages.py": line})
    assert not ok and "reglages.py" in err


def test_fichier_trop_gros_refuse(repo):
    ok, err = commit(repo, {"donnees.json": "0" * 5000}, env={"GARDE_FOU_MAX_OCTETS": "1000"})
    assert not ok and "trop gros" in err
