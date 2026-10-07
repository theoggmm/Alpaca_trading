# Alpaca_trading

Passage d'ordres sur Alpaca (paper trading par défaut) depuis le terminal, via le SDK officiel `alpaca-py`.

## Environnement

- Gestionnaire : `uv` (`/Users/theodoremeyer/.local/bin/uv`)
- Python 3.12 isolé dans `/Users/theodoremeyer/Documents/Alpaca_trading/.venv`
- Dépendances déclarées dans `pyproject.toml`, versions figées dans `uv.lock`

Reconstruire l'environnement :

```bash
/Users/theodoremeyer/.local/bin/uv sync --project /Users/theodoremeyer/Documents/Alpaca_trading
```

## Clés API

```bash
cp /Users/theodoremeyer/Documents/Alpaca_trading/.env.example /Users/theodoremeyer/Documents/Alpaca_trading/.env
```

Coller ensuite les clés **Paper Trading** (tableau de bord Alpaca → Paper → API Keys) dans `.env`. Ne jamais partager ce fichier.

## Utilisation

Toutes les commandes s'écrivent sous la forme :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/.venv/bin/python /Users/theodoremeyer/Documents/Alpaca_trading/trade.py account
```

| Sous-commande | Effet |
|---|---|
| `account` | Solde, buying power, P&L du jour, état du marché |
| `quote AAPL` | Dernier bid/ask |
| `buy AAPL --qty 1` | Achat de 1 action au marché |
| `buy AAPL --notional 100` | Achat pour 100 $ |
| `buy AAPL --qty 2 --type limit --limit-price 200` | Achat à cours limité |
| `sell AAPL --qty 1 --type stop --stop-price 180` | Vente stop |
| `sell AAPL --qty 1 --type stop_limit --stop-price 180 --limit-price 179` | Vente stop limite |
| `positions` | Positions ouvertes et P&L latent |
| `orders` / `orders --all` | Ordres ouverts / tous les ordres |
| `cancel <order_id>` | Annuler un ordre |
| `cancel-all` | Annuler tous les ordres ouverts |
| `close AAPL` | Clôturer une position au marché |
| `close-all` | Clôturer toutes les positions et annuler les ordres |

Options : `--tif day|gtc|opg|cls|ioc|fok` (durée de validité, `day` par défaut), `-y` pour ne pas demander de confirmation.
Chaque ordre affiche un récapitulatif `[PAPER]` et demande confirmation avant l'envoi.
Les règles propres à Alpaca (fractions, `--notional`, `--tif` autorisés selon le type d'ordre) sont vérifiées par l'API, qui renvoie un message d'erreur explicite.

## Sécurité

- Paper trading par défaut. Le compte réel exige `ALPACA_PAPER=false` dans `.env` **et** des clés de compte réel.
- Le marché actions US est ouvert de 9h30 à 16h00, heure de New York. En dehors de ces horaires, un ordre `market` en `day` reste en attente jusqu'à l'ouverture.
