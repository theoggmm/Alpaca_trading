"""
Cache disque des réponses réseau (règle 10). Volatil : research/outputs/ est ignoré par git.
"""

import pickle
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[1] / "research" / "outputs" / "cache"


def cached(key, fetch, max_age=None):
    """
    Valeur en cache pour key (chemin relatif au cache), sinon fetch() puis mise en cache.
    max_age (timedelta) : au-delà, la valeur est relue à la source.
    """
    path = CACHE_DIR / f"{key}.pkl"
    if path.exists() and (max_age is None or time.time() - path.stat().st_mtime <= max_age.total_seconds()):
        return pickle.loads(path.read_bytes())
    value = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(value))
    return value
