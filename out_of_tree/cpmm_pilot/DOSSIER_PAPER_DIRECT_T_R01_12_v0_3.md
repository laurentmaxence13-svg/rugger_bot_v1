# Test PAPER en direct : preuve de fonctionnement autonome (T-R01-12, v0.3)

**v0.3 = v0.2 (17a3b2d, f9d2b7bf) + deux faits techniques relevés en écrivant livepaper 0.1 (R04-17) :**
1. **L'ordre dans le slot.** `cpmmx.timeline` exige le `transactionIndex`, qui ordonne la chaîne des réserves.
   `getTransaction` ne le renvoie pas ; GTFA le renvoie.
   - (i-a) `getSignaturesForAddress` + `getTransaction` avec le RANG de `getSignaturesForAddress` : non admissible tant
     que l'ordre n'est pas vérifié contre GTFA sur données réelles (≈ 100 crédits, texte du propriétaire) et ancré par
     R02. livepaper le refuse.
   - (i-b) Une sonde `getSignaturesForAddress` (limit 1, 1 crédit), puis GTFA (10 crédits par appel) seulement s'il y a
     du nouveau, plus `getSlot` (1 par sondage). Sur les 3 pools éligibles B, avec les débits de R03, cela fait
     ≈ 38 400 crédits par jour à 60 s et ≈ 62 200 à 30 s.
   - Coût corrigé de (i-a), `getSlot` compris : à 30 s, 8 640 + 10 250 + 2 880 ≈ **21 800** par jour (v0.2 : 18 900,
     sans `getSlot`).
2. **L'historique de 7 jours** (b₃, G-0 initial) doit précéder le départ : une collecte fraîche par le collecteur de
   R03 coûte ≈ 0,1 crédit par transaction, soit ≈ 7 200 pour les 3 pools.

**Plafond D-3 révisé, pour 24 h sur 3 pools :**
- avec (i-b) à 60 s : ≈ 38 400 + 7 200 ≈ **45 600 crédits** ;
- avec (i-a) vérifié, à 30 s : ≈ 21 800 + 7 200 + 100 ≈ **29 100**.

La réserve de 32 340 pour le 06/12 reste intouchable. livepaper 0.1 est écrit hors ligne et ne peut pas appeler le
réseau.

**Mise à jour après le texte livepaper v2 (1366025b, projet) et les exigences de R02 (14:50Z) :**
- univers et b₃ tirés de l'ELIGIBLE ancré, **sans nouvel historique** : les ≈ 7 200 crédits ci-dessus disparaissent ;
- la vérification d'ordre précède le test ; elle coûte ≈ 100 crédits ;
- la voie suit son verdict :
  - (i-a) toutes les 30 s : ≈ 21 800 crédits par jour ;
  - (i-b) toutes les **150 s** : 3 sondes, GTFA si nouveau (probabilités 0,99 / 0,99 / 0,76) et `getSlot`, soit
    ≈ 31 crédits par sondage × 576 ≈ **18 100** par jour ;
- un seul compteur, plafond **25 000**, arrêt dur à **24 500**. Les deux voies tiennent sur 24 h.

La suite du texte est celle de la v0.2.

Texte de la v0.2 :

# Test PAPER en direct : preuve de fonctionnement autonome (T-R01-12, v0.2)

**v0.2 = v0.1 (e2e48c6, be45b2b5) + faits de R03 (14:41Z), tirés de ses registres sans aucun appel :**
1. **Pas de websocket dans le conteneur.** Le proxy ne laisse pas passer les « WebSocket upgrades ». L'option (ii)
   n'est donc possible que sur l'ordinateur du propriétaire.
2. **Les processus meurent au bout de 2 h au plus**, et le conteneur redémarre sans préavis, de quelques fois par jour
   à quelques fois par semaine selon R03 (NON MESURÉ précisément).
   - Les réveils programmés sont des tours de session : send_later convient toutes les 15 min à 2 h, et un cron a un
     intervalle d'au moins 1 h.
   - Un lancement à la minute exige donc une relance toutes les 2 h au plus.
