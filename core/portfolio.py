"""
Simulation d'un investissement réparti à parts égales sur les titres d'une liste du screener.

Achat : premier échange à partir de l'heure d'entrée (la liste est disponible 15 min après la décision).
Vente : dernier échange avant l'heure de sortie (30 min avant la clôture). Entre les deux, la valeur
suit le dernier échange connu ; après la sortie, elle est figée. Fractions d'action admises.
Montants en Decimal (règle des nombres d'argent de CLAUDE.md).
"""

from decimal import ROUND_DOWN, Decimal

from core.datation import usable_bars
from core.screener import MINUTE, session_trades

AMOUNTS = (Decimal("10000"), Decimal("25000"), Decimal("50000"), Decimal("100000"), Decimal("1000000"))


def _first_open(bars, start):
    """symbole -> prix d'ouverture de la première barre commençant à start ou après."""
    after = bars[bars["timestamp"] >= start].sort_values("timestamp")
    return {symbol: group["open"].iloc[0] for symbol, group in after.groupby("symbol", sort=True)}


def _last_close(bars):
    """symbole -> prix de clôture de la dernière barre."""
    ordered = bars.sort_values("timestamp")
    return {symbol: group["close"].iloc[-1] for symbol, group in ordered.groupby("symbol", sort=True)}


def simulate(symbols, entry_bars, exit_bars, last_trades, entry_time, exit_time, now, amounts=AMOUNTS):
    """
    symbols     : titres de la liste.
    entry_bars  : barres minute à partir de entry_time (prix d'achat).
    exit_bars   : barres minute jusqu'à exit_time (prix de vente).
    last_trades : symbole -> (horodatage, prix), pour la valeur en cours entre l'achat et la vente.
    Retourne {"status": "waiting" | "live" | "closed", "n", "mean_return", "gains": {montant: gain}}.
    """
    entry_bars = usable_bars(entry_bars, MINUTE, now)
    exit_bars = usable_bars(exit_bars, MINUTE, min(now, exit_time))
    last_trades = session_trades(last_trades, entry_time, exit_time, now)

    entry = {s: p for s, p in _first_open(entry_bars, entry_time).items() if s in symbols}
    if now >= exit_time and set(entry) <= set(_last_close(exit_bars)):
        status, current = "closed", _last_close(exit_bars)
    else:
        status, current = "live", {s: price for s, (_, price) in last_trades.items()}
    held = [s for s in symbols if s in entry and s in current]
    if not symbols or not held:
        return {"status": "waiting", "n": len(symbols), "priced": 0, "mean_return": None, "gains": {}}

    returns = [current[s] / entry[s] - 1 for s in held]
    mean = sum(returns) / len(held)
    return {
        "status": status,
        "n": len(symbols),
        "priced": len(held),
        "mean_return": float(mean),
        # Montant réparti à parts égales sur les titres valorisés : gain = montant × variation moyenne.
        "gains": {str(amount): str((amount * mean).quantize(Decimal("0.01"))) for amount in amounts},
    }


def entry_prices(entry_bars, entry_time, now):
    """symbole -> prix d'achat : premier échange à partir de entry_time, connu à now."""
    entry_bars = usable_bars(entry_bars, MINUTE, now)

    return _first_open(entry_bars, entry_time)


def order_plan(symbols, prices, amount):
    """
    Nombre entier d'actions à acheter pour répartir amount à parts égales entre symbols, au prix indiqué.
    Part par titre = amount / nombre de titres ; quantité = part / prix arrondie à l'entier inférieur
    (jamais au-delà de la part). Un titre sans prix est listé sans quantité.
    Retourne {"share", "rows": [{"symbol", "price", "qty", "cost"}], "total_cost", "cash_left"}.
    """
    if not symbols:
        return {"share": None, "rows": [], "total_cost": "0.00", "cash_left": str(amount)}
    share = (amount / len(symbols)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    rows, total = [], Decimal("0")
    for symbol in symbols:
        price = prices.get(symbol)
        qty = None if price is None else int(share // price)
        cost = None if qty is None else (qty * price).quantize(Decimal("0.01"))
        total += cost or 0
        rows.append({"symbol": symbol, "price": None if price is None else str(price), "qty": qty,
                     "cost": None if cost is None else str(cost)})
    return {"share": str(share), "rows": rows, "total_cost": str(total), "cash_left": str(amount - total)}
