# T-R01-10 — PROJET de fiche de gel G2-3 « pools nommés » (4 pools), code de verdict, jalon 3 (v0.4)

RUGGER 01, 24/11/2026. Avis de R02 sur la portée restreinte (note 23f02580, registre d4c8f950), relayé par R04
(18:47Z).
- **Prête à ancrer, NON ancrée.** 0 crédit dépensé, aucun essai consommé, la fenêtre n'est pas lue.
- **Autorisée** par la décision R04-1 (24/11, 20:38Z, par délégation du propriétaire) : essai 169, ≤ 33 000 crédits. R02 ancre la fiche ET le code de verdict avant toute collecte.
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

## 1. Code de verdict : `g23five` 0.1 (écrit, à auditer)

- `cpmm_pilot/g23five_pkg/g23five/verdict.py`, sha 8b8ee5da940c929ce802e905c4890ad1b63dfe38418de249b8d1c32e0e07f177 (0.1).
- Il contient : la sélection avant T0, le bootstrap par blocs pool-jour stratifié par pool, les planchers, la garde
  « sans le pool le plus fourni », le rapport par pool, K01 et le vocabulaire.
- Il réutilise sans les modifier cpmmgen2, cpmmprereg, cpmmcost, g1ind et cpmmpilot 0.1.6.
- 12 tests ; 33 mutants sur 33 détectés (README_G23FIVE_v0_1.md).

## 2. PROJET de fiche de gel G2-3 « 4 pools nommés »

**Estimand (R02 23f02580).** « La règle G2-3 est-elle nette positive sur CES 4 pools, nommés avant T0, dans une
fenêtre future ? »
- Aucune généralisation à d'autres pools.
- Les résultats sont publiés pool par pool.

**Règle (inchangée).** Au swap i :
- acheteurs distincts (payeurs de frais des achats) sur ]t − 600 ; t] ≥ 2 × b₃(pool) ;
- délai de 3 600 s par pool ;
- b₃ = médiane des 1 008 fenêtres de 600 s de [T0 − 7 j ; T0) ;
- un pool avec b₃ = 0 est exclu.

**Univers (règle (a) fixée, R02 835d648e).**
- Les pools CPMM 0,25 %, établis, ≥ 100 SOL, avec au moins 3 déclenchements G2-3 sur [T0 − 7 j ; T0), les 5
  premiers au plus, égalités départagées par l'identifiant.

| Pool | Déclenchements G2-3 sur 7 j avant T0 | P(entrée un jour donné) = 1 − e^(−λ) |
|---|---|---|
| AEZjoU | 128 | 1,00 |
| Gms3Ma | 105 | 1,00 |
| G8kgi7 | 95 | 1,00 |
| GdxFyc | 21 | 0,95 |

- 2yLFom (2 déclenchements) est exclu. Kish des comptes : 349² / 36 875 = **3,30** ; part du premier pool : 37 %.
- Liste hachée à T0 : `<sha256>`.
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
- IC par bootstrap par blocs pool-jour, stratifié par pool, 10 000 tirages, graine = sha de la fiche[:8].
- **Planchers** : ≥ 30 pool-jours avec entrée ; ≥ 3 pools ; N de Kish ≥ 2,5 ; aucun pool > 50 % des entrées. Sinon
  INCONCLUSIF.
- **GO_PILOTE** seulement si la borne inférieure à 95 % est > 0 sur l'ensemble ET sans le pool le plus fourni.
  **NO-GO** si la borne haute est < 0. Sinon **INCONCLUSIF**.

**n attendu.**
- Au plus 24 entrées par pool-jour (délai de 3 600 s) ; le nombre réel par pool-jour est NM jusqu'au comptage
  avant T0.
- Cible de puissance : 155 entrées (σ 2,5 %, δ +0,5 %, α 0,05). « Sous la cible » est publié.

**Crédits.** Plafond **33 000** (R02 835d648e), à 0,103 crédit par transaction des 4 pools sur la fenêtre.

**Essais et décisions du propriétaire.**
- 1 essai : l'essai 169, réaffecté (texte 76a7e655).
- Crédits ; GO de la fenêtre ; puis le code `g23five`, à écrire seulement après la signature.

## 3. Ce qui manque pour la confirmation (jalon 3)

- **Mêmes 4 pools**, fenêtre NEUVE et disjointe, fiche ancrée avant ses données.
- **n_c** : G2-1 et G2-2 sont inapplicables, donc K = 1. Avec α₂ = 0,025 et σ_c = max(σ du pilote, 2,5 %),
  n_c = **197** si σ_c = 2,5 % (221 si l'option 0,05/3 est retenue). Davantage si le σ du pilote est plus grand.
- **Critère** :
  - c1 : borne inférieure > 0, au même bootstrap stratifié ;
  - c2 : borne inférieure de l'écart au témoin apparié > 0 ;
  - c3 : les deux moitiés > 0 ;
  - c4 : vente nulle comptée ;
  - c5 : 10 slots et sans le pool le plus fourni ;
  - A1 : 1 échec.
- **Durée** : 197 / (entrées par jour mesurées au pilote) : NM.
- **Crédits** : 0,103 × transactions des 4 pools sur cette durée : NM.
- **Manquent** :
  - l'autorisation de l'essai de confirmation ;
  - les crédits ;
  - la règle d'ancrage du design stratifié (à geler par R02 avec le code `g23five`).

Candidate à 0 essai. Rien ici n'est un résultat économique.