3. **Les crédits disponibles ne suffisent pas.** Il reste 6 010 crédits dans le budget livesim. La réserve de 32 340
   est destinée au relevé du 06/12 et ne doit pas être entamée.
   - Le moins cher à la minute coûte ≈ 25 700 crédits par jour sur les 8 pools (calcul identique de R03).
   - **Il faut donc un nouveau plafond, par un texte du propriétaire.**
4. Débits mesurés par R03 : 9,87 transactions/min au total, dont 5zk4vh 4,64, GaPTvX 1,90 et 6CQSpR 0,57.
   - Mon estimation de ≈ 10 250 transactions/jour sur les 3 éligibles est cohérente : 7,11 × 1 440 = 10 238.

Le reste de la v0.1 est inchangé. Les corrections sont marquées « v0.2 ».

RUGGER 01, 25/11/2026. Directive du propriétaire (≈ 14:39Z), relayée par R04 (14:40Z).
- Dossier HORS LIGNE : aucun code n'est branché, aucun crédit n'est dépensé.
- C'est un test PAPER : aucun ordre, aucune signature, aucun envoi.
- Le test s'ajoute à la simulation de 24 h ; il ne la remplace pas.
- G2-3 et N1 gelés ne sont pas modifiés. Les pools pilotes sont refusés, comme dans livesim.
- **Étiquette** `PAPER_LIVE_DEMO`. Ce n'est jamais un trade du Master et cela ne compte jamais pour 50/20.
- Base : protocole PAPER_LIVE v0.2 (S-1 à S-6, arrêts 0 à 7), plbench 0.2 et DX_VALEURS v0.2.

## 1. Architecture minimale (nouveau paquet `livepaper` 0.1 ; il n'importe que du code gelé)

Une boucle par lot reçu : **événement → décision → ordre fictif → atterrissage simulé → sortie**.

1. **Réception.** Les transactions brutes du pool sont stockées telles quelles (page + sha256). Chaque lot reçoit son
   heure de réception (horloge murale + horloge monotone) et son slot.
2. **Ligne.** `TL.build`, puis `cpmmrecon.rebuild` (variante B) ou rien (variante A). G-0 = `pool_gate` de cpmmcost
   0.3.1, sur la ligne tronquée à la réception, comme `livesim.truncated`.
3. **Décision.** `cpmmgen2.decisions_g23`, avec le b₃ gelé recalculé sur les 7 jours avant le départ, sur la ligne
   **tronquée à l'heure de réception**.
   - Une décision est `LIVE` la première fois qu'elle apparaît.
   - Son heure de décision est l'heure de réception, et non l'heure du swap déclencheur.
   - Aucune donnée postérieure à la réception n'entre dans la décision. Le journal chaîné (point 4) le rend vérifiable.
4. **Ordre fictif.** 0,1 SOL. L'heure de l'ordre est l'heure de décision.
5. **Atterrissage simulé.** `cpmmcost.position`, avec ses règles gelées :
   - latence de 4 slots comptée **depuis la réception** ;
   - frais de la config du pool ;
   - impact par la courbe sur l'état d'atterrissage, et garde d'achat ;
   - échecs `FROZEN_FAILURES`.

   Il est résolu dès que l'état d'atterrissage est connu, c'est-à-dire au lot suivant.
6. **Sortie.** TP, SL et horloge de G2-3, par `cpmmprereg.exit_point`, comme dans g23run. Les positions sont gérées
   sans intervention humaine.
   - Témoin apparié tiré avec une graine déclarée.
   - Marques N1 horaires par lpcost, sur les pools N1 retenus, comme dans livesim.
7. **Univers.** Les pools qualifiés de livesim. Les décisions ne portent que sur les éligibles (G-0 et b₃ > 0).
   Diagnostic du 25/11 : 1 éligible avec la variante A, 3 avec la variante B (commit de4889c).

Estimation : 1 jour de code, de tests et de mutants, puis l'audit de R02.

## 2. Source temps réel et crédits Helius Free par jour

Bases de calcul :
- **Coûts** relevés dans le registre de dépense de R03 (`ledger_livesim.json`) : `getSignaturesForAddress` 1 crédit,
  `getTransaction` 1, `getTransactionsForAddress` (GTFA) 10, par appel.
