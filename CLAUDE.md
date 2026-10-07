# CLAUDE.md — <nom de ton projet>

> Chargé par Claude à chaque session. Ne contient que l'invariant : ce qui ne change pas d'une semaine
> à l'autre. Tout le reste est derrière un lien. Lisible par un humain en dix minutes.
> Les `<…>` et les « à déterminer » sont à remplir par le propriétaire du dépôt.

## Ce qu'est ce projet aujourd'hui

<Deux ou trois phrases, à remplir. Exemple de forme :>

1. **Une recherche de stratégies sur <marché : actions US, crypto, …>**, backtestée en local, selon
   le protocole de [`PROTOCOL.md`](PROTOCOL.md). État : <aucune expérience en cours / expérience 00N
   en cours, jugée sur le futur>.
2. **<Un serveur / rien>** : <ce qui tourne en continu, s'il y a quelque chose — un tableau de bord,
   un rafraîchissement quotidien>. → [`RUNBOOK.md`](RUNBOOK.md)

**Rien n'achète tout seul.** Tant qu'aucune décision humaine datée ne dit le contraire dans
`research/experiments/decisions.md`, aucun programme de ce dépôt ne passe d'ordre. Un ordre
automatique, s'il en existe un jour, est **borné** (un seul type d'ordre, une liste blanche, un
fichier d'arrêt), décidé par le propriétaire, écrit noir sur blanc ici (règle 11).

**Backtest d'abord ; le paper trading ensuite ; un live éventuel après, et seulement après.**

**Objectif du propriétaire** : <à déterminer — par exemple : « je veux +X % net par trade sur un
horizon de N jours, avec un capital de <ordre de grandeur> ». Toute mesure se reporte aussi avec cet
objectif, pas seulement en rendement à horizon fixe.>

Avant de commencer une session : lire la dernière entrée de [`JOURNAL.md`](JOURNAL.md). En finir une :
en écrire une.

## Règles non négociables

1. **Datation.** Toute donnée utilisée pour une décision prise en `t` est antérieure à `t`.
   L'invariant est **structurel**, pas conventionnel : la fonction qui calcule un signal reçoit
   l'indice de décision et **tronque les données à `[0, i)` dès sa première ligne**, ce qui rend une
   donnée de date `≥ i` physiquement inatteignable. Chaque famille livre le test qui le prouve
   (`tests/test_datation_modele.py` en est le modèle). → [`PROTOCOL.md`](PROTOCOL.md) §2
2. **Métriques.** Un seul module : `core/performance_metrics.py`. Le Sharpe se calcule sur des
   rendements de **portefeuille indexés par date**, jamais par trade. `sharpe()` lève
   `UndatedReturnsError` sur une série non datée et `DuplicateDateError` sur des dates dupliquées —
   on ne contourne pas ces exceptions, on agrège via `portfolio_returns_from_trades()`. Aucune
   réimplémentation, nulle part.
3. **Juge glissant.** Toute hypothèse est jugée **uniquement sur les données postérieures à son
   pré-enregistrement**. Une fenêtre déjà regardée est consommée : un re-run dessus est un
   **diagnostic**, jamais un verdict. Ouvrir un juge = acte humain explicite, une seule fois.
4. **Pré-enregistrement.** Hypothèse, méthode et critères chiffrés écrits et **commités AVANT** de
   regarder la donnée. Les seuils ne se réécrivent jamais après lecture. → [`PROTOCOL.md`](PROTOCOL.md) §1
5. **Trace.** Pas de verdict sans `research/experiments/runs/<famille>/<run_id>/` contenant les
   trades, `results.json` et un **`git_sha` réel** — jamais `working-tree`.
6. **Garde-fou de plausibilité.** Tout run affichant un **rendement annualisé > 100 %** est SUSPECT
   et **bloque la promotion** jusqu'à explication écrite. Reporter systématiquement le rendement
   total et le rendement annualisé, pas seulement Sharpe et drawdown.
