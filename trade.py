"""
Passage d'ordres sur Alpaca en ligne de commande.

Paper trading par défaut : le compte réel n'est utilisé que si ALPACA_PAPER=false
est écrit explicitement dans le fichier .env situé à côté de ce script.
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopLimitOrderRequest,
    StopOrderRequest,
)

from infra.alpaca_api import load_credentials
from infra.http import FetchError
from infra.trace import latest_per_session, load_runs, variant_of

FAMILY = "reprise_apres_baisse"
NEW_YORK = ZoneInfo("America/New_York")

PRICE_FIELDS = ("limit_price", "stop_price")

# Type d'ordre -> (classe de requête, champs de prix obligatoires)
ORDER_TYPES = {
    "market": (MarketOrderRequest, ()),
    "limit": (LimitOrderRequest, ("limit_price",)),
    "stop": (StopOrderRequest, ("stop_price",)),
    "stop_limit": (StopLimitOrderRequest, ("limit_price", "stop_price")),
}


@dataclass(frozen=True)
class Context:
    trading: TradingClient
    data: StockHistoricalDataClient
    paper: bool


def build_context():
    try:
        api_key, secret_key, paper = load_credentials()
    except FetchError as e:
        sys.exit(f"Erreur : {e}")
    return Context(
        trading=TradingClient(api_key, secret_key, paper=paper),
        data=StockHistoricalDataClient(api_key, secret_key),
        paper=paper,
    )


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #

def positive_decimal(text):
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"nombre invalide : {text}")
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError(f"doit être strictement positif : {text}")
    return value


def as_flags(fields):
    return ", ".join("--" + field.replace("_", "-") for field in fields)


def money(value):
    return f"{Decimal(value):,.2f} $"


def describe_order(order):
    """Résumé lisible, commun aux requêtes envoyées et aux ordres renvoyés par l'API."""
    size = f"qty={order.qty}" if order.qty is not None else f"notional={order.notional} $"
    prices = "".join(
        f" {field.removesuffix('_price')}={getattr(order, field)}"
        for field in PRICE_FIELDS
        if getattr(order, field, None) is not None
    )
    return (f"{order.side.value.upper()} {order.symbol} {size} "
            f"type={order.type.value}{prices} tif={order.time_in_force.value}")


def print_order(order):
    print(f"  [{order.status.value}] {describe_order(order)}")
    print(f"      id={order.id}  exécuté={order.filled_qty} @ {order.filled_avg_price or '-'}")


def confirm_or_abort(message, assume_yes):
    if not assume_yes and input(f"{message} [o/N] ").strip().lower() not in ("o", "oui"):
        sys.exit("Annulé.")


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #

def cmd_account(ctx, args):
    account = ctx.trading.get_account()
    clock = ctx.trading.get_clock()
    print(f"Compte        : {account.account_number} ({account.status.value})")
    print(f"Equity        : {money(account.equity)}")
    print(f"Cash          : {money(account.cash)}")
    print(f"Buying power  : {money(account.buying_power)}")
    print(f"P&L du jour   : {money(Decimal(account.equity) - Decimal(account.last_equity))}")
    print(f"Marché        : {'OUVERT' if clock.is_open else 'FERMÉ'} "
          f"(prochaine ouverture {clock.next_open}, prochaine fermeture {clock.next_close})")


def cmd_quote(ctx, args):
    symbol = args.symbol.upper()
    quote = ctx.data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]
    print(f"{symbol}  bid={quote.bid_price} x {quote.bid_size}   "
          f"ask={quote.ask_price} x {quote.ask_size}   ({quote.timestamp})")


def cmd_positions(ctx, args):
    positions = ctx.trading.get_all_positions()
    if not positions:
        print("Aucune position ouverte.")
    for p in positions:
        print(f"  {p.symbol:<6} qty={p.qty:<10} prix moyen={money(p.avg_entry_price):>14}  "
              f"actuel={money(p.current_price):>14}  valeur={money(p.market_value):>16}  "
              f"P&L={money(p.unrealized_pl)} ({Decimal(p.unrealized_plpc) * 100:+.2f} %)")


def cmd_orders(ctx, args):
    status = QueryOrderStatus.ALL if args.all else QueryOrderStatus.OPEN
    orders = ctx.trading.get_orders(filter=GetOrdersRequest(status=status, limit=args.limit))
    if not orders:
        print("Aucun ordre.")
    for order in orders:
        print_order(order)