- **Volume** mesuré sur les pages pré-départ (7 jours) :
  - 8 pools qualifiés : 99 451 transactions, soit **≈ 14 200 par jour** ;
  - 3 pools éligibles avec B (GaPTvX, 6CQSpR, 5zk4vh) : **≈ 10 250 par jour**.
- **Offre Free** : 1 000 000 crédits par mois, soit ≈ 33 300 par jour, et 10 requêtes/s.
  - **Le solde restant n'est pas mesuré ici** : la collecte de la fenêtre G2-3, en cours jusqu'au 06/12, consomme la
    même offre. R03 doit donner le solde.

Crédits par jour selon l'option :

| Option | 3 pools éligibles | 8 pools qualifiés | Latence de réception |
|---|---|---|---|
| (i) `getSignaturesForAddress` toutes les P s par pool, puis `getTransaction` par transaction nouvelle | P = 30 s : 8 640 + 10 250 = **≈ 18 900** ; P = 15 s : ≈ 27 500 | P = 60 s : 11 520 + 14 200 = **≈ 25 700** ; P = 30 s : ≈ 37 200, au-delà du rythme Free | ≤ P + 1 s |
| (ii) websocket `logsSubscribe` (un abonnement `mentions` par pool), puis `getTransaction` par notification — **v0.2 : impossible dans le conteneur (proxy), possible seulement sur l'ordinateur du propriétaire** | ≈ 10 250, plus le coût websocket **NON MESURÉ** | ≈ 14 200 + NON MESURÉ | ≈ 1 s |
| (iii) GTFA toutes les P min par pool (jusqu'à 100 transactions par appel) | P = 5 min : ≈ 8 700 ; P = 1 min : ≈ 43 200, au-delà | P = 5 min : ≈ 23 100 | ≤ P |

- **(ii)** Le code existant (`bot/live/helius_ws_forward_paper.py`) a déjà ouvert `logsSubscribe` sur
  `mainnet.helius-rpc.com` avec l'offre Free. Deux points sont **à vérifier par R03 sur la tarification archivée** :
  la facturation des websockets et la limite du nombre d'abonnements.
  - Une notification ne sert que de déclencheur. Le décodage se fait sur `getTransaction`, où cpmmrecon reconstitue
    les journaux tronqués.
  - Après une coupure, on rattrape par `getSignaturesForAddress`. Les décisions rattrapées sont étiquetées
    `decided_after_gap` et publiées à part.
- **Recommandation (v0.2).** Option (i) sur les 3 pools éligibles, P = 30 s : ≈ 18 900 crédits sur 24 h, sans
  inconnue de tarif. Elle exige un nouveau plafond, car le reliquat est de 6 010 et la réserve de 32 340 est
  intouchable.
  - Avec les 6 010 crédits actuels, l'option (i) à 60 s sur les 3 pools couvre ≈ 8 h (4 320 + 10 250 par jour, soit
    ≈ 14 600 par jour).
  - Variante sans nouveau plafond : GTFA toutes les 15 min, ≈ 7 700 par jour sur 8 pools (R03). Elle dépasse encore
    le reliquat sur 24 h ; ce n'est plus du « direct ».
  - L'option (ii) n'est possible que sur l'ordinateur du propriétaire.
- Le rythme reste ≤ 1 requête/s en moyenne, loin de la limite de 10 requêtes/s.

## 3. Hôte

| Hôte | Faits | Conséquence |
|---|---|---|
| Conteneur de R03, processus enchaînés | Gratuit. Limite de 2 h par processus (R03 : timeout maximal de 7 200 000 ms). Redémarrages sans préavis. Pas de websocket. Relance par send_later (au mieux toutes les 15 min à 2 h) | Trous à chaque relance : **mesurés et publiés** (début, fin, slots manqués). Le rattrapage est étiqueté `decided_after_gap`. Le journal est poussé sur git toutes les 15 min. Le secret reste injecté par le proxy, sans lecture par l'agent (règle D-5) |
| GitHub Actions planifié | Le cron a un pas minimal de 5 min, avec des retards fréquents ; un travail dure au plus 6 h. Minutes gratuites illimitées si le dépôt est public, 2 000 par mois s'il est privé (visibilité **à confirmer**) : 24 h continues = 1 440 min | Il faut un secret Actions et le déverrouillage audité des workflows Helius, verrouillés depuis la tâche #48 : **décision du propriétaire** |
| Ordinateur du propriétaire | Gratuit. Pas de limite de 2 h. Le propriétaire garde la clé | Le propriétaire lance un script et garde la machine allumée 24 h. Le journal est envoyé à la fin, ou toutes les heures |

