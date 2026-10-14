"""
Domaine d'activité officiel des sociétés, lu dans les données EDGAR de la SEC.

Le domaine est le bureau d'examen de la SEC qui suit la société (champ ownerOrg, par exemple
« 06 Technology »), complété du code SIC. La SEC exige un User-Agent portant un nom et un e-mail
de contact (SEC_USER_AGENT dans .env) et au plus 10 requêtes par seconde.
"""

import json
import re
from datetime import timedelta
from decimal import Decimal

from infra import env
from infra.cache import cached
from infra.http import Reader

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
MIN_INTERVAL_S = 0.15
# Le bureau d'examen et le code SIC d'une société changent rarement : relus au plus tous les 30 jours.
PROFILE_MAX_AGE = timedelta(days=30)


def _profile(reader, cik):
    data = reader.get(SUBMISSIONS_URL.format(cik=cik)).json()
    owner_org = data.get("ownerOrg") or None
    return {
        "owner_org": owner_org,
        "domain": re.sub(r"^\d+\s+", "", owner_org) if owner_org else None,
        "sic": data.get("sic") or None,
        "sic_description": data.get("sicDescription") or None,
    }


CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/EarningsPerShareDiluted.json"


def _reader():
    return Reader(MIN_INTERVAL_S, {"User-Agent": env.require("SEC_USER_AGENT", "nom et e-mail de contact exigés par la SEC")})


def _tickers(reader, day):
    return cached(f"{day}/sec_company_tickers",
                  lambda: {v["ticker"]: int(v["cik_str"]) for v in reader.get(TICKERS_URL).json().values()})


def _eps_declarations(reader, cik):
    """Bénéfice dilué par action déclaré en dollars (normes US) : [{"start", "end", "val", "filed"}]."""
    response = reader.get(CONCEPT_URL.format(cik=cik), missing_ok=True)
    if response is None:
        return []
    data = json.loads(response.text, parse_float=Decimal)
    return [{"start": e["start"], "end": e["end"], "val": Decimal(str(e["val"])), "filed": e["filed"]}
            for e in data.get("units", {}).get("USD/shares", []) if "start" in e]


def eps(symbols, day):
    """
    symbole -> déclarations de bénéfice dilué par action (SEC, US GAAP, en dollars), lues le jour day.
    Un symbole inconnu de la SEC ou sans ces déclarations reçoit une liste vide.
    """
    reader = _reader()
    tickers = _tickers(reader, day)
    result = {}
    for symbol in symbols:
        cik = tickers.get(symbol.replace(".", "-"))
        result[symbol] = [] if cik is None else cached(f"{day}/sec_eps/{cik:010d}", lambda: _eps_declarations(reader, cik))
    return result


def profiles(symbols, day):
    """
    symbole -> {"cik", "owner_org", "domain", "sic", "sic_description"}.
    Un symbole inconnu de la SEC est absent du résultat.
    """
    reader = _reader()
    tickers = _tickers(reader, day)
    result = {}
    for symbol in symbols:
        cik = tickers.get(symbol.replace(".", "-"))  # la SEC écrit BRK-B, Alpaca BRK.B
        if cik is not None:
            profile = cached(f"sec/submissions/{cik:010d}", lambda: _profile(reader, cik), max_age=PROFILE_MAX_AGE)
            result[symbol] = {"cik": cik, **profile}
    return result
