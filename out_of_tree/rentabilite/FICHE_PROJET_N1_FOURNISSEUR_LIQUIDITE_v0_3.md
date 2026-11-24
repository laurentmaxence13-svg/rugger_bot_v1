# PROJET de fiche de gel N1 « fournisseur de liquidité » sur la fenêtre G2-3 (v0.3)

RUGGER 01, 24/11/2026.
- Décisions et audits :
  - R04-3 et R04-4 : N1 engagé, essai 170, PAPER uniquement ;
  - R02 : N1 RECEVABLE (notes 0b64abd6 et 2f2e0707) ; lpcost 0.1 PASS TECHNIQUE ; g23five 0.1.1 PASS.
- **Prête à ancrer, NON ancrée.** R02 l'ancre avec la fiche G2-3 v0.6 et le code, AVANT toute lecture de la fenêtre,
  donc avant le 06/12/2026 10:21:26Z.
- Aucune donnée de la fenêtre n'est lue ; 0 crédit.
- **v0.3** : réponses de R02 intégrées.
  - Le critère est le NET (L3).
  - α est de 0,05 par hypothèse au pilote ; Holm en confirmation.
  - Univers sans filtre de rotation.
  - Un pool-jour non valorisable vaut une perte totale.
  - Ajouts : adresses, alignement, sha, limites, vocabulaire, et le code de verdict `n1verdict` 0.1.
- Ce n'est pas un trade du Master et cela ne compte jamais pour 50/20. Étiquettes : MASTER_RESEARCH_PAPER,
  HISTORICAL_REPLAY, LP_SIDE_RESEARCH.

## 1. Estimand et critère

« Une position de fournisseur de liquidité de 0,1 SOL est déposée au début de chaque jour et retirée au début du jour
suivant, coûts complets compris. Son NET en SOL est-il positif sur CES 4 pools, dans CETTE fenêtre ? »
- Le critère est le **net en SOL**, exposition au prix comprise (L3).
- Sont DESCRIPTIFS, sans verdict :
  - `hold_pnl` (détention des mêmes jetons) et `lp_vs_hold`, avec leurs bornes au même bootstrap ;
  - les frais perçus et la perte d'inventaire estimés ;
  - les sensibilités.

## 2. Univers (R02 (3) : SANS filtre de rotation)

Les 4 pools nommés par G2-3, dans cet ordre (le même que la fiche G2-3 v0.5) :
1. `AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca`
2. `Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr`
3. `G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh`
4. `GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A`

Le sha de la liste, adresses jointes par « \n », vaut
`812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80`. Il a été recalculé par R02.

**Option rotation (R04-4), NON retenue par défaut.**
- `n1rot` 0.1 est écrit et non exécuté.
- Si R04 la retient malgré l'acceptation de R02 (registre 2f2e0707) :
  - R02 audite `n1rot` et fixe son seuil avant toute mesure ;
  - R03 l'exécute sur les pages pré-T0 seulement ;
  - la liste retenue remplace celle ci-dessus, dans une v0.4 ;
  - moins de 3 pools rend N1 NON ÉVALUABLE, et l'essai 170 n'est pas consommé.

## 3. Fenêtre, pool-jours et données

- **Fenêtre** : [24/11/2026 10:21:26Z ; 06/12/2026 10:21:26Z), D = 12 j, T0 = 24/11/2026 10:21:26Z.
- **Pool-jours alignés sur T0** : pour k = 0 … 11, la position part au début du jour k (T0 + k × 86 400 s) et se
  termine au début du jour k + 1 (T0 + (k + 1) × 86 400 s).
  - L'horloge atterrit après la latence gelée.
  - Il y a 1 position par pool et par jour, soit 48 pool-jours au plus.
- **Pages** : les MÊMES que G2-3 (collecte R03, cpmmpilot 0.2.8), donc **0 crédit de plus**.
  - La ligne de chaque pool contient aussi ses pages PRÉ-T0 d'A2r. Elles servent UNIQUEMENT à l'état du pool au
    premier atterrissage, jamais à un résultat.
  - `n1verdict` refuse une ligne sans état avant T0.

## 4. Coûts, loyer, valeur d'un pool-jour non valorisable

- **Frais** :
  - part LP = 0,25 % × (1 − 12 % − 4 %) = 0,21 % du volume ;
  - frais créateur (500 ppm s'il figure dans l'AmmConfig lue) payé par nos 2 échanges, jamais reçu par les
    fournisseurs ;
  - AmmConfig U-1 lue et hachée avec son slot.
- **Transactions** : 105 000 lamports figés × **6 transactions** (échange d'entrée, dépôt, retrait, échange de sortie,
  fermeture WSOL, nettoyage).
  - Garde d'achat de 20 000 ppm ; pires états H-1 ; latence de 4 slots.
- **Loyer** : compte fermé, les 2 loyers sont rendus. Après 3 nettoyages échoués, ils sont perdus ; c'est une
  sensibilité publiée.
