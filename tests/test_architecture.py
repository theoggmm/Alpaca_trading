"""
Frontières du code (CLAUDE.md, Conventions) :
- core/ ne fait aucun réseau et n'importe ni infra/, ni research/, ni dashboard/ ;
- infra/ n'importe ni research/, ni dashboard/ ;
- seuls les modules de ORDER_WRITERS écrivent chez le courtier ; tout le reste est en lecture.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# À déplacer dans infra/ (CLAUDE.md) : écart connu, en attente de décision du propriétaire.
ORDER_WRITERS = {"trade.py"}
ORDER_WRITE_MARKERS = ("submit_order", "replace_order", "cancel_order", "close_position",
                       "close_all_positions", ".post(", ".put(", ".patch(", ".delete(")

FORBIDDEN_IMPORTS = {
    "core": {"infra", "research", "dashboard", "requests", "alpaca", "urllib", "http", "socket", "subprocess"},
    "infra": {"research", "dashboard"},
}


def _python_files(*parts):
    return [p for p in ROOT.joinpath(*parts).rglob("*.py") if ".venv" not in p.parts]


def _imported_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_frontieres_d_import():
    for package, forbidden in FORBIDDEN_IMPORTS.items():
        for path in _python_files(package):
            bad = _imported_roots(path) & forbidden
            assert not bad, f"{path.relative_to(ROOT)} importe {sorted(bad)}"


def test_un_seul_module_ecrit_chez_le_courtier():
    for path in _python_files():
        relative = path.relative_to(ROOT)
        if relative.parts[0] == "tests" or str(relative) in ORDER_WRITERS:
            continue
        source = path.read_text(encoding="utf-8")
        found = [m for m in ORDER_WRITE_MARKERS if m in source]
        assert not found, f"{relative} contient {found} : seul {sorted(ORDER_WRITERS)} peut écrire"
