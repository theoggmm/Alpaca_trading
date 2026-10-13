# Famille `reprise_apres_baisse`

**Statut : `diagnostic`.** Les critères ci-dessous sont fixés et commités avant le premier run, mais
aucune hypothèse de performance n'est pré-enregistrée et aucun juge n'est ouvert : la liste produite
n'est ni un verdict, ni une recommandation. Le système conclut (« ces titres remplissent les
critères ») ; il ne décide pas (règle 11 de `CLAUDE.md`).

## Mécanisme observé

Des actions calmes et très échangées qui ont baissé sur le dernier mois, puis montent depuis deux
séances et pendant la première heure de la séance du jour. L'idée du propriétaire : repérer une
reprise en cours après une baisse.

## Critères (`criteres.json`, version 1)

Appliqués dans cet ordre, à l'instant de décision = ouverture de la séance + 60 minutes (New York) :

| # | Critère | Valeur |
|---|---|---|
| 1 | Univers | Actions US actives et négociables chez Alpaca, présentes dans l'annuaire Nasdaq Trader, hors ETF et hors titres de test. Les cryptos sont exclues par construction (classe `us_equity`). |
| 2 | Historique complet | 61 clôtures quotidiennes, la dernière étant la séance précédente |
| 3 | Prix minimum | Dernière clôture ≥ 5 $ |
| 4 | Volume échangé | Moyenne de (clôture × volume) sur 20 séances ≥ 20 000 000 $ |
| 5 | Volatilité basse | Écart-type des rendements quotidiens sur 60 séances ≤ quantile 0,5 des titres restants (interpolation linéaire, `numpy.quantile`) |
| 6 | En baisse sur un mois | Rendement sur 21 séances < 0 |
| 7 | Hausse des derniers jours | Rendement > 0 à chacune des 2 dernières séances |
| 8 | Hausse première heure | Dernier cours connu à la décision > premier cours de la séance |
| 9 | Classement | Du plus fort repli sur 21 séances au plus faible (égalité : ordre alphabétique) |
| 10 | Diversification | Un titre n'est retenu que si sa corrélation (rendements quotidiens, 60 séances) avec chaque titre déjà retenu est ≤ 0,6 ; arrêt à 20 titres |

La liste n'est **jamais complétée** en assouplissant un critère : si moins de 20 titres passent, elle
en compte moins, et l'entonnoir (nombre de titres après chaque critère) l'indique.

Modifier un seuil = nouvelle version de `criteres.json`, commitée avant le run qui l'utilise.

## Tendance par domaine (bulles du tableau de bord)

Complément de lecture, **pas un critère de sélection**. Pour chaque domaine d'activité, moyenne simple
des variations sur 21 séances de tous les titres de l'univers liquide (critères 2 à 4 : historique
complet, prix minimum, volume échangé). Une bulle par domaine : verte si la moyenne est positive,
rouge si elle est négative, de taille proportionnelle au nombre de titres. Le nombre de titres du
jour retenus dans le domaine est indiqué dans la bulle.

Domaine = bureau d'examen de la SEC qui suit la société (champ `ownerOrg` d'EDGAR, par exemple
« 06 Technology »). Un titre inconnu de la SEC (fonds, certaines sociétés étrangères) n'est pas
classé et le nombre de ces titres est affiché. Si la SEC ne répond pas, la liste du jour est quand
même produite et l'erreur est enregistrée dans le run.

## Sources

- **Cours** : Alpaca, données consolidées (feed `sip`), ajustées des splits et dividendes. Offre gratuite :
  les 15 dernières minutes ne sont pas servies, d'où un run au plus tôt à 10 h 45 (New York).
- **Calendrier des séances** : Alpaca (`/v2/calendar`).
- **Indicateur ETF** : annuaire officiel de Nasdaq Trader (`nasdaqlisted.txt`, `otherlisted.txt`) ;
  l'horodatage de création des fichiers est enregistré dans chaque run.
- **Domaines** : SEC, `https://www.sec.gov/files/company_tickers.json` (symbole → CIK) et
  `https://data.sec.gov/submissions/CIK##########.json` (`ownerOrg`, `sic`, `sicDescription`).
  La SEC exige un User-Agent avec nom et e-mail de contact : variable `SEC_USER_AGENT` du `.env`.
  Profils mis en cache 30 jours.

## Limites connues

- **Diversification de la sélection** : elle se fait sur la corrélation des cours (le but recherché :
  limiter les titres qui bougent ensemble), pas sur le domaine SEC, qui sert seulement aux bulles.
- **Non testé sur le passé** : aucun backtest. L'historique des runs, produit au jour le jour, est la
  seule observation ; il pourra servir de juge sur le futur si une hypothèse est pré-enregistrée.
- **Volatilité relative** : « basse » veut dire « dans la moitié la moins volatile ce jour-là », pas
  sous un seuil absolu.

## Trace

Chaque run écrit `research/experiments/runs/reprise_apres_baisse/r00N/results.json` (critères, sources,
entonnoir, sélection, `git_sha` du code commité) et une ligne dans `research/experiments/registry.csv`.
Un seul run par séance ; le run refuse de tourner si le code n'est pas commité. `run_screener.sh`
commite ensuite ces deux fichiers (et rien d'autre) et les pousse sur GitHub.
