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
