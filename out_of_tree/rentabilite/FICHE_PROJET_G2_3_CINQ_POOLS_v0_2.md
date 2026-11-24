# T-R01-10 — PROJET de fiche de gel G2-3 « 5 pools nommés » (v0.1), travail estimé, jalon 3 (v0.2)

RUGGER 01, 24/11/2026. Avis de R02 sur la portée restreinte (note 23f02580, registre d4c8f950), relayé par R04
(18:47Z).
- **PROJET, NON gelé, NON ancré.** 0 crédit dépensé, aucun code écrit, aucun essai consommé.
- La règle G2-3 est celle de `cpmmgen2.decisions_g23` (0.2, PASS R02), **inchangée**.
- **v0.2** : alignée sur le texte de R02 présenté au propriétaire (note 76a7e655, registre 5694b0bd) :
  - T0 = 24/11/2026 10:21:26Z ;
  - D = 7 j ;
  - plancher de 30 pool-jours ;
  - essai 169 réaffecté ;
  - ≤ 20 000 crédits ;
  - collecte après l'ancrage de la fiche ET du code de verdict audité.
  Le seuil de 45 pool-jours de la v0.1 est retiré.

## 1. Travail estimé pour écrire et tester le verdict à ce design

**Choix : un nouveau module `g23five`**, qui importe sans les modifier :
- `cpmmgen2` : décisions, b₃, comptage ;
- `cpmmprereg.positions` et `cpmmcost` : coûts, garde, sorties ;
- `cpmmpilot.step1.zero_sale` : K01 ;
- les fonctions descriptives de g1ind.

Étendre cpmmgen2, qui est audité, toucherait du code gelé.

| Élément | Contenu | Estimation |
|---|---|---|
| Sélection des pools avant T0 | ≥ 3 déclenchements G2-3 sur [T0 − 7 j ; T0) (`cpmmgen2.trigger_count`), liste nommée et hachée ; données ≥ T0 refusées | 0,5 h |
| Bootstrap par blocs pool-jour, stratifié par pool | Rééchantillonne les jours DANS chaque pool, puis la moyenne nette sur tous les pools ; graine = fiche ; 10 000 tirages | 1 h |
| Planchers | ≥ 30 pool-jours avec entrée, ≥ 3 pools, N de Kish (Σnₚ)² / Σnₚ² ≥ 2,5, aucun pool > 50 % des entrées → sinon INCONCLUSIF | 0,5 h |
| Mot du pilote | GO_PILOTE seulement si borne inférieure unilatérale > 0 sur l'ensemble ET sans le pool le plus fourni ; NO-GO si borne haute < 0 ; sinon INCONCLUSIF | 0,5 h |
| Rapport | Résultats par pool, témoin apparié inchangé, vocabulaire fermé, K01 | 0,5 h |
| Tests sur fixtures + mutants (≈ 30) + MANIFEST | Frontières des planchers, Kish, exclusion du pool le plus fourni, stratification, graine | 2 à 3 h |
| **Total** | Hors cycle d'audit R02 | **≈ 5 à 6 h** |

## 2. PROJET de fiche de gel G2-3 « 5 pools nommés »

**Estimand (R02 23f02580).** « La règle G2-3 est-elle nette positive sur CES 5 pools, nommés avant T0, dans une
fenêtre future ? »
- Aucune généralisation à d'autres pools.
- Les résultats sont publiés pool par pool.

**Règle (inchangée).** Au swap i :
- acheteurs distincts (payeurs de frais des achats) sur ]t − 600 ; t] ≥ 2 × b₃(pool) ;
- délai de 3 600 s par pool ;
- b₃ = médiane des 1 008 fenêtres de 600 s de [T0 − 7 j ; T0) ;
- un pool avec b₃ = 0 est exclu.

**Univers.**
- Les 5 pools CPMM 0,25 %, établis, ≥ 100 SOL, qui ont le plus de déclenchements G2-3 sur [T0 − 7 j ; T0), parmi ceux
  qui en ont au moins 3. Égalités départagées par l'identifiant.