7. **Secrets.** Jamais dans un fichier suivi par git : ni `.env`, ni clé d'API, ni identifiant, ni
   dans un log, un rapport ou un message de commit. **Aucun agent ne lit, n'affiche ni ne copie un
   fichier `.env`, sur le poste comme sur le serveur** ; les secrets ne sont chargés que par le code,
   via `load_dotenv`, et jamais imprimés. Un agent ne source donc jamais un `.env` dans un shell et
   n'en fait aucune copie. `tests/test_secrets.py` le vérifie. → [`SECURITE.md`](SECURITE.md)
8. **Un seul module de logique.** Backtest, paper et live importent le **même** module métier de
   `core/`. Aucune réimplémentation parallèle : la divergence entre « la version du backtest » et
   « la version du live » est la cause racine classique d'une perte réelle.
9. **Synchronisation.** **Local ↔ GitHub · serveur ↔ GitHub · JAMAIS local ↔ serveur.** Aucun
   `scp`, aucun `rsync` entre le poste et le serveur, dans aucun sens, pour aucun fichier. Ce qui
   doit passer d'une machine à l'autre passe par un commit : le serveur reçoit le code par
   `git pull --ff-only` et livre ses journaux par `git push` ; le local les récupère par `git pull`.
10. **Preuve avant estimation.** Une date, un prix, un événement n'est **confirmé** que sur une
    source officielle (le document de la société, le régulateur, le courtier), jamais sur une
    estimation ou un calendrier tiers seul. Deux sources en désaccord = non confirmé, signalé.
    Chaque requête réseau dans son propre `try`, timeouts courts, `User-Agent` identifié, cache
    disque, cadence respectée. Aucun clic humain ne remplace une preuve.
11. **Conclure ≠ décider.** Le système **peut conclure** : un énoncé daté, chiffré et sourcé (une
    probabilité, un comptage, une comparaison) qui porte toujours **n**, sa **source** (run,
    `git_sha`, fenêtre) et son **statut** (`diagnostic` · `pré-enregistré` · `jugé forward`). Il
    **ne décide jamais** : aucun ordre, aucun « buy / sell / hold », aucune taille de position. La
    décision est un acte humain, pris hors du système et **observé** par lui.
    **Exception possible, bornée, à écrire ici le jour où elle existe** : <aucune pour l'instant>.
    Si un jour le système passe un ordre, l'entrée de `decisions.md` qui l'autorise précise : le
    seul type d'ordre permis, la liste blanche du module d'écriture (un seul module dans `infra/`),
    le préfixe des identifiants d'ordres, le fichier d'arrêt `config/state/KILL_SWITCH`, le journal
    append-only de chaque action, et ce qui reste interdit (tout achat automatique, tout ordre au
    marché, toute vente à découvert, tout ordre sur un titre non détenu).

### Garde-fous d'action (aucun agent ne les franchit seul)

- **Ouvrir un juge (holdout)** = acte humain explicite.
- **Promouvoir un algo** (paper ou live) = acte humain explicite.
- **Toucher au serveur ou au capital** = acte humain explicite. Un agent prépare les commandes et
  les scripts (`deploy/`) ; le propriétaire les exécute.
- **Archive avant destruction** : `mv` vers un dossier d'archive avant tout `rm`.
- **Audit ≠ permission de modifier.** Un bug trouvé pendant une relecture se signale ; il se
  corrige sur validation.
- **Avant de coder, chercher.** Une fonction demandée existe peut-être déjà dans `core/` ou
  `infra/` : on l'importe, on ne la recopie pas. Deux implémentations d'une même chose = un bug.

## Conventions

- **Un dossier par FAMILLE** (= un mécanisme économique) sous `research/algorithms/<famille>/`,
  miroir dans `research/outputs/<famille>/` (volatil, gitignoré) et
  `research/experiments/runs/<famille>/` (durable). Une variante vit SOUS sa famille, jamais à côté.
- **Identifiants** : expérience `00N` par famille · décision `<exp>.<n>` (transversales `T#`) ·
  run `r00N` relatif à la famille.
- **Frontière** : `research/`, `live/` et `dashboard/` importent `core/` et `infra/` ; `core/` et
  `infra/` n'importent jamais les autres (`tests/test_architecture.py`). `core/` ne fait aucun
  réseau ; `infra/` ne contient aucune logique de décision.
