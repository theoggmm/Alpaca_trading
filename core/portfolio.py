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
# Coût par ordre (achat et vente), en points de base : écart entre prix d'achat et de vente et frais.
# Hypothèse fixée et commitée avant l'expérience 001 ; 5 points de base = 0,05 % par ordre.
COST_BPS = Decimal("5")
# Impôt français sur les plus-values de cession d'actions d'un particulier résident, hors PEA :
# prélèvement forfaitaire unique 2026 = 12,8 % d'impôt sur le revenu + 18,6 % de prélèvements sociaux.
# Taux relevé le 15 octobre 2026 sur des sites spécialisés (socic.fr, dougs.fr, sinvestir.fr), NON
# confirmé sur impots.gouv.fr (règle 10). Hors simulation figée de l'expérience 001 : affichage seulement.
TAX_RATE = Decimal("0.314")
# Vente anticipée de chaque titre des listes (toutes stratégies, décision du propriétaire du 16 octobre 2026) :
# dès qu'un cours minute passe 1,5 % sous le prix d'achat (stop) ou 3 % au-dessus (objectif), le titre est vendu
# à ce cours ; le reste de la liste continue jusqu'à l'heure de vente.
STOP_LOSS = Decimal("0.015")
TAKE_PROFIT = Decimal("0.03")


def _first_open(bars, start):
    """symbole -> prix d'ouverture de la première barre commençant à start ou après."""
    after = bars[bars["timestamp"] >= start].sort_values("timestamp")
    return {symbol: group["open"].iloc[0] for symbol, group in after.groupby("symbol", sort=True)}


def _last_close(bars):
    """symbole -> prix de clôture de la dernière barre."""
    ordered = bars.sort_values("timestamp")
    return {symbol: group["close"].iloc[-1] for symbol, group in ordered.groupby("symbol", sort=True)}


def early_exits(path_bars, entry, entry_time, exit_time, now, stop_loss=STOP_LOSS, take_profit=TAKE_PROFIT):
    """
    Ventes anticipées : symbole -> {"at", "price", "reason"} au premier cours minute (clôture de la minute,
    séance régulière) entre l'achat et la vente qui atteint le stop (prix d'achat × (1 - stop_loss) ; None : pas de stop) ou
    l'objectif (× (1 + take_profit)), connu à now. Vente à ce cours : de quoi compter le glissement au-delà du seuil.
    take_profit None : pas d'objectif, seul le stop vend plus tôt (variante « stop seul » des tests).
    """
    path_bars = usable_bars(path_bars, MINUTE, min(now, exit_time))

    path_bars = path_bars[(path_bars["timestamp"] >= entry_time) & path_bars["symbol"].isin(list(entry))]
    result = {}
    for symbol, bars in path_bars.sort_values("timestamp").groupby("symbol", sort=True):
        low = None if stop_loss is None else entry[symbol] * (1 - stop_loss)
        high = None if take_profit is None else entry[symbol] * (1 + take_profit)
        if low is None and high is None:
            continue
        hit = bars[(False if low is None else bars["close"] <= low) | (False if high is None else bars["close"] >= high)]
        if not hit.empty:
            price = hit["close"].iloc[0]
            result[symbol] = {"at": hit["timestamp"].iloc[0].isoformat(), "price": price,
                              "reason": "stop" if low is not None and price <= low else "objectif"}
    return result


