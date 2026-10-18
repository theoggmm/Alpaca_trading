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

## 2026-10-14 (suite) — Deux versions de la liste chaque jour

**Question posée** : produire chaque jour deux listes, l'une avec les critères d'origine, l'autre avec
le PER < 12 en plus.

**Fait** : `criteres_sans_per.json` (version 1) et `criteres_per12.json` (version 2) ; le run quotidien
produit un run par version (champ `variant`). Tableau de bord : sélecteur « Version » à côté de « Séance » ;
le suivi en direct, les graphiques et « Depuis l'ouverture » couvrent les titres des deux listes ;
« Fois dans les 20 » est compté par version. Le 14 octobre : r002 (sans PER, 20 titres) et r003
(PER < 12, 4 titres). 34 tests verts.

Autrement dit : chaque jour, tu peux comparer la liste d'origine et la liste filtrée par le PER.

## 2026-10-15 — Simulation d'investissement

**Question posée** : un tableau en bas du tableau de bord, pour les deux versions : 10 k$, 25 k$, 50 k$,
100 k$ et 1 M$ répartis à parts égales, achetés après la première heure (liste disponible), vendus 30 min
avant la clôture, en direct puis figé ; test sur la séance du 14 octobre.

**Fait** : `core/portfolio.py` (Decimal, troncature à l'instant d'observation, 4 tests) ; suivi en direct et
état de fin de séance. 14 octobre (définitif) : PER < 12 +0,76 % (+756,74 $ sur 100 k$), sans PER +0,38 %
(+382,84 $) ; recalcul indépendant identique. 38 tests verts.

Autrement dit : chaque jour, tu vois ce qu'aurait rapporté chaque montant, avec un achat réaliste.

## 2026-10-15 (suite) — Suivi des résultats, pré-enregistrement, test sur le passé, réalisme

**Question posée** : ajouter, sans rien retirer, (1) le suivi des résultats dans le temps, (2) un critère
de réussite fixé à l'avance, (3) un test sur le passé, (4) les frais et les actions entières.

**Fait** :
- (4) `core/portfolio.py` : frais de 0,05 % par ordre (`COST_BPS`), rendement après frais, gain en actions
  entières ; repères univers liquide et SPY ; section « Ordres à passer » (10 000 $, PER < 12).
- (2) `experiences/001_per12_vs_sans_per.md` pré-enregistré et commité avant sa fenêtre (40 séances à partir
  du 16 octobre) ; `research/experiments/decisions.md` créé (T1, T2, T3, 001.1) ;
  `core/performance_metrics.py`, seul module de métriques, testé.
- (1) Section « Historique des résultats » : résumé, courbe cumulée, tableau par séance, avancement de 001.
- (3) `backtest.py` : rejoue les deux versions sur 6 mois avec les mêmes fonctions de `core/`, résultat
  tracé dans `backtests/b00N/` (statut diagnostic) ; section « Test sur le passé » du tableau de bord.
- `infra/http.py` : pause puis nouvel essai sur une réponse 429 (trop de requêtes).

Autrement dit : tu vois désormais chaque jour ce que chaque liste rapporte vraiment, frais compris, et la
règle qui dira dans deux mois si le PER < 12 aide vraiment est écrite d'avance.

**Points signalés** : le test sur le passé ne voit que les titres encore cotés aujourd'hui, ce qui le rend
trop flatteur ; il sert à repérer un problème, pas à décider.

## 2026-10-15 (soir) — Deux règles contre l'achat au sommet

**Question posée** : AT&T remplissait tous les critères (+1,52 % sur la première heure) mais a été acheté
à son plus haut ; ajouter une règle pour l'éviter. Règles 1 (confirmation) et 2 (pas au sommet) retenues.

**Fait** : deux listes en plus, les deux existantes inchangées (expérience 001 figée) :
- version 3 « PER < 12 + confirmation » : à 10 h 45, prix ≥ prix de 10 h 30 ; liste et achat à 11 h 00 ;
- version 4 « PER < 12 + pas au sommet » : à 10 h 30, au moins 0,2 % sous le plus haut de la première heure.
`core/screener.py` (règles, datation testée), simulation et « Depuis l'achat » à l'heure d'achat de chaque
version, onglet Détail (tableau des quatre versions), Méthodologie, test sur le passé à quatre versions.
Expérience 002 pré-enregistrée (40 séances à partir du 16 octobre), décisions T4 et 002.1. Tâche planifiée
lancée deux fois (vers 16 h 45 et 17 h 02). Pages Alpaca de 5 000 barres (une page de 10 000 frôlait le
délai de 10 s et bloquait le test sur le passé). 52 tests verts.

