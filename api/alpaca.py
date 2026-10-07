"""
Serverless function to fetch Alpaca trading data
"""
import json
import os
from alpaca.trading.client import TradingClient

def handler(request):
    """Fetch account data from Alpaca API"""
    try:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")

        if not api_key or not secret_key:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing API keys"})
            }

        trading = TradingClient(api_key, secret_key, paper=True)

        # Get account data
        account = trading.get_account()
        positions = trading.get_all_positions()
        orders = trading.get_orders(limit=10)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "account": {
                    "equity": str(account.equity),
                    "cash": str(account.cash),
                    "buying_power": str(account.buying_power)
                },
                "positions": [
                    {
                        "symbol": p.symbol,
                        "qty": p.qty,
                        "avg_entry_price": str(p.avg_entry_price),
                        "current_price": str(p.current_price),
                        "unrealized_pl": str(p.unrealized_pl)
                    }
                    for p in positions
                ],
                "orders": [
                    {
                        "id": o.id,
                        "symbol": o.symbol,
                        "qty": o.qty,
                        "status": o.status.value,
                        "side": o.side.value
                    }
                    for o in orders
                ]
            }),
            "headers": {"Content-Type": "application/json"}
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
