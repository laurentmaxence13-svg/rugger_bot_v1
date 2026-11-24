# T-R01-10 — PROJET de fiche de gel G2-3 « pools nommés » (4 pools), code de verdict, jalon 3 (v0.5)

RUGGER 01, 24/11/2026. Avis de R02 sur la portée restreinte (note 23f02580, registre d4c8f950), relayé par R04
(18:47Z).
- **Prête à ancrer, NON ancrée.** 0 crédit dépensé, aucun essai consommé, la fenêtre n'est pas lue.
- **Autorisée par R04-1, délégation du propriétaire 52f821b9 ; texte de collecte du propriétaire à coller dans la
  session R03.** Essai 169, ≤ 33 000 crédits. R02 ancre la fiche ET le code de verdict avant toute collecte.
- **v0.5** : corrections 1 à 5 de l'audit R02 de la v0.4 (adresses complètes et liste hachée, b₃ gelés, sha du
  code, passages caducs retirés, c2), et code de verdict `g23five` 0.1.1 (écart au témoin descriptif).
- La règle G2-3 est celle de `cpmmgen2.decisions_g23` (0.2, PASS R02), **inchangée**.
- **v0.4** : D = 12 confirmé par R02 (c301e993), selon la règle « rafales » 4e08d2a2 (r × D ≥ 45 et P(≥ 30 pool-jours) ≥ 0,90
  par rééchantillonnage des 7 jours observés). Le code de verdict `g23five` 0.1 est écrit (§ 1).