- Liste nommée : `<5 pools, b₃ par pool, comptes>`. Hachée à T0 : `<sha256>`.
- Pages pré-T0 d'A2r INTERDITES comme pilote (comptes déjà vus) ; elles ne servent qu'à la sélection si R02 l'admet.
- Moins de 3 pools qualifiés : **NON ÉVALUABLE, aucun essai consommé**.

**Fenêtre.**
- [T0 ; T0 + 7 j), T0 = 24/11/2026 10:21:26Z, fenêtre jamais lue.
- **ALERTE R01 (24/11, 18:55Z), envoyée à R02 et à R04 avant la signature : D = 7 j est insuffisant pour le plancher
  de 30 pool-jours.**
  - 5 pools × 7 j = 35 pool-jours au maximum ; avec 3 ou 4 pools, le plancher est impossible.
  - Avec λ = déclenchements avant T0 / 7 par pool, p = 1 − e^(−λ) et une binomiale(35, p) (jours supposés
    indépendants) :

| Déclenchements par pool en 7 j avant T0 | Espérance de pool-jours avec entrée | P(≥ 30) | D pour P ≥ 90 % |
|---|---|---|---|
| 3 (critère actuel) | 12,2 | ≈ 0 | ≈ 21 j |
| 7 | 22,1 | 0,003 | ≈ 11 j |
| 14 | 30,3 | 0,67 | ≈ 8 j |
| 19 | 32,7 | 0,97 | 7 j |

  - Options soumises à R02 :
    - (i) D = 7 et ≥ 19 déclenchements par pool sur 5 pools exigés avant T0, sinon NON ÉVALUABLE sans essai ;
    - (ii) D fixé par « P(plancher) ≥ 0,9 » à partir des comptes avant T0 ;
    - (iii) plancher adapté au nombre de pools retenus, ce qui change le design.
  - En attente de la décision de R02. **Ce projet ne sera pas gelé avant.**

**Ordre, garde, sorties, coûts, témoin.** Ceux de R-CP1, inchangés :
- 0,1 SOL, +4 slots, H-1 ;
- garde 20 000 ppm ;
- TP / SL ±2 %, horloge 30 min ;
- cpmmcost 0.3, compte fermé ;
- vente nulle K01 par `cpmmpilot.step1.zero_sale` ;
- témoin `cpmmprereg.placebo`, graine de CETTE fiche.

**Inférence (R02).**
- IC par bootstrap par blocs pool-jour, stratifié par pool, 10 000 tirages, graine = sha de la fiche[:8].
- **Planchers** : ≥ 30 pool-jours avec entrée ; ≥ 3 pools ; N de Kish ≥ 2,5 ; aucun pool > 50 % des entrées. Sinon
  INCONCLUSIF.
- **GO_PILOTE** seulement si la borne inférieure à 95 % est > 0 sur l'ensemble ET sans le pool le plus fourni.
  **NO-GO** si la borne haute est < 0. Sinon **INCONCLUSIF**.

**n attendu.**
- Au plus 24 entrées par pool-jour (délai de 3 600 s) ; le nombre réel par pool-jour est NM jusqu'au comptage
  avant T0.
- Cible de puissance : 155 entrées (σ 2,5 %, δ +0,5 %, α 0,05). « Sous la cible » est publié.

**Crédits.** ≤ 20 000 (texte 76a7e655, pour D = 7) : 0,103 × transactions des 5 pools sur 7 j avant T0 + D j. À
revoir si D change.

**Essais et décisions du propriétaire.**
- 1 essai : l'essai 169, réaffecté (texte 76a7e655).
- Crédits ; GO de la fenêtre ; puis le code `g23five`, à écrire seulement après la signature.

## 3. Ce qui manque pour la confirmation (jalon 3)

- **Mêmes 5 pools**, fenêtre NEUVE et disjointe, fiche ancrée avant ses données.
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
- **Crédits** : 0,103 × transactions des 5 pools sur cette durée : NM.
- **Manquent** :
  - l'autorisation de l'essai de confirmation ;
  - les crédits ;
  - la règle d'ancrage du design stratifié (à geler par R02 avec le code `g23five`).

Candidate à 0 essai. Rien ici n'est un résultat économique.