- **Un seul module écrit chez le courtier**, dans `infra/`, nommé dans `tests/test_architecture.py`
  (`ORDER_WRITERS`). Tout le reste est en lecture (`GET`) et un test le prouve.
- **Nomenclature** : le vocabulaire du courtier tel quel pour ses objets (`account.cash`,
  `position.qty`, `order.side`) ; le reste en `snake_case` ; l'objet de configuration racine
  s'appelle `config`. Les nombres d'argent en `Decimal`, jamais en `float`.
- **Python <3.12>**, `venv/`. **Un seul environnement** : `requirements.txt` épinglé (`==`),
  identique en local et sur le serveur, `pytest` inclus. Rien n'est installé à la main hors de ce
  fichier.
- Chemins auto-détectés par `Path(__file__).resolve().parents[N]`, aucun chemin absolu en dur.
- **Un objectif par commit**, message explicite. Branche `main` par défaut ; chantier long =
  branche + worktree. Jamais `--force`, `--amend`, `--no-verify` sans demande explicite.
  **`git pull` avant `git push`**. Tests verts avant chaque push.
- **Rapports au propriétaire.** Un rapport, une entrée de journal, une réponse en session commence
  par **rappeler la question posée**, en une phrase. Chaque paragraphe (et chaque table) se termine
  par **une phrase simple, sans mot technique**, qui dit ce que ça signifie pour lui — par exemple :
  « Autrement dit : acheter à l'ouverture après cette nouvelle perd de l'argent, quelle que soit
  l'année. » Un paragraphe sans cette phrase n'est pas fini.
- **Les docs décrivent le code, pas l'inverse.** Si une doc contredit le code, c'est la doc qui a
  tort : on le signale et on la corrige dans le **même commit** que le travail concerné.

## Faits d'infrastructure (permanents — à remplir)

- **Courtier** : <nom>. Clés : <paper / live>, droits <lecture seule / ordres>. Feed de données :
  <consolidé / partiel>, abonnement <à déterminer>. Les clés du monitoring servent en **lecture
  seule**.
- **Historique des délistés** : <le fournisseur sert-il l'historique des titres disparus ? à
  vérifier avant tout backtest — sinon l'univers est biaisé>.
- **Serveur** : <aucun / un, décrit dans `RUNBOOK.md` : système, utilisateur de service sans
  privilège, clé SSH dédiée, dépôt cloné depuis GitHub, `.env` en `640` propriété de l'utilisateur de
  service>.
- **Fuseau horaire des marchés** : <ex. heure de New York>. Tout horaire de timer s'écrit dans ce
  fuseau, jamais dans l'heure locale du serveur.

## Où trouver le reste

| Fichier | Contenu |
|---|---|
| [`README.md`](README.md) | Entrée humaine : à quoi sert ce dépôt, comment démarrer |
| [`SPEC.md`](SPEC.md) | Ce que le système EST : arborescence, modules, contrats de données |
| [`PROTOCOL.md`](PROTOCOL.md) | Protocole expérimental : pré-enregistrement → juge → verdict |
| [`SECURITE.md`](SECURITE.md) | Secrets, clés, serveur, kill switch |
| [`ROADMAP.md`](ROADMAP.md) | Où on va, et ce qui est réfuté (à ne pas ressusciter) |
| [`JOURNAL.md`](JOURNAL.md) | Journal de bord append-only, une entrée par session |
| [`RUNBOOK.md`](RUNBOOK.md) | Opérations du serveur |
| [`GLOSSAIRE.md`](GLOSSAIRE.md) | Les mots techniques, expliqués |
| `research/experiments/decisions.md` | Journal des décisions, append-only — **on n'édite jamais une entrée passée** |
| `research/experiments/registry.csv` | Registre des runs |

**Compétences disponibles** (`.claude/skills/`) : pré-enregistrement d'expérience, écriture d'un
verdict, ouverture de juge, vérification de l'invariant de datation, métriques de performance.
Elles se déclenchent seules quand la tâche correspond.

## En cas de doute

L'état courant fait foi dans cet ordre : le **code**, puis `decisions.md`, puis les docs de tête.
Quand une règle de ce fichier et une demande en session se contredisent : on s'arrête, on cite la
règle, on demande au propriétaire — on ne contourne pas en silence.
