# RUGGER MASTER — État unique (tenu par R04)

Mis à jour le 2026-11-22 à 20:30Z (corrections R02 appliquées).
Légende des preuves :
- « vérifié » : R04 l'a constaté lui-même (ref git, statut de session) ;
- « déclaré » : affirmé par l'agent, ancré à son registre ou dans son message.

## 1. Autorisations du propriétaire en vigueur

| # | Autorisation | Source | Périmètre / plafond / conditions |
|---|---|---|---|
| A1 | Travaux techniques hors ligne permanents | Directives « autonomie maximale » et « autonomie totale », événement 60283acd, 22/11 20:23:48Z | Recherche, code, tests, mutation, intégrité, audits, protocoles, documentation, commits, préparation. Aucune exécution sur les données protégées hors des autorisations A3 à A5. |
| A2 | Analyses hors ligne gratuites sur W1 ancré | Directive 5aff3383 du 20/11 19:00Z, point 1 | Après PASS de R02. Une seule exécution par analyse. Les critères sont fixés avant l'exécution. |
| A3 | Verdict technique PAPERSTREAM W1 | Décision de continuité du 22/11, point 1 | R02 documente 191/128 et rend un verdict distinct. L'échec initial de psverdict reste enregistré. Aucun recalcul qui remplacerait le premier résultat. |
| A4 | cpmmfmt 0.1, une fois, sur P0 visible aca7de08 | 22/11, point 2 | Hors ligne, sans réseau, sans données réservées. Contrôle par R02. **Consommée** : autorisation écrite dans la session R03 (événement 7aec4137, 20:24:05Z, vérifié par R02) ; exécution unique de 20:24:20Z à 20:24:25Z. |
| A6 | feeage 0.2 sur P0 visible | 5aff3383, point 2 ; 55678c09 (20/11 19:22Z), après contrôle du MANIFEST aca7de08 | **Consommée** (fait). |
| A7 | Répartition des rôles : R02 fait l'audit statistique et le protocole W2, R03 les analyses économiques autorisées | 47308aed, 20/11 19:10Z | Précise aussi : « 66 $ n'est pas une autorisation de dépense ». |
| A5 | Vérifications hors ligne de PAPERSTREAM 0.5.x sur W1 | 22/11, point 3 | Après validation de R02. Les résultats du run 0.4 ne sont jamais remplacés. Objectif : identité exacte avec W1 et respect des limites mémoire. |

**Non autorisé** (le silence du propriétaire ne vaut jamais accord) :
- trading réel ;
- toute dépense (Google Cloud ou autre) ;
- lancement d'A2 ;
- transfert Google Cloud ;
- nouvelle collecte ;
- crédits Helius (pilote CPMM étapes 0 et 1, collecte W2) ;
- lancement de W2 ;
- fusion dans `main` ;
- contournement des protections ;
- jeton dans un chat ;
- modification rétroactive des critères ;
- dépassement du plafond d'essais.

Plafond d'essais : N = 168 sur 170, hors HW1. La lecture HW1 ajoute +5. Le pilote CPMM R-CP1 porterait N à 169 sur 170 (note CPMM v0.2). Confirmé par R02 (Dossier B v1.9, 2c25a090, § 5) : le plafond de 170 s'entend hors HW1 ; HW1 ajoute 5 essais publiés à part, soit 173 au total, sans violation. Il reste 2 essais hors HW1. L'admission C-B coûte +0, car c'est une règle fermée.

## 2. Décisions réellement réservées au propriétaire — BLOQUÉ PAR LE PROPRIÉTAIRE

| Décision | Ce qui est prêt | Débloque |
|---|---|---|
| Signer l'exception A2 : fiche R02 v1.1 (e2a93ea8) avec son erratum v2.6.6, B1, C1/P1, ≤ 66 $ TTC, risque de sauvegarde | Paquet v2.6.6 au PASS de R02 (d0c2ccd, MANIFEST 490a28f1) ; texte du § 7 transmis à 17:43Z | Verdict officiel W1, puis HW1, puis C-B |
| Pilote CPMM : source U-2, puis GO étape 0 (≤ 100 crédits), puis GO étape 1 (≤ 50 k) | Protocole v1.2 (a3a285a1) | Données CPMM réelles |
| Variables W2 : format, k, plafond, plan Helius | Dossier B v1.9 | Lancement W2 |
| Retrait du secret Helius de l'environnement R03 ; désactivation des 4 routines d'étiquette du 05/11 | — | Hygiène |

## 3. Tâches priorisées (autorisées, en parallèle)

| Prio | Tâche | Agent | Autorisation | État |
|---|---|---|---|---|
| P1 | Terminer le run 0.5.1 sur W1, sans modification | R03 | A5 | En cours depuis 15:29:53Z. À 20:20Z, 51 pools sur 2 273 et 53,3 % des octets traités (déclaré) |
| P1 | Lire le verdict 0.5.1 une seule fois avec ps051verdict 0.2, puis audit sans ajustement des critères | R03 puis R02 | A5 | En attente de la fin du run |
| P1 | Profil technique d'un pool, puis vérification de la 0.5.2.1 sur W1 (ps0521verdict 0.1) | R03, après GO de R02 | A5 | En attente du verdict 0.5.1 |
| P2 | Préparer hors ligne la chaîne verdict W1, puis HW1, puis C-B : scripts, critères gelés, tests | R01 ; audit R02 | A1 | w1chain 0.1 livrée (5a87ea8, vérifié). Audit R02 : **CORRECTIONS REQUISES** (c6629433). K-1, bloquant : le critère (viii) est exigé à tort pour l'admission, et la condition de sensibilité au payeur manque. Correction par R01 en cours. |
| P2 | Audit complet du modèle de coûts | R02 | A1 | **Fait** (voir § 4) |
| P3 | Plan de mesure hors ligne de l'atterrissage (N-4) et du glissement (N-5) sur les tx déjà collectées ; garde de glissement pour le moteur PAPER (préparation seulement) | R01 ; audit R02 | A1 | À faire |
| P2 | Préparer la réorientation CPMM, sans exploitation rétrospective : simulateur de coûts, critères gelés, decoder prêt pour cpmmfmt | R01 ; audit R02 | A1 | À faire |
| P3 | Liste des obstacles au PAPER BUY/SELL en flux temps réel, avec plan de tests hors ligne. Les rejeux restent étiquetés HISTORICAL_REPLAY. | R01 ; audit R02 | A1 | À faire |
| P4 | Préparer A2 v2.6.6 hors ligne : create_vm.sh sans valeurs de projet, checklist propriétaire | R04 | A1 | Prêt à remplir sur signature |

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

## 5. Incidents

- 22/11 : R04 avait daté par erreur la directive d'autonomie de « ~19:45Z » ; elle date de 20:23:48Z. Corrigé ici, à la demande de R02.
- 22/11, 15:36–15:41Z : des messages de R02 adressés à R04 ont été perdus. Ils ont été rattrapés à 17:43Z.
- 22/11, entre 04:30Z et 15:33Z : le conteneur de R03 a redémarré 2 fois (epoch 195 → 197). W1 complet n'existe que dans ce conteneur ; la copie externe en couvre environ 71 %.
- Les sessions s'arrêtent dès qu'elles n'ont plus de tâche. La relance se fait par send_message de R04 au contrôle horaire, et R03 entretient une tâche de fond.
