# Alpaca_trading

Deux outils, sur le marché actions US via Alpaca :

1. **Screener « reprise après baisse »** : chaque jour de bourse, une heure après l'ouverture, liste jusqu'à
   20 actions qui remplissent des critères fixés à l'avance, garde l'historique et produit un tableau de bord.
   Il ne passe aucun ordre. → [`research/algorithms/reprise_apres_baisse/README.md`](research/algorithms/reprise_apres_baisse/README.md)
2. **`trade.py`** : passage d'ordres manuel en ligne de commande (paper trading par défaut).

Les règles du dépôt sont dans [`CLAUDE.md`](CLAUDE.md) ; le journal de bord dans [`JOURNAL.md`](JOURNAL.md).

## Arborescence

| Chemin | Rôle |
|---|---|
| `core/` | Logique pure, sans réseau : univers, critères, invariant de datation |
| `infra/` | Accès réseau en lecture (Alpaca, Nasdaq Trader), cache disque, trace des runs |
| `research/algorithms/reprise_apres_baisse/` | Critères des deux versions (`criteres_sans_per.json`, `criteres_per12.json`) et run quotidien |
| `research/experiments/runs/reprise_apres_baisse/` | Historique : un dossier par séance (`results.json`) |
| `research/experiments/registry.csv` | Registre des runs |
| `dashboard/` | Gabarit et génération du tableau de bord (`index.html`, généré) |
| `tests/` | Datation, critères, frontières du code, secrets |
| `run_screener.sh` | Run du jour, régénération du tableau de bord, historique poussé sur GitHub |
| `live_bubbles.sh` | Suivi en direct des bulles par domaine pendant la séance |

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

## Screener

Lancer le run du jour (au plus tôt 1 h 15 après l'ouverture de New York), régénérer le tableau de bord,
puis commiter l'historique du jour et l'envoyer sur GitHub (tests verts et `git pull --ff-only` avant) :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/run_screener.sh
```

Ouvrir le tableau de bord dans Chrome (français, puis version anglaise ; un lien en haut de page
passe de l'une à l'autre) :

```bash
open -a "Google Chrome" /Users/theodoremeyer/Documents/Alpaca_trading/dashboard/index.html
```

```bash
open -a "Google Chrome" /Users/theodoremeyer/Documents/Alpaca_trading/dashboard/index_en.html
```

## Bulles en direct

Pendant la séance de New York, suivre la tendance moyenne de chaque domaine (classement SEC) :
journée, première heure, 2 séances, 1 semaine, 1 mois. Prix toutes bourses avec 15 minutes de retard
(offre gratuite Alpaca). Le tableau de bord est régénéré chaque minute et se recharge seul ; le suivi
s'arrête seul après la clôture (Ctrl+C pour l'arrêter avant) :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/live_bubbles.sh
```

**Démarrage automatique** (installé) : un service macOS ouvre chaque jour de semaine à 14 h 15 (Paris)
une fenêtre Terminal qui lance le suivi ; il attend l'ouverture, s'arrête seul après la clôture, ne
fait rien un jour férié, et un seul suivi tourne à la fois. Mac en veille à 14 h 15 : lancé au réveil.
Fermer la fenêtre arrête le suivi du jour. Journal : `~/Library/Logs/alpaca_trading_live.log`.

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/deploy/install_live_agent.sh
```

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/deploy/uninstall_live_agent.sh
```

Les mesures, séance en cours comprise : dernier prix / clôture d'il y a N séances − 1
(journée : N = 1 ; 2 séances : N = 2 ; 1 semaine : N = 5 ; 1 mois : N = 21). Première heure : prix à la
fin des 60 premières minutes / premier prix de la séance − 1, affichée 15 minutes après la fin de la
première heure. Dans le tableau de la sélection du jour, la colonne « Depuis l'ouverture » donne pour
chaque titre : dernier prix / premier prix de la séance − 1. Dernier prix = dernier échange de la séance régulière (ni pré-ouverture, ni après
16 h 00 : l'enchère de clôture n'est pas comptée). Chaque domaine se déplie en la liste de ses titres (mêmes colonnes, triables), avec deux comptages :
« Fois dans les 20 » (jours dans la sélection du screener) et « Fois top 20 du domaine » (séances
terminées finies parmi les 20 meilleurs de son domaine sur la journée). Chaque symbole (listes par domaine et
sélection du jour) ouvre au clic son graphique : 21 dernières clôtures et prix du jour, mis à jour en
direct. Les clôtures de tout l'univers sont écrites une fois par séance dans `dashboard/charts_data.js`
(non suivi par git). Univers : titres assez liquides (critères 2 à 4, identiques dans les deux versions). Seul le dernier
état en direct est gardé (`research/outputs/live/latest.json`, non suivi par git).

**Simulation (bas de page).** Pour chaque version de la liste : 10 k$, 25 k$, 50 k$, 100 k$ et 1 M$
répartis à parts égales sur ses titres, achetés au premier échange à partir de 10 h 45 (New York, liste
disponible) et vendus au dernier échange avant 15 h 30 (30 min avant la clôture). Gain en direct entre
les deux, figé ensuite et gardé dans l'état de fin de séance. Montants bruts, avant frais et impôts.

**Menu « Séance ».** Une entrée par jour de bourse. La séance du jour apparaît avec les premiers prix
et bouge en direct ; à la clôture elle est figée (provisoire le soir, définitive le lendemain avec les
corrections d'Alpaca, puis plus jamais modifiée). Une séance passée est chargée à la demande depuis
`dashboard/sessions/<date>.js` (régénéré depuis `research/experiments/final/`, non suivi par git).

**Fin de séance, même Mac fermé pendant la clôture.** L'état de fin de séance (bulles et colonne
« Ouverture → clôture ») est reconstitué depuis l'historique minute d'Alpaca : dernier échange de
chaque titre avant 16 h 00 (New York), sans l'enchère de clôture. Il est produit par le suivi en
direct après la clôture (ou à son réveil), et rattrapé pour toute séance manquée par `run_screener.sh`
ou à la main. Il est gardé dans `research/experiments/final/<famille>/<date>.json` et poussé sur GitHub
avec l'historique :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/.venv/bin/python -m dashboard.final reprise_apres_baisse
```

Lancer les tests :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/.venv/bin/python -m pytest /Users/theodoremeyer/Documents/Alpaca_trading
```

## trade.py

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

| `buy-list --amount 100000` | Acheter la liste du jour (version PER < 12 par défaut), montant réparti à parts égales, ordres au marché en dollars, après confirmation |
| `buy-list --amount 100000 --variant sans_per` | Même chose avec la liste sans PER |
| `sell-list` | Vendre au marché les positions des titres de la liste du jour (à lancer vers 15 h 30, New York), après confirmation |

`buy-list` et `sell-list` acceptent `--dry-run` (montrer le plan sans rien envoyer) et `--session AAAA-MM-JJ`.

Options : `--tif day|gtc|opg|cls|ioc|fok` (durée de validité, `day` par défaut), `-y` pour ne pas demander de confirmation.
Chaque ordre affiche un récapitulatif `[PAPER]` et demande confirmation avant l'envoi.
Les règles propres à Alpaca (fractions, `--notional`, `--tif` autorisés selon le type d'ordre) sont vérifiées par l'API, qui renvoie un message d'erreur explicite.

## Sécurité

- Paper trading par défaut. Le compte réel exige `ALPACA_PAPER=false` dans `.env` **et** des clés de compte réel.
- Le marché actions US est ouvert de 9h30 à 16h00, heure de New York. En dehors de ces horaires, un ordre `market` en `day` reste en attente jusqu'à l'ouverture.
