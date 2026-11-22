# P3 — Obstacles au PAPER BUY/SELL du MASTER en flux temps réel, et plan de tests hors ligne (v0.1)

RUGGER 01, 22/11/2026. Tâche P3 de `docs/ops/ETAT_RUGGER_MASTER.md` (62c4525), autorisation A1 (hors ligne).

- Rien n'est connecté au réseau, rien n'est signé ni envoyé.
- Tout rejeu reste étiqueté **HISTORICAL_REPLAY**. Il ne compte jamais pour les seuils protégés de 50 cycles qualifiés
  et 20 créateurs.
- Un « genuine Master PAPER BUY/SELL » exige un flux réel prospectif. Il n'existe pas aujourd'hui : **NON prouvé**.

## 0. Point de départ vérifié

- **paperstream 0.4** (audité, engine.py e86f66b0) pousse les événements un par un dans `StreamTrade`.
- Sur W1, le flux est identique octet pour octet au bundle L1 ancré (3 sha). Le chemin décision → BUY/SELL PAPER
  coûté → journal fonctionne donc en flux, sur données passées.
- **Écart prouvé par les tests de rtgate 0.1** :
  - `StreamTrade` ne contrôle que l'ordre du temps, alors que le rejeu en lot prouve qu'aucun trade ne manque, par la
    chaîne des réserves de `pool_timeline.build_timeline` ;
  - sur la fixture publique C7F9 (24 slots à plusieurs événements), un événement perdu, un doublon ou un slot
    réordonné change le résultat de `StreamTrade` SANS erreur ;
  - la porte `rtgate` remet la preuve du lot devant le flux : les doublons sont écartés, le slot est réordonné par la
    chaîne, et un trou, un retard ou un début de courbe manquant donne INCOMPLET (le pool est fermé, sans rattrapage).

## 1. Obstacles

Nature : C = code (hors ligne, faisable par nous) ; D = données ou réseau (accord du propriétaire) ; I = infrastructure
(accord du propriétaire) ; R = règle protégée (jamais contournée).

| # | Obstacle | Nature | État au 22/11 | Ce qui le lève |
|---|---|---|---|---|
| O-1 | Trous, doublons et réordonnancement dans le slot, livrés par un websocket (reconnexion, tampon perdu) | C | **Levé hors ligne par rtgate 0.1** (21 tests, 16/16 mutants) | Brancher rtgate devant tout flux réel |
| O-2 | Fin de slot inconnue : rtgate garde le slot ouvert jusqu'au slot suivant ; la décision du slot s attend donc la preuve que s est fini | C + D | Déclaré, mesuré sur rejeu seulement | Signal de fin de slot (notification de slot ou de bloc), à mesurer en réel |
| O-3 | La notification `logsSubscribe` (`helius_ws_forward_paper`) ne porte que des journaux, au niveau `confirmed`. Or le décodeur gelé `launchlab_events` lit l'événement dans les INSTRUCTIONS INTERNES d'un `getTransaction` (self-CPI `emit_cpi!`), et non dans les lignes `Program data:`, qui peuvent être tronquées | C + D | Vérifié dans le code. Il faut donc un `getTransaction` par transaction notifiée : latence (O-6) et crédits (O-15) | Soit un appel par transaction (crédits à chiffrer), soit un abonnement au niveau transaction (fournisseur, coût à chiffrer) ; un décodage depuis les journaux exigerait une preuve de non-troncature, ce qui fait un nouveau code à auditer |
| O-4 | Rollback : un événement `confirmed` peut disparaître (fork). `StreamTrade` n'a pas d'API de retrait | C | Non traité | Soit attendre `finalized` (latence, voir O-6), soit marquer INCOMPLET tout pool touché par un retrait ; à tester par injection |
| O-5 | Histoire depuis le lancement : les traits du MASTER, le taux de frais causal et la porte rtgate exigent le pool depuis 0/0 | D | rtgate refuse un début en milieu de courbe | Abonnement continu AVANT les créations ; tout pool vu en cours de route reste INCOMPLET |
| O-6 | Latence : l'ordre atterrit 4 slots plus tard (≈ 0,86 s à 210–222 ms par slot, mesuré). Réception, décodage, décision et (en réel) envoi doivent tenir dans ce budget | D + I | Les horloges de `helius_rolling_signed_paper` mesurent le coût du récepteur, pas la latence de bout en bout | Mesure prospective de bout en bout, sans ordre ; en PAPER, l'atterrissage reste modélisé (H-1, pire cas) |
| O-7 | Historique des créateurs (`CreatorHistory`) et échauffement : W1 utilise 402 800 slots (≈ 1 jour) avant l'évaluation | D + I | En rejeu, il vient des archives | Magasin d'historique tenu en continu, échauffement déclaré avant toute décision comptée |
| O-8 | SOL/USD au fil de l'eau, avec la garde du chargeur gelé (collectée, acceptation mesurée) | D | La série W1 est un fichier ancré ; aucun flux de prix n'est autorisé | Source de prix approuvée (Pyth : étude R1–R9 déjà faite), même garde ; sinon WAIT |
| O-9 | Coût de calcul par événement : le `_evaluate` gelé est quadratique (`as_of` linéaire sur 21 937 points) | C | paperstream 0.5.2.1 (memo, PASS R02) : 2,0–2,6 s contre 77–85 s sur fixture de taille W1 ; vérification sur W1 en attente (A5) | Vérification 0.5.2.1 sur W1, puis budget par événement mesuré |
| O-10 | Positions qui migrent : `migrated_unpriced` ; la vente sur CPMM n'est pas certifiée (C-1 non passé) | D | Pont v4cpmm et cpmmcost prêts, sur données synthétiques | Données CPMM réelles (pilote : source U-2, GO étage 0) |
| O-11 | Seuils protégés : l'entrée opérationnelle exige 50 cycles qualifiés et 20 créateurs indépendants ; les cycles rejoués ne comptent jamais | R | Le MASTER doit rester WAIT tant qu'ils ne sont pas atteints en prospectif | Accumulation PROSPECTIVE seulement ; aucun abaissement, aucun réétiquetage |
| O-12 | Hôte : un observateur 24 h ne tourne pas sur un runner GitHub Actions standard | I | Render et Vercel sont des déploiements séparés ; aucune modification de production | Hôte approuvé par le propriétaire (dépense) ; jamais sur la seule foi de tests unitaires |
| O-13 | Identifiants : la clé du fournisseur ne doit jamais être lue ni exposée ; le retrait du secret Helius de l'environnement R03 est demandé | I | Les clients existants la gardent en mémoire de processus seulement | Décision du propriétaire (§ 2 de l'état unique) |
| O-14 | Étiquetage dans Rugger Wallet : rejeu, démonstrateur DexScreener et futur flux réel doivent rester distincts | C | L'affichage HISTORICAL_REPLAY existe (provenance exacte) | Catégorie séparée pour un flux réel, testée avant tout branchement |
| O-15 | Crédits et quotas : `getTransaction` par événement, reprises après reconnexion | D | Aucun crédit autorisé (état unique § 1) | Chiffrage par R03, puis accord du propriétaire |