- **Pool-jour non valorisable (R02 (4))** : perte totale de la mise et des 6 transactions, soit **−100 630 000
  lamports** aux échecs gelés, avec les loyers en plus s'ils sont perdus.
  - Les causes sont closes, dans `n1verdict.UNPRICED` : événement LP au point d'atterrissage, état de sortie vide,
    pool vidé, événement LP sur coffre vide, type LP inconnu, aucun état au point d'atterrissage.
  - Toute autre erreur arrête le verdict.
- **Sensibilités (descriptives)** : (1, 1, 1) échec ; garde à 50 000 ppm ; loyers perdus (0, 0, 3).

## 5. Inférence et mot (`n1verdict` 0.1 → `g23five` 0.1.1, sans modification)

- `g23five.stratified_bounds` : blocs pool-jour stratifiés par pool, 10 000 tirages, graine = **int(sha de CETTE
  fiche ancrée[:8], 16)**.
- **Planchers de G2-3** : ≥ 30 pool-jours entrés ; ≥ 3 pools ; Kish ≥ 2,5 ; aucun pool > 50 %. Sinon INCONCLUSIF,
  avant tout NO-GO.
- **Garde de G2-3** : GO_PILOTE seulement si la borne basse à 95 % est > 0 sur l'ensemble ET sans le pool le plus
  fourni. NO-GO si la borne haute est < 0. Sinon INCONCLUSIF.
- G-0 (décodeur) non passé → STOP, sans aucun chiffre.
- Puissance : 48 pool-jours au plus, contre une cible de 155. **« Sous la cible »** est publié d'office.

## 6. Multiplicité (R02 (2))

- α = 0,05 unilatéral par hypothèse au pilote.
- G2-3 et N1 portent sur la même fenêtre et les mêmes pools ; la corrélation est déclarée et publiée avec les deux
  mots.
- Holm en confirmation.

## 7. Limites déclarées (R02)

- **L1** : la fraction f d'un événement LP d'autrui = montant / coffre BRUT, frais protocole et fonds inclus, alors
  que la part se calcule sur les réserves LP. Léger biais.
- **L2** : nos propres échanges et dépôts ne sont pas rejoués dans les états suivants. La part est minime et couverte
  par les pires états.
- **L3** : le net inclut l'exposition au prix (`hold_pnl`). C'est le résultat en SOL, seul critère ; `lp_vs_hold`
  est descriptif.

## 8. Portée restreinte et vocabulaire

- Le mot ne vaut que pour ces 4 pools, cette fenêtre et ce protocole quotidien.
- Un GO_PILOTE autorise seulement à PROPOSER une confirmation sur les mêmes pools dans une fenêtre neuve.
- Aucune généralisation : ni à d'autres pools, ni à d'autres durées, ni au Master.
- Mots du verdict : STOP, INCONCLUSIF, NO-GO, GO_PILOTE.
- Vocabulaire fermé, contrôlé sur tout le document par `g1ind.check_vocabulary`.

## 9. Essai

- L'essai 170.
- Il est consommé à l'ancrage. Il ne l'est pas si l'option rotation est retenue et donne NON ÉVALUABLE.

## 10. Code à ancrer avec la fiche

| Code | Version | Empreinte | Statut |
|---|---|---|---|
| `n1verdict` | 0.1 | MANIFEST `d4e8c110eebaef4bb146d36dbbb1fa86fac965ff94e04dc1b8a1b4d23bea4111` ; verdict.py `f57cff0545d00f64b23cf6f8a5c9f46527c91763a95a41896c374ffa1926107a` | à auditer |
| `lpcost` | 0.1 | MANIFEST `c4ffa128d130ea8a0b09a6f67ce663cc2df5d6ffeb190f16a6800f38865b9c1a` | PASS TECHNIQUE R02 |
| `g23five` | 0.1.1 | MANIFEST `06a2786245e683e7a8ae245b7d880cd02d3976deaa65d305a40e048858f45811` | PASS R02 |
| `cpmmcost` | 0.3 | MANIFEST `a0bd2adbfaeaa5b14b79c200b066f9a14bb1408c57469e319d6e1db9b92de547` | PASS R02 |
| `closedacct` | 0.2 | MANIFEST `6d420ffa0e988e5e2698867758638707d762549c24aa0e328a5cc2f68b4f4620` | dépendance de cpmmcost 0.3 ; R02 doit confirmer la version |
| `cpmmx` | — | arbre git `e103437142c74830e6ddc293d84529501f6b1162` (commit 99c6688, branche claude/r01-master-v3-lab) ; pas de MANIFEST | réutilisé tel quel |
| `g1ind` | 0.6.1 | MANIFEST `12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a` | PASS R02 |
| `cpmmpilot` | 0.2.8 | sha À VENIR (R03), comme la fiche G2-3 v0.6 | collecte |

Rien ici n'est un résultat économique.
