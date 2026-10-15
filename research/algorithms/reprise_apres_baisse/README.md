# Famille `reprise_apres_baisse`

**Statut : `diagnostic`.** Les critères ci-dessous sont fixés et commités avant le premier run, mais
aucune hypothèse de performance n'est pré-enregistrée et aucun juge n'est ouvert : la liste produite
n'est ni un verdict, ni une recommandation. Le système conclut (« ces titres remplissent les
critères ») ; il ne décide pas (règle 11 de `CLAUDE.md`).

## Mécanisme observé

Des actions calmes et très échangées qui ont baissé sur le dernier mois, puis montent depuis deux
séances et pendant la première heure de la séance du jour. L'idée du propriétaire : repérer une
reprise en cours après une baisse.

## Critères : deux versions produites à chaque séance

- **Sans PER** : `criteres_sans_per.json` (version 5), critères 1 à 10 ci-dessous avec 8 ter et 8 quater.
- **PER < 12** : `criteres_per12.json` (version 6), les mêmes + 8 bis.

Décision en deux temps (10 h 30 puis 10 h 45, New York), listes et achat à 11 h 00. Chaque séance produit un
run par version (champ `variant` : `sans_per`, `per12`). Versions précédentes dans `archive/` (1 et 2 :
sans les deux règles, utilisées du 13 au 15 octobre ; 3 et 4 : une règle chacune, retirées avant tout run).
Les runs r001 et r002 sont la version 1, r003 et r005 la version 2, r004 la version 1.
Les règles sont en réglage (propriétaire, 15 octobre 2026) : l'expérience 001 est suspendue.

### Détail des critères

Appliqués dans cet ordre, à l'instant de décision = ouverture de la séance + 60 minutes, puis + 15 minutes
pour la confirmation (heure de New York) :

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
| 8 bis | PER (version 2) | Prix à la décision / bénéfice dilué par action des 12 derniers mois < 12. Bénéfice US GAAP en dollars déclaré à la SEC, déposé avant le jour de décision ; bénéfice nul, négatif ou non disponible = titre exclu |
| 8 ter | Pas au sommet (versions 5 et 6) | Dernier prix à 10 h 30 ≤ plus haute clôture minute de la première heure × (1 − 0,002) |
| 8 quater | Confirmation (versions 5 et 6) | Dernier prix à 10 h 45 ≥ dernier prix à 10 h 30 ; la hausse de la première heure (critère 8) reste mesurée à 10 h 30 |
| 9 | Classement | Du plus fort repli sur 21 séances au plus faible (égalité : ordre alphabétique) |
| 10 | Diversification | Un titre n'est retenu que si sa corrélation (rendements quotidiens, 60 séances) avec chaque titre déjà retenu est ≤ 0,6 ; arrêt à 20 titres |

La liste n'est **jamais complétée** en assouplissant un critère : si moins de 20 titres passent, elle
en compte moins, et l'entonnoir (nombre de titres après chaque critère) l'indique.

Modifier un seuil = nouvelle version du fichier de critères concerné, commitée avant le run qui l'utilise.

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

- **Bénéfices (PER)** : SEC, `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/EarningsPerShareDiluted.json`. 12 mois glissants = dernier exercice, ou exercice précédent + cumul de l'exercice en cours − même cumul un an plus tôt. Les sociétés qui ne déposent pas ce poste en US GAAP (sociétés étrangères, certaines banques, fonds) sont exclues.

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
- **Test sur le passé = diagnostic** (`backtest.py`, résultats dans `backtests/b00N/`) : univers des
  titres encore cotés aujourd'hui (biais du survivant), indicateur ETF d'aujourd'hui, pas de repère
  « univers liquide ». Il ne sert pas de juge : seule l'expérience 001, sur les séances à venir, en sert.
- **Volatilité relative** : « basse » veut dire « dans la moitié la moins volatile ce jour-là », pas
  sous un seuil absolu.

## Trace

Chaque run écrit `research/experiments/runs/reprise_apres_baisse/r00N/results.json` (critères, sources,
entonnoir, sélection, `git_sha` du code commité) et une ligne dans `research/experiments/registry.csv`.
Un seul run par séance ; le run refuse de tourner si le code n'est pas commité. `run_screener.sh`
commite ensuite ces deux fichiers (et rien d'autre) et les pousse sur GitHub.

## Expérience 001 (pré-enregistrée)

`experiences/001_per12_vs_sans_per.md` : la liste PER < 12 rapporte-t-elle plus que la liste sans PER et
que l'univers liquide, après frais ? Fenêtre : 40 séances à partir du 15 octobre 2026 (amendement 001.2). Confirmée si
l'écart quotidien moyen est positif et le t apparié ≥ 1,685. Critères, heures, frais et simulation figés
pendant la fenêtre ; décision 001.1 dans `research/experiments/decisions.md`.

## Règles contre l'achat au sommet

Origine : AT&T le 15 octobre, retenue à +1,52 % sur la première heure, à son plus haut de la journée à
10 h 35, en baisse dès l'achat de 10 h 45. Dans `screen`, les règles 8 ter et 8 quater sont appliquées
après le critère 8 et avant le PER (entonnoir : `pas_au_sommet`, `confirmation`). L'expérience 002 (une
liste par règle) a été retirée avant toute donnée ; l'effet des règles se lit, en diagnostic, dans le test
sur le passé (versions actuelles contre versions 1 et 2).

## Historique des versions

- **Version 1** (13–14 octobre 2026, runs r001 et r002) : critères 1 à 10 sans PER.
- **Version 2** (à partir du 15 octobre 2026, décision du propriétaire) : + PER sur 12 mois glissants < 12.
  Diagnostic sur la séance du 14 octobre (déjà regardée, donc sans valeur de preuve) : 44 titres en hausse
  sur la première heure, 6 avec un PER < 12, 4 après diversification (PRI, WTRG, PRU, SIGI). La liste peut
  compter bien moins de 20 titres ; elle n'est jamais complétée.
- **Versions 3 et 4** (15 octobre 2026, décision T4) : une règle chacune ; retirées le soir même, avant tout
  run (décision T5).
- **Versions 5 et 6** (à partir du 16 octobre 2026, décision T5) : versions 1 et 2 + pas au sommet +
  confirmation ; listes et achat à 11 h 00.
