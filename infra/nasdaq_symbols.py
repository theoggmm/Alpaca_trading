"""
Annuaire officiel des symboles cotés aux États-Unis, publié par Nasdaq Trader.

nasdaqlisted.txt couvre le Nasdaq ; otherlisted.txt couvre NYSE, NYSE American, NYSE Arca,
Cboe et IEX. Chaque ligne porte l'indicateur ETF (Y/N) et l'indicateur de titre de test.
"""

import csv
import io

from infra.http import Reader

FILES = {
    "nasdaqlisted": ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol"),
    "otherlisted": ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol"),
}
CREATION_PREFIX = "File Creation Time:"


def listings():
    """
    Retourne (symbole -> {"name", "etf", "test_issue"}, fichier -> horodatage de création publié).
    """
    reader = Reader(min_interval_s=1.0)
    symbols, created = {}, {}
    for name, (url, symbol_column) in FILES.items():
        lines = reader.get(url).text.splitlines()
        if not lines[-1].startswith(CREATION_PREFIX):
            raise ValueError(f"{url} : dernière ligne inattendue, fichier peut-être tronqué")
        created[name] = lines[-1].split("|")[0].removeprefix(CREATION_PREFIX).strip()
        for row in csv.DictReader(io.StringIO("\n".join(lines[:-1])), delimiter="|"):
            symbols[row[symbol_column]] = {
                "name": row["Security Name"].strip(),
                "etf": row["ETF"] == "Y",
                "test_issue": row["Test Issue"] == "Y",
            }
    return symbols, created
