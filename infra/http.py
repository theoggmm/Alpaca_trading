"""
Requêtes HTTP en lecture (GET) : délai court, User-Agent identifié, cadence bornée (règle 10).
"""

import time

import requests

TIMEOUT_S = 10
USER_AGENT = "Alpaca_trading/0.1 (screener personnel, lecture seule)"


class FetchError(RuntimeError):
    pass


class Reader:
    def __init__(self, min_interval_s, headers=None):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, **(headers or {})})
        self._min_interval_s = min_interval_s
        self._last_request = 0.0

    def get(self, url, params=None):
        """Retourne la réponse (statut 200 exigé) ; lève FetchError sinon."""
        wait = self._min_interval_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        try:
            response = self._session.get(url, params=params, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            raise FetchError(f"Requête impossible vers {url} : {e}") from e
        if response.status_code in (401, 403):
            raise FetchError(f"{url} a répondu {response.status_code} : accès refusé, identifiants invalides ou révoqués")
        if response.status_code != 200:
            raise FetchError(f"{url} a répondu {response.status_code} : {response.text[:200]}")
        return response
