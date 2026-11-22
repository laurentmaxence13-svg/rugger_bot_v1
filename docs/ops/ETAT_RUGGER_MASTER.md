# RUGGER MASTER — État unique (tenu par R04)

Mis à jour le 2026-11-22 à 19:50Z.
Légende des preuves :
- « vérifié » : R04 l'a constaté lui-même (ref git, statut de session) ;
- « déclaré » : affirmé par l'agent, ancré à son registre ou dans son message.

## 1. Autorisations du propriétaire en vigueur

| # | Autorisation | Source | Périmètre / plafond / conditions |
|---|---|---|---|
| A1 | Travaux techniques hors ligne permanents | Directive d'autonomie du 22/11 | Recherche, code, tests, mutation, intégrité, audits, protocoles, documentation, commits, préparation. Aucune exécution sur les données protégées hors des autorisations A3 à A5. |
| A2 | Analyses hors ligne sur les données déjà autorisées | 21/11 | Après PASS de R02. Une seule exécution par analyse. Les critères sont fixés avant l'exécution. |
| A3 | Verdict technique PAPERSTREAM W1 | Décision de continuité du 22/11, point 1 | R02 documente 191/128 et rend un verdict distinct. L'échec initial de psverdict reste enregistré. Aucun recalcul qui remplacerait le premier résultat. |
| A4 | cpmmfmt 0.1, une fois, sur P0 visible aca7de08 | 22/11, point 2 | Hors ligne, sans réseau, sans données réservées. Contrôle par R02. **Bloquée par la plateforme** : le classifieur de R03 exige que le propriétaire écrive l'autorisation dans la session R03. |
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

Plafond d'essais : N = 168 sur 170, hors HW1. La lecture HW1 ajoute +5.

## 2. Décisions réellement réservées au propriétaire — BLOQUÉ PAR LE PROPRIÉTAIRE

| Décision | Ce qui est prêt | Débloque |
|---|---|---|
| Écrire l'autorisation A4 dans la session R03 | Texte transmis le 22/11 à 15:27Z | Contrôle du format CPMM |
| Signer l'exception A2 : fiche R02 v1.1 (e2a93ea8) avec son erratum v2.6.6, B1, C1/P1, ≤ 66 $ TTC, risque de sauvegarde | Paquet v2.6.6 au PASS de R02 (d0c2ccd, MANIFEST 490a28f1) ; texte du § 7 transmis à 17:43Z | Verdict officiel W1, puis HW1, puis C-B |
| Pilote CPMM : source U-2, puis GO étape 0 (≤ 100 crédits), puis GO étape 1 (≤ 50 k) | Protocole v1.2 (a3a285a1) | Données CPMM réelles |
| Variables W2 : format, k, plafond, plan Helius | Dossier B v1.9 | Lancement W2 |
| Retrait du secret Helius de l'environnement R03 ; désactivation des 4 routines d'étiquette du 05/11 | — | Hygiène |

## 3. Tâches priorisées (autorisées, en parallèle)

| Prio | Tâche | Agent | Autorisation | État |
|---|---|---|---|---|
| P1 | Terminer le run 0.5.1 sur W1, sans modification | R03 | A5 | En cours depuis 15:29:53Z (déclaré) |
| P1 | Lire le verdict 0.5.1 une seule fois avec ps051verdict 0.2, puis audit sans ajustement des critères | R03 puis R02 | A5 | En attente de la fin du run |
| P1 | Profil technique d'un pool, puis vérification de la 0.5.2.1 sur W1 (ps0521verdict 0.1) | R03, après GO de R02 | A5 | En attente du verdict 0.5.1 |
| P2 | Préparer hors ligne la chaîne verdict W1, puis HW1, puis C-B : scripts, critères gelés, tests | R01 ; audit R02 | A1 | À faire |
| P2 | Audit complet du modèle de coûts : frais de courbe et de tx, impact de prix, délais, échecs, fermeture des comptes (rent) | R02 | A1 | À faire |
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
| 22/11 | PASS de R02 : ps051verdict 0.2 (092ab57), A2 v2.6.6 (d0c2ccd), paperstream 0.5.2.1 (99a8a35), ps0521verdict 0.1 (5bc67c6) | registre R02 | commits vérifiés ; PASS déclarés |
| 22/11 | Fiche d'exception A2 v1.1 | e2a93ea8 | déclaré (R02) |

## 5. Incidents

- 22/11, 15:36–15:41Z : des messages de R02 adressés à R04 ont été perdus. Ils ont été rattrapés à 17:43Z.
- 22/11, entre 04:30Z et 15:33Z : le conteneur de R03 a redémarré 2 fois (epoch 195 → 197). W1 complet n'existe que dans ce conteneur ; la copie externe en couvre environ 71 %.
- Les sessions s'arrêtent dès qu'elles n'ont plus de tâche. La relance se fait par send_message de R04 au contrôle horaire, et R03 entretient une tâche de fond.
