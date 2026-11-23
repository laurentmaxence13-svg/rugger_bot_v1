# RUGGER MASTER — État unique (tenu par R04)

Mis à jour le 2026-11-23 à 10:35Z.
Légende des preuves :
- « vérifié » : R04 l'a constaté lui-même (ref git, statut de session) ;
- « déclaré » : affirmé par l'agent, ancré à son registre ou dans son message.

## 1. Autorisations vérifiées à la source

Référence : REGISTRE_AUTORISATIONS_VERIFIEES_R02_v1_0.md, sha256 a4b9d467…69e2 (registre R02 0dbe0572). Couverture partielle : session R04 avec deux trous, R01 en cours d'extraction.

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
| PAPER_LIVE | Choix A, B ou C face au facteur ≈ 16 de crédits (7,68 M getTransaction contre ≈ 467 k Free) ; puis D-1, D-3, D-5, D-6, D-7 (DX v0.2, 7f6c5f4, CONFORME selon R02) | session de l'exécutant |
| W2 | Format, k, plafond, plan Helius, GO (après A2, HW1 et C-B) | session du propriétaire |
| Hygiène | Retirer le secret Helius de R03 ; désactiver les 4 routines d'étiquette | paramètres |

## 2 bis. Opérations prêtes (code audité, sans décision en attente côté agents)

- A2 : paquet v2.6.6 au PASS R02 ; chaîne w1chain 0.2 au PASS (verdict → HW1 → C-B).
- CPMM : cpmmfmt CONFORME, cpmmcost 0.3, cpmmprereg 0.2 (R-CP1 figée) ; règles de lecture gelées par R02.
- PAPER_LIVE : protocole v0.2 conforme ; plbench 0.2 ; rtgate 0.2 ; papercost 0.1 ; landslip ; DX v0.2. Seul l'adaptateur d'acquisition reste à écrire, après le choix de D-2.
- Preuves : intégrité W1 sans écart ; remise au propriétaire des preuves de moins de 100 Mo confiée à R03.

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

## 5. Incidents

- 22/11 : R04 avait daté par erreur la directive d'autonomie de « ~19:45Z » ; elle date de 20:23:48Z. Corrigé ici, à la demande de R02.
- 23/11 08:47:44Z : le conteneur de R03 a redémarré ; les données ont survécu (0 écart d'intégrité). Seuls ≈ 71 % de W1 sont copiés à l'extérieur, le reste serait perdu à la fin de la session.
- 22/11 21:43Z : R01 a d'abord signalé une « décision δ » à prendre par le propriétaire, puis l'a retirée à 21:44Z après l'avis de R02. R04 l'avait transmise entre-temps et l'a corrigée.
- 22/11 20:28Z : un message de R02 à R01 a été perdu. Il demandait le plan de mesure N-4/N-5 et la garde de glissement ; il est absent du journal de R01 (2e perte de la journée). R01 demande le texte exact à R02. Ces travaux deviennent la tâche P3-b, placée avant P3-c.
- 22/11, 15:36–15:41Z : des messages de R02 adressés à R04 ont été perdus. Ils ont été rattrapés à 17:43Z.
- 22/11, entre 04:30Z et 15:33Z : le conteneur de R03 a redémarré 2 fois (epoch 195 → 197). W1 complet n'existe que dans ce conteneur ; la copie externe en couvre environ 71 %.
- Les sessions s'arrêtent dès qu'elles n'ont plus de tâche. La relance se fait par send_message de R04 au contrôle horaire, et R03 entretient une tâche de fond.
