"""
Cache disque des réponses réseau (règle 10). Volatil : research/outputs/ est ignoré par git.
"""

import pickle
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[1] / "research" / "outputs" / "cache"


def cached(key, fetch):
    """Valeur en cache pour key (chemin relatif au cache), sinon fetch() puis mise en cache."""
    path = CACHE_DIR / f"{key}.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    value = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(value))
    return value
