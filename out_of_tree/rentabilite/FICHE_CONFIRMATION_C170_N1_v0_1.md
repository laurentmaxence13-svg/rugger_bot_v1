# Fiche de confirmation C-170 — N1 « fournisseur de liquidité », conception R04-6 (jalon 3), PROJET v0.1

RUGGER 01, 24/11/2026.
- Décisions : R04-7 ; R02 (22:47Z, registre). Fiche pilote ancrée : N1 v0.7 (`9eb19fb7…`, registre f0129441, graine
  2662440887).
- **PROJET, à ancrer par R02 AVANT le 06/12/2026 10:21:26Z.**
- **Lue SEULEMENT si le pilote N1 rend GO_PILOTE.** Sinon aucune donnée n'est lue pour elle et rien n'est consommé.
- Essai : C-170. Une confirmation sans changement de règle compte pour +0 (R-0.5, R02).
- Ce n'est pas un trade du Master et cela ne compte jamais pour 50/20. Étiquettes : MASTER_RESEARCH_PAPER,
  HISTORICAL_REPLAY, LP_SIDE_RESEARCH.
- Rien ici n'est un résultat économique.

## 1. Ce qui est repris SANS CHANGEMENT de la fiche pilote N1 v0.7

- **Pools** : les MÊMES 3 pools, liste `c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da`. La rotation
  n'est pas remesurée.
- **Position** : une par pool, 0,5 % de la réserve WSOL lue à l'ouverture (état de décision à T0_C), ouverte au début
  du jour 0 et retirée à la fin du jour 11.
- **Mot** : l'écart à la détention, net de TOUS les coûts (C1), avec les coûts / 12 par pool-jour (C2).
- **Coûts** : lpcost 0.2, garde de 20 000 ppm, 6 tx à 105 000 lamports, loyers.
- **Position non valorisable** : perte totale répartie sur 12 jours, liste fermée des causes.
- **Planchers** : ≥ 30 pool-jours, ≥ 3 pools, Kish ≥ 2,5, aucun pool > 50 %.
- **Garde K-1** : sans le pool à la plus grande somme d'écarts.
- **Bootstrap** : blocs de 2 jours stratifiés par pool, 10 000 tirages.
- **Limites L1 à L4.**
- **Graine** : int(sha de CETTE fiche ancrée[:8], 16).

## 2. Fenêtre, n_c, puissance

- **Fenêtre** : [06/12/2026 10:21:26Z ; 18/12/2026 10:21:26Z), T0_C = 1 796 552 486, D_c = 12 (R02). Elle n'est pas
  allongée : cela changerait la configuration.
- **δ** = 0,05 % de la mise par jour (R02).
- **σ_c** = max(σ du pilote par pool-jour, 0,5 %) (plancher R02). σ du pilote = écart type d'échantillon des valeurs
  journalières de l'écart (en part de la mise) des pool-jours du pilote.
- **n_c** = ⌈((z₁₋α + z₀,₈) · σ_c / δ)²⌉ : **785** au plancher si α = 0,025 ; **951** si α = 0,0125.
- **Déclaré d'avance** : une fenêtre donne au plus 36 pool-jours (3 pools × 12). La confirmation N1 sera donc publiée
  **« sous la cible »**. Un CONFIRMÉ reste possible si tous les critères passent, mais avec une puissance faible,
  publiée.

## 3. Critères (CONFIRMÉ = TOUS, au seuil α de l'hypothèse)

| Critère | Calcul (n1verdict 0.3, alpha = α, phase confirmation) |
|---|---|
| c1 | borne basse de l'écart moyen > 0 (blocs de 2 jours) |
| c2 | borne basse > 0 sans le pool qui porte le résultat (K-1) |
| c3 | les deux moitiés > 0 : jours 0–5 et 6–11 (`halves`) |
| c4 | positions non valorisables comptées en perte totale, jamais retirées |
| A1 | écart moyen > 0 avec (1, 1, 1) échec (sensibilité `one_failure_per_tx`) |

- **Planchers** manqués : INCONCLUSIF.
- **Sinon** : TOUS les critères → **CONFIRMÉ** ; un critère manqué → **NON CONFIRMÉ**.
- Il n'y a pas de témoin : la comparaison à la détention est déjà dans le mot.

## 4. Holm entre G2-3 et N1 (α₂ = 0,025, R02)

- Mêmes règles que la fiche C-169 § 4 (`g23five.holm`).
- La valeur p de N1 = `p_value` de n1verdict 0.3 (bootstrap en blocs de 2 jours).
- CONFIRMÉ exige le rejet par Holm ET les critères au seuil α de cette hypothèse.

## 5. Code, données et exécution

| Élément | Version | Empreinte | Statut |
|---|---|---|---|
| `n1verdict` | 0.3 | MANIFEST `290266016ab61e4864e3874ca20c38d5e35464f28af51fba10c48ac0fc352ed7` ; verdict.py `91c701c7…` ; lines.py `5f4c66dd…` | à auditer (R02) |
| `g23five` | 0.3 | MANIFEST `683b30c3a74c62bc875e1aada51674d4d2135fe0842fdea33d3386f7241a8a18` | à auditer (R02) |
| `lpcost` | 0.2 | `ee9c144ca85f3de9489c60e0c74edf8ee685ed1e851d8d74aa392863313849eb` | PASS R02 |
| `cpmmpilot` | 0.2.8 | `7251d4fe27355d066d33e08f0c9e42dffa04f890646cc50de07e2a0acc442058` | PASS R02 |

- **Pages** : celles de la fenêtre de confirmation [T0_C ; T0_C + 12 j) des 3 pools.
  - Si la confirmation G2-3 est aussi collectée, ce sont les mêmes pages : 0 crédit de plus.
  - Si N1 est seul retenu, la collecte se limite aux 3 pools ; l'estimation = crédits mesurés de ces 3 pools au
    pilote ; plafond à fixer par R04, au plus 33 000.
- **Pages « pré-T0_C »** : celles de la fin de la fenêtre pilote, déjà collectées. Elles servent seulement à l'état
  au premier atterrissage (même règle (b) que le pilote).
- **Exécution unique par R03**, après l'ancrage de cette fiche, la collecte et le verdict pilote GO_PILOTE :

  `python -B -m n1verdict.lines --u2 U2.json --pre-root <pages avant T0_C> --window-root <pages de confirmation> --t0-slot <slot de T0_C> --sheet-sha <sha de cette fiche> --g0 passed|not_passed --phase confirmation --alpha <0,025 ou 0,0125 selon Holm> --result RESULT.json`

  Le chemin Python porte g23five 0.3, lpcost 0.2 et n1verdict 0.3.

## 6. Portée

- Ces 3 pools, cette configuration (0,5 % de la réserve, 12 jours, un aller-retour), une condition nécessaire.
- CONFIRMÉ ne fait pas de N1 un trade du Master et n'engage aucun capital, aucun ordre réel, aucun armement LIVE.
