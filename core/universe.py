"""
Univers éligible : actions US cotées, négociables chez le courtier, hors ETF et hors titres de test.

Sources : la liste des actifs du courtier (Alpaca) et l'annuaire officiel des symboles
de Nasdaq Trader, qui porte l'indicateur ETF pour tous les titres cotés aux États-Unis.
"""


def eligible_symbols(assets, listings):
    """
    assets   : actifs du courtier, dicts avec "symbol", "class", "status", "tradable".
    listings : symbole -> {"name", "etf", "test_issue"} (annuaire Nasdaq Trader).
    Retourne (symboles triés, entonnoir {étape: nombre}).
    """
    tradable = [a["symbol"] for a in assets
                if a["class"] == "us_equity" and a["status"] == "active" and a["tradable"]]
    listed = [s for s in tradable if s in listings]
    stocks = [s for s in listed if not listings[s]["etf"] and not listings[s]["test_issue"]]
    funnel = {
        "actifs_negociables": len(tradable),
        "cotes_sur_une_bourse_us": len(listed),
        "hors_etf_et_titres_de_test": len(stocks),
    }
    return sorted(stocks), funnel
