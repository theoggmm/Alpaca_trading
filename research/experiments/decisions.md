# Journal des décisions

Append-only : on n'édite jamais une entrée passée. Décisions transversales `T#`, décisions d'expérience
`<expérience>.<n>`. Chaque entrée : date, décision, par qui, ce qu'elle autorise ou interdit.

## T1 — 2026-10-14 — Critère PER < 12 adopté (propriétaire)

Les critères version 2 (version 1 + PER sur 12 mois glissants < 12) sont appliqués à partir de la
séance du 15 octobre ; une liste de moins de 20 titres est acceptée.

## T2 — 2026-10-14 — Deux versions chaque séance (propriétaire)

Chaque séance produit une liste « sans PER » (version 1) et une liste « PER < 12 » (version 2).

## T3 — 2026-10-15 — Ordres passés uniquement à la main (propriétaire)

`trade.py buy-list` et `sell-list` préparent les ordres sur la liste du jour ; le propriétaire les
lance et les confirme lui-même. Aucun ordre automatique : aucune exception à la règle 11 n'est ouverte.

## 001.1 — 2026-10-15 — Pré-enregistrement de l'expérience 001

Fichier `research/algorithms/reprise_apres_baisse/experiences/001_per12_vs_sans_per.md`, commité avant
la fenêtre de jugement (40 séances à partir du 16 octobre 2026). Juge à ouvrir par le propriétaire.

## 001.2 — 2026-10-15 — Fenêtre de l'expérience 001 avancée au 15 octobre (propriétaire)

Le propriétaire demande que la séance du 15 octobre compte. Amendement écrit dans le fichier de
l'expérience et commité avant la publication de la liste du jour et avant l'heure d'achat (10 h 45,
New York) : aucun résultat de cette séance n'était connu. Fenêtre : 40 séances à partir du 15 octobre
2026. Seuils et mesure inchangés.

## T4 — 2026-10-15 — Deux versions contre l'achat au sommet (propriétaire)

À partir de la séance du 16 octobre, deux listes s'ajoutent aux deux existantes, inchangées :
version 3 « PER < 12 + confirmation » (prix à 10 h 45 ≥ prix à 10 h 30, achat à 11 h 00) et version 4
« PER < 12 + pas au sommet » (à 10 h 30, au moins 0,2 % sous le plus haut de la première heure). Les ordres
à passer restent calculés sur la liste PER < 12. Aucune règle de l'expérience 001 n'est modifiée.

## 002.1 — 2026-10-15 — Pré-enregistrement de l'expérience 002

Fichier `research/algorithms/reprise_apres_baisse/experiences/002_regles_contre_le_sommet.md`, commité
avant la première séance des versions 3 et 4 et avant leur test sur le passé. Fenêtre : 40 séances à
partir du 16 octobre 2026.

## T5 — 2026-10-15 — Deux listes, chacune avec les deux règles contre l'achat au sommet (propriétaire)

Remplace T4 avant tout run des versions 3 et 4. À partir du 16 octobre : « sans PER » (version 5) et
« PER < 12 » (version 6) = versions 1 et 2 + « pas au sommet » (à 10 h 30, au moins 0,2 % sous le plus haut
de la première heure) + « confirmation » (à 10 h 45, prix ≥ prix de 10 h 30). Décision à 10 h 45, listes et
achat à 11 h 00 (New York). Versions 1 à 4 archivées dans `research/algorithms/reprise_apres_baisse/archive/`.

## 001.3 — 2026-10-15 — Expérience 001 suspendue

Les règles sont en réglage pour environ une semaine (propriétaire) : l'expérience est suspendue et sera
pré-enregistrée à nouveau, avec une nouvelle fenêtre, quand les règles seront figées.

## 002.2 — 2026-10-15 — Expérience 002 retirée avant toute donnée

Remplacée par T5 (les deux règles dans les deux listes). Aucun run des versions 3 et 4.

