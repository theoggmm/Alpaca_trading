# Expérience 001 — La liste PER < 12 fait-elle mieux que la liste sans PER et que le marché ?

**Statut : pré-enregistré** le 15 octobre 2026, avant la première séance de la fenêtre de jugement.
Ce fichier est commité avant que la moindre donnée de la fenêtre existe ; ses seuils ne se réécrivent
jamais (règle 4 de `CLAUDE.md`). Toute modification de ce qui est figé ci-dessous = nouvelle expérience.

## Question

En achetant chaque jour la liste du screener une heure et quart après l'ouverture et en la revendant
30 minutes avant la clôture, la version **PER < 12** rapporte-t-elle plus que la version **sans PER**,
et plus que l'ensemble des titres liquides ?

## Mesure

- **Rendement d'une séance** pour une liste : champ `net_mean_return` de la simulation enregistrée dans
  l'état de fin de séance **définitif** (`research/experiments/final/reprise_apres_baisse/<date>.json`,
  `portfolio.versions.<version>`). Montant réparti à parts égales, achat au premier échange à partir de
  10 h 45 (New York), vente au dernier échange avant 15 h 30 (New York), coût de 5 points de base par
  ordre (achat et vente).
- **Liste PER < 12 vide** ce jour-là : rendement 0 (pas d'investissement, pas de frais).
- **Repère « univers »** : mêmes règles appliquées à tous les titres liquides du jour, à parts égales
  (`portfolio.benchmarks.univers`). **SPY** (`portfolio.benchmarks.spy`) : reporté à titre descriptif,
  sans hypothèse testée.
- **Séance sans état définitif ou sans simulation** : exclue du calcul et comptée à part dans le verdict.
- Calculs par `core/performance_metrics.py` uniquement (`summary`, `paired_difference`).

## Fenêtre de jugement

Les **40 séances** de bourse à partir du **16 octobre 2026** inclus (calendrier Alpaca). Les séances du
13, 14 et 15 octobre et tout test sur le passé sont des **diagnostics** : déjà regardés, ils ne comptent pas.

## Hypothèses et critères (chiffrés, figés)

Pour chaque hypothèse : écarts quotidiens appariés sur les séances de la fenêtre.
**Confirmée** si la moyenne des écarts est **> 0** et le t apparié **≥ 1,685** (test unilatéral à 5 %,
39 degrés de liberté). Sinon : **non confirmée** (ce qui ne prouve pas l'inverse).

| | Hypothèse |
|---|---|
| H1 | PER < 12 rapporte plus que sans PER |
| H2 | PER < 12 rapporte plus que l'univers liquide |
| H3 | Sans PER rapporte plus que l'univers liquide |

Le verdict reporte aussi, pour chaque série : rendement total, rendement annualisé (suspect au-delà de
100 %, règle 6), part des séances positives, pire séance.

## Figé pendant la fenêtre

`criteres_sans_per.json` (version 1), `criteres_per12.json` (version 2), heures d'achat et de vente,
`COST_BPS = 5` et `core/portfolio.simulate`.

## Juge

Ouvert par le propriétaire, explicitement, une seule fois, après la 40ᵉ séance (vers mi-décembre 2026).
Le verdict est écrit dans `research/experiments/decisions.md` avec les chiffres et le `git_sha`.

## Amendement 001.2 — fenêtre avancée au 15 octobre 2026 (propriétaire)

Écrit et commité le 15 octobre 2026 vers 10 h 44 (New York), **avant** que la liste du jour existe et
avant l'heure d'achat (10 h 45) : aucun résultat de la séance du 15 n'a été vu. Sur demande du
propriétaire, la fenêtre de jugement devient **les 40 séances à partir du 15 octobre 2026 inclus**.
Rien d'autre ne change : mesure, hypothèses, seuils (moyenne > 0 et t apparié ≥ 1,685) et éléments
figés restent ceux écrits ci-dessus. Les séances du 13 et 14 octobre restent des diagnostics.

## Amendement 001.3 — suspendue le 15 octobre 2026 au soir (propriétaire)

Le propriétaire règle encore les critères (règles contre l'achat au sommet ajoutées aux deux listes à
partir du 16 octobre) : la fenêtre ne peut pas tenir ce qui est « figé » ci-dessus. L'expérience est
**suspendue** ; aucune séance n'est comptée. Elle sera **pré-enregistrée à nouveau**, avec ses fichiers de
critères et une nouvelle fenêtre de 40 séances, le jour où le propriétaire figera les règles (dans environ
une semaine, selon lui). Seuils inchangés.
