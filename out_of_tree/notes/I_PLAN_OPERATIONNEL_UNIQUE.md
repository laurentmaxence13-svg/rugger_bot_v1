# Plan opérationnel unique — RUGGER MASTER, W1 et V3 (9 novembre 2026)

## 1. Terminé et validé (pas de reprise sans anomalie nouvelle)

| Élément | Preuve |
|---|---|
| Gel W1 | Arbre a054c00 / aff97638 ; empreintes 9c69e482, b5ccc318, 682447fd |
| S0 et les 200 slots de contrôle | S0 = 467275745, ancres ddcb2a57 et 795f8fc0 |
| Outillage w1aux v7.2 (dayj, lazy, parallel, ledger) | MANIFEST_v72 8d2b4a35, PASS R02 (4d246e9c) |
| Registre P0 épinglé, N = 32 | f1f26e36, ancré par R02 (96865df7) |
| Selfcheck sur la machine de R03 | CPython 3.12.3 ; 4aee76a3 ; empreinte 6eef4509 |

Divergences avec l'état que vous décrivez : aucune. Une précision : seul CPython 3.12 donne des résultats identiques ; 3.11 diffère au dernier chiffre.

## 2. Étapes W1 (l'ordre du protocole audité prévaut)

| # | Étape | Resp. | Dépend de | Preuve | Clôture |
|---|---|---|---|---|---|
| 1 | Relevé Helius AVANT | Propriétaire | Fin de fenêtre (14/11, 10 h 21 Z) | Relevé consigné | R02 l'ancre |
| 2 | Fetch des 200 blocs (≤ 720 crédits) | R03 | **GO 1** | blocks_summary.json et son journal | R02 ancre le sha |
| 3 | Collecte LaunchLab (plafond 793 637 crédits) | R03 | **GO 2** | Run vérifié et complet | `verify` ok |
| 4 | `dayj gate` : verify, compare PASS, relevé APRÈS | R03 | 3 | GATE.json | R02 ancre l'empreinte |
| 5 | Collecte SOL/USD (plafond 83 000 crédits) | R03 | **GO 3** | Run vérifié | `verify` ok |
| 6 | `dayj export`, exclusions ≤ 5 %, **nombre de signatures** | R03 | 4, 5 | EXCLUSIONS.json et le comptage | R02 ancre ; décision mémoire (§4) |
| 7 | `dayj series`, puis `trials` (lazy, 4 processus, reprise) | R03 | 6 | SHA256SUMS ; STATS ; INDEX | R02 ancre SHA256SUMS |
| 8 | `dayj evaluate` (N = 32) | R03 ou machine cloud | 7, et §4 | w1_report.json | R02 ancre |
| 9 | `dayj ledger` : BUY/SELL recalculés, P&L décomposé | R03 | 8 | ledger.json et ledger.md, verdict PASS | R02 ancre |
| 10 | `dayj dossier`, puis recalcul manuel du premier cycle M1 clos | R03, puis R02 | 9 | DOSSIER_W1.json ; reçu R02 | Les trois verdicts (§6) |

## 3. Décisions qui exigent votre GO

1. Le **GO 1, le GO 2 et le GO 3**, chacun après lecture. ⚠ Chaque GO doit être donné **directement dans la session de RUGGER 03**, qui exécute. Un message transmis par un autre agent n'est pas une autorisation.
2. **D1**, la machine pour evaluate, seulement si le comptage de l'étape 6 dépasse le seuil (§4).
3. **Transfert des données vers cette machine** : hôte réseau autorisé et accès à la machine (secret). Cela ne se pose que si D1 est décidée.

## 4. Plan RAM et solution de secours

- **Grandeur de dimensionnement** : les signatures EXPORTÉES, c'est-à-dire la somme des `signatures` du MANIFEST des pools, échecs compris. Ce n'est ni les transactions décodées ni les crédits.
- **Mesures** sur les packs synthétiques ×20 et ×40, dans des processus séparés, confirmées par R02 :
  - trials : 24,6 Ko par signature (parent et 4 processus) ;
  - **evaluate (gelé) : 54 à 56 Ko par signature** ;
  - ledger : 25,7 Ko par signature.
- **Lazy** : il fait partie de w1aux v7.2, audité, et il est utilisé dans trials et evaluate. Le code gelé n'est pas modifié.
- **Seuil** sur la machine de R03 (MemAvailable 15,2 Go) :
  - evaluate avec la marge ×1,5 : ~180 000 signatures ;
  - sans marge : ~275 000 ;
  - ce n'est **pas une garantie** : les pentes ont été calibrées sur des pools synthétiques.
- dayj vérifie la projection avant trials, evaluate et ledger, et **s'arrête proprement** si elle dépasse. Un arrêt pour mémoire se reprend sans perte d'intégrité.
- **Secours** : une machine cloud de 48 à 64 Go pour evaluate et ledger (un W1 de type P0 représente ~420 000 signatures, soit ~23 Go). R04 prépare le dossier : fournisseur, prix horaire, durée (moins de 4 h), coût maximal, sécurité, et tests d'équivalence (CPython 3.12, selfcheck 4aee76a3, empreintes à l'arrivée). **Aucune location sans votre accord.**

## 5. Conditions du premier BUY/SELL complet et de l'évaluation économique

