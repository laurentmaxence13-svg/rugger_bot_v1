# PROJET de fiche de gel N1 « fournisseur de liquidité », conception R04-6, fenêtre G2-3 (v0.6)

RUGGER 01, 24/11/2026.
- **Décision R04-6** (21:27Z et 21:29Z), avis de R02 ancré : recevable sous C1 et C2. Essai 170, PAPER uniquement.
- **Prête à ancrer, NON ancrée.** R02 l'ancre avec son code AVANT toute lecture de la fenêtre, donc avant le
  06/12/2026 10:21:26Z.
- Aucune donnée de la fenêtre n'est lue.
- **v0.6** : c'est la fiche à ancrer, appelée « v0.5 » dans le message de R02 de 21:56Z. La v0.5 (4f43a7a4) était le
  brouillon d'avant la mesure.
  - Elle inscrit la sortie de n1rot, VÉRIFIÉE par R02 (sortie 6b9b02a9, liste c72bd586) : N1 est ÉVALUABLE sur
    3 pools, au plus 36 pool-jours.
  - Elle référence n1verdict 0.2.1 (garde K-1).
- **v0.5** : audit R02 de R04-6 intégré.
  - PASS pour g23five 0.2, lpcost 0.2 et n1rot 0.2.
  - n1verdict 0.2.1 corrige la réserve K-1 (garde « sans le pool qui porte le résultat »).
  - (i) ACCEPTÉ : une position non valorisable vaut une perte totale.
  - (ii) FEU VERT donné à R03 pour UNE exécution de n1rot 0.2. Elle a été faite le 24/11 à 21:55Z (§ 3).
- **v0.4** : elle remplaçait la conception « 0,1 SOL, aller-retour quotidien » de la v0.3.
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
- **Exécution (faite)** : une seule, par R03, le 24/11/2026 à 21:55:21Z, hors ligne, 0 crédit (commit R03 98156b7).
  - Sortie `N1ROT_RESULT.json` : sha256 `6b9b02a949c2dc5859332ac2fae814c17f491a21c3fa173682a8122dc26171c3`, recalculé et
    VÉRIFIÉ par R02.
  - Autres empreintes de l'exécution : MANIFEST n1rot 2a17791d, u2 3ca0260a, pages pré-T0 8fb3cac4, AmmConfig
    `be8d13d1a6def925af32187937fde9ef21d2d7ca5efb1c6e1fd6611b3f12cfe1`.
  - 1 385 transactions n'ont pas été décodées ; c'est déclaré.
  - Aucun rendement LP n'a été calculé.

| Pool | Rotation médiane (par jour) | Seuil R04-6 du pool | Rapport | Retenu |
|---|---|---|---|---|
| AEZjoU | 26,45 % | 21,91 % | 1,21× (marge faible) | OUI |
| Gms3Ma | 0,19 % | 21,85 % | 0,01× | NON |
| G8kgi7 | 128,48 % | 21,88 % | 5,87× | OUI |
| GdxFyc | 29,05 % | 23,20 % | 1,25× (marge faible) | OUI |

- **Univers N1 (ANCRÉ par cette fiche)**, dans l'ordre de la fiche G2-3 :
  1. `AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca`
  2. `G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh`
  3. `GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A`
- Le sha de la liste, adresses jointes par « \n », vaut
  `c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da`. Il a été recalculé par R01 et par R02.
- **Marges déclarées** : AEZjoU et GdxFyc dépassent le seuil de peu (1,21× et 1,25×). Le seuil n'est qu'une condition
  nécessaire, et la LVR n'y est pas comptée.

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
- **Valeur (R02 (i), ACCEPTÉE)** : la perte totale de la mise, des transactions et des loyers, répartie sur les
  12 jours.
  - Chaque jour vaut −(1 + (transactions + loyers) / mise) / 12.
  - La mise est 0,5 % de la réserve SOL avant le dernier swap pré-T0.
- **Refus de garde** : aucune position. Les 12 jours sont publiés et ne comptent pas comme entrées.

