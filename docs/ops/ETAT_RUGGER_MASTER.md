# RUGGER MASTER — État unique (tenu par R04)

Mis à jour le 2026-11-23 à 14:00Z.
Légende des preuves :
- « vérifié » : R04 l'a constaté lui-même (ref git, statut de session) ;
- « déclaré » : affirmé par l'agent, ancré à son registre ou dans son message.

## 0. Rapport de direction (programme de recherche de rentabilité, directive du 23/11)

**A. Meilleure stratégie actuelle** : AUCUNE n'est confirmée. Aucune n'a même un rendement net positif mesuré. La moins mauvaise mesurée est MASTER, à −4,26 % net [−6,69 ; −1,95], n 128, sur W1, EXPLORATOIRE, verdict NÉGATIF. Le placebo du palier bas fait −1,82 % (comparateur).

**B. Classement des pistes** (potentiel, pas performance) :
1. CPMM R-CP1 (mean reversion sur pools établis) : préenregistrée, 0 $, 1 essai, GO_PILOTE au mieux. BLOQUÉE : choix U-2 et GO de l'étape 0.
2. LaunchLab C-B : ≤ 66 $ TTC, 5 essais (HW1). Peut s'arrêter sans candidat. BLOQUÉE : signature A2.
3. CPMM B1 (momentum, miroir de R-CP1 : hausse ≥ 3 % en 10 min) : même collecte, 0 crédit de plus, essai n° 170, fiche séparée ancrée avant T0. Retenue par R04 le 23/11 (confirmé par écrit à R02). Fiche B1 7c26497f **ancrée avant T0** ; code cpmmb1 0.1 (b630ea3b) PASS conditionnel (il manque un test de frontière).
4. Autres familles (E2, E3, A2, F1, H1…) : catalogue R-1 (8fd8cf84, PASS R02 sous corrections). Budget d'essais épuisé après B1 : autorisation chiffrée du propriétaire requise.

**C. Nouveaux résultats** : tableau consolidé v0.2 (4b369cf) : 7 NÉGATIVES, 1 INCONCLUSIVE, 0 rentable. Décomposition des pertes W1 : la perte vient des coûts (courbe 60 %, loyer 37 %), sans avantage brut. Tableau de bord MASTER : win rate 30,5 %, profit factor 0,42.

**D. Prochains tests décisifs** :
- R-CP1, étape 0 : ≤ 100 crédits, gratuit. Elle dit si l'univers CPMM suffit (STOP si moins de 20 pools).
- Étape 1 : ≤ 50 k crédits, gratuit dans l'offre Free. Premier verdict indépendant (G-1).

**E. Décisions** : STOP pour les 7 stratégies NÉGATIVES dans leur forme testée. INCONCLUSIF pour T3′. Autorisations demandées : U-2 et étape 0 (R-CP1) ; § 7 A2 (C-B).

**F. Trajectoire PAPER** : protocole PAPER_LIVE v0.2 et banc prêts. Il manque le choix A, B ou C (crédits ×16), puis D-1, D-3, D-5, D-6 et D-7. Aucune stratégie n'est encore candidate au PAPER prospectif.

**Travaux en cours (23/11, après-midi)** :
- R01 : R-1 catalogue A à H, R-2 décomposition des pertes W1 (descriptive), R-3 tableau de bord étendu.
- R02 : note HW1 / plafond d'essais, cadre multi-générations, définitions des indicateurs, audits.
- R-2 w1decomp 0.2 : PASS R02 (29083bff), exécution unique par R03 autorisée. R-3 dashx : en attente d'une v0.2 alignée sur b31a3c47.
- R03 : inventaire des champs de W1 **fait** (déclaré) : 57,7 % des 322 146 signatures sont des échecs, sans corps de transaction ; détenteurs partiels ; rien après la migration CPMM. P0 visible non scanné, faute d'autorisation. Exécutions uniques après PASS R02.

## 0 bis. Programme de recherche (piloté par R04)

**Génération 1 : CPMM établi** (pilote commun, données indépendantes, essais n° 169 et 170)
- A1 R-CP1 : mean reversion. B1 : momentum miroir. Toutes deux préenregistrées et ancrées avant T0.
- Procédure de déblocage, en trois autorisations distinctes, écrites dans la session R03 (textes exacts produits par R02) :
  Ordre recommandé par R02 : étape 0, puis U-2, puis étape 1.
  **Textes intégraux prêts à signer** : AUTORISATIONS_CPMM_TEXTES_INTEGRAUX_R02_v1_3.md (sha 443bbfb9 ; remplace la v1.2 5c6e8fc1, dont l identifiant du programme CPMM dans B(b) était faux : « …KP8C » au lieu de « …KP1C », valeur vérifiée par R04 dans le code, 15 occurrences ; la v1.2 remplaçait déjà la v1.1 468fe2ad). B : permutation déterministe, GTFA sans repli. C : arrêt au point (2) si le coût prévu dépasse 32 900 crédits ; C-bis optionnel pour un plafond plus élevé dans l offre Free.. A étape 0 (≤ 100 crédits) ; B U-2, option (b) recommandée : getProgramAccounts, ≤ 5 000 crédits, sans hôte tiers ; C étape 1 (≤ 50 000 crédits, arrêt dur à 49 000, D de 1,4 à 27,4 j selon le débit) ; D génération 2 (+3 essais, choix α). Quota : relevé par le propriétaire avant et après chaque étape ; STOP si le disponible est inférieur à plafond × 1,5, ou si l'écart dépasse 10 % du plafond.
  1. **Étape 0** (≤ 100 crédits) : vecteurs de test publics V-1′ (50 à 100 transactions CPMM) pour certifier le décodeur (porte G-0). Aucune liste, aucun rendement. En cas d'échec, tout s'arrête sans aucun essai consommé.
  2. **U-2** : autoriser l'API publique Raydium (hôte et requêtes), plus les lectures on-chain de qualification. Liste hachée à T0, juste avant la fenêtre ; moins de 20 pools = STOP.
  - Méthode U-2 (R03, a14580a4, sans réseau) :
    - A. API Raydium list-v2, 0 crédit, instantané brut haché ;
    - B. comptes de pool et AmmConfig (taux 0,25 %) ;
    - C. vaults WSOL ≥ 100 SOL à T0 ;
    - D. transaction de création (âge ≥ 7 j, non LaunchLab), ≈ 10 crédits par pool.
    L'étape 0 couvre A à C (≈ 24 crédits) et 1 ou 2 contrôles D. D et la collecte relèvent de l'étape 1.
  - Quota : dernier solde ancré, 637 612 crédits Free (relevé du 14/11, remise à zéro le 07/12/2026). R03 n'a fait aucune requête depuis. Vérification fraîche : lecture du tableau de bord **par le propriétaire**, à 0 crédit, AVANT puis APRÈS l'étape 0. Tout écart = STOP.
  3. **Étape 1** : « GO étape 1, ≤ 50 000 crédits », après lecture du résultat de l'étape 0. Pilote R-CP1 + B1, puis verdict G-1.
