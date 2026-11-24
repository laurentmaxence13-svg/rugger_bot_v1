# T-R01-8 — Expériences réalisables à verdict rapide (v0.2), orientée jalon 1

RUGGER 01, 24/11/2026. Directive du propriétaire de 18:00:32Z (T1 : R-CP1 et B1 clos, INFAISABLES sur la U-2 du 24/11,
essais 169-170 non consommés ; T2 : mesure d'activité des 259 pools de L) et complément de 18:05Z, relayés par R04.
- **Aucun rendement n'est calculé**, aucune hypothèse gelée n'est modifiée, aucun code n'est écrit.
- Seul calcul : la barre, par la fonction barmap existante (`cpmm_gross_required`).
- « NM » = NON MESURÉ.
- **v0.2** : v0.1 (91ad98f5, registre 6e2bf9af ; calculs (a) et (c) EXACTS selon R02) avec ses réserves R1 à R3.

**Faits d'activité utilisés** (R04, branche R03, 7 jours, 24 pools U-2) :
- 3 pools à > 1 000 swaps/j, 6 à > 100, 14 à < 5 ;
- R-CP1 : 61 déclenchements pour 87 249 swaps, soit **1 pour 1 430 en moyenne**. Le taux de 1 pour 600 ne vaut que sur
  les 2 pools qui ont déclenché. **[R02 R1]** Ce taux dépend de la volatilité du pool, pas seulement de son
  activité (AEZjoU : 37 690 swaps, aucun déclencheur). Les calculs portent donc sur une fourchette de 600 à 1 430
  swaps par déclencheur ;
- frais payés : médiane 8 000 lamports, p90 105 000 ;
- échecs : 24,6 % ;
- coût de collecte mesuré : **0,152 crédit par swap** (13 260 / 87 249, [R02 R2]).

## 1. Pourquoi le jalon 1 échoue aujourd'hui, et ce qu'il faut

- Le plancher G-1 (30 entrées ET 20 pools entrés) exige 20 pools qui déclenchent au moins une fois dans la fenêtre.
- Un pool attend λ = swaps/j × D / r déclenchements, avec r entre 600 et 1 430 swaps par déclencheur.
- Nombre de pools actifs nécessaires pour atteindre 20 pools entrés avec 90 % de chances (loi de Poisson,
  binomiale) :

| λ par pool | Pools nécessaires | Activité d'un pool, D = 3,33 j (r = 600 → 1 430) | D = 7 j (r = 600 → 1 430) |
|---|---|---|---|
| 1 | **37** | ≥ 180 → **429** swaps/j | ≥ 86 → 204 swaps/j |
| 2 | **26** | ≥ 360 → **859** swaps/j | ≥ 171 → 409 swaps/j |
| 3 | 22 | ≥ 540 → 1 288 swaps/j | ≥ 257 → 613 swaps/j |

**[R02 R1] L'activité seule ne garantit pas le plancher** : un pool actif mais calme ne déclenche pas.

- **n = 155** demande 155 × r = **93 000 à 221 650 swaps** dans l'univers (jours = swaps / S, S = swaps/j de
  l'univers), soit ≈ **14 100 à 33 700 crédits** pour la fenêtre, plus le comptage de 7 jours avant T0.
- **Seuil N_eff à demander à T2** : ≥ 37 pools à ≥ 180–429 swaps/j, ou ≥ 26 à ≥ 360–859. C'est une condition
  nécessaire, non suffisante : la volatilité de chaque pool décide du reste. En dessous, G-1 reste INCONCLUSIF par
  construction. La U-2 actuelle (3 pools à > 1 000) en est loin.

**Barre de coût, CPMM 0,25 %** (frais de base 5 000 + priorité) :

| Cas | Barre |
|---|---|
| Valeur gelée (priorité 100 000) | **1,12 %** (100 SOL) |
| Sensibilité, frais médian mesuré 8 000 lamports | 0,73 % |
| Sensibilité, frais médian et 24,6 % d'échecs | 0,74 % (100 SOL) ; 0,94 % (50) ; 0,58 % (500) |
| Valeur gelée et 24,6 % d'échecs | 1,26 % |

Les sensibilités ne remplacent pas le coût gelé. Le verdict reste calculé par cpmmcost 0.3.

## 2. Candidates (au plus 4)

| Candidate | Univers | Déclenchements / j | Jours → plancher ; → 155 | Crédits (pilote) | Barre | Décision du propriétaire |
|---|---|---|---|---|---|---|
| **A. R-CP1 / B1 sur univers qualifié par activité** | Pools CPMM 0,25 % de L avec ≥ 180 swaps/j (N_eff ≥ 37) | S / r : ≈ 4,7 à 11 si S ≈ 6 700 | Plancher ≈ 3,3 j si N_eff suffit ; 155 en ≈ 14 à 33 j (S ≈ 6 700) | ≈ 14 100 à 33 700 + avant T0 | 1,12 % (sensibilité 0,74 %) | Nouvelle fiche de gel, même règle et autre univers (critère d'activité déclaré avant T0) ; réemploi des essais 169-170 |
| **B. G2-3 (largeur de la demande), même univers** | Idem ; un pool avec b₃ = 0 est exclu | NM : à compter par R03 avec `cpmmgen2.trigger_count` sur les 7 j avant T0 (comptage, sans rendement) | NM | 0,152 × swaps nécessaires (NM) + avant T0 | 1,12 % | Texte D (+3 essais), ou une tranche pour G2-3 seule |
| **C. N1 fournisseur de liquidité (CPMM 0,25 %)** | Unité = pool-jour, sans déclencheur | 1 observation par pool actif et par jour | 20 pools actifs : plancher en 1,5 j ; 155 pool-jours en ≈ 8 j | Même collecte : tous les swaps et événements LP des pools | Frais perçus 84 % de 0,25 % moins la perte d'inventaire : σ NM | Décision de principe (ce n'est pas un trade du Master) ; nouveau modèle de coût LP, code et audit R02 |
| D. Autres (A2, G3-1, G3-2) | — | A2 : NM, arbitrage plus rapide que 4 slots ; G3-1 : paires rares ; G3-2 : ≥ 30 dépôts improbables | > A | — | — | Aucune recommandée |

**Suite jusqu'au jalon 3 (confirmation sur fenêtre neuve).**
- **A** : n_c = 221 (σ 2,5 %, α 0,05/3) → 132 600 à 316 030 swaps ; ≈ 20 à 47 j si S = 6 700 ; ≈ 20 200 à 48 000
  crédits.
- **B** : n_c = 262 (Holm, α₂) ou 221 ; jours NM.
- **C** : NM (σ des pool-jours inconnue). Une confirmation demande une fenêtre neuve d'au moins autant de pool-jours.

## 3. Le plancher « 20 pools entrés » est-il le bon design ?

**Non, pour des univers où l'activité se concentre.**
- Il protège contre un verdict porté par un ou deux pools (grappes trop peu nombreuses pour le bootstrap).
- Mais avec 3 pools actifs sur 24, il rend G-1 inatteignable quelle que soit la durée.
- **[R02 R3]** Des grappes pool-jour sous-estimeraient la variance si l'effet d'un pool persiste d'un jour à
  l'autre : je retire cette proposition.
- **Alternative pour une génération FUTURE**, sans toucher aux fiches gelées, à fixer par R02 au préenregistrement :
  - inférence groupée par POOL, ou modèle hiérarchique déclaré ;
  - un **N effectif de Kish minimal**, (Σnₚ)² / Σnₚ², à la place du compte brut de pools ;
  - en complément seulement : au moins 5 pools distincts, et aucun pool au-delà d'⅓ des entrées ;
  - univers déclaré « pools actifs » avant T0.
- **Prix de ce choix** : une conclusion limitée aux pools actifs. C'est le lieu même où l'on exécuterait.

## 4. Classement par délai jusqu'à un verdict indépendant

1. **A**, si T2 donne N_eff ≥ 37 (ou ≥ 26) aux seuils de la fourchette, et si ces pools déclenchent. G-1 en ≈ 3 à
   33 j, ≈ 14 100 à 33 700 crédits, code déjà audité. **Moins probable si T2 est faible** [R02].
2. **C**, le plus rapide en jours une fois codée. Il faut d'abord la décision de principe et un modèle audité ; σ NM.
3. **B**, après le comptage de ses déclenchements par R03 (0 crédit si les 7 jours avant T0 sont déjà collectés).

**Si T2 donne N_eff < 26 : aucune expérience CPMM à déclencheur n'atteint le jalon 1 avec le plancher actuel.** Il
reste C, ou le design du § 3 pour une génération future.

Candidates à 0 essai ; rien ici n'est un résultat économique.