## T6 — 2026-10-15 — Deux règles de tendance ajoutées aux deux listes (propriétaire)

Avant le premier run des versions 5 et 6 (16 octobre) : « marché en bonne forme » (la veille, SPY a clôturé
au-dessus de sa moyenne des 50 dernières séances ; sinon aucune liste ce jour-là) et « pas en chute » (à
10 h 30, prix au plus 5 % sous la moyenne des 50 dernières clôtures). Choisies après examen des séances du
13 au 15 octobre (diagnostic, 68 titres) : à vérifier par le test sur le passé.

## T7 — 2026-10-15 — Seuil de PER relevé de 12 à 25 (propriétaire)

Avant le premier run de la version 6 (16 octobre) : la liste avec PER retient les titres dont le PER sur
12 mois glissants est inférieur à 25 (et non plus 12). Fichier `criteres_per12.json` (nom et variante `per12`
gardés pour la continuité de l'historique). Les séances archivées (14 et 15 octobre) restent à 12.

## T8 — 2026-10-16 — Plusieurs stratégies suivies en parallèle (propriétaire)

En papier, à partir du 16 octobre : la stratégie principale (achat 11 h 00, vente 15 h 30) et quatre variantes,
chacune avec son tableau de bord : « achat à 10 h 30 » (mêmes règles sur la première demi-heure), « vente à la
clôture » (vente 15 h 55), et deux stratégies « ouverture » (autre logique : fin de veille en hausse, nuit en
hausse de +0,5 % à +3 % avant 9 h 15, marché en bonne forme ; achat 9 h 30, vente après 1 h ou 2 h). Règles
« ouverture » proposées par l'agent et retenues par défaut faute de réponse ; à tester sur le passé. Les ordres
à passer restent calculés sur la stratégie principale seulement.

## T9 — 2026-10-16 — Trois stratégies de nuit avec leur propre sélection (propriétaire)

En papier, à partir du 16 octobre : achat 15 h 00 et vente le lendemain à 10 h 30 ; achat 15 h 00 et vente le
lendemain à l'ouverture ; achat 15 h 55 et vente le lendemain à l'ouverture (New York). Sélection « fin de
journée » (core/closing.py), demandée par le propriétaire et chiffrée par l'agent : journée en hausse de +0,5 %
à +4 %, dernière heure avant la décision en hausse, au plus 1 % sous le plus haut du jour, marché en bonne forme,
PER < 25 pour la seconde liste ; décision 15 min avant l'achat. Le résultat d'une séance est compté le jour de
l'achat, une fois la vente du lendemain connue.

## T10 — 2026-10-16 — Vente anticipée de chaque titre : stop −1,5 %, objectif +3 % (propriétaire)

Toutes stratégies, toutes listes, en simulation : un titre est vendu dès qu'un cours minute (séance régulière)
passe 1,5 % sous son prix d'achat ou 3 % au-dessus, au cours de cette minute ; les autres titres restent jusqu'à
l'heure de vente. Les repères (univers liquide, SPY) n'ont pas de vente anticipée. Les tests sur le passé déjà
faits ne l'appliquent pas : à refaire.

## T11 — 2026-10-16 — Deux stratégies de plus (propriétaire)

« Achat à 10 h 30, vente à la clôture » (16 h 30 → 21 h 55, Paris : mêmes règles que « Achat à 10 h 30 », vente avant
15 h 55 New York), placée après « Achat à 10 h 30 » ; « Nuit : achat 15 h 55, vente le lendemain 10 h 30 » (21 h 55 →
16 h 30, Paris : sélection « fin de journée » décidée à 15 h 40 New York), placée en dernier. Dix stratégies en tout.

## T12 — 2026-10-16 — Confirmation : baisse de 0,2 % tolérée (propriétaire)

À partir du 19 octobre, pour les quatre stratégies « reprise après baisse » (principale, vente à la clôture,
achat à 10 h 30, achat à 10 h 30 / vente à la clôture) : une action est gardée si son prix à la confirmation n'est
pas plus de 0,2 % sous celui de la fin de la première période (avant : aucune baisse tolérée). Constat du
16 octobre : 37 des 43 titres écartés par la confirmation, la plupart pour quelques centièmes de pour cent ;
avec 0,2 % de tolérance, 18 titres auraient été gardés. Les listes du 16 octobre ne sont pas refaites.

## T13 — 2026-10-16 — Tolérance de 0,2 % appliquée dès les listes du 16 octobre (propriétaire)

Complète T12 : à la demande du propriétaire, la tolérance s'applique dès aujourd'hui. Les listes du 16 octobre des
quatre stratégies « reprise » sont refaites après coup (17 h 35 Paris) avec les mêmes données, tronquées à la même
heure de décision : principale r008/r009, vente_cloture, achat_10h30 et achat_10h30_vente_cloture r003/r004.
Les anciennes listes (r006/r007, r001/r002) restent dans l'historique ; la plus récente fait foi. Les prix d'achat
mis en cache pour 10 h 30 et 11 h 00 sont archivés (research/outputs/cache_superseded/) puis relus. Statut :
diagnostic papier — ces listes n'ont pas été connues à l'heure d'achat.

## T14 — 2026-10-16 — Comparaison « sans stop/objectif » (propriétaire)

Affichage seulement, aucune règle ne change : à côté de chaque résultat avec la vente à −1,5 % / +3 %, le même
calcul si chaque titre était gardé jusqu'à l'heure de vente (après frais) — accueil (aujourd'hui et depuis le
16 octobre, par liste), simulation, suivi des positions, historique des résultats. Séries `per12_sans_regle`,
`sans_per_sans_regle`. But : voir si la règle rapporte ou coûte.

## T15 — 2026-10-18 — Tests des 10 stratégies sur 2025 (diagnostic, propriétaire)

Demande du propriétaire : tester chaque stratégie sur un mois de baisse du S&P 500, six mois de 2025 et toute
l'année 2025. Mois retenu : mars 2025 (SPY −5,57 % clôture à clôture, le pire mois de 2025). Une passe sur les
250 séances de 2025 (backtest_strategies.py, git_sha 9f7922d), trois tranches par stratégie : mars, janvier-juin,
année. Règles actuelles, stop −1,5 % / objectif +3 %, 0,05 % de frais par ordre. Statut : diagnostic (fenêtre
passée, aucune règle ne change). Onglet « Tests » du tableau de bord. Mars 2025 : aucune liste, la règle « marché en
bonne forme » a bloqué tout le mois. Séance écourtée (3 juillet) : les achats de 15 h 00 sont impossibles, comptés 0.

## T16 — 2026-10-18 — Trois nouvelles stratégies (11 à 13), suivies en papier dès le 19 octobre (propriétaire)

Demande du propriétaire : proposer trois stratégies, nouvelles règles comprises, en combinant ce qui marche et
selon l'état du marché ; garde de quelques jours au plus (fixée à 3 séances, MAX_HOLD_SESSIONS).
- 11 nuit_marche_tient : liste « fin de journée » à 14 h 45 si SPY ≥ −0,2 % depuis l'ouverture ; vente à
  l'ouverture suivante ; stop −1,5 %, pas d'objectif.
- 12 bascule_fin_de_journee : 14 h 45 si le marché tient, sinon 15 h 40 si SPY a monté sur la dernière heure,
  sinon rien ; vente le lendemain 10 h 30 ; stop −1,5 %, pas d'objectif.
- 13 repli_tendance_3j : actions calmes en tendance (MM20 > MM50), 3 à 10 % sous le plus haut de 10 séances, en
  baisse le jour même ; achat 15 h 55, vente 3 séances plus tard à 15 h 55 ; stop −3 %, objectif +3 % ; capital
  en 3 tranches (achats qui se chevauchent).
Règles 11 et 12 choisies en lisant 2025 (diagnostic : 2025 n'est pas une preuve). Contrôle sur 2024, jamais
regardé avant (backtest_strategies --year 2024, mêmes règles, figées avant le lancement) :
11 : +0,6 % (PER) / +2,9 % (sans PER) ; 12 : +6,4 % / +3,3 % ; 13 : +4,9 % / +6,8 %. Les 10 stratégies d'avant
perdent toutes en 2024 (−3 % à −24 %). Règles figées à partir de maintenant ; jugement sur les séances futures.
Statut : diagnostic, paper trading seulement, aucun ordre.

## T17 — 2026-10-18 — Stratégies 14 à 23 (propriétaire), suivies en papier dès le 19 octobre

Demande du propriétaire : le plus possible avec 10 000 $, le moins de jours perdants ; puis trois stratégies gardées
plusieurs séances (achat dans la journée). 14 bascule sans stop, 15 nuit si le marché tient vendue 10 h 30 sans stop,
16 bascule actions en série (2 séances de hausse), 17 bascule actions calmes (30 %), 18 leaders de la semaine,
19 repli si le marché tient, 20 repli rapide (+2 %, 2 séances), 21 reprise gardée 2 séances, 22 repli du matin
3 séances, 23 leaders 3 séances. Tests 2024 et 2025 (diagnostic ; 14 et 15 choisies en lisant les deux années) :
meilleure moyenne à 10 000 $ : 14 sans PER, +52 $ par semaine, 55 % de séances investies positives, pire séance
−305 $. Aucune stratégie n'approche 5 000 $ par semaine ni n'est positive chaque jour. Règles figées ; jugement sur
les séances futures. Statut : diagnostic, paper trading seulement, aucun ordre.

## T18 — 2026-10-18 — Sélection du jour (propriétaire), suivie en papier dès le 19 octobre

Règle demandée : chaque séance, 0 à 3 stratégies (dernier résultat positif, puis 3 dernières séances), au plus 7 actions,
aucune si le marché va mal ; filtres publications de résultats (dates estimées d'après les 8-K 2.02 passés de la SEC),
secteur en baisse, largeur du marché, peur (VIXY). Candidates : stratégies de fin de journée gardées une nuit (7-12,
14-18). Code : core/selection.py, dashboard/daily_pick.py (en direct), selection_backtest.py (passé). Tests 2024 / 2025
(diagnostic) : règle complète −9,0 % / +4,0 % ; choix seul −16,8 % / +0,3 % ; toujours la stratégie 14 (7 actions)
+19,8 % / +55,5 %, avec garde-fous du marché +12,4 % / +29,2 %. Conclusion : le choix par résultats récents et les
filtres du jour font moins bien que la stratégie 14 seule. La sélection reste suivie en papier, à la demande du
propriétaire. Statut : diagnostic, aucun ordre.

## T19 — 2026-10-18 — Sélection du jour, version 2 (propriétaire), dès le 19 octobre

Remplace la règle T18 (choix par résultats récents, qui perdait). Toujours la stratégie 14 (sans PER, 7 premières
actions) ; pas d'achat le lundi ; pas d'achat si VIXY a bougé de plus de ±3 % depuis l'ouverture à 14 h 45 ; marché en
bonne forme. Plus de filtres largeur, publications, secteur. Règles trouvées sur les jours perdants de la stratégie 14
en 2024 et 2025, chacune vraie dans les deux années (diagnostic, pas une preuve) : +36,1 % (2024) et +62,7 % (2025)
contre +19,8 % et +55,5 % ; séances perdantes 62 et 47 contre 91 et 72 ; pire séance −3,3 % et −4,1 %. Contrôle hors
échantillon : 2021-2023 (tests en cours), puis les séances futures. Statut : diagnostic, papier, aucun ordre.

## T20 — 2026-10-18 — La règle en vigueur devient une stratégie (propriétaire)

« Règle en vigueur (version 2) » (strategies/regle_en_vigueur, ordre 0, en tête de l'accueil) : critères de la
stratégie 14 avec count 7, skip_weekdays [0] et market_max_fear_move 0,03 (VIXY) dans la liste elle-même, mesurés à
chaque heure de décision (14 h 45 ou 15 h 40). Même règle que T19, une seule implémentation (règle 8) : la sélection
du jour en direct (dashboard/daily_pick.py) et sa page sont archivées (dashboard/archive/). Tests 2024, 2025 et
semaine du 12 octobre lancés ; 2021-2023 avec les autres stratégies. Statut : diagnostic, papier, aucun ordre.

## T21 — 2026-10-19 — Règle en vigueur, version 3 (propriétaire : « adapter après 2021-2023 »)

Tests 2021-2023 : la version 2 fait +1,6 % / −17,8 % / −3,3 % (sans PER, 7 actions). Critère : ne garder que les
règles qui améliorent au moins 4 années sur 5. Gardées : pas le lundi (4/5) ; achat seulement si SPY est en hausse
depuis l'ouverture à 14 h 45 (market_min_day_return 0, 4/5). Retirée : peur calme (2/5). Nouvelle règle : critères de
nuit_tient_10h30 (fin de journée, décision 14 h 45, achat 15 h 00, vente le lendemain 10 h 30, sans stop ni objectif),
count 7, market_min_day_return 0, skip_weekdays [0]. Sur le passé (rejeu des 7 premières actions) : 2021 +24,2 %,
2022 −7,1 %, 2023 +2,5 %, 2024 +17,1 %, 2025 +36,2 %, cinq ans +89 % (version 2 : +73 %). Les cinq années ont servi au
choix (diagnostic) ; jugement sur les séances futures. Réglages de la version 2 archivés
(research/algorithms/reprise_apres_baisse/archive/regle_en_vigueur_v2/). Statut : papier, aucun ordre.

## T22 — 2026-10-19 — Règle « marché en bonne forme » suspendue le 19 octobre 2026 (propriétaire)

Le S&P 500 est sous sa moyenne de 50 séances : toutes les listes du jour sortaient vides. À la demande du propriétaire,
la règle est suspendue pour cette séance seulement (research/algorithms/reprise_apres_baisse/overrides.json,
« ignore_market_health »), toutes stratégies ; les autres règles restent (dont « pas le lundi » de la règle en
vigueur). Les listes du matin déjà sorties vides sont refaites avec les mêmes données, tronquées à la même heure de
décision ; les vides restent dans l'historique. Chaque run concerné porte un champ « override ». Statut : papier.

## T23 — 2026-10-19 — Règle « marché en bonne forme » suspendue aussi le 20 octobre, avec avertissement (propriétaire)

Le 20 octobre 2026 est ajouté à overrides.json. Chaque liste faite ainsi enregistre si la règle l'aurait bloquée
(« market_healthy », clôture de SPY la veille et sa moyenne de 50 séances, lues à la décision) ; si oui, un
avertissement s'affiche au-dessus de la liste et en haut de l'accueil (⚠ sur les stratégies concernées).

## T24 — 2026-10-20 — Liste « Nasdaq (7) » pour chaque stratégie (propriétaire)

Troisième liste (criteres_nasdaq.json) : règles de la liste sans PER, actions cotées sur le Nasdaq (champ exchange des
actifs d'Alpaca), toujours 7 titres (fill_to_count : critères relâchés pas à pas, core/fill.py, titres ajoutés marqués
« closest_fit »), sans règle de marché bloquante (bonne forme, tient / remonte — sauf le choix de l'heure d'une bascule —,
lundi, peur). Faite pour le 19 octobre (rejouée, données tronquées à chaque décision) et en direct dès le 20 octobre.
Statut : papier, aucun ordre.