- Résultats publiés après le pilote, pour chaque hypothèse : n, net coûts complets et net gelé, win rate, gain et perte moyens, profit factor, IC (bootstrap groupé), écart au placebo, 7 sensibilités. Mot maximal : GO_PILOTE. Une confirmation ultérieure sur données nouvelles est requise.

**Génération 2** (en préparation, sans essai consommé)
- R01 a livré 3 fiches PROJET (6e000c8, sha e3f6b6eb), en CPMM établi, avec les sorties et les coûts de R-CP1 :
  - **G2-1** chute non routée : la baisse vient de ventes directes des détenteurs (test du mécanisme R-CP1) ;
  - **G2-2** épuisement vendeur : entrée après l'arrêt des ventes ;
  - **G2-3** pools peu disputés : faible compétition des robots, ce qui teste si la perte vient de l'exécution.
  Audit R02 (ca690ac3) : RECEVABLE SOUS CONDITIONS. La même collecte que R-CP1/B1 est **REFUSÉE** (K = 5 sur une seule fenêtre) : il faut une fenêtre SUIVANTE, ≤ 50 000 crédits. Les 3 hypothèses dépendent du déclencheur R-CP1 et seraient retirées si R-CP1 et B1 échouent toutes deux ; R02 demande au moins une hypothèse indépendante. v0.3 (ba7173b, sha 2e618be0) : G2-1 18/24, G2-2 17/24, G2-3 « élargissement de la demande » 15/24 (corrigée par R02 : la largeur de la demande a déjà été testée par T1, NÉGATIVE ; indépendante de la famille 10 min). Table CONTRÔLÉE et ANCRÉE avant T0 (f4027134). G2-1 et G2-2 sont retirées si R-CP1 et B1 sont NÉGATIVES. Pour lancer : +3 essais (170 → 173), crédits d'une fenêtre nouvelle (≤ 50 000) et choix de la confirmation (Holm, 262 entrées, recommandé ; ou 0,05/3, 221 entrées).
- R02 gèle les critères de sélection AVANT tout résultat du pilote.
- R03 chiffre les besoins en données.
- Lancement : il faut une autorisation chiffrée d'essais au-delà de 170 et le choix de la règle α.

**Interdits permanents** : les cellules positives D3 de W1 (n 16 et 17) ne sont pas une preuve ; aucun critère n'est modifié après observation.

**Chaîne hors ligne du pilote CPMM : PASS R02 (3b28ff5e, 22:32Z)** : cpmmpilot 0.1.6 f934bd2 + g1ind 0.6.1 f31269e. R02 a rejoué 28/28 tests et 35/35 + 50/50 mutants. Ordre fixé par R02 (3b28ff5e) : (1) textes A, B, C écrits par le propriétaire et vérifiés par R02 ; (2) ensuite seulement, transport réel 0.2 de R03, audité avant tout appel ; (3) liste V-1′ ancrée ; (4) fiches de gel. R04 avait demandé à R03 d'écrire le transport tout de suite ; R03 a refusé à juste titre, la demande est retirée. **Attestations R02 (108e6375, 24/11 06:56Z)**. Étape 0 NON totalement couverte par les collectes des 10 et 11/11 (étages a et b, 5 pools, 280 swaps) : C-1 volume (280 < 1 000), sorties exactes (0 < 50) et modification de liquidité (0) manquent. Ils seront jugés à l'étape 1 (porte G-0 ; G-0 en échec = STOP, sans verdict économique). La méthode U-2 couvre U-1, WSOL, CP-1, CP-2, l'âge et les exclusions (u2.py) ; U-4 est vérifié par pool_gate à l'étape 1. Quota requis : B + C = 82 500 ; dernier solde ancré 637 612, ancien, à relever par le propriétaire. **Transport 0.2 : PASS R02** (déclaré, ~22:57Z) : 34/34 tests, 49/49 mutants, connexion Helius verrouillée ; branche R03 en 9db2f12 (vérifié). **Mise à jour de R02 à 22:34Z** : R03 est autorisé à ÉCRIRE et faire auditer le transport 0.2, verrouillé, sans aucune exécution avant les textes signés. **Option proposée au propriétaire (note R02 fb28705b)** : l'étape 0 est déjà largement faite depuis le 10/11 (100 tx publiques à 0 crédit, MANIFEST 8895cbee, décodeur exact 80/80). Il peut déclarer l'étape 0 satisfaite, et le texte A devient inutile ; il ne reste que B et C.

**Priorité (R02 et R04, 23/11 22:20Z)** : le code est en avance sur les autorisations. Les générations 2 et 3 sont exécutables, mais elles sont au-delà du budget de 170 essais. Aucun nouveau chantier de code n'est ouvert tant que le propriétaire n'a pas décidé : A, B, C (v1.3), puis D, puis la tranche 174-175.

## 0 ter. File de travaux (relance du 23/11 soir) — responsable, livrable, critère de réussite

