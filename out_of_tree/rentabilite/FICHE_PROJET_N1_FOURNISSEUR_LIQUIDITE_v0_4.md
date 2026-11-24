# PROJET de fiche de gel N1 « fournisseur de liquidité », conception R04-6, fenêtre G2-3 (v0.4)

RUGGER 01, 24/11/2026.
- **Décision R04-6** (21:27Z et 21:29Z), avis de R02 ancré : recevable sous C1 et C2. Essai 170, PAPER uniquement.
- **Prête à ancrer, NON ancrée.** R02 l'ancre avec son code AVANT toute lecture de la fenêtre, donc avant le
  06/12/2026 10:21:26Z.
- Aucune donnée lue ; n1rot n'est PAS exécuté : il attend le feu vert de R02.
- **v0.4** : elle remplace la conception « 0,1 SOL, aller-retour quotidien » de la v0.3, dont l'audit est suspendu.
- Ce n'est pas un trade du Master et cela ne compte jamais pour 50/20. Étiquettes : MASTER_RESEARCH_PAPER,
  HISTORICAL_REPLAY, LP_SIDE_RESEARCH.

## 1. Position et estimand

- **Position** : par pool, UNE position LP notionnelle.
  - Sa taille est 0,5 % de la réserve WSOL lue à l'ouverture (état de décision à T0).
  - Elle est ouverte une fois au début du jour 0 et retirée une fois à la fin du jour 11.
  - Elle n'engage aucun capital.
- **Estimand (C1)** : « Sur CES pools et dans CETTE fenêtre, la position LP bat-elle la détention des mêmes jetons,
  nette de TOUS les coûts ? »
  - **Le mot porte sur l'ÉCART À LA DÉTENTION**, net des coûts d'entrée et de sortie, des transactions et des loyers.
  - **Le net absolu en SOL**, qui inclut l'exposition au prix, est publié en DESCRIPTIF.
- **Portée déclarée** : une condition NÉCESSAIRE, pas un rendement absolu ; taille notionnelle ; aucun capital.

## 2. Mesure (`lpcost` 0.2, `continuous_position`)

- **G(t)** = V_LP(t) − V_DÉTENTION(t), au prix observé du pool.
  - V_LP = 2 s(t) Q(t), avec s(t) notre part après les événements LP d'autrui.
  - V_DÉTENTION = base déposée × Q/B + SOL déposé.
- **Écart** = G(fin) − G(début) − coûts.
- **Coûts** : entrée, sortie, 6 transactions et loyers perdus.
  - Entrée : l'échange de mise // 2 sur le pire état d'atterrissage, avec la garde de 20 000 ppm et la latence de
    4 slots.
  - Sortie : l'arrondi du retrait, puis la vente au pire des 4 candidats.
  - Transactions : 6 × 105 000 lamports figés.
- **Marques aux bornes de jour** : le premier état observé après la borne, c'est-à-dire les réserves journalisées
  avant le premier swap suivant, avec notre part après les événements LP strictement antérieurs. Ce marquage est
  exact et ne franchit jamais un événement LP.
- **Pool-jour k (C2)** = variation de G sur le jour k − coûts / 12, en unités de la mise du pool. La somme des
  12 jours est exactement l'écart.
- **Identité exacte** : net absolu = écart + G(début) + mouvement de prix des jetons détenus ; le résidu est nul.

## 3. Univers et règle de rotation (`n1rot` 0.2, fixée AVANT la mesure)

- **Pools candidats** : les 4 de G2-3, dans l'ordre de la fiche G2-3 v0.5 (liste
  `812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80`) :
  1. `AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca`
  2. `Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr`
  3. `G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh`
  4. `GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A`
- **Rotation mesurée** : volume côté SOL / (2 × réserve SOL avant le premier swap du jour), médiane des 7 jours de
  [T0 − 7 j ; T0), sur les pages PRÉ-T0 d'A2r. Aucun rendement LP n'est calculé.
- **Seuil `r04_6_break_even`, calculé EN CODE, pool par pool** :

  rot\* = (6 transactions + coût d'entrée + coût de sortie à prix constant) / (12 × mise × taux de palier ×
  (1 − parts protocole et fonds))

  - Il est lu sur le dernier état pré-T0 du pool.
  - Ordre de grandeur synthétique : environ 25 % par jour à 100 SOL, 22 % à 200 SOL ; 2 points de plus avec 500 ppm de
    frais créateur.
  - Ce n'est qu'une condition nécessaire : la LVR n'est pas comptée.
- **Règle** :
  - un pool est retenu si sa rotation médiane est ≥ son seuil ;
  - N1 est évaluable seulement avec ≥ 3 pools retenus ;
  - sinon N1 est **NON ÉVALUABLE** : aucun ancrage, et l'essai 170 est épargné.
- **Exécution** : une fois, par R03, hors ligne, 0 crédit, après le feu vert de R02.
  - La sortie et son sha sont recopiés ici (§ 9) avant l'ancrage.
  - La liste retenue remplace la liste candidate.

## 4. Fenêtre et données

- **Fenêtre** : [24/11/2026 10:21:26Z ; 06/12/2026 10:21:26Z), D = 12 j.
- **Pages** : les MÊMES que G2-3, collectées par R03 avec cpmmpilot 0.2.8 : 0 crédit de plus.
- **État avant T0** (point (b) accepté par R02) : la ligne de chaque pool contient aussi ses pages PRÉ-T0 d'A2r.
  - Elles servent UNIQUEMENT à l'état au premier atterrissage et à la mise d'une position non valorisable, jamais à
    un résultat.
  - La ligne est construite par R03.