- **v0.3** : valeurs fixées par R02 (erratum 835d648e).
  - Les règles (a) et (b) de la v0.1 sont ACCEPTÉES et FIXÉES : ≥ 3 déclenchements G2-3, les 5 premiers, et D tel
    que l'espérance des pool-jours avec entrée soit ≥ 45.
  - Leur application donne **4 pools** (2yLFom n'a que 2 déclenchements), **D = 12 j**, Kish 3,30.
  - Autres paramètres, repris de la note 76a7e655 : essai 169 réaffecté ; collecte après l'ancrage de la fiche ET
    du code de verdict audité.
- L'alerte de la v0.2 (D = 7) est levée : elle supposait des pools au seuil de 3 déclenchements. Les comptes réels
  sont bien au-dessus (§ 2). L'option (iii) est refusée par R02 : le plancher reste celui de 23f02580.

## 1. Code de verdict et code gelé (sha)

| Code | Version | Empreinte (sha256 du MANIFEST, sauf mention) | Statut |
|---|---|---|---|
| `g23five` | 0.1.1 | MANIFEST_g23five_v0_1_1.txt `06a2786245e683e7a8ae245b7d880cd02d3976deaa65d305a40e048858f45811` ; verdict.py `52b9d2b03331700b61dda69510563a3b93ed75118d993ecbac68d6a95388fb6e` | 0.1 PASS TECHNIQUE R02 ; 0.1.1 à auditer |
| `cpmmgen2` (règle G2-3, b₃, comptage) | 0.2 | `70ef9a9b46145436b160ce2907c433df9532f39942124a81ce11a7a3e314fcf5` | PASS R02 |
| `cpmmprereg` (positions, témoin, moitiés, n requis) | 0.2 | `9d8ebde62b4a05ce64a86f526d5f729d97f49bcdfee0589a0b5a46899089e5bf` | PASS R02 |
| `cpmmcost` (coûts, garde, G-1) | 0.3 | `a0bd2adbfaeaa5b14b79c200b066f9a14bb1408c57469e319d6e1db9b92de547` | PASS R02 |
| `g1ind` (lignes comptées K01, vocabulaire) | 0.6.1 | `12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a` | à auditer ; à défaut 0.6 `cda05131abb343677978152dbf0dde79976214f82b1add4f0bf091efc6a36314` (PASS R02) |
| `cpmmpilot` (collecte et positions, R03) | 0.2.8 | sha À VENIR (R03) | collecte |

- **Rôle de cpmmpilot.** La collecte et le calcul des positions se font avec la 0.2.8 de R03. Le verdict n'emploie de
  cpmmpilot que `step1.zero_sale` et `step1.zero_sale_net_lamports` (vente nulle K01), via g1ind. Les tests de
  g23five et de g1ind ont été rejoués sur la 0.1.6 (f934bd2). La 0.2.8 doit donner les mêmes valeurs K01 :
  −100 420 000 (0, 0, 0), −100 735 000 (1, 1, 1) et −102 669 280 (0, 0, 3) lamports.
- `g23five` contient : la sélection avant T0, le bootstrap par blocs pool-jour stratifié par pool, les planchers, la
  garde « sans le pool le plus fourni », le rapport par pool, K01, le vocabulaire et, en 0.1.1, l'écart au témoin
  avec ses bornes au même bootstrap (descriptif).
- 13 tests ; 40 mutants sur 40 détectés (README_G23FIVE_v0_1_1.md).

## 2. PROJET de fiche de gel G2-3 « 4 pools nommés »

**Estimand (R02 23f02580).** « La règle G2-3 est-elle nette positive sur CES 4 pools, nommés avant T0, dans une
fenêtre future ? »
- Aucune généralisation à d'autres pools.
- Les résultats sont publiés pool par pool.

**Règle (inchangée).** Au swap i :
- acheteurs distincts (payeurs de frais des achats) sur ]t − 600 ; t] ≥ 2 × b₃(pool) ;
- délai de 3 600 s par pool ;
- b₃ = médiane des 1 008 fenêtres de 600 s de [T0 − 7 j ; T0), GELÉ par pool (tableau de l'univers) ;
- un pool avec b₃ = 0 est exclu.

**Univers (règle (a) fixée, R02 835d648e).**
- Les pools CPMM 0,25 %, établis, ≥ 100 SOL, avec au moins 3 déclenchements G2-3 sur [T0 − 7 j ; T0), les 5
  premiers au plus, égalités départagées par l'identifiant.

| Pool (adresse complète) | Déclenchements G2-3 sur 7 j avant T0 | b₃ GELÉ | P(entrée un jour donné) = 1 − e^(−λ) |
|---|---|---|---|
| `AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca` | 128 | 2 | 1,00 |
| `Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr` | 105 | 1 | 1,00 |
| `G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh` | 95 | 6 | 1,00 |
| `GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A` | 21 | 1 | 0,95 |

- **b₃ gelés par pool** (source G2_3_PER_DAY_K 6def2254) : ils sont fixés ici et ne sont pas recalculés sur la
  fenêtre.

- 2yLFom (2 déclenchements) est exclu. Kish des comptes : 349² / 36 875 = **3,30** ; part du premier pool : 37 %.
- Liste hachée (`g23five.select(...)['list_sha256']`, adresses jointes par « \n » dans l'ordre ci-dessus) :
  `812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80`.
- Moins de 3 pools qualifiés aurait donné NON ÉVALUABLE, sans essai.

**Fenêtre (règle (b) fixée ; D = 12 confirmé par R02 c301e993, règle 4e08d2a2).**
- [24/11/2026 10:21:26Z ; 06/12/2026 10:21:26Z), soit D = 12 j, jamais lue.
- D = 12 tient avec la règle 4e08d2a2 : r × D ≥ 45, et P(≥ 30 pool-jours) ≥ 0,90 par rééchantillonnage des
  7 jours observés, 10 000 tirages, graine 20261124. Le calcul et la table par pool et par jour sont ceux de R02 et
  R03 ; ils ne sont pas refaits ici.
- Pages pré-T0 d'A2r : sélection seulement, jamais comme pilote.
- **Réserve (R02)** : ces comptes viennent d'une seule semaine. Une baisse d'activité (retour vers la moyenne) peut
  réduire les pool-jours. Le plancher et la garde « sans le pool le plus fourni » le couvrent, au prix d'un
  INCONCLUSIF possible.

**Ordre, garde, sorties, coûts, témoin.** Ceux de R-CP1, inchangés :
- 0,1 SOL, +4 slots, H-1 ;
- garde 20 000 ppm ;
- TP / SL ±2 %, horloge 30 min ;
- cpmmcost 0.3, compte fermé ;
- vente nulle K01 par `cpmmpilot.step1.zero_sale` ;
- témoin `cpmmprereg.placebo`, graine de CETTE fiche.

**Inférence (R02 ; code `g23five.report`).**
- IC par bootstrap par blocs pool-jour, stratifié par pool, 10 000 tirages, graine = int(sha de la fiche ANCRÉE[:8], 16).
- Écart au témoin : bornes à 95 % au même bootstrap stratifié (primaire et témoin tirés chacun par pool-jour),
  DESCRIPTIF, non décisionnel.
- **Planchers** : ≥ 30 pool-jours avec entrée ; ≥ 3 pools ; N de Kish ≥ 2,5 ; aucun pool > 50 % des entrées. Sinon
  INCONCLUSIF.
- **GO_PILOTE** seulement si la borne inférieure à 95 % est > 0 sur l'ensemble ET sans le pool le plus fourni.
  **NO-GO** si la borne haute est < 0. Sinon **INCONCLUSIF**.

**n attendu.**
- Au plus 24 entrées par pool-jour (délai de 3 600 s) ; le nombre réel par pool-jour est NM jusqu'au comptage
  avant T0.
- Cible de puissance : 155 entrées (σ 2,5 %, δ +0,5 %, α 0,05). « Sous la cible » est publié.

**Crédits.** Plafond **33 000** (R02 835d648e), à 0,103 crédit par transaction des 4 pools sur la fenêtre.

**Essai et autorisation.**
- 1 essai : l'essai 169, réaffecté (texte 76a7e655).
- Autorisée par R04-1, délégation du propriétaire 52f821b9 ; texte de collecte du propriétaire à coller dans la
  session R03.

## 3. Ce qui manque pour la confirmation (jalon 3)

- **Mêmes 4 pools**, fenêtre NEUVE et disjointe, fiche ancrée avant ses données.
- **n_c** : G2-1 et G2-2 sont inapplicables, donc K = 1. Avec α₂ = 0,025 et σ_c = max(σ du pilote, 2,5 %),
  n_c = **197** si σ_c = 2,5 % (221 si l'option 0,05/3 est retenue). Davantage si le σ du pilote est plus grand.
- **Critère** :
  - c1 : borne inférieure > 0, au même bootstrap stratifié ;
  - c2 : borne inférieure de l'écart au témoin > 0, IC au même bootstrap stratifié (`g23five.difference_bounds`) ;
  - c3 : les deux moitiés > 0 ;
  - c4 : vente nulle comptée ;
  - c5 : 10 slots et sans le pool le plus fourni ;
  - A1 : 1 échec.
- **Durée** : 197 / (entrées par jour mesurées au pilote) : NM.
- **Crédits** : 0,103 × transactions des 4 pools sur cette durée : NM.
- **Manquent** :
  - l'autorisation de l'essai de confirmation ;
  - les crédits ;
  - l'ancrage de cette fiche et du code `g23five` 0.1.1 par R02.

Candidate à 0 essai. Rien ici n'est un résultat économique.
