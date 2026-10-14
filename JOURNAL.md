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

## 2026-10-14 — Bulles en direct

**Question posée** : des bulles pour la semaine, les deux derniers jours, la première heure et la
journée en direct, mises à jour automatiquement.

**Fait** :
- Domaines SEC vérifiés sur la séance du 13 octobre : 2 098 des 2 099 titres liquides connus de la
  SEC, 15 sans domaine. Contact SEC ajouté par le propriétaire dans `.env`.
- Choix du propriétaire : prix toutes bourses avec 15 min de retard (le temps réel consolidé est
  payant), périodes jusqu'au prix du moment, suivi lancé à la main (`live_bubbles.sh`).
- `dashboard/live.py` : toutes les minutes pendant la séance, moyenne par domaine pour la journée,
  la première heure, 2 séances, 1 semaine et 1 mois ; page qui se recharge seule. Seuls les échanges
  de la séance régulière comptent. 19 tests verts, dont la datation du direct.
- État de fin de séance du 13 octobre produit avec les vraies données pour montrer la page.

Autrement dit : pendant la séance, la page montre minute par minute quels domaines montent et
lesquels baissent, avec 15 minutes de retard.

**Point à noter** : la SEC a un domaine « Crypto Assets » : ce sont des actions de sociétés liées
aux cryptos (pas des cryptos), elles restent dans l'univers.

## 2026-10-14 (suite) — Version anglaise, colonne « depuis l'ouverture », fin de séance

**Question posée** : une version anglaise du tableau de bord, la variation en direct de chaque titre
depuis l'ouverture, et les chiffres de fin de séance même si le Mac est fermé à la clôture.

**Fait** :
- `dashboard/index_en.html`, même gabarit que la page française (textes FR/EN, formats de nombres).
- Colonne « Depuis l'ouverture » : dernier prix / premier prix de la séance, mise à jour par le suivi.
- Option A choisie par le propriétaire : l'état de fin de séance est reconstitué depuis l'historique
  minute (dernier échange avant 16 h 00), au réveil du suivi ou par `run_screener.sh`, et gardé dans
  `research/experiments/final/`. Séance du 13 octobre rattrapée et poussée sur GitHub. 22 tests verts.

Autrement dit : les chiffres de l'ouverture à la clôture ne se perdent plus, quelle que soit l'heure
à laquelle le Mac se rouvre.

**Signalé au propriétaire** : le projet Vercel de l'ancien site est encore relié au dépôt et échoue
à chaque push (sans conséquence) ; à déconnecter ou supprimer depuis son compte Vercel.

## 2026-10-14 (suite) — Listes par domaine et démarrage automatique

**Question posée** : cliquer sur un domaine pour voir tous ses titres avec les mêmes colonnes, en
direct, et que le suivi démarre tout seul chaque jour.

**Fait** :
- Chaque domaine se déplie en la liste de ses titres (journée, première heure, 2 séances, semaine,
  mois), classée du meilleur au moins bon, triable par colonne ; ★ = sélection du jour.
- Démarrage automatique accordé par le propriétaire : service launchd (`deploy/install_live_agent.sh`),
  chaque jour de semaine à 14 h 15 (Paris), qui ouvre le suivi dans Terminal (macOS refuse aux services
  d'arrière-plan l'accès à Documents). Verrou d'instance unique. Corrigé : un suivi lancé avant
  l'ouverture demandait des cours trop récents (refus 403 de l'offre gratuite).
- Premier lancement automatique le 14 octobre à 10 h 32 (Paris) : en attente de l'ouverture.

Autrement dit : chaque jour de bourse, le suivi démarre seul et les listes bougent pendant la séance.

**Écart signalé** : l'heure du service est en heure de Paris (launchd ne connaît que l'heure locale) ;
14 h 15 précède l'ouverture de New York toute l'année et le suivi attend lui-même l'ouverture.

## 2026-10-14 (suite) — Répétition générale avant l'ouverture

**Question posée** : vérifier que tout fonctionne et fonctionnera à l'ouverture du jour.

**Fait** : répétition sur la séance réelle du 13 octobre, hors des fichiers du tableau de bord
(accès Alpaca et SEC, code commité, run de 17 h rejoué à blanc avec la même sélection que r001,
séance rejouée à 10 h 00, 11 h 00 et 16 h 00, pages FR et EN affichées par Chrome) : 29 vérifications
sur 29. Service de démarrage chargé, verrou vérifié, tâche de 17 h active. 26 tests verts.

**Trouvé et corrigé** :
- Les barres minute d'Alpaca sont corrigées après coup : lues la nuit même, 10 titres sur 2 099
  avaient un dernier prix différent (SKYD 9,27 au lieu de 7,07, la clôture officielle). La fin de
  séance du soir est désormais provisoire et recalculée à neuf 12 h après la clôture ; celle du
  13 octobre est remplacée par sa version définitive (l'ancienne est archivée).
- Une coupure réseau faisait échouer tout un calcul : jusqu'à 3 essais par requête.
- Les graphiques comptaient une séance de trop pour « 1 mois » : alignés sur la colonne.

Autrement dit : tout ce qui peut être testé avant l'ouverture l'a été sur de vraies données ; la
première séance en direct reste à observer.

## 2026-10-14 (suite) — Premières minutes en direct, liste à 16 h 45, séances figées

**Question posée** : vérifier les premières minutes en direct ; avancer la liste à 16 h 45 ; une
séance par jour dans le menu, en direct pendant la journée puis figée à la clôture.

**Fait** :
- Premières minutes en direct vérifiées : mise à jour chaque minute, retard de 15 min, 2 084 titres
  sur 2 093 cotés à 9 h 46 (New York) ; journée, semaine et mois recalculés indépendamment pour 5 titres :
  identiques à 4 décimales.
- Tâche quotidienne avancée (déclenchement 16 h 44 min 56 s, Paris) ; le run attend au plus 20 min
  les données de la première heure au lieu d'abandonner.
- Menu « Séance » par jour : séance du jour en direct, séances passées figées (corrigées une fois le
  lendemain, choix du propriétaire), chargées à la demande.

Autrement dit : chaque jour de bourse a sa page, vivante pendant la séance puis figée pour de bon.

## 2026-10-14 (suite) — Critère PER < 12 adopté (version 2)

**Question posée** : ajouter un PER inférieur à 12, le tester sur la séance du jour, puis l'adopter.

**Fait** :
- PER sur 12 mois glissants, bénéfice dilué par action déposé à la SEC (US GAAP, en dollars), seules
  les déclarations déposées avant le jour de décision servent. Variante commitée avant le test.
- Diagnostic sur le 14 octobre : 4 titres au lieu de 20 (PRI, WTRG, PRU, SIGI) ; 29 exclus pour PER ≥ 12,
  9 faute de bénéfice exploitable, 2 par la diversification.
- Décision du propriétaire : version 2 devient le critère quotidien à partir du 15 octobre ; moins de
  20 titres accepté. r001 et r002 restent tels quels (version 1). 33 tests verts.

Autrement dit : dès demain, la liste ne contient que des titres au PER inférieur à 12, souvent peu nombreux.

**Points signalés** : le PER suit les bénéfices officiels, éléments exceptionnels compris (WTRG : 7,2) ;
les titres sans bénéfice US GAAP déposé (étrangers, certaines banques) sont exclus.