| ID | Resp. | Livrable | Réussite | État |
|---|---|---|---|---|
| T-R01-1 | R01 | Code de règle et de témoin, plus fiches de gel complètes, pour G2-1, G2-2 et G2-3 | PASS R02 ; ancrables dès la signature du texte D | cpmmgen2 0.2 : **PASS R02** (fiches v0.2 prêtes, non gelées). Historique : la 0.1 avait un PASS conditionnel (3199ea74). Restent K-1 (Holm anti-conservateur si une hypothèse n'a pas de p) et K-2 (essais comptés au début de la collecte). |
| T-R01-2 | R01 | Carte du seuil de rentabilité : avantage brut minimal selon le palier de frais, la taille rapportée à la réserve, la priorité, le loyer, les échecs (0 à 60 %) et la latence | PASS R02 ; 3 leviers principaux chiffrés | **barmap 0.1 PASS** (9a0b4e72). Barrière CPMM 0,25 % à 100 SOL : 1,12 % (bornes plausibles 0,59 à 4,01 %). Leviers, par ordre : palier de frais, priorité, lieu, puis réserve ≈ loyer. |
| T-R01-3 | R01 | Génération 3 : 2 ou 3 fiches PROJET hors famille « 10 min », notées sur a21f90f3 | recevabilité R02 | livrée (f14b464) : G3-1 « écart inter-pools » (loi du prix unique), 17/24 ; G3-2 « approfondissement de liquidité », 17/24. Il faudrait les essais 174 et 175 et une fenêtre propre. Audit R02 : RECEVABLE EN PROJET (a3f194dc). |
| T-R01-4 | R01 | Paquet g1verdict : calcul G-1 gelé (net, win rate, PF, IC groupé, écart apparié, 7 sensibilités, vocabulaire fermé, « sous la cible ») ; interface avec cpmmpilot | PASS R02 | confié 21:22Z, prioritaire. **FAIT** (071bb01) : pilot_verdict est CONFORME aux fiches, 14/14 clauses, sans doublon. K01 et K02 sont à trancher par R02. S01 et S02 (appel et signature dans cpmmpilot) sont à corriger par R03. |
| T-R01-5 | R01 | Module g1ind 0.1 (ex-« pilotreport ») : métriques b31a3c47, écart apparié, 7 sensibilités, « sous la cible ». Il n'altère pas le code gelé et cpmmpilot l'appelle. | PASS R02 | livré (c300593, MANIFEST c29662bf) : 13 tests, 32/32 mutants. Grille MEV : NON MESURÉ sur CPMM. v0.2 (3b13efe, MANIFEST 3d518522) applique les décisions de R02 : K01, une position non valorisée vaut 0 et compte (r = −1,0235, perte totale) ; K02, option (a). 40/40 mutants. v0.4 (e927a14, MANIFEST 201e4349) applique la règle unique de vente nulle de R02 : r = −(mise + (4 + échecs) × 105 000) / mise. Résultat identique au code de cpmmpilot 0.1.4 (6190277). 45/45 mutants. PASS R02 sur la 0.3. v0.5 (8a2b8c4, MANIFEST d81c7898) : valeur de vente nulle vérifiée contre la fonction importée de cpmmpilot ; 45/45 mutants. PASS R02 sur la 0.4. cut_time fixé par R02 au milieu temporel de la fenêtre, ancré dans chaque fiche. v0.6 (3d9166d, MANIFEST cda05131) : moitiés via la fonction gelée cpmmprereg.halves ; 49/49 mutants ; **PASS R02, version à intégrer**. Puis 0.6.1 (f31269e, MANIFEST 12a2e661) : vente nulle « loyer perdu » avec les échecs de la série ; rejouée sur cpmmpilot 0.1.6 (f934bd2), 50/50 mutants ; audit R02 en attente. Intégration dans cpmmpilot confiée à R03. |
| T-R01-6 | R01 | Génération 3 exécutable : code de règle et de témoin, plus fiches de gel non ancrées, pour G3-1 et G3-2, avec les réserves de a3f194dc | PASS R02 ; ancrables dès l autorisation de la tranche 174-175 | livré (d150ce0, MANIFEST 812884bf) : règle, témoin et comptage de population avant T0 ; NON ÉVALUABLE sans essai consommé si moins de 10 mints en paire ou moins de 30 dépôts ; 2 fiches non ancrées ; 40/40 mutants. G3-1 exige aussi une source U-2 qui liste les pools par mint. Audit R02 en cours. |
| T-R02-1 | R02 | Audits de T-R01-1 à T-R01-3 | verdict écrit et sha pour chacun | au fil de l'eau |
| T-R02-2 | R02 | Puissance réaliste de la génération 2 (σ plausibles, effet net) → durée et crédits pour n = 155 et 262 | table chiffrée pour le texte de crédits | **FAIT** (b237941d) : n pilote = 155, 303 ou 619 pour σ = 2,5, 3,5 ou 5 %. Le pilote atteint la pleine puissance avec 50 000 crédits seulement si R̂ ≤ ≈ 967 tx par pool et par jour ; sinon, résultat publié « sous la cible », remédiable par C-bis. Génération 2 : ≈ 100 000 crédits Free par fenêtre, à fixer après la mesure de R̂. |
| T-R03-0 | R03 | Paquet cpmmpilot : runner étape 0 → U-2 → étape 1, faux RPC, compteur de crédits, arrêts, gel, reprise, sortie gz. Réutilise sans modification les règles gelées de R01. | PASS R02 | **écrit** : cpmmpilot 0.1 (9169b10, vérifié en tête de claude/admiring-curie-r2gl1p ; MANIFEST b987e697), 14/14 tests. PASS CONDITIONNEL R02 (0b3a3033). À corriger : runner de mutants et 4 tests manquants ; G-1 via la fonction gelée cpmmcost.pilot_verdict ; exclusion des Token-2022 REFUSÉE (univers gelé). Liste V-1′ à ancrer avant l'étape 0. Puis 0.1.5 (b0e5b37) : 27 tests, 33/33 mutants, mais avec g1ind 0.3. Passage à g1ind 0.6 demandé, en 0.1.6. Audit R02 : 0.1.5 NON CONFORME (6f071c5a), erratum de R02 sur la vente nulle avec loyer perdu ; la 0.1.6 doit intégrer g1ind 0.6.x. |
| T-R03-1 | R03 | Répétition hors ligne de toute la chaîne du pilote CPMM, avec faux RPC (crédits, arrêts, U-2, gel, reprise, G-1) | journal avec sha et audit R02 | **répété hors ligne** en 25 s (journal 5fa940a6). Chaîne complète OK, 6 arrêts sur 6 conformes. Restent : G-1 en code gelé (T-R01-4) et le transport réel (v0.2, après audit). |
| T-R03-2 | R03 | Plan de ressources (disque, mémoire, durée, risques, sauvegardes) pour le pilote et la génération 2 | document avec sha | **FAIT** (67e6cb78) : pilote ≤ ≈ 325 000 tx, ≈ 0,6 Go en gz, collecte rétrospective de ≈ 10 min après T0 + D. Seul risque grave : la fin de session (archive remise en 7 parties de 90 Mo). Génération 2 et PAPER_LIVE : le disque bloque (6,7 Go libres), il faut une sauvegarde externe ou un autre environnement. |
| T-R03-3 | R03 | Contrôle d'intégrité W1, seulement s'il y a eu un redémarrage depuis 08:47Z | 0 écart | **FAIT, 0 écart** (redémarrage à 21:04:29Z ; 13 sha recalculés) |

## 1. Autorisations vérifiées à la source

Référence : REGISTRE_AUTORISATIONS_VERIFIEES_R02_v1_0.md, sha256 a4b9d467…69e2 (registre R02 0dbe0572). Amendement 1 : sha256 d784ef31…5715 (R02 b8195721). R01 est lu du 14/11 au 23/11 : on n'y trouve ni B1, ni GCP, ni Helius, ni étage 0, ni U-2, ni PAPER_LIVE. ed672cdb (20/11) valide le choix TECHNIQUE C1-b + D2 du ledger, et non le volet financier de B1.

| Autorisation | Source | Couvre | NE couvre PAS |
|---|---|---|---|
| Travaux techniques hors ligne permanents | R04 60283acd (22/11), 813ab515 (23/11) | code, tests, audits, protocoles, documentation | A2, Google Cloud, crédits Helius, collecte, dépense |
| Analyses hors ligne W1 après PASS R02 | 5aff3383 point 1 (20/11) | landslip sur W1 (fait) | collecte, dépense |
| Vérifications 0.5.x | R02 7350829b point 3 (22/11) | consommé (0.5.1 et 0.5.2.1 VERIFIED) | — |
| cpmmfmt 0.1, une fois | R03 7aec4137 (22/11) | consommé | pilote CPMM, crédits Helius |
| CPMM, source publique gratuite | R04 7ede3e39 (10/11) | exemples pour le décodeur | liste U-2, crédits |
| Proposer Raydium U-2, préparer l'étage 0 | R04 2d49816b point 4 (23/11) | proposer, préparer | appel à l'API, exécution de l'étage 0 |
| Sauvegarde W1 ≤ 1,00 $ cumulé | R03 fe5be941, 61008bcc, 576b1b1c, bf07ca21 (17–20/11) | sauvegarde seule | A2, VM, autre bucket |
| **Suspension** de la sauvegarde | R03 52c8a431, R04 3cee6c73 (21/11) | — | exécution de la ligne précédente (SUSPENDUE) |
| Plan de préservation W1 | R04 2d49816b point 2 (23/11) | un plan (fait : R03 8969e61a) | transfert des données brutes |
| Principe Helius Developer ≤ 100 $ HT | R04 66e09996 (04/11) | principe | paiement |
| Préparation technique LIVE | R04 10f2725b (04/11) | préparer | activer, payer, héberger |
| Voie B Google Cloud 60 $ | R03 8cfead0e (15/11) | **caduque** (retirée par b9e596e3, 15/11) | — |
| **B1 signé** | recherché | **aucun trouvé** | — |

Plafond d'essais : N = 168 sur 170, hors HW1. HW1 ajoute +5, publié à part, soit 173 au total. R-CP1 porterait N à 169.

## 2. Opérations bloquées — clauses précises manquantes

| Opération | Clause manquante, et elle seule | Où |
|---|---|---|
| A2, puis HW1, puis C-B | Recopier et signer le § 7 de la fiche v1.1 (e2a93ea8), avec v2.6.6 (490a28f1) : exception Google Cloud limitée à A2 ; B1 (C1/P1) ; 66 $ TTC avec alerte ; DEADLINE ≤ 49 h, puis DELETE ; jetons déposés par le propriétaire ; risque accepté | session du propriétaire |
| Sauvegarde GCS des lots 6a, 6b et 7 | « Je lève la suspension », puis dépôt d'un jeton par le propriétaire lui-même | session R03, formulaire « network secret » |
| Données brutes W1 hors conteneur | Choisir une option du plan R03 (8969e61a) : (a) GCS ou (d) archives dans l'app | session R03 |
| Liste U-2 du pilote CPMM | « J'autorise un appel à l'API publique Raydium (hôte précisé) pour la liste des candidats U-2 », avec ouverture réseau. Raydium seul ne suffit pas : il faut aussi des lectures sur la chaîne (étage 1). | session R03 |
| Pilote CPMM, étage 0 | « GO étape 0, ≤ 100 crédits Helius » | session R03 |
| Pilote CPMM, étage 1 | « GO étape 1, ≤ 50 000 crédits », après l'étage 0 | session R03 |
| Mesure des échecs N-4 | Collecte qui conserve les transactions échouées, avec un plafond | session R03 |
| PAPER_LIVE | Choix A, B ou C face au facteur ≈ 16 de crédits. Option A chiffrée par R03 sur la grille archivée du 08/11 (b6794b16, fa152d54) : offre Helius Developer à 49 $ HT par mois (58,80 $ TTC), soit 10 M crédits et 50 req/s. Plafond prudent ≈ 61 $ TTC avec une marge ×1,3 et le WebSocket (volume non mesuré, hypothèse ≈ 0,3 M crédits). Grille à relire en ligne avant décision. Le principe Developer ≤ 100 $ HT (66e09996, 04/11) existe, mais ce n'est pas une autorisation de paiement. Coût de l'hôte (D-1) en plus (7,68 M getTransaction contre ≈ 467 k Free) ; puis D-1, D-3, D-5, D-6, D-7 (DX v0.2, 7f6c5f4, CONFORME selon R02) | session de l'exécutant |
| W2 | Format, k, plafond, plan Helius, GO (après A2, HW1 et C-B) | session du propriétaire |
| Inventaire des champs sur P0 visible | « J'autorise R03 à exécuter une seule fois l'inventaire de couverture des champs (fieldinv, comptes seulement) hors ligne sur le pack P0 visible aca7de08. » | session R03 |
| Contrôle global des tests entre générations | Choisir : (a) dépense d'α, α_g = 0,05 × 2^(−g), avec un risque total de faux CONFIRMÉ ≤ 5 % (recommandé par R02) ; ou (b) α = 0,05 par génération, avec publication du nombre de générations. Cadre R02 b4edc143. | session du propriétaire |
| Dépasser le plafond de 170 essais exploratoires (il en reste 2 ; R-CP1 → 169, B1 → 170). Cas concret : génération 2 = essais 171 à 173, sur une fenêtre suivante | Autorisation écrite et chiffrée du nombre d'essais supplémentaires, ET règle de correction ancrée avant les données. Sinon, veto de R02 (note 8a9c8f84). | session du propriétaire |
| Hygiène | Retirer le secret Helius de R03 ; désactiver les 4 routines d'étiquette | paramètres |

## 2 bis. Opérations prêtes (code audité, sans décision en attente côté agents)

- A2 : paquet v2.6.6 au PASS R02 ; chaîne w1chain 0.2 au PASS (verdict → HW1 → C-B).
- CPMM : cpmmfmt CONFORME, cpmmcost 0.3, cpmmprereg 0.2 (R-CP1 figée) ; règles de lecture gelées par R02.
- PAPER_LIVE : protocole v0.2 conforme ; plbench 0.2 ; rtgate 0.2 ; papercost 0.1 ; landslip ; DX v0.2. Seul l'adaptateur d'acquisition reste à écrire, après le choix de D-2.
- Preuves : intégrité W1 sans écart ; archive de preuves remise au propriétaire le 23/11 vers 10:40Z (PREUVES_W1_R03_20261123.tar.gz, 1 049 141 o, sha 91ddb11e, 34 fichiers, scan de secrets 0, sans données brutes) ; écart avec l'annonce de 10:37Z expliqué : la v1 (3be6210e) contenait dans son SHA256SUMS une auto-entrée vide, ce qui l'aurait rendue invérifiable. Elle a été régénérée sans cette entrée, sans changement des 34 preuves, et R02 a ancré 91ddb11e. La v1 est conservée localement et n'a pas été envoyée.

## 3. Tâches priorisées (autorisées, en parallèle)

| Prio | Tâche | Agent | Autorisation | État |
|---|---|---|---|---|
| P1 | Terminer le run 0.5.1 sur W1, sans modification | R03 | A5 | **Fait** : de 15:29:53Z à 22:00:48Z, sans coupure, rc 0 |
| P1 | Lire le verdict 0.5.1 une seule fois avec ps051verdict 0.2, puis audit sans ajustement des critères | R03 puis R02 | A5 | **VERIFIED** (14/14). Ancrage R02 en attente |
| P1 | Profil technique d'un pool, puis vérification de la 0.5.2.1 sur W1 (ps0521verdict 0.1) | R03, après GO de R02 | A5 | **0.5.2.1 VERIFIED** (14/14) |
| P1 | landslip 0.1 measure sur W1 ancré ebe1959d (comptes seulement) | R03, après GO de R02 | A2 | Exécutée sur les 2 273 pools, sans erreur (déclaré R03, 22:42Z). Ancrée et lue par R02. |
| P2 | Préparer hors ligne la chaîne verdict W1, puis HW1, puis C-B : scripts, critères gelés, tests | R01 ; audit R02 | A1 | w1chain 0.1 livrée (5a87ea8, vérifié). Audit R02 : **CORRECTIONS REQUISES** (c6629433). K-1, bloquant : le critère (viii) est exigé à tort pour l'admission, et la condition de sensibilité au payeur manque. w1chain 0.2 (a49f398, MANIFEST eff1d847) corrige K-1. **PASS R02** (déclaré). |
| P2 | Audit complet du modèle de coûts | R02 | A1 | **Fait** (voir § 4) |
| P3 | Plan de mesure hors ligne de l'atterrissage (N-4) et du glissement (N-5) sur les tx déjà collectées ; garde de glissement pour le moteur PAPER (préparation seulement) | R01 ; audit R02 | A1 | À faire |
| P2 | Préparer la réorientation CPMM, sans exploitation rétrospective : simulateur de coûts, critères gelés, decoder prêt pour cpmmfmt | R01 ; audit R02 | A1 | cpmmcost 0.1 livré (6cd08e6, MANIFEST 127049f5). Contenu : modèle de coûts complet ; seuil 0,815 % (déclaré 0,82 %) ; barre de travail 1,12 % à 100 SOL ; admission des pools avec le décodeur cpmmfmt ; aucune donnée lue. 0.1 : PASS conditionnel R02. Version 0.2 (a611621, MANIFEST 3adeba68) : chaque échec retarde l'atterrissage d'un ordre renvoyé de +4 slots (H-1) ; graine issue de la fiche de gel. **PASS R02** sur la 0.2 (déclaré). Pilote BLOQUÉ PAR LE PROPRIÉTAIRE (U-2, GO étapes 0 et 1). |
| P3 | Liste des obstacles au PAPER BUY/SELL en flux temps réel, avec plan de tests hors ligne. Les rejeux restent étiquetés HISTORICAL_REPLAY. | R01 ; audit R02 | A1 | rtgate 0.1 et sa note (f2452a9, vérifié ; MANIFEST a226aeac). Constat : le moteur en flux accepte des événements perdus, doublés ou réordonnés, ce qui change le résultat. rtgate répare ou ferme le pool (INCOMPLET). 15 obstacles recensés, dont, côté propriétaire : hôte 24 h, source de données et de prix, crédits getTransaction, secret Helius. BUY/SELL PAPER du vrai Master : **non prouvé**. **PASS R02** sur la 0.1 (déclaré). Version 0.2 (22c595b, MANIFEST 8423a07c) : 5 tests ajoutés, **PASS R02** (déclaré). |
| P3-b | Plan de mesure N-4/N-5 et garde de glissement | R01 ; audit R02 | A1 | landslip 0.1 (8e432a5, MANIFEST 446b30da) : compteur hors ligne ; garde réglée à 2 % à l'achat et 5 % en sensibilité ; audit R02 en cours. **PASS R02** (61059c95). Autorisation tranchée par R02 : rien ne couvre P0. L'exécution unique sur W1 ancré (export ebe1959d) est couverte par A2, aux conditions suivantes : mesure descriptive, 0 essai ; comptes seulement ; aucun paramètre gelé modifiable au vu du résultat ; après le verdict 0.5.1 ; holdout refusé ; sortie ancrée par R02 avant lecture. Si le contrôle d'accès de R03 refuse : BLOQUÉ PAR LE PROPRIÉTAIRE, avec la formule de R02. |
| P3-c | Moteur PAPER « coûts complets » en nouvelle version, sans toucher au code gelé : N-1/N-2, N-3, N-4, N-5, N-7, N-8 ; fixtures uniquement | R01 ; audit R02 | A1 | papercost 0.1 (2937aa3, MANIFEST 3ce631ff). Avec les options neutres, il reproduit le moteur gelé octet pour octet. Rien n'est appliqué à W1. **PASS R02** (déclaré). Garde des lanceurs ajoutée (dac9a10). |
| P3-d | Modèle de sensibilité N-6 (MEV/Jito) et protocole préenregistré du PAPER prospectif en flux réel (conception seulement ; l'hôte et la source relèvent du propriétaire) | R01 ; audit R02 | A1 | Livré (a94a660, MANIFEST 82b94d0c) : mevsens 0.1, 6 scénarios non calibrés ; protocole PAPER_LIVE v0.1, brouillon (14 jours, critères S-1 à S-6). Prérequis du propriétaire D-1 à D-7 : hôte 24 h, source du flux, plafond de crédits, SOL/USD en direct, secret, interface unique, texte d'autorisation. mevsens : **PASS R02** (déclaré). Protocole PAPER_LIVE : R02 le déclare conforme en v0.2 (registre f9bd7816), sous réserve des 7 décisions du propriétaire ; R01 y intègre les corrections. |
| P4 | Proposition « moteur W2 coûts complets » : assemblage papercost + rtgate + garde landslip, gelé avant toute donnée W2. **Proposition seulement** : son adoption modifierait le Dossier B gelé, donc BLOQUÉ PAR LE PROPRIÉTAIRE pour l'adoption. | R01 ; audit R02 | A1 | w2cost 0.1 (3aa57de, MANIFEST 3300268f) : **PASS R02** pour le code, proposition **non adoptée**. Avis R02 accepté par R01 : le Dossier B v1.9 reste inchangé. Le GO de C-B est déjà net du loyer perdu : δ = +2 % et n_min = 414 restent corrects. A0 n'est que publié, jamais décisionnel. Une éventuelle publication complémentaire « net coûts complets » ne porterait aucun critère. Aucune décision urgente. |
| P4 | Préparer A2 v2.6.6 hors ligne : create_vm.sh sans valeurs de projet, checklist propriétaire | R04 | A1 | Prêt à remplir sur signature |
| E-1 | PL-1 : banc d'essai PAPER_LIVE de bout en bout sur fixtures (rtgate, papercost, journal, rapprochement, S-1 à S-6), étiqueté SIMULATED_FEED ; liste des valeurs attendues pour D-1 à D-7 | R01 ; audit R02 | A1 | plbench 0.1 livré (f6288ce, MANIFEST c37f6a19) : chaîne flux → rtgate → papercost → L1 gelé → rapprochement → S-1 à S-6 → 8 arrêts. Le fichier DX_VALEURS_PROPRIETAIRE_v0_1.md donne les valeurs exactes à fournir. Reste à écrire, après le choix de D-2 : l'adaptateur d'acquisition. plbench 0.2 (04b623e) applique les règles de lecture gelées par R02 ; sur fixtures, résultat INCONCLUSIF (population 0), comme attendu. Audit R02 en cours. |
| E-1 | CPMM-2 : préenregistrement de l'hypothèse CPMM (règle de décision, effet minimal net, puissance, témoin, essais 169/170, arrêt) | R01 ; audit R02 | A1 | cpmmprereg 0.1 livré (7e60f0b, MANIFEST 7fd87b82) : R-CP1 figée en code ; n = 155 au pilote et 221 en confirmation (σ 2,5 % déclaré, δ +0,5 % net) ; 1 essai ; STOP sans essai consommé si moins de 20 pools éligibles. Version 0.2 (059a3b5) : amendement A1 de R02 intégré (déclencheurs comptés sur 7 jours avant T0, σ de confirmation, conditions de CONFIRMÉ). cpmmcost 0.3 (7deb7b7) : garde de glissement de 2 % à l'achat CPMM (sensibilité 5 %), échec facturé. Audit R02 en cours. |
| E-1 | Gel des règles de lecture statistique : pilote CPMM et PAPER_LIVE, critères économiques en coûts complets | R02 | A1 | **Fait** : REGLES_LECTURE_GELEES_CPMM_PAPERLIVE_R02_v1_0.md (registre R02). Vocabulaire fermé : STOP / INCONCLUSIF / NÉGATIF / GO_PILOTE / CONFIRMÉ / RENTABLE. « Rentable » n'est permis que si R-0.6 est remplie : CONFIRMÉ sur des données indépendantes en coûts complets, net > 0 avec 1 échec et 10 slots, PAPER_LIVE POSITIF avec les reçus de cycle, audit écrit de R02. Bootstrap groupé de 10 000 tirages, sans arrêt anticipé. Étape 0 CPMM sans chiffre économique ; étape 1 plafonnée à GO_PILOTE. Pour le MASTER gelé en PAPER_LIVE, le résultat attendu déclaré est NÉGATIF. |
| E-0 | Contrôle d'intégrité local des preuves W1 (sha contre registre R02) et inventaire des risques de perte | R03 | A1 | **Fait, 0 écart** (déclaré). Vérifiés : 26 sha ancrés, 2 273 archives, 2 294 sorties préliminaires, 29 549 .pkl, 3 × 2 273 checkpoints, 26 fichiers inbound, arbre gelé. Disque : 21 Go utilisés, 6,7 Go libres. |

## 4. Résultats

| Date | Résultat | Preuve | Statut |
|---|---|---|---|
| 22/11 03:52Z | Run PAPERSTREAM 0.4 sur W1 (out3), rc 0 | sha 56ff15ec | déclaré (R03) |
| 22/11 03:54Z | psverdict 0.2 : **IDENTITY_FAILED** (master_closed 191 contre 128), échec maintenu | sortie 8ef04608, registre R02 46040a43 | déclaré |
| 22/11 | Verdict distinct : **identité technique prouvée** ; les 3 sha sont identiques | b2e2cc53 | déclaré (R02) |
| 22/11 15:37Z | Réconciliation : 191 = 63 (échauffement) + 128 (évaluation) + 0 | cyclesplit db66af7, sortie 90adc6b0 | déclaré ; commit vérifié |
| 22/11 | PASS de R02 : cyclesplit 0.1 (db66af7), paperstream 0.5.2 (672eeae), ps051verdict 0.2 (092ab57), A2 v2.6.6 (d0c2ccd), paperstream 0.5.2.1 (99a8a35), ps0521verdict 0.1 (5bc67c6) | registre R02 | commits vérifiés ; PASS déclarés |
| 22/11 | Fiche d'exception A2 v1.1 | e2a93ea8 | déclaré (R02) |
| 22/11 20:24Z | cpmmfmt 0.1, exécution unique sur P0 aca7de08, rc 0. Résultats : 360 archives, dont 8 CPMM ; 21 475 tx, dont 26 CPMM ; 26 frames sur 26 décodées, dont 25 swap_current ; creditable_for_c1 = false ; aucun réseau. | FORMAT_COUNTS.json, sha 44826f54 | déclaré (R03). Audit R02 : **FORMAT CONFORME** (registre fe3488ca). LpChange et l'ancien format ne sont pas exercés. Non créditable pour C-1. |

| 22/11 20:28Z | Audit du modèle de coûts. **Partie marché exacte** (frais de courbe, impact propre, rejeu des échanges réels, latence). **Exécution incomplète**, et toujours dans le sens optimiste : N-1 loyer ignoré ; N-2 fermeture ; N-3 échecs ; N-4 atterrissage supposé certain ; N-5 aucune garde de glissement ; N-6 MEV/Jito ; N-7 WSOL ; N-8 positions ouvertes exclues. Le net W1 de −4,26 % est une **borne haute** (≈ −6,3 % avec le loyer). C-B prudent, mais ne couvre pas N-4 à N-6. Règle fixée avant W2 : « rentable » exigera en plus un net > 0 avec 1 échec et 10 slots, ainsi qu'une mesure PAPER temps réel de l'atterrissage et du glissement. | AUDIT_MODELE_COUTS_PAPER_CB_R02_v1_0.md (registre R02) | déclaré (R02) |

| 22/11 22:00Z | PAPERSTREAM 0.5.1 sur W1 : **VERIFIED**, 14 contrôles sur 14 true. Les 3 sha du bundle sont identiques ; master 191 ; 913 cycles réconciliés sur les 3 bras. Mémoire : somme des RSS ≤ 1 347 Mio contre 8 749 Mo projetés (ratio 0,154), sans override. Le résultat 0.4 est inchangé. **Aucun gain de vitesse** (6 h 31). Cause : SolUsdSeries.as_of, corrigée en 0.5.2.1. | ps051verdict02_out1.json, sha 1997a9d8 ; PAPERSTREAM.json cc2af356 | déclaré (R03) ; ancrage R02 en attente |

| 22/11 22:40Z | PAPERSTREAM **0.5.2.1** sur W1 : **VERIFIED** (14 contrôles sur 14 true). Durée 20 min 05 s, contre 6 h 31 pour la 0.5.1 (≈ ×19,5). W1 reproduit à l'octet : 3 sha, master 191, 913 cycles sur les 3 bras. Somme des RSS ≤ 1 512 Mio, contre 8 749 Mo projetés. Résultats 0.4 et 0.5.1 inchangés. | sortie ps0521verdict sha 173ed23b ; PAPERSTREAM.json cb287a2d | déclaré (R03) ; ancrage R02 en attente |

| 22/11 22:44Z | landslip 0.1 measure sur W1 (comptes seulement). **Lecture corrigée par R02** : 60,4 % des achats suivent un autre trade du pool à ≤ 3 slots, et 63,8 % à ≤ 4. L'activité est dense : des trades s'intercalent souvent pendant notre latence de 4 slots, ce qui est cohérent avec H-1 et la garde. Notre glissement n'est **pas** mesuré. Phrase retirée par R02 : « ~60 % des achats d'autrui atterrissent avant nous ». **Échecs (N-4)** : mesure structurellement nulle, car l'export ne conserve que les transactions réussies (backfill_export.py:166-167). N-4 n'est mesurable qu'avec une nouvelle collecte : BLOQUÉ PAR LE PROPRIÉTAIRE. | registre R02 | déclaré (R02) |

| 23/11 12:31Z | **Tableau consolidé de rentabilité v0.2, CONFORME selon R02** (registre 4b031215). Tout est exploratoire (W1) et rien n'est rentable. NÉGATIF : MASTER −4,26 % [−6,69 ; −1,95] (≈ −6,3 % avec loyer), C-A −5,45 %, L1 −5,14 %, L3 −7,81 %, crible L1 −10,29 %, T1 −5,59 %, C-D −4,59 %. INCONCLUSIF : T3′ (n 23). Placebos : W1 −4,60 %, palier bas −1,82 %. Aucune position : C-B, C-C, C-E, R-CP1. | TABLEAU_CONSOLIDE_RENTABILITE_v0_2.md (R01 2309060, sha 60499ad4, recalculé par R04). **Version finale 4b369cf (sha ebf63663, recalculé par R04)** : formulation du coût cloud (« ≤ 66 $ TTC, ≈ 64,7 estimés ») ; placebo sans verdict ; synthèse 7 NÉGATIVES, 1 INCONCLUSIVE. | vérifié par R04 ; contenu audité R02 |

| 23/11 13:57Z | R02 : (1) note HW1 / plafond (8a9c8f84) : pas d'incohérence. Plafond exploratoire : 168/170. HW1 : 5 hypothèses gelées avant W1, correction de Holm, publiées à part. (2) Cadre multi-générations (b4edc143) : générations de 3 hypothèses au plus, sur fenêtres disjointes ; W1 non clos tant que A2 n'est pas fait, donc seules les analyses descriptives sont permises. (3) Définitions gelées des indicateurs (b31a3c47) : l'expectancy est le chiffre de décision ; drawdown descriptif ; 7 sensibilités. | registre R02 | déclaré (R02) |

| 23/11 14:17Z | **Décomposition des pertes W1** (w1decomp 0.2, DESCRIPTIVE, exploratoire ; sortie df0d9cbb reproduite par R02). La perte MASTER vient des coûts : frais de courbe 59,8 %, loyer 36,5 %, tx 3,8 %. Brut −0,72 % [−3,11 ; +1,65] : aucun avantage de prix avant frais. Net −4,26 % ; −6,29 % avec loyer perdu. Après l'entrée : pic médian à 5 slots, 1er passage sous l'entrée à 17 slots en médiane. Cellules D3 légèrement positives (n 16 et 17) : NON INTERPRÉTABLES, bruit sur 24 cellules. | vérification R02 ee86eee4 | déclaré (R02) |

| 23/11 14:22Z | **Tableau de bord étendu** (dashx 0.2, sortie ef6b5b44 reproduite par R02). MASTER W1 (n 128) : win rate 30,5 % ; gain moyen +10,3 % ; perte moyenne −10,6 % ; profit factor 0,42 ; espérance −4,26 % ; drawdown 0,546 SOL (5,45 mises, la courbe ne dépasse jamais son départ). Sans les 5 meilleures : −5,33 %. Compte fermé : −4,36 %. Loyer perdu : −6,29 %. Écart au placebo +1,23 % [−2,23 ; +4,82], non significatif. Placebo W1 −4,59 %, PF 0,22. Verdicts inchangés. | vérification R02 595025c3 | déclaré (R02) |

| 23/11 17:24Z | R02 : **certificat d'enregistrement R-CP1 / B1 CONFORME** (d34c2c4e). R-CP1 : −3 % en 600 s ; B1 : +3 %. Les deux : ≥ 20 swaps, TP/SL ±2 %, 30 min, garde 2 %, α 0,05 puis 0,05/3, n 155, essais 169 et 170, témoins appariés par pool. Textes d'autorisation des étapes (b484d384), dont les champs sont à remplir par R03. Critères de sélection génération 2 (a21f90f3) : α_g = 0,025 × 2^(−(g−2)) pour g ≥ 2, risque total ≤ 0,10 ; demande de +3 essais (170 → 173). | registre R02 | déclaré (R02) |

## 5. Incidents

- 22/11 : R04 avait daté par erreur la directive d'autonomie de « ~19:45Z » ; elle date de 20:23:48Z. Corrigé ici, à la demande de R02.
- 23/11 21:23Z : fausse alerte. R02 avait bien reçu T-R01-3 ; son audit (a3f194dc) est arrivé à 21:24Z.
- 23/11 21:11Z : erreur d identifiant du programme CPMM dans le texte B(b) v1.2, déjà présenté au propriétaire ; corrigée en v1.3 (443bbfb9).
- 23/11 21:04:29Z : redémarrage du conteneur de R03 (5e observé) ; intégrité W1 à 0 écart.
- 23/11 08:47:44Z : le conteneur de R03 a redémarré ; les données ont survécu (0 écart d'intégrité). Seuls ≈ 71 % de W1 sont copiés à l'extérieur, le reste serait perdu à la fin de la session.
- 22/11 21:43Z : R01 a d'abord signalé une « décision δ » à prendre par le propriétaire, puis l'a retirée à 21:44Z après l'avis de R02. R04 l'avait transmise entre-temps et l'a corrigée.
- 22/11 20:28Z : un message de R02 à R01 a été perdu. Il demandait le plan de mesure N-4/N-5 et la garde de glissement ; il est absent du journal de R01 (2e perte de la journée). R01 demande le texte exact à R02. Ces travaux deviennent la tâche P3-b, placée avant P3-c.
- 22/11, 15:36–15:41Z : des messages de R02 adressés à R04 ont été perdus. Ils ont été rattrapés à 17:43Z.
- 22/11, entre 04:30Z et 15:33Z : le conteneur de R03 a redémarré 2 fois (epoch 195 → 197). W1 complet n'existe que dans ce conteneur ; la copie externe en couvre environ 71 %.
- Les sessions s'arrêtent dès qu'elles n'ont plus de tâche. La relance se fait par send_message de R04 au contrôle horaire, et R03 entretient une tâche de fond.