Autrement dit : dès demain, tu verras deux listes de plus, et dans deux mois une règle écrite d'avance dira
si l'une d'elles évite vraiment d'acheter au sommet.

**Points signalés** : le suivi en direct s'est arrêté vers 15 h 45 (New York) faute d'avoir été relancé
après une modification de la page ; relancé avant la clôture. WSE affiche un PER de 0,24 dans le test sur
le passé : donnée SEC probablement erronée, à vérifier.

## 2026-10-15 (nuit) — Deux listes, chacune avec les deux règles

**Question posée** : le propriétaire règle encore ses critères (environ une semaine) ; il veut deux listes,
sans PER et PER < 12, toutes deux avec les règles « pas au sommet » et « confirmation ».

**Fait** : versions 5 (sans PER) et 6 (PER < 12) à partir du 16 octobre ; listes et achat à 11 h 00 (New York).
Versions 1 à 4 archivées (`archive/`). Expérience 001 suspendue (001.3), expérience 002 retirée avant toute
donnée (002.2), décision T5. Repères achetés à l'heure d'achat des listes du jour. Test sur le passé : listes
actuelles contre listes d'avant les règles. Tâche planifiée : un seul lancement vers 17 h 02 (Paris).
Travail fait dans une copie séparée du dépôt, intégré après l'état de fin de séance du 15 octobre.

Autrement dit : dès demain, tes deux listes évitent d'acheter au sommet ; le test officiel attendra que tu
aies fini tes réglages.

## 2026-10-15 (nuit, suite) — Archive des trois premières séances, test sur le passé relancé

**Question posée** : ranger les trois dernières séances dans une section d'archive et relancer le test sur
les 6 derniers mois.

**Fait** : onglet Archive (résumé, courbe, tableau par séance, listes) pour les séances du 13 au 15 octobre,
faites avec les anciennes règles ; groupe « Archive » dans le menu « Séance ». Résultats, « Fois dans les 20 »,
« Fois top 20 du domaine » et « Titres les plus souvent retenus » repartent du 16 octobre (`RULES_SINCE`).
Rien n'est effacé. Test sur le passé à quatre versions arrêté (règles abandonnées) ; relancé sur les deux
listes actuelles, comparées aux listes d'avant les règles.

Autrement dit : le tableau de bord repart à zéro demain avec les nouvelles règles, et l'ancien reste consultable à part.

## 2026-10-15 (nuit, fin) — Deux règles de tendance

**Question posée** : ajouter une règle de tendance ; après examen des trois premières séances, règles 1
(« pas en chute ») et 3 (« marché en bonne forme ») retenues.

**Fait** : `core/screener.py` (`market_in_uptrend`, règles `max_below_ma` / `ma_sessions` et
`market_symbol` / `market_ma_sessions`, datation testée), critères des versions 5 et 6, barres quotidiennes
de SPY lues à part par le run et le test sur le passé, onglet Détail, Méthodologie, décision T6. 56 tests verts.

Autrement dit : dès demain, pas de liste les jours où tout le marché va mal, et plus d'actions en chute libre.

**Points signalés** : examen des trois séances (68 titres) : titres à moins de 5 % sous leur moyenne −0,02 %
en moyenne, les autres −0,32 % ; trois jours ne prouvent rien, le test sur 6 mois tranchera mieux.

## 2026-10-15 (nuit) — PER < 25, et correction du test sur le passé

**Question posée** : passer le seuil de PER à 25 pour les listes de demain.

**Fait** : `criteres_per12.json` à `max_pe` 25 (décision T7) ; libellés « PER < 25 » (l'archive garde
« PER < 12 ») ; les tests sur le passé affichent le seuil réellement testé.

**Point signalé et corrigé** : le test sur le passé gardait en cache les prix d'achat et de vente des seuls
titres retenus ; un test relancé avec d'autres règles trouvait des prix manquants pour ses nouveaux titres,
écartés sans bruit. Le test de 6 mois du 15 octobre (jours 1 à ~49) en est faussé. Les prix sont désormais lus
pour tous les candidats du jour (nouveau nom de cache) ; les tests sont relancés.

