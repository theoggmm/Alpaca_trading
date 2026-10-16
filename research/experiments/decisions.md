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