def build_order_request(args):
    request_class, required = ORDER_TYPES[args.type]
    missing = [f for f in required if getattr(args, f) is None]
    unexpected = [f for f in PRICE_FIELDS if f not in required and getattr(args, f) is not None]
    if missing:
        sys.exit(f"Erreur : un ordre {args.type} requiert {as_flags(missing)}")
    if unexpected:
        sys.exit(f"Erreur : {as_flags(unexpected)} ne s'applique pas à un ordre {args.type}")

    # Le SDK attend des float ; un Decimal saisi (<= 15 chiffres significatifs) est restitué à l'identique.
    size = {"qty": float(args.qty)} if args.qty is not None else {"notional": float(args.notional)}
    prices = {f: float(getattr(args, f)) for f in required}
    return request_class(
        symbol=args.symbol.upper(),
        side=args.side,
        time_in_force=TimeInForce(args.tif),
        **size,
        **prices,
    )


def cmd_order(ctx, args):
    request = build_order_request(args)
    mode = "PAPER" if ctx.paper else "!!! RÉEL !!!"
    confirm_or_abort(f"[{mode}] {describe_order(request)}\nEnvoyer l'ordre ?", args.yes)
    print("Ordre envoyé :")
    print_order(ctx.trading.submit_order(order_data=request))


def cmd_cancel(ctx, args):
    ctx.trading.cancel_order_by_id(args.order_id)
    print(f"Demande d'annulation envoyée pour {args.order_id}.")


def cmd_cancel_all(ctx, args):
    confirm_or_abort("Annuler TOUS les ordres ouverts ?", args.yes)
    print(f"{len(ctx.trading.cancel_orders())} ordre(s) en cours d'annulation.")


def cmd_close(ctx, args):
    symbol = args.symbol.upper()
    confirm_or_abort(f"Clôturer toute la position {symbol} au marché ?", args.yes)
    print("Ordre de clôture envoyé :")
    print_order(ctx.trading.close_position(symbol))


# --------------------------------------------------------------------------- #
# Ordres sur la liste du screener (une version : sans PER ou PER < 12)
# --------------------------------------------------------------------------- #

def _session_list(variant, session):
    """Liste la plus récente d'une version pour une séance (date de New York, aujourd'hui par défaut)."""
    key = session or datetime.now(timezone.utc).astimezone(NEW_YORK).date().isoformat()
    runs = [r for r in latest_per_session(load_runs(FAMILY)) if r["session_date"] == key and variant_of(r) == variant]
    if not runs:
        sys.exit(f"Pas de liste « {variant} » pour la séance du {key} (elle est produite à 10 h 45, New York).")
    if not runs[0]["selection"]:
        sys.exit(f"La liste « {variant} » du {key} ({runs[0]['run_id']}) ne contient aucun titre.")
    return runs[0]