Autrement dit : dès demain la liste avec PER s'ouvre aux PER jusqu'à 25, et les tests sont refaits proprement.

## 2026-10-16 — Plusieurs stratégies, un tableau de bord chacune

**Question posée** : tester en parallèle d'autres heures d'achat et de vente, chacune sur son tableau de bord ;
dont une stratégie achat à l'ouverture, vente après 1 h (2 h au plus), choisie sur la dernière heure de la veille
et la nuit ; en direct dès aujourd'hui.

**Fait** : `core/strategy.py` (une stratégie = un dossier : strategy.json + fichiers de critères ; stockage sous
la famille) ; `core/opening.py` (sélection « ouverture », décision à 9 h 15, datation testée) ; le run produit
les listes de toutes les stratégies, le suivi en direct les produit dès qu'elles sont prêtes (9 h 30 pour
« ouverture ») et suit toutes les stratégies ; une page par stratégie (bandeau, menu « Stratégie ») et un
accueil `dashboard/accueil.html`. Caches d'achat et de vente nommés par l'heure. Décision T8. 60 tests verts.

Autrement dit : cinq façons de suivre les listes tournent en papier dès aujourd'hui, chacune sur sa page.

**Points signalés** : PER suspects (BKNG 0,97, VIPS 1,41, WSE 0,24 : devise ou division d'actions) ; le test sur
le passé ne sait pas encore rejouer les stratégies « ouverture » ; noms des stratégies en français sur les pages
anglaises.

## 2026-10-16 (suite) — Stratégies de nuit

**Question posée** : acheter en fin de séance (1 h avant la clôture, ou juste avant) et vendre le lendemain
(à l'ouverture, ou 1 h après), avec des règles de sélection propres : la journée et la dernière heure avant l'achat.

**Fait** : `core/closing.py` (sélection « fin de journée », datation testée), `exit_next_open_minutes` dans
strategy.json, états de fin de séance refaits dès la vente du lendemain (suivi en direct, rattrapage), définitifs
12 h après la vente ; trois stratégies `nuit_*`. Décision T9. 61 tests verts. Essai sur le 15 octobre : 355 titres
passent les règles, 20 retenus par liste.

Autrement dit : trois façons de garder des actions pendant la nuit sont suivies dès ce soir ; leur premier
résultat sera connu lundi matin.

**Points signalés** : PER suspects (CHTR 2,85, BKNG 0,97, VIPS 1,41, WSE 0,24) ; tests sur le passé à adapter
aux stratégies « ouverture » et « nuit ».

## 2026-10-16 (suite) — PER corrigé

**Question posée** : corriger les PER aberrants (BKNG 0,97, VIPS 1,41, WSE 0,24, CHTR 2,85).

**Fait** : causes trouvées une par une. BKNG : division d'actions 25 pour 1 le 6 avril 2026, bénéfices d'avant et
d'après mélangés ; VIPS, WSE : sociétés étrangères (20-F), bénéfice en devise locale étiqueté dollars ; CHTR : chiffre
juste (cours très bas). Correctifs : bénéfices des seuls 10-K / 10-Q (`infra/sec.py`, cache `sec_eps_us`), ramenés aux
actions d'aujourd'hui avec les divisions d'Alpaca (`infra/alpaca_api.py` `splits`, `core/fundamentals.py`
`split_adjusted`, `run.earnings`, utilisé aussi par le test sur le passé). BKNG 15,9 ; VIPS et WSE exclus. 62 tests verts.

Autrement dit : la liste avec PER ne retient plus de titres à cause d'une erreur de calcul.

## 2026-10-16 (suite) — Stop et objectif par titre

**Question posée** : dans la simulation, vendre chaque titre dès qu'il perd 1,5 % ou gagne 3 %.

**Fait** : `core/portfolio.py` (`early_exits`, `STOP_LOSS`, `TAKE_PROFIT`, paramètre `path_bars` de `simulate`) ;
trajet minute des titres des listes lu au fil de la séance par le suivi, à la fin de séance et, de nuit, le
lendemain jusqu'à la vente ; test sur le passé ; colonne « Depuis l'achat » et note de la simulation ; méthodologie ;
décision T10. 63 tests verts. Essai sur le 15 octobre : 4 et 2 titres vendus au stop, résultat quasi inchangé.

Autrement dit : une action qui chute de 1,5 % ou monte de 3 % est vendue tout de suite dans la simulation.

## 2026-10-16 (suite) — Méthodologie complète

**Question posée** : que tout figure sur la page Méthodologie.

**Fait** : sections ajoutées (FR/EN), valeurs lues dans les fichiers de stratégies et de critères : les stratégies
(tableau généré : sélection, décision, achat, vente, New York et Paris), sélection « ouverture », sélection « fin de
journée », achats de nuit, tableaux de bord (accueil, onglets, heures de Paris, production des listes, archive, tests
d'un mois) ; limites des nouvelles stratégies et du stop ; sommaire et numérotation régénérés. Déjà présents :
stop / objectif (simulation), PER corrigé (critère PER).

Autrement dit : la page Méthodologie décrit maintenant toutes les stratégies et toutes les règles en vigueur.

## 2026-10-16 (suite) — Essai complet du tableau de bord

**Question posée** : vérifier que tout fonctionne dans l'ensemble du tableau de bord.

**Fait** : 63 tests verts ; séance du 14 octobre rejouée de bout en bout dans un dossier temporaire (historique
réel intact) : 20 listes (10 stratégies × 2), états de fin de séance, ventes de nuit le 15, stop et objectif,
22 pages ; chaque page affichée dans Chrome, tous les onglets ouverts : aucune erreur JavaScript, aucune valeur
manquante, pages anglaises sans français. Deux défauts trouvés et corrigés : achats de 15 h 55 restés « en attente »
(prix d'achat demandés trop tôt dans l'état de fin de séance) ; titre de l'onglet de la méthodologie anglaise.

Autrement dit : les dix stratégies produisent leurs listes, leurs simulations et leurs pages sans erreur.

**Points signalés** : le suivi en direct proprement dit (minute par minute pendant la séance) ne peut s'essayer qu'en
séance : vérification prévue à l'ouverture. Détails d'affichage : heure de vente « 9:31 » pour « à l'ouverture » dans
la simulation, formats d'heure mêlés (15:00 / 03:00 PM) sur les pages anglaises, texte d'introduction de la sélection
qui parle de « première heure » pour toutes les stratégies.

## 2026-10-16 (suite) — Suivi des positions ; prix de vente de nuit corrigés

**Question posée** : sous la sélection, une section qui dit pour chaque action si elle est encore détenue ou vendue,
et combien elle a rapporté ou coûté.

**Fait** : `simulate` garde la situation de chaque titre des listes (`positions`) ; section « Suivi des positions »
(onglet Aujourd'hui) : situation, variation, gain ou perte après frais sur la part de 10 000 $, prix d'achat, dernier
prix ou prix de vente, heure (New York, Paris), total. Méthodologie complétée.

**Défaut trouvé et corrigé** : les prix de vente étaient gardés en cache sous la seule heure (« 10 h 30 ») : une vente
de nuit à 10 h 30 le lendemain reprenait les prix de 10 h 30 du jour d'achat (ceux de la stratégie « ouverture 1 h »).
Cache désormais nommé par la date et l'heure ; test ajouté. Exemple (14 octobre, essai) : nuit 15 h 00 → 10 h 30,
PER < 25, +1,47 % faux, +2,18 % juste. 64 tests verts. Suivi en direct relancé avec ce code avant l'ouverture.

Autrement dit : tu vois action par action ce qui est encore en jeu et ce que chaque vente a rapporté, et les ventes de
nuit sont maintenant au bon prix.

## 2026-10-16 (suite) — Confirmation plus tolérante

**Question posée** : la liste principale du jour n'a que 6 titres sur 20 ; appliquer la tolérance de 0,2 %.

**Fait** : `confirmation_tolerance` (core/screener.py), 0,002 dans les critères des quatre stratégies « reprise » ;
test ; textes du tableau de bord et de la méthodologie ; décision T12. 65 tests verts. Dès le 19 octobre.

Autrement dit : une action qui fait du surplace entre 10 h 30 et 10 h 45 reste dans la liste ; seules celles qui
retombent nettement sont écartées.

**Ajout (même jour)** : à la demande du propriétaire, listes du 16 octobre refaites avec la tolérance (décision T13).
Principale : 10 titres (PER < 25) et 15 (sans PER) au lieu de 3 et 6 ; achat à 10 h 30 : 6 et 11 au lieu de 2 et 4.

Autrement dit : la journée d'aujourd'hui compte déjà avec la nouvelle règle, mais c'est une reconstitution après coup.

**Ajout (même jour)** : question posée — voir ce que j'aurais gagné sans la règle −1,5 % / +3 %. Colonnes
« sans stop/objectif » à l'accueil et dans chaque tableau de bord (décision T14), en direct. 66 tests verts.

Autrement dit : chaque jour, on voit côte à côte le résultat avec la règle et sans elle.

**Ajout (même jour)** : question posée — pourquoi certaines cases « Depuis l'ouverture » / « Depuis l'achat » étaient
vides. Le Mac s'est endormi de 18 h 20 à 18 h 58 (Paris) au milieu d'un passage du suivi ; au réveil, les derniers
prix lus étaient plus récents que l'heure de début du passage et ont été écartés comme « venant du futur » (règle
de datation). Correction : l'heure de référence est prise après la lecture des prix. Le passage suivant (19 h 00)
avait déjà tout rempli.

Autrement dit : rien n'était faux, il manquait seulement des prix pendant quelques minutes à cause de la mise en veille.

## 2026-10-18 — Tableau de bord épuré

**Question posée** : n'afficher que les résultats du jour et ceux depuis le 16 octobre 2026, sans les tests sur les
années passées.

**Fait** : onglets « Tests d'un mois » et « Archive » retirés, section des tests sur le passé retirée de « Résultats »,
menu des séances limité aux séances depuis le 16 octobre. Rien n'est supprimé : runs, tests et états restent sur
disque (research/experiments/) et peuvent être réaffichés.

Autrement dit : le tableau de bord ne montre plus que ce qui a été fait avec les règles actuelles.

## 2026-10-18 — Tests 2025 des 10 stratégies

**Question posée** : onglet renommé « Tests » ; tester les 10 stratégies sur un mois de baisse du S&P 500, six mois
de 2025 et toute l'année 2025.

**Fait** : backtest_strategies.py (une passe sur 2025, processus parallèles, ~2 h), 30 résultats, onglet « Tests »
(mois par mois, semaines, jours pour mars, colonne sans stop/objectif). Décision T15.

Autrement dit : sur 2025, aucune stratégie ne gagne d'argent avec ses deux listes, sauf les achats de nuit sans
filtre PER (+4 % à +7 % sur l'année) ; les frais de chaque jour pèsent lourd.

## 2026-10-18 (suite) — Trois nouvelles stratégies

**Question posée** : proposer trois stratégies pour gagner le plus, en mélangeant ce qui marche et selon le marché,
garde de quelques jours au plus ; les ajouter au tableau de bord et à la méthodologie ; les tester sur la semaine passée.

**Fait** : règles « marché qui tient / qui remonte », bascule, repli dans une tendance, garde de plusieurs séances,
stop et objectif par stratégie ; production des listes, suivi en direct, pages, méthodologie (section 7 bis) ;
tests 2025, 2024 et semaine du 12 octobre ; décision T16. 72 tests verts ; essai de bout en bout sur le 13 octobre.

Autrement dit : sur 2024, année jamais regardée pour les régler, les trois nouvelles stratégies gagnent un peu
(+3 % à +7 %) quand les dix anciennes perdent toutes ; c'est encourageant, pas encore une preuve.

## 2026-10-18 (fin) — Stratégies 14 à 23

**Question posée** : sept stratégies pour gagner le plus avec 10 000 $ et le moins de jours perdants, puis trois
stratégies gardées plusieurs séances.

**Fait** : nouveaux filtres (série, calme, semaine, repli si le marché tient, baisses consécutives), sortie sans stop,
dix stratégies, pages et méthodologie (7 ter, 7 quater), tests 2024, 2025 et semaine ; décision T17. 74 tests verts.

Autrement dit : la meilleure (bascule sans stop) rapporte en moyenne environ 50 $ par semaine avec 10 000 $ sur
2024-2025, gagne un peu plus d'une séance sur deux, et perd parfois 300 $ dans une séance.