## 2. Plan de tests hors ligne (sans réseau, données déjà détenues ou synthétiques)

| Test | Obstacle | État |
|---|---|---|
| T-1 Livraison en ordre = rejeu gelé (5 stratégies × 3 pools) | O-1 | FAIT (rtgate) |
| T-2 Slots inversés et doublons → réparés, résultat identique | O-1 | FAIT |
| T-3 Sans la porte, la perte, le doublon et le réordonnancement changent le résultat sans erreur | O-1 | FAIT (preuve de l'obstacle) |
| T-4 Événement perdu → INCOMPLET ; position ouverte signalée ; aucun résultat publié | O-1 | FAIT |
| T-5 Début en milieu de courbe → INCOMPLET | O-5 | FAIT |
| T-6 Retards (même slot après reconnexion ; slot intermédiaire) → refusés | O-1 | FAIT |
| T-7 Reconnexion déclarée : guérie seulement par une chaîne exacte ; non guérie en fin de flux → INCOMPLET | O-1 | FAIT |
| T-8 Autre pool, événement en violation, source autre que HISTORICAL_REPLAY → refus | O-1, O-14 | FAIT |
| T-9 Un slot est poussé dès qu'un slot postérieur arrive (pas avant) | O-2 | FAIT |
| T-10 Le moteur derrière la porte est paperstream 0.4 audité (sha e86f66b0) | — | FAIT |
| T-11 Rollback simulé (retrait d'un événement déjà poussé) → pool INCOMPLET | O-4 | À ÉCRIRE (rtgate 0.2) |
| T-12 Un `getTransaction` enregistré (fixtures) décodé par `launchlab_events` = l'événement du rejeu ; des journaux tronqués ne sont jamais acceptés comme source | O-3 | À ÉCRIRE |
| T-13 Budget par événement : temps de `push` en fonction de la longueur de l'historique, avec 0.4 et 0.5.2.1 (série de taille W1) | O-9 | À ÉCRIRE après la vérification 0.5.2.1 sur W1 |
| T-14 Rugger Wallet : un enregistrement rtgate ne peut pas s'afficher comme cycle MASTER, ni compter pour 50/20 | O-11, O-14 | À ÉCRIRE |
| T-15 SOL/USD absent ou périmé à la décision → WAIT journalisé, jamais de taux déclaré | O-8 | À ÉCRIRE |

## 3. Ordre proposé (sans rien lancer)

1. R02 audite rtgate 0.1 et cette note.
2. J'écris T-11 à T-15 (rtgate 0.2), hors ligne.
3. Le propriétaire décide l'hôte, la source de données et de prix, et les crédits (O-6, O-8, O-12, O-13, O-15).
   Sans ces décisions : **WAIT**.
4. Seulement après : une observation prospective sans ordre, étiquetée à part. Les seuils 50/20 sont comptés sur
   elle seule.
