# Expérience 002 — Une règle contre l'achat au sommet améliore-t-elle la liste PER < 12 ?

**Statut : pré-enregistré** le 15 octobre 2026 au soir, avant la première séance des nouvelles versions
et avant tout test sur le passé de leurs règles. Ce fichier est commité avant que la moindre donnée de la
fenêtre existe ; ses seuils ne se réécrivent jamais (règle 4 de `CLAUDE.md`).

## Origine

Séance du 15 octobre 2026 : AT&T (T) remplit tous les critères avec +1,52 % sur la première heure, atteint
son plus haut de la journée à 10 h 35 et redescend dès l'achat de 10 h 45. Un exemple n'est pas une preuve :
l'expérience mesure si l'une des deux règles proposées améliore réellement la liste.

## Versions comparées

| Version | Fichier | Règle ajoutée à la version 2 (PER < 12) | Achat |
|---|---|---|---|
| 2 · `per12` | `criteres_per12.json` | — (référence) | 10 h 45 |
| 3 · `per12_confirmation` | `criteres_per12_confirmation.json` | À 10 h 45, prix ≥ prix de 10 h 30 (`confirmation_minutes` = 15) | 11 h 00 |
| 4 · `per12_pas_au_sommet` | `criteres_per12_pas_au_sommet.json` | À 10 h 30, prix ≤ plus haute clôture minute de la première heure × (1 − 0,002) | 10 h 45 |

Vente : dernier échange avant 15 h 30 (New York) pour toutes. Heures de New York.

## Mesure

Identique à l'expérience 001 : `net_mean_return` de l'état de fin de séance **définitif**
(`portfolio.versions.<version>`), 5 points de base par ordre, parts égales ; liste vide = 0 ; séance sans
état définitif ou sans simulation : exclue et comptée à part. Calculs par `core/performance_metrics.py`.

## Fenêtre de jugement

Les **40 séances** à partir du **16 octobre 2026** inclus (calendrier Alpaca). Tout test sur le passé de
ces règles est un **diagnostic** et ne compte pas.

## Hypothèses et critères (chiffrés, figés)

Écarts quotidiens appariés sur les séances de la fenêtre. **Confirmée** si la moyenne des écarts est
**> 0** et le t apparié **≥ 1,685** (unilatéral, 5 %, 39 degrés de liberté). Sinon : **non confirmée**.

| | Hypothèse |
|---|---|
| H1 | PER < 12 + confirmation rapporte plus que PER < 12 |
| H2 | PER < 12 + pas au sommet rapporte plus que PER < 12 |

Le verdict reporte aussi, pour chaque version : rendement total, annualisé (suspect au-delà de 100 %),
part des séances positives, pire séance, nombre moyen de titres et nombre de séances à liste vide.

## Figé pendant la fenêtre

Les quatre fichiers de critères, les heures d'achat et de vente, `COST_BPS = 5`, `core/portfolio.simulate`,
et dans `core/screener.screen` les règles `min_gap_below_high` et `confirmation_minutes`.

## Juge

Ouvert par le propriétaire, explicitement, une seule fois, après la 40ᵉ séance. Verdict écrit dans
`research/experiments/decisions.md` avec les chiffres et le `git_sha`.