## 6. Inférence et mot (`n1verdict` 0.2 → `g23five` 0.2, sans modification)

- Bootstrap par blocs de **2 jours consécutifs** par pool (`block_days = 2`), stratifié par pool.
  - 10 000 tirages, graine = **int(sha de CETTE fiche ancrée[:8], 16)**.
  - La fiche G2-3 reste sur g23five 0.1.1, avec des blocs d'1 jour.
- **Planchers de G2-3 inchangés, garde K-1** :
  - planchers : ≥ 30 pool-jours entrés, ≥ 3 pools, Kish ≥ 2,5, aucun pool > 50 % ; sinon INCONCLUSIF, avant tout
    NO-GO ;
  - NO-GO si la borne haute à 95 % est < 0 ;
  - GO_PILOTE seulement si la borne basse est > 0 sur l'ensemble ET **sans le pool qui porte le résultat** : le pool
    à la plus grande somme d'écarts, égalités par l'identifiant (K-1 de R02 ; tous les pools ont 12 pool-jours, donc
    « le plus fourni » serait arbitraire) ;
  - sinon INCONCLUSIF.
- G-0 non passé → STOP.
- **Planchers sur 3 pools** : au plus 36 pool-jours, Kish 3, part 33 %.
  - Si un seul pool n'a pas de position (refus de garde), il reste 24 pool-jours, sous 30 : le mot est INCONCLUSIF.
  - Une position non valorisable reste une entrée, comptée en perte totale.
- Puissance : 36 pool-jours au plus (3 pools × 6 blocs de 2 jours) ; une seule position par pool, donc une forte
  dépendance au sein d'un pool. « Sous la cible » est publié d'office.
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
- Il est consommé à l'ancrage : n1rot a rendu N1 évaluable (3 pools).

## 9. Code et données à ancrer avec la fiche

| Élément | Version | Empreinte | Statut |
|---|---|---|---|
| `n1verdict` | 0.2.1 | MANIFEST `09156b085cc432fa3524783838c02977b6869514b5f31a091a61ab39885e999d` ; verdict.py `e6db8985b24e8eb4f7246428041a3f9d8a22d7ea580a9ef05c7d1d2631a199f8` | 0.2 PASS sous réserve K-1 ; 0.2.1 (K-1 corrigé) à vérifier par R02 |
| `lpcost` | 0.2 | MANIFEST `ee9c144ca85f3de9489c60e0c74edf8ee685ed1e851d8d74aa392863313849eb` ; continuous.py `e849033f…` ; model.py `ba31fcfb…` (0.1, inchangé) | PASS R02 |
| `n1rot` | 0.2 | MANIFEST `2a17791d1098c6a4b1ec155cb5dd8dcfcf067bd445e4467e2ce3a0020cc53fba` ; rotation.py `ae57b86a…` | PASS R02 ; feu vert d'exécution donné à R03 |
| `g23five` | 0.2 | MANIFEST `099ea5321908768374e0aae4a170dc4e3fa99f2105d67bbfb65c9e4c40d0c4ad` ; verdict.py `15749bd5…` | PASS R02 |
| `cpmmcost` | 0.3 | `a0bd2adbfaeaa5b14b79c200b066f9a14bb1408c57469e319d6e1db9b92de547` | PASS R02 |
| `closedacct` | 0.2 | `6d420ffa0e988e5e2698867758638707d762549c24aa0e328a5cc2f68b4f4620` | dépendance de cpmmcost ; R02 doit confirmer la version |
| `cpmmx` | — | arbre git `e103437142c74830e6ddc293d84529501f6b1162` (99c6688) | réutilisé tel quel |
| `g1ind` | 0.6.1 | `12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a` | PASS R02 (vocabulaire) |
| `cpmmpilot` | 0.2.8 | sha À VENIR (R03) | collecte |
| sortie de n1rot | — | `6b9b02a949c2dc5859332ac2fae814c17f491a21c3fa173682a8122dc26171c3` ; liste `c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da` | VÉRIFIÉE par R02 : 3 pools, ÉVALUABLE |

Rien ici n'est un résultat économique.
