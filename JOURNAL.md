# Journal de bord

Append-only : une entrée par session, la plus récente en bas. On n'édite jamais une entrée passée.

## 2026-10-13 — Screener « reprise après baisse »

**Question posée** : chaque jour, une heure après l'ouverture de New York, lister 20 actions US
diversifiées, calmes et très échangées, en baisse sur le dernier mois mais en hausse depuis deux
séances et pendant la première heure, avec un tableau de bord et un historique.

**Fait** :
- Famille `reprise_apres_baisse` : critères chiffrés dans `criteres.json` (version 1), commités avant
  tout run. Statut `diagnostic` : aucune hypothèse de performance pré-enregistrée, aucun juge ouvert.
- `core/` (logique pure, troncature à l'instant de décision dès la première ligne), `infra/` (lectures
  Alpaca et Nasdaq Trader, cache disque, trace des runs avec `git_sha`), `dashboard/` (page générée).
- Tests verts (14) : datation, critères, frontières du code, secrets.
- `trade.py` charge désormais ses clés via `infra.alpaca_api.load_credentials` (une seule implémentation).
- Tâche planifiée `screener-reprise-apres-baisse` : du lundi au vendredi à 17 h 00 (Paris), quand
  l'application Claude est ouverte.

Autrement dit : le screener est prêt et testé, mais il n'a encore jamais tourné sur de vraies données.

**Bloquant** : les clés Alpaca du `.env` sont refusées (401). Elles ont sans doute été régénérées
ou révoquées. Le propriétaire doit en créer de nouvelles (compte paper) et les coller dans `.env`.

**Écarts à `CLAUDE.md`, signalés et non tranchés** :
- Le minuteur de la tâche planifiée est en heure de Paris (l'outil ne connaît que l'heure locale).
  Le run calcule lui-même l'heure de New York et refuse de tourner avant 10 h 45 (New York) ;
  17 h 00 à Paris tombe toujours après, même pendant les semaines de décalage des changements d'heure.
- `trade.py` écrit chez le courtier depuis la racine du dépôt, pas depuis `infra/`.
- Environnement `uv` + `.venv` + `pyproject.toml`, au lieu de `venv/` + `requirements.txt` épinglé.
- `pyproject.toml` liste encore Flask et gunicorn, devenus inutiles.
- Les `<…>` de `CLAUDE.md` restent à remplir ; `PROTOCOL.md`, `SPEC.md`, `SECURITE.md` n'existent pas.

Autrement dit : rien de tout cela n'empêche le screener de fonctionner, mais ce sont des points à
décider par le propriétaire.

## 2026-10-13 (suite) — Historique sur GitHub et bulles par domaine

**Question posée** : faire apparaître l'historique sur GitHub chaque jour, et ajouter des bulles
qui montrent la tendance moyenne de chaque domaine, en vert si elle est positive, en rouge sinon.

**Fait** :
- Premier vrai run `r001` (séance du 2026-10-13) : 20 titres sur 20, entonnoir 13 499 → 20.
- `run_screener.sh` commite uniquement l'historique (runs et registre) et le pousse sur GitHub,
  après des tests verts et un `git pull --ff-only`. `r001` est sur GitHub.
- Bulles par domaine (choix du propriétaire : domaines officiels de la SEC, variation sur un mois
  de tout le domaine). Domaine = bureau d'examen de la SEC (`ownerOrg`). Complément de lecture,
  pas un critère. 16 tests verts.

Autrement dit : l'historique est sauvegardé en ligne chaque jour et le tableau de bord aura ses
bulles dès le prochain run.

**En attente** : le propriétaire doit ajouter `SEC_USER_AGENT` (nom et e-mail) dans `.env`. Sans
cette ligne, la liste est produite mais les bulles affichent « Domaines indisponibles ».
`r001` n'a pas de bulles : il a été produit avant cette fonction et un run passé ne se réécrit pas.
