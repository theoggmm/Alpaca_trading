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
puis commiter l'historique du jour et l'envoyer sur GitHub (tests verts et `git pull --ff-only` avant).
Deux listes par séance (sans PER, PER < 25), avec quatre règles de prudence (« marché en bonne forme »,
« pas en chute », « pas au sommet », « confirmation ») :
décision à 10 h 45 (New York), listes disponibles à 11 h 00. La tâche planifiée lance le script vers
17 h 02 (Paris) :

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

**Méthodologie.** Lien en haut du tableau de bord : `dashboard/methodologie.html` (anglais :
`methodology_en.html`), régénérée avec lui depuis `dashboard/methodology_template.html`. Seuils, heures,
frais et montants y sont lus dans le code et les fichiers de critères au moment de la génération.

## Stratégies

Plusieurs stratégies sont suivies en parallèle, chacune avec son tableau de bord ; l'accueil les compare :

```bash
open -a "Google Chrome" /Users/theodoremeyer/Documents/Alpaca_trading/dashboard/accueil.html
```

Une stratégie = un dossier : la principale est `research/algorithms/reprise_apres_baisse/` (`strategy.json` et
ses fichiers de critères) ; les autres sont dans `strategies/<id>/`. `strategy.json` donne le nom, la description
et l'heure de vente (`exit_before_close_minutes` ou `exit_after_open_minutes`) ; l'heure d'achat découle des
critères (décision + 15 min). Deux sortes de critères : « reprise après baisse » (`core/screener.py`) et
« ouverture » (`core/opening.py`, `"signal": "ouverture"`). Pour ajouter une stratégie : copier un dossier,
changer l'identifiant, la place (`order` : 1 en premier sur l'accueil et dans le menu), le nom et les heures. Le suivi en direct produit chaque liste dès que ses données sont
prêtes ; ses runs vont dans `research/experiments/runs/reprise_apres_baisse/strategies/<id>/`.

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

**Simulation (onglet Résultats, un tableau par version).** Pour chaque version de la liste : 10 k$, 25 k$, 50 k$, 100 k$ et 1 M$
répartis à parts égales sur ses titres, achetés au premier échange à partir de 10 h 45 (New York, liste
disponible) et vendus au dernier échange avant 15 h 30 (30 min avant la clôture). Gain en direct entre
les deux, figé ensuite et gardé dans l'état de fin de séance. Trois colonnes : **brut** ; **après frais**
(0,05 % par ordre, achat et vente : `COST_BPS` de `core/portfolio.py`) ; **actions entières** (nombre
d'actions arrondi à l'unité inférieure, reste non investi). Repères, mêmes règles : **univers liquide**
(tous les titres liquides du jour) et **SPY** (S&P 500). Avant impôts.

**Ordres à passer.** 10 000 $ répartis sur la liste avec PER en actions entières : symbole, nombre
d'actions, prix à saisir, coût, reste. En direct pendant la séance, puis figé sur le prix d'achat de 10 h 45.
Les ordres se passent à la main (`trade.py buy-list`, ci-dessous) : aucun programme n'en passe seul.

**Archive.** Les séances faites avec des règles remplacées (13, 14 et 15 octobre 2026) sont rangées dans
l'onglet Archive (résultats, courbe, listes) et dans un groupe « Archive » du menu « Séance » ; les résultats et
les comptages actuels partent du 16 octobre (`RULES_SINCE` de `dashboard/build.py`). Rien n'est effacé.

**Historique des résultats.** Chaque séance, rendement après frais de chaque version et des deux repères
(liste vide = 0 %) : résumé (séances, moyenne, total cumulé, annualisé — signalé ⚠ au-delà de
100 %, séances positives, pire séance), courbe cumulée et tableau par séance. Calculs par
`core/performance_metrics.py` uniquement. L'encadré suit l'**expérience 001**, pré-enregistrée
(`research/algorithms/reprise_apres_baisse/experiences/001_per12_vs_sans_per.md`) : 40 séances à partir
du 15 octobre 2026 (séance du jour comprise), critères chiffrés figés, verdict ouvert par le propriétaire seulement à la fin.

**Test sur le passé (diagnostic).** Rejoue les deux versions sur les 6 derniers mois avec le même code
(listes calculées à 10 h 30 avec les seules données connues à ce moment, mêmes règles d'achat, de vente
et de frais), comparées à SPY. Le résultat est écrit dans
`research/experiments/runs/reprise_apres_baisse/backtests/b00N/results.json` (avec `git_sha`) et affiché
en bas du tableau de bord. Biais connu : seuls les titres encore cotés aujourd'hui sont testés. Durée :
plusieurs dizaines de minutes la première fois (données mises en cache ensuite) :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/.venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest --months 6
```

Même test sur le dernier mois (affiché à côté : chaque durée garde son dernier résultat) :

```bash
/Users/theodoremeyer/Documents/Alpaca_trading/.venv/bin/python -m research.algorithms.reprise_apres_baisse.backtest --months 1
```

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

| `buy-list --amount 100000` | Acheter la liste du jour (version avec PER par défaut), montant réparti à parts égales, ordres au marché en dollars, après confirmation |
| `buy-list --amount 100000 --variant sans_per` | Même chose avec la liste sans PER |
| `sell-list` | Vendre au marché les positions des titres de la liste du jour (à lancer vers 15 h 30, New York), après confirmation |

`buy-list` et `sell-list` acceptent `--dry-run` (montrer le plan sans rien envoyer) et `--session AAAA-MM-JJ`.

Options : `--tif day|gtc|opg|cls|ioc|fok` (durée de validité, `day` par défaut), `-y` pour ne pas demander de confirmation.
Chaque ordre affiche un récapitulatif `[PAPER]` et demande confirmation avant l'envoi.
Les règles propres à Alpaca (fractions, `--notional`, `--tif` autorisés selon le type d'ordre) sont vérifiées par l'API, qui renvoie un message d'erreur explicite.

## Sécurité

- **Garde-fou anti-secrets** (`deploy/hooks/pre-commit`) : avant chaque commit, refuse un fichier `.env` ou de clé,
  une chaîne qui ressemble à une clé (Alpaca, GitHub, AWS, clé privée) ou un secret écrit en clair, et tout fichier de
  plus de 50 Mo ; n'affiche jamais la valeur trouvée. Prouvé par `tests/test_garde_fou.py`. À activer une fois par copie
  du dépôt :

```bash
git -C /Users/theodoremeyer/Documents/Alpaca_trading config core.hooksPath deploy/hooks
```

- Paper trading par défaut. Le compte réel exige `ALPACA_PAPER=false` dans `.env` **et** des clés de compte réel.
- Le marché actions US est ouvert de 9h30 à 16h00, heure de New York. En dehors de ces horaires, un ordre `market` en `day` reste en attente jusqu'à l'ouverture.