## 5. Position non valorisable, refus de garde

- **Causes « non valorisable »** : une liste FERMÉE (`n1verdict.UNPRICED`, point (a) accepté).
  - Événement LP au point d'atterrissage, état de sortie vide, pool vidé, événement LP sur coffre vide, type LP
    inconnu, aucun état au point d'atterrissage.
  - Toute autre erreur arrête le verdict.
- **Valeur proposée pour R04-6** : la perte totale de la mise et des transactions, répartie sur les 12 jours.
  - Chaque jour vaut −(1 + (transactions + loyers) / mise) / 12.
  - La mise est 0,5 % de la réserve SOL avant le dernier swap pré-T0.
  - **À CONFIRMER PAR R02** : sa décision (c), −100 630 000 lamports, portait sur la conception de la v0.3.
- **Refus de garde** : aucune position. Les 12 jours sont publiés et ne comptent pas comme entrées.

## 6. Inférence et mot (`n1verdict` 0.2 → `g23five` 0.2, sans modification)

- Bootstrap par blocs de **2 jours consécutifs** par pool (`block_days = 2`), stratifié par pool.
  - 10 000 tirages, graine = **int(sha de CETTE fiche ancrée[:8], 16)**.
  - La fiche G2-3 reste sur g23five 0.1.1, avec des blocs d'1 jour.
- **Planchers et garde de G2-3, inchangés** :
  - planchers : ≥ 30 pool-jours entrés, ≥ 3 pools, Kish ≥ 2,5, aucun pool > 50 % ; sinon INCONCLUSIF, avant tout
    NO-GO ;
  - NO-GO si la borne haute à 95 % est < 0 ;
  - GO_PILOTE seulement si la borne basse est > 0 sur l'ensemble ET sans le pool le plus fourni ;
  - sinon INCONCLUSIF.
- G-0 non passé → STOP.
- Puissance : 48 pool-jours au plus, soit 4 pools × 6 blocs de 2 jours ; une seule position par pool, donc une forte dépendance au sein d'un pool. « Sous la cible » est publié
  d'office.
- **Sensibilités (descriptives)** : (1, 1, 1) échec ; garde à 50 000 ppm ; loyers perdus.

## 7. Multiplicité, limites, portée, vocabulaire

- **Multiplicité** : α = 0,05 unilatéral par hypothèse au pilote, avec la mention « 2 hypothèses sur la même
  fenêtre » (G2-3 et N1, corrélées). Holm en confirmation.
- **L1** : la fraction f d'un événement LP d'autrui est calculée sur le coffre BRUT (frais protocole et fonds
  inclus). Léger biais.
- **L2** : nos propres échanges et dépôts ne sont pas rejoués (0,5 % de la réserve) ; les pires états à l'entrée et à
  la sortie couvrent cet effet.
- **L3** : le mot porte sur l'écart à la détention net de tous les coûts. C'est une condition nécessaire, pas un
  rendement absolu ; le net absolu est descriptif.
- **Portée** :
  - ces pools, cette fenêtre, cette configuration (0,5 % de la réserve, 12 jours, un aller-retour) ;
  - un GO_PILOTE autorise seulement à PROPOSER une confirmation sur les mêmes pools dans une fenêtre neuve ;
  - aucune généralisation, ni au Master.
- **Vocabulaire** : mots STOP, INCONCLUSIF, NO-GO, GO_PILOTE ; vocabulaire fermé contrôlé sur tout le document.

## 8. Essai

- L'essai 170.
- Il est consommé à l'ancrage, et seulement si n1rot rend N1 évaluable.

## 9. Code et données à ancrer avec la fiche

| Élément | Version | Empreinte | Statut |
|---|---|---|---|
| `n1verdict` | 0.2 | MANIFEST `75134f87156470e556c2f61b8b9f8c74965170a4014920c8d0bb12f7f25b1b27` ; verdict.py `ce565f19c5f93f7802eebc15b2e8c2f053850fe9d147ea746dcb6414b019d1b3` | à auditer |
| `lpcost` | 0.2 | MANIFEST `ee9c144ca85f3de9489c60e0c74edf8ee685ed1e851d8d74aa392863313849eb` ; continuous.py `e849033f…` ; model.py `ba31fcfb…` (0.1, inchangé) | à auditer |
| `n1rot` | 0.2 | MANIFEST `2a17791d1098c6a4b1ec155cb5dd8dcfcf067bd445e4467e2ce3a0020cc53fba` ; rotation.py `ae57b86a…` | à auditer, puis feu vert d'exécution |
| `g23five` | 0.2 | MANIFEST `099ea5321908768374e0aae4a170dc4e3fa99f2105d67bbfb65c9e4c40d0c4ad` ; verdict.py `15749bd5…` | à auditer |
| `cpmmcost` | 0.3 | `a0bd2adbfaeaa5b14b79c200b066f9a14bb1408c57469e319d6e1db9b92de547` | PASS R02 |
| `closedacct` | 0.2 | `6d420ffa0e988e5e2698867758638707d762549c24aa0e328a5cc2f68b4f4620` | dépendance de cpmmcost ; R02 doit confirmer la version |
| `cpmmx` | — | arbre git `e103437142c74830e6ddc293d84529501f6b1162` (99c6688) | réutilisé tel quel |
| `g1ind` | 0.6.1 | `12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a` | PASS R02 (vocabulaire) |
| `cpmmpilot` | 0.2.8 | sha À VENIR (R03) | collecte |
| sortie de n1rot | — | sha À VENIR (R03) | après le feu vert |

Rien ici n'est un résultat économique.