def simulate(symbols, entry_bars, exit_bars, last_trades, entry_time, exit_time, now, amounts=AMOUNTS,
             path_bars=None, take_profit=TAKE_PROFIT, stop_loss=STOP_LOSS):
    """
    symbols     : titres de la liste.
    entry_bars  : barres minute à partir de entry_time (prix d'achat).
    exit_bars   : barres minute jusqu'à exit_time (prix de vente).
    last_trades : symbole -> (horodatage, prix), pour la valeur en cours entre l'achat et la vente.
    path_bars   : barres minute entre l'achat et la vente (séance régulière) : si elles sont données, chaque
                  titre est vendu plus tôt s'il touche le stop ou l'objectif (early_exits). Sans elles
                  (repères), pas de vente anticipée.
    Retourne {"status": "waiting" | "live" | "closed", "n", "mean_return", "gains": {montant: gain}, ...}.
    """
    entry_bars = usable_bars(entry_bars, MINUTE, now)
    exit_bars = usable_bars(exit_bars, MINUTE, min(now, exit_time))
    last_trades = session_trades(last_trades, entry_time, exit_time, now)

    entry = {s: p for s, p in _first_open(entry_bars, entry_time).items() if s in symbols}
    # Après l'heure de vente : prix de vente = dernier échange avant elle ; un titre sans échange dans la
    # fenêtre de vente est écarté de la répartition (comme un titre sans échange à l'achat).
    if now >= exit_time:
        status, current = "closed", _last_close(exit_bars)
        if exit_bars.empty:
            # Prix de vente pas encore servis (15 min de retard) : dernier échange connu avant l'heure de vente,
            # sinon seuls les titres vendus au stop ou à l'objectif seraient comptés pendant ces minutes.
            current = {s: price for s, (_, price) in last_trades.items()}
    else:
        status, current = "live", {s: price for s, (_, price) in last_trades.items()}
    early = {} if path_bars is None else early_exits(path_bars, entry, entry_time, exit_time, now, stop_loss=stop_loss,
                                                               take_profit=take_profit)
    hold = dict(current)  # prix sans la règle stop / objectif : chaque titre gardé jusqu'à l'heure de vente
    current.update({s: e["price"] for s, e in early.items()})
    held = [s for s in symbols if s in entry and s in current]
    positions = None if path_bars is None else _positions(symbols, entry, current, early, status, last_trades, exit_bars,
                                                          hold)
    if not symbols or not held:
        return {"status": "waiting", "n": len(symbols), "priced": 0, "mean_return": None, "gains": {}, "early_exits": {},
                **({"positions": positions} if positions is not None else {})}

    returns = [current[s] / entry[s] - 1 for s in held]
    mean = sum(returns) / len(held)
    cost = COST_BPS / Decimal("10000")
    # Après frais : achat payé (1 + coût), vente reçue (1 - coût).
    net = sum(current[s] * (1 - cost) / (entry[s] * (1 + cost)) - 1 for s in held) / len(held)
    return {
        "status": status,
        "n": len(symbols),
        "priced": len(held),
        "mean_return": float(mean),
        # Montant réparti à parts égales sur les titres valorisés : gain = montant × variation moyenne.
        "gains": {str(amount): str((amount * mean).quantize(Decimal("0.01"))) for amount in amounts},
        "cost_bps": str(COST_BPS),
        "net_mean_return": float(net),
        "net_gains": {str(amount): str((amount * net).quantize(Decimal("0.01"))) for amount in amounts},
        # Actions entières (arrondies vers le bas) au prix d'achat, après frais ; le reste n'est pas investi.
        "whole_gains": {str(amount): str(_whole_shares_gain(amount, held, entry, current, cost)) for amount in amounts},
        # Titres vendus avant l'heure de vente (stop ou objectif) et leur rendement brut.
        "early_exits": {s: {"at": e["at"], "price": str(e["price"]), "reason": e["reason"],
                            "return": float(e["price"] / entry[s] - 1)} for s, e in early.items()},
        # Listes seulement (path_bars donné) : situation de chaque titre (suivi des positions).
        **({"positions": positions} if positions is not None else {}),
        # Listes seulement : le même calcul sans la règle stop / objectif (comparaison, rien n'est vendu autrement).
        **({} if path_bars is None else _without_rule(symbols, entry, hold, cost, amounts)),
    }


def _without_rule(symbols, entry, hold, cost, amounts):
    """Rendement moyen brut et après frais si chaque titre est gardé jusqu'à l'heure de vente (sans stop ni objectif)."""
    held = [s for s in symbols if s in entry and s in hold]
    if not held:
        return {}
    mean = sum(hold[s] / entry[s] - 1 for s in held) / len(held)
    net = sum(hold[s] * (1 - cost) / (entry[s] * (1 + cost)) - 1 for s in held) / len(held)
    return {"hold_mean_return": float(mean), "hold_net_mean_return": float(net),
            "hold_net_gains": {str(amount): str((amount * net).quantize(Decimal("0.01"))) for amount in amounts}}


def _positions(symbols, entry, current, early, status, last_trades, exit_bars, hold=None):
    """
    Situation de chaque titre de la liste : « not_bought » (pas encore acheté), « held » (encore détenu, valeur au
    dernier prix connu), « stop » / « objectif » (vendu plus tôt), « sold » (vendu à l'heure de vente). Avec le prix
    d'achat, le dernier prix ou le prix de vente, son heure, la variation brute et après frais.
    """
    cost = COST_BPS / Decimal("10000")
    exit_times = {sym: bars["timestamp"].max() for sym, bars in exit_bars.groupby("symbol")} if not exit_bars.empty else {}
    result = {}
    for s in symbols:
        if s not in entry:
            result[s] = {"state": "not_bought"}
            continue
        if s in early:
            state, at = early[s]["reason"], early[s]["at"]
        elif status == "closed":
            state, at = "sold", exit_times[s].isoformat() if s in exit_times else None
        else:
            state, at = "held", last_trades[s][0].isoformat() if s in last_trades else None
        price = current.get(s)
        result[s] = {"state": state, "entry": str(entry[s]), "price": None if price is None else str(price), "at": at,
                     "return": None if price is None else float(price / entry[s] - 1),
                     "net_return": None if price is None else float(price * (1 - cost) / (entry[s] * (1 + cost)) - 1)}
        # Sans la règle stop / objectif : même titre gardé jusqu'à l'heure de vente (ou dernier prix connu).
        kept = (hold or {}).get(s)
        result[s]["hold_net_return"] = (None if kept is None
                                        else float(kept * (1 - cost) / (entry[s] * (1 + cost)) - 1))
    return result


def after_tax(gains):
    """
    montant -> gain après impôt (texte, 2 décimales) : un gain perd TAX_RATE ; une perte n'est pas imposée
    et reste entière (elle réduit l'impôt sur les autres gains de l'année, ce que ce calcul ne compte pas).
    """
    def keep(gain):
        gain = Decimal(gain)
        return gain if gain <= 0 else (gain * (1 - TAX_RATE)).quantize(Decimal("0.01"))

    return {amount: str(keep(gain)) for amount, gain in gains.items()}


def _whole_shares_gain(amount, held, entry, current, cost):
    share = (amount / len(held)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    gain = Decimal("0")
    for s in held:
        qty = int(share // (entry[s] * (1 + cost)))
        gain += qty * (current[s] * (1 - cost) - entry[s] * (1 + cost))
    return gain.quantize(Decimal("0.01"))


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