def cmd_buy_list(ctx, args):
    run = _session_list(args.variant, args.session)
    items = run["selection"]
    # Montant réparti à parts égales, arrondi au cent inférieur pour ne jamais dépasser le total.
    share = (args.amount / len(items)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    mode = "PAPER" if ctx.paper else "!!! RÉEL !!!"
    print(f"[{mode}] Liste {run['run_id']} ({args.variant}), séance du {run['session_date']} : {len(items)} titres, "
          f"{money(share)} chacun, {money(share * len(items))} au total (achat au marché, montant en dollars).")
    for item in items:
        price = Decimal(item["price_at_decision"])
        print(f"  {item['symbol']:<6} {item['name'][:40]:<40} {money(share):>14}  "
              f"≈ {(share / price).quantize(Decimal('0.0001'))} actions à ~{money(price)} (prix à la décision)")
    if args.dry_run:
        print("Mode --dry-run : aucun ordre envoyé.")
        return
    confirm_or_abort(f"Envoyer ces {len(items)} ordres d'achat au marché ?", args.yes)
    for item in items:
        request = MarketOrderRequest(symbol=item["symbol"], notional=float(share), side=OrderSide.BUY,
                                     time_in_force=TimeInForce.DAY)
        try:
            print_order(ctx.trading.submit_order(order_data=request))
        except APIError as e:
            print(f"  {item['symbol']} : ordre refusé par Alpaca : {e}")


def cmd_sell_list(ctx, args):
    run = _session_list(args.variant, args.session)
    symbols = {item["symbol"] for item in run["selection"]}
    positions = [p for p in ctx.trading.get_all_positions() if p.symbol in symbols]
    if not positions:
        sys.exit(f"Aucune position ouverte sur les titres de la liste {run['run_id']}.")
    mode = "PAPER" if ctx.paper else "!!! RÉEL !!!"
    print(f"[{mode}] Vente au marché des positions de la liste {run['run_id']} ({args.variant}) :")
    for p in positions:
        print(f"  {p.symbol:<6} qty={p.qty:<12} valeur={money(p.market_value):>14}  P&L={money(p.unrealized_pl)}")
    total = sum(Decimal(p.unrealized_pl) for p in positions)
    print(f"  P&L latent total : {money(total)}")
    if args.dry_run:
        print("Mode --dry-run : aucun ordre envoyé.")
        return
    confirm_or_abort(f"Vendre ces {len(positions)} positions au marché ?", args.yes)
    for p in positions:
        try:
            print_order(ctx.trading.close_position(p.symbol))
        except APIError as e:
            print(f"  {p.symbol} : ordre refusé par Alpaca : {e}")


def cmd_close_all(ctx, args):
    confirm_or_abort("Clôturer TOUTES les positions et annuler tous les ordres ?", args.yes)
    print(f"{len(ctx.trading.close_all_positions(cancel_orders=True))} position(s) en cours de clôture.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    parser = argparse.ArgumentParser(description="Trading Alpaca en ligne de commande")
    sub = parser.add_subparsers(dest="command", required=True)

    with_symbol = argparse.ArgumentParser(add_help=False)
    with_symbol.add_argument("symbol")
    with_confirm = argparse.ArgumentParser(add_help=False)
    with_confirm.add_argument("-y", "--yes", action="store_true", help="Ne pas demander de confirmation")

    sub.add_parser("account", help="Infos du compte et état du marché").set_defaults(func=cmd_account)
    sub.add_parser("quote", parents=[with_symbol], help="Dernier bid/ask").set_defaults(func=cmd_quote)
    sub.add_parser("positions", help="Positions ouvertes").set_defaults(func=cmd_positions)

    p = sub.add_parser("orders", help="Ordres (ouverts par défaut)")
    p.add_argument("--all", action="store_true", help="Inclure les ordres clôturés")
    p.add_argument("--limit", type=int, default=50, help="Nombre maximum d'ordres (défaut : 50)")
    p.set_defaults(func=cmd_orders)

    for side, label in ((OrderSide.BUY, "Ordre d'achat"), (OrderSide.SELL, "Ordre de vente")):
        p = sub.add_parser(side.value, parents=[with_symbol, with_confirm], help=label)
        size = p.add_mutually_exclusive_group(required=True)
        size.add_argument("--qty", type=positive_decimal, help="Nombre d'actions")
        size.add_argument("--notional", type=positive_decimal, help="Montant en $")
        p.add_argument("--type", default="market", choices=ORDER_TYPES)
        p.add_argument("--limit-price", type=positive_decimal)
        p.add_argument("--stop-price", type=positive_decimal)
        p.add_argument("--tif", default=TimeInForce.DAY.value, choices=[t.value for t in TimeInForce],
                       help="Durée de validité (défaut : day)")
        p.set_defaults(func=cmd_order, side=side)

    p = sub.add_parser("cancel", help="Annuler un ordre")
    p.add_argument("order_id")
    p.set_defaults(func=cmd_cancel)

    sub.add_parser("cancel-all", parents=[with_confirm], help="Annuler tous les ordres ouverts") \
        .set_defaults(func=cmd_cancel_all)
    sub.add_parser("close", parents=[with_symbol, with_confirm], help="Clôturer une position") \
        .set_defaults(func=cmd_close)
    sub.add_parser("close-all", parents=[with_confirm], help="Clôturer toutes les positions") \
        .set_defaults(func=cmd_close_all)

    with_list = argparse.ArgumentParser(add_help=False)
    with_list.add_argument("--variant", default="per12", choices=["per12", "sans_per"],
                           help="Version de la liste (défaut : per12, PER < 12)")
    with_list.add_argument("--session", help="Séance AAAA-MM-JJ (défaut : aujourd'hui, heure de New York)")
    with_list.add_argument("--dry-run", action="store_true", help="Montrer le plan sans rien envoyer")
    p = sub.add_parser("buy-list", parents=[with_list, with_confirm],
                       help="Acheter la liste du jour, montant réparti à parts égales")
    p.add_argument("--amount", type=positive_decimal, required=True, help="Montant total en $")
    p.set_defaults(func=cmd_buy_list)
    sub.add_parser("sell-list", parents=[with_list, with_confirm],
                   help="Vendre au marché les positions de la liste du jour").set_defaults(func=cmd_sell_list)

    return parser


def main():
    args = build_parser().parse_args()
    ctx = build_context()
    if not ctx.paper:
        print("ATTENTION : mode RÉEL activé (ALPACA_PAPER=false).", file=sys.stderr)
    try:
        args.func(ctx, args)
    except APIError as e:
        sys.exit(f"Erreur API Alpaca : {e}")


if __name__ == "__main__":
    main()
