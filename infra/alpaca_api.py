"""
Accès en lecture seule à l'API Alpaca.

Les clés sont chargées depuis le fichier .env du dépôt par load_dotenv et ne sont jamais affichées.
Les montants sont lus en Decimal directement depuis le JSON (aucun passage par float).
"""

import json
from datetime import date, datetime, time
from decimal import Decimal

import pandas as pd

from infra import env
from infra.http import Reader

TRADING_URL = {True: "https://paper-api.alpaca.markets", False: "https://api.alpaca.markets"}
DATA_URL = "https://data.alpaca.markets"
# Limite Alpaca : 200 requêtes par minute ; on reste à 3 par seconde au plus.
MIN_INTERVAL_S = 0.34
SYMBOLS_PER_REQUEST = 500
# Une page de 10 000 barres minute met jusqu'à ~10 s à arriver (délai maximal de infra/http.py) : 5 000.
BARS_PER_PAGE = 10000   # maximum servi par Alpaca : deux fois moins de pages
BAR_COLUMNS = ["symbol", "timestamp", "open", "close", "volume"]


def load_credentials():
    """(clé, secret, paper) ; paper vaut True sauf si ALPACA_PAPER=false est écrit explicitement."""
    api_key = env.require("ALPACA_API_KEY", "clé API Alpaca")
    secret_key = env.require("ALPACA_SECRET_KEY", "clé secrète Alpaca")
    paper = env.optional("ALPACA_PAPER", "true").strip().lower() != "false"
    return api_key, secret_key, paper


def _json(response):
    return json.loads(response.text, parse_float=Decimal)


class AlpacaReader:
    def __init__(self):
        api_key, secret_key, self.paper = load_credentials()
        self._reader = Reader(MIN_INTERVAL_S, {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key})
        self.trading_url = TRADING_URL[self.paper]

    def sessions(self, start, end):
        """Séances entre deux dates incluses : [(date, ouverture, clôture)], heures de New York."""
        days = _json(self._reader.get(f"{self.trading_url}/v2/calendar",
                                      {"start": start.isoformat(), "end": end.isoformat()}))
        return [(date.fromisoformat(d["date"]), time.fromisoformat(d["open"]), time.fromisoformat(d["close"]))
                for d in days]

    def session(self, day):
        """(ouverture, clôture) de la séance du jour donné, heure de New York ; None si marché fermé."""
        found = [(o, c) for d, o, c in self.sessions(day, day) if d == day]
        return found[0] if found else None

    def assets(self):
        """Actifs actions US actifs : symbol, name, class, status, tradable, exchange."""
        assets = _json(self._reader.get(f"{self.trading_url}/v2/assets",
                                        {"status": "active", "asset_class": "us_equity"}))
        return [{k: a[k] for k in ("symbol", "name", "class", "status", "tradable", "exchange")} for a in assets]

    def splits(self, start, end):
        """
        Divisions et regroupements d'actions de tous les titres entre deux dates :
        [{"symbol", "ratio" (nouvelles actions pour une ancienne, Decimal), "ex_date" (ISO)}].
        """
        params = {"types": "forward_split,reverse_split", "start": start.isoformat(), "end": end.isoformat(),
                  "limit": 1000}
        rows = []
        while True:
            page = _json(self._reader.get(f"{DATA_URL}/v1/corporate-actions", params))
            for kind in ("forward_splits", "reverse_splits"):
                rows += [{"symbol": x["symbol"], "ratio": Decimal(str(x["new_rate"])) / Decimal(str(x["old_rate"])),
                          "ex_date": x["ex_date"]} for x in (page.get("corporate_actions") or {}).get(kind, [])]
            if not page.get("next_page_token"):
                return rows
            params["page_token"] = page["next_page_token"]

    def latest_trades(self, symbols, feed):
        """
        symbole -> (horodatage UTC, prix Decimal) du dernier échange connu.
        feed "delayed_sip" : toutes bourses, 15 minutes de retard (offre gratuite).
        """
        trades = {}
        for i in range(0, len(symbols), SYMBOLS_PER_REQUEST):
            page = _json(self._reader.get(f"{DATA_URL}/v2/stocks/trades/latest",
                                          {"symbols": ",".join(symbols[i:i + SYMBOLS_PER_REQUEST]), "feed": feed}))
            trades.update({symbol: (pd.Timestamp(t["t"]).to_pydatetime(warn=False), Decimal(str(t["p"])))
                           for symbol, t in (page.get("trades") or {}).items()})
        return trades

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
