"""
Accès en lecture seule à l'API Alpaca.

Les clés sont chargées depuis le fichier .env du dépôt par load_dotenv et ne sont jamais affichées.
Les montants sont lus en Decimal directement depuis le JSON (aucun passage par float).
"""

import json
import os
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from infra.http import FetchError, Reader

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

TRADING_URL = {True: "https://paper-api.alpaca.markets", False: "https://api.alpaca.markets"}
DATA_URL = "https://data.alpaca.markets"
# Limite Alpaca : 200 requêtes par minute ; on reste à 3 par seconde au plus.
MIN_INTERVAL_S = 0.34
SYMBOLS_PER_REQUEST = 500
BARS_PER_PAGE = 10000
BAR_COLUMNS = ["symbol", "timestamp", "open", "close", "volume"]


def load_credentials():
    """(clé, secret, paper) ; paper vaut True sauf si ALPACA_PAPER=false est écrit explicitement."""
    load_dotenv(ENV_FILE)
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise FetchError(f"ALPACA_API_KEY et ALPACA_SECRET_KEY doivent être définis dans {ENV_FILE}")
    paper = os.getenv("ALPACA_PAPER", "true").strip().lower() != "false"
    return api_key, secret_key, paper


def _json(response):
    return json.loads(response.text, parse_float=Decimal)


class AlpacaReader:
    def __init__(self):
        api_key, secret_key, self.paper = load_credentials()
        self._reader = Reader(MIN_INTERVAL_S, {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key})
        self.trading_url = TRADING_URL[self.paper]

    def session(self, day):
        """(ouverture, clôture) de la séance du jour donné, heure de New York ; None si marché fermé."""
        days = _json(self._reader.get(f"{self.trading_url}/v2/calendar",
                                      {"start": day.isoformat(), "end": day.isoformat()}))
        if not days or days[0]["date"] != day.isoformat():
            return None
        return time.fromisoformat(days[0]["open"]), time.fromisoformat(days[0]["close"])

    def assets(self):
        """Actifs actions US actifs : symbol, name, class, status, tradable, exchange."""
        assets = _json(self._reader.get(f"{self.trading_url}/v2/assets",
                                        {"status": "active", "asset_class": "us_equity"}))
        return [{k: a[k] for k in ("symbol", "name", "class", "status", "tradable", "exchange")} for a in assets]

    def bars(self, symbols, timeframe, start, end):
        """
        Barres consolidées (feed SIP), ajustées des splits et dividendes, entre start et end (UTC).
        timeframe : "1Day" ou "1Min".
        """
        rows = []
        for i in range(0, len(symbols), SYMBOLS_PER_REQUEST):
            params = {
                "symbols": ",".join(symbols[i:i + SYMBOLS_PER_REQUEST]),
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": "all",
                "feed": "sip",
                "limit": BARS_PER_PAGE,
                "sort": "asc",
            }
            while True:
                page = _json(self._reader.get(f"{DATA_URL}/v2/stocks/bars", params))
                for symbol, bars in (page.get("bars") or {}).items():
                    rows.extend((symbol, datetime.fromisoformat(b["t"]), Decimal(str(b["o"])),
                                 Decimal(str(b["c"])), int(b["v"])) for b in bars)
                if not page.get("next_page_token"):
                    break
                params["page_token"] = page["next_page_token"]
        frame = pd.DataFrame(rows, columns=BAR_COLUMNS)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame
