"""
Trace des runs (règle 5) : research/experiments/runs/<famille>/<run_id>/results.json,
avec le git_sha réel du code qui l'a produit, et une ligne dans le registre.
"""

import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "research" / "experiments"
RUNS_DIR = EXPERIMENTS_DIR / "runs"
REGISTRY = EXPERIMENTS_DIR / "registry.csv"
REGISTRY_COLUMNS = ["run_id", "family", "session_date", "decision_time", "git_sha", "status", "n_selected"]
# Le code qui produit un run doit être commité : aucune modification en cours sur ces chemins.
CODE_PATHS = ("core", "infra", "research/algorithms", "dashboard")


class TraceError(RuntimeError):
    pass


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def committed_git_sha():
    """SHA du commit courant ; refuse si le code (CODE_PATHS) a des modifications non commitées."""
    pending = _git("status", "--porcelain", "--", *CODE_PATHS)
    if pending:
        raise TraceError(f"Code non commité, run refusé (règle 5) :\n{pending}")
    return _git("rev-parse", "HEAD")


def load_runs(family):
    """
    Tous les results.json de la famille, du plus ancien au plus récent (à séance égale, par numéro de run :
    un run recalculé pour une séance déjà produite vient après celui qu'il remplace à l'affichage).
    """
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in (RUNS_DIR / family).glob("r*/results.json")]
    return sorted(runs, key=lambda r: (r["decision_time"], r["run_id"]))


def variant_of(run):
    """Version des critères d'un run ; les runs antérieurs au champ « variant » se déduisent de leurs critères."""
    return run.get("variant") or ("per12" if run["criteria"].get("max_pe") else "sans_per")


def latest_per_session(runs):
    """Le run le plus récent de chaque séance et de chaque version (runs triés par load_runs)."""
    return list({(run["session_date"], variant_of(run)): run for run in runs}.values())


def next_run_id(family):
    numbers = [int(p.name[1:]) for p in (RUNS_DIR / family).glob("r[0-9][0-9][0-9]*") if p.name[1:].isdigit()]
    return f"r{max(numbers, default=0) + 1:03d}"


def save_run(family, payload):
    """Écrit results.json (jamais d'écrasement) et ajoute la ligne du registre. Retourne le chemin."""
    run_dir = RUNS_DIR / family / payload["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    path = run_dir / "results.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    new_registry = not REGISTRY.exists()
    with REGISTRY.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        if new_registry:
            writer.writeheader()
        writer.writerow({"family": family, "n_selected": len(payload["selection"]),
                         **{k: payload[k] for k in REGISTRY_COLUMNS if k in payload}})
    return path