Recommandation : le conteneur de R03, pour un premier test de 24 h, sans dépense. Les trous font partie de la preuve :
ils sont mesurés et publiés, jamais masqués.

## 4. Preuve d'autonomie

- **Journal chaîné.** Chaque enregistrement porte le sha256 du précédent. Types :
  - `RECEIVED` : slot, signature, sha brut, heures murale et monotone ;
  - `DECISION` : il ne cite que des `RECEIVED` antérieurs dans la chaîne ;
  - `ORDER`, `LANDING`, `EXIT`, `MARK` ;
  - `WAIT`, avec son motif ;
  - `GAP` : début, fin et cause.
- **Horodatage externe.** La tête de chaîne est commitée et poussée toutes les 15 min, et son sha est envoyé à R02.
  Une écriture après coup changerait la tête déjà publiée.
- **Témoin** apparié, tiré avec une graine déclarée avant le départ ; publié à côté, jamais fusionné.
- **Rejouabilité** (S-2). Le rejeu hors ligne des pages brutes stockées, par le même code (sha fixé au départ), doit
  redonner chaque enregistrement `DECISION` à `EXIT` **octet pour octet**. Un seul écart = ÉCHEC.
- **Comparaison a posteriori.** `livesim bilan`, sur les mêmes pages, donne la simulation faite après coup.
  - On publie, décision par décision, l'écart d'heure (réception − swap déclencheur), l'écart d'état d'atterrissage
    et l'écart de P&L simulé.
  - Les décisions présentes d'un seul côté sont listées avec leur cause (trou, latence, troncature).
  - C'est une mesure du fonctionnement, pas un verdict.
- **Critères techniques** (protocole v0.2, sans critère économique) :
  - S-2 : identité du rejeu ;
  - S-3 : p95 réception → décision ≤ 4 slots, hors attente de sondage, qui est publiée à part ;
  - S-4 : aucun module de signature ou d'envoi ;
  - arrêts 0 à 7.

## 5. Ce qui est gratuit, et ce qui demande le propriétaire

| Point | Gratuit | Décision du propriétaire |
|---|---|---|
| Code `livepaper` 0.1, tests, mutants, audit R02 | Oui | — |
| Hôte : conteneur R03 | Oui | — |
| Crédits sur 24 h : ≈ 18 900 (option (i), 3 pools) ou ≈ 25 700 (8 pools) | **Non (v0.2)** : le reliquat est de 6 010, la réserve du 06/12 est intouchable | **Plafond D-3** : par exemple 20 000 crédits pour 24 h sur 3 pools, ou 30 000 sur 8 pools, arrêt à 98 % sans reprise, en plus de la réserve de 32 340 |
| Websocket (option ii) | À vérifier | Seulement s'il est facturé |
| GitHub Actions ou ordinateur du propriétaire | Oui, si le dépôt est public, ou sur l'ordinateur du propriétaire | Déverrouillage audité et secret Actions, ou lancement par le propriétaire |
| Offre payante (plus de crédits, flux transactionnel) | Non | Montant à relever par R03 sur la page archivée ; non nécessaire pour 24 h sur 3 à 8 pools |
| Texte d'autorisation (D-7) et gestion du secret (D-5) | — | Oui, avant tout lancement |

**Ce qui bloque le lancement (v0.2)** : le nouveau plafond de crédits D-3, par un texte du propriétaire (le reliquat
de 6 010 ne couvre qu'≈ 8 h) ; le texte D-7 ; l'audit de livepaper 0.1 par R02 ; le choix de variante (cda64700).
Pour une latence de l'ordre de la seconde (websocket), il faut aussi l'ordinateur du propriétaire comme hôte.