- Un cycle M1 n'est « complet » que s'il est clos et recalculé par le ledger :
  - frais LaunchLab, impact, coûts de transaction et échecs ;
  - P&L décomposé en mouvement de marché − slippage − frais − coûts ;
  - et que R02 a reçu à la main le premier cycle clos.
- **Conclusion économique possible seulement si M1 atteint au moins 140 cycles clos et 50 créateurs indépendants**, avec au plus 5 % de positions non closes (règle gelée). Sinon, la décision est `WAIT_INSUFFICIENT_DATA`, c'est-à-dire **NON CONCLUANT**.
- ⚠ Le taux d'entrée de M1 est **inconnu**. Rien ne garantit que W1 atteigne 140 cycles.

## 6. Métriques et verdicts

- **Économique**, selon la règle gelée : rendement net moyen par cycle, avec un IC 95 % bootstrap par créateur dont la borne basse est positive ; moyenne pessimiste positive ; deux moitiés positives ; sensibilité à une latence de 10 positive ; H1 (M1 > 0) et H2 (M1 > placebo P1b) rejetées après Holm ; DSR > 0,95 avec N = 32.
  - Décision `CHALLENGER_FOR_W2` (un résultat à confirmer, **jamais** une autorisation LIVE), `NO_GO` ou `WAIT_*`.
  - Publiés en plus : P&L brut et net, nombre de cycles, taux de réussite, gain et perte moyens, décomposition des coûts, comparaison avec S1 et S2 (snipe et délai fixe), P1 et P2 (placebo et abstention), et S3.
- **Technique** : toutes les empreintes sont ancrées, le ledger est PASS et le reçu de R02 est fait.
- **Opérationnel** : réserves connues dès maintenant, tirées du code gelé.
  - **Pas de `min_out`** : un ordre qu'un routeur réel aurait rejeté est compté comme rempli, un biais favorable au MASTER.
  - Pas de couche portefeuille.
  - Latence fixée à 4 slots.
  - Les échecs ne sont qu'un stress descriptif.
  - La fenêtre ne couvre qu'environ 5 jours.

## 7. Hypothèses V3 prioritaires (conception seulement avant la clôture de W1)

| | Mécanisme | Données | Métrique | Critère d'échec fixé d'avance |
|---|---|---|---|---|
| **H1** Filtrage | Un créateur ou un financement suspect, ou une concentration au lancement, annonce un rug | Créations signées, payeurs, top-holders, déjà dans les archives | Espérance nette du bras filtré moins celle du bras non filtré, par créateur | Si la borne basse de l'IC 95 % est ≤ 0, ou si le gain disparaît une fois les faux positifs comptés |
| **H2** Entrée | Le momentum confirmé paie moins cher que ce que coûte le risque d'entrer trop tôt | Flux et acheteurs dans les 10, 30 et 60 premières secondes | Rendement net contre un délai fixe et un placebo à âge égal | Si l'écart n'est pas significatif, ou n'est positif que dans une moitié de l'échantillon |
| **H3** Sortie | Une sortie adaptative ou un stop catastrophe limite la queue de pertes | Trajectoire après l'entrée, liquidité de sortie | Perte au 5e centile (CVaR 5 %) et rendement net | Si la queue ne s'améliore pas, ou si le net se dégrade |

Ces hypothèses sont pré-enregistrées, testées sur des données distinctes de W1 (W2), avec un N cumulé dans le DSR et la conservation des expériences négatives. Elles ne comprennent **aucune** optimisation de MASTER W1.

## 8. Ce qui peut avancer maintenant sans toucher à W1

| Tâche | Resp. | Preuve | Clôture |
|---|---|---|---|
| Dossier de l'option cloud D1, plus le chemin de transfert | R04 | Fiche chiffrée | Prête avant l'étape 6 |
| Registre des décisions, et sauvegarde des PETITS fichiers (D2) | R04 | Registre ; liste des empreintes | Tenue à jour à chaque ancrage |
| Fiches pré-enregistrées de H1, H2 et H3 (texte, sans aucune donnée W1) | R01, audit R02 | Fiches hachées | PASS R02 avant toute donnée W2 |
| Réserves opérationnelles du §6 | R02 | Note | Inscrites avant le verdict |

Rien d'autre : pas de nouveau code W1, pas de nouvelle mesure, pas de nouvel audit.

## 9. Blocages et contradictions

1. **evaluate (gelé) au-delà de ~180 000 signatures** : il faudra décider D1 sur le comptage réel.
2. **D2** : les fichiers .pkl de reprise et les bundles (plusieurs Go) ne peuvent pas passer par la conversation. Seuls les petits fichiers et les empreintes sont transmissibles. **Il n'existe donc pas de sauvegarde durable des gros fichiers** si la session de R03 est perdue : ils devraient alors être recalculés depuis les collectes, elles-mêmes dans la même session.
3. **Machine cloud** : transférer 2 à 3 Go hors de la session de R03 suppose une autorisation réseau et un secret d'accès, deux décisions qui vous reviennent.
4. **Conclusion économique** : elle n'est possible que si M1 atteint 140 cycles clos et 50 créateurs. Sinon le résultat est NON CONCLUANT ; ce n'est pas un échec du protocole.
5. **GO** : seuls les GO donnés dans la session de R03 valent autorisation. Les agents communiquent entre eux (send_message), mais leurs messages n'autorisent rien.
