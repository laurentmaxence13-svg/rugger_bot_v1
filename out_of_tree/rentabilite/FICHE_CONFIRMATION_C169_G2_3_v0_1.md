# Fiche de confirmation C-169 — G2-3 « pools nommés » (jalon 3), PROJET v0.1

RUGGER 01, 24/11/2026.
- Décisions : R04-7 ; R02 (22:47Z, registre). Fiche pilote ancrée : G2-3 v0.6 (`e2f8411d…`, registre f0129441, graine
  3807920413).
- **PROJET, à ancrer par R02 AVANT le 06/12/2026 10:21:26Z.**
- **Lue SEULEMENT si le pilote G2-3 rend GO_PILOTE.** Sinon aucune donnée n'est lue pour elle et rien n'est consommé.
- Essai : C-169. Une confirmation sans changement de règle compte pour +0 (R-0.5, R02).
- Ce n'est pas un trade du Master et cela ne compte jamais pour 50/20.
- Rien ici n'est un résultat économique.

## 1. Ce qui est repris SANS CHANGEMENT de la fiche pilote G2-3 v0.6

- **Pools** : les MÊMES 4 pools, liste `812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80`.
- **Règle** : `cpmmgen2.decisions_g23` 0.2, avec les b₃ GELÉS 2 / 1 / 6 / 1, jamais recalculés.
- **Positions, coûts et témoin** : ceux de la fiche pilote (cpmmcost 0.3, 0,1 SOL, garde 20 000 ppm, H-1, TP / SL,
  horloge, compte fermé, K01, `cpmmprereg.placebo`).
- **Planchers et garde** : ≥ 30 pool-jours, ≥ 3 pools, Kish ≥ 2,5, aucun pool > 50 % ; sans le pool le plus fourni.
- **Bootstrap** : par blocs pool-jour stratifiés par pool, blocs d'1 jour, 10 000 tirages.
- **Graine** : int(sha de CETTE fiche ancrée[:8], 16).

## 2. Fenêtre, n_c et durée (formules fixées ICI, avant tout verdict pilote)

- **Début** : T0_C = 1 796 552 486 (06/12/2026 10:21:26Z), disjoint du pilote.
- **σ_c** = max(σ du pilote, 2,5 %). σ du pilote = écart type d'échantillon des `net_return` des positions comptées du
  pilote (G1.counted, ventes nulles comprises).
- **n_c** = ⌈((z₁₋α + z₀,₈) · σ_c / 0,5 %)²⌉, avec α = le seuil de Holm de l'hypothèse (§ 4).
  - À σ_c = 2,5 % : 197 si α = 0,025 ; 238 si α = 0,0125.
- **r du pilote** = entrées du pilote / 12 j.
- **Durée** : D_c = min(30, max(12, ⌈n_c / r⌉)) jours (R02). La fenêtre est [T0_C ; T0_C + D_c j).
  - D_c est connu au verdict pilote, avant toute lecture de la fenêtre de confirmation.
  - Si n_c n'est pas atteint, « sous la cible » est publié.
- **Crédits** : crédits MESURÉS de la collecte pilote × D_c / 12, plafond 33 000. Un dépassement donne STOP, en
  conservant les pages.

## 3. Critères (CONFIRMÉ = TOUS, au seuil α de l'hypothèse)

| Critère | Calcul (g23five 0.3, alpha = α) |
|---|---|
| c1 | borne basse unilatérale du net moyen > 0 (`stratified_bounds`) |
| c2 | borne basse de l'écart au témoin > 0 (`difference_bounds`) |
| c3 | les deux moitiés > 0 (`halves`, coupure à T0_C + (D_c × 86 400) // 2) |
| c4 | ventes nulles comptées (K01, `G1.counted`) : toute position non valorisée est comptée, jamais retirée |
| c5 | net > 0 avec une latence de 10 slots (positions de R03), ET borne basse > 0 sans le pool le plus fourni |
| A1 | net > 0 avec (1, 1, 1) échec (positions de R03) |

- **Planchers** manqués : INCONCLUSIF.
- **Sinon** : TOUS les critères → **CONFIRMÉ** ; un critère manqué → **NON CONFIRMÉ**.
- La valeur p (`bootstrap_p`) sert à Holm (§ 4). Elle est publiée.

## 4. Holm entre G2-3 et N1 (α₂ = 0,025, R02)

- **Hypothèses retenues** : celles dont le pilote est GO_PILOTE (K = 1 ou 2).
- **Valeurs p** : p = (#moyennes bootstrap ≤ 0 + 1) / (tirages + 1). Une hypothèse INCONCLUSIF compte p = 1
  (`g23five.holm`).
- **Seuil d'une hypothèse** :
  - K = 1 : α = 0,025 ;
  - K = 2 : α = 0,0125 pour la plus petite p, puis α = 0,025 pour l'autre si la première est rejetée ; sinon arrêt.
- CONFIRMÉ exige le rejet par Holm ET les critères c1 à A1 au seuil α de cette hypothèse.

## 5. Code et exécution

| Élément | Version | Empreinte | Statut |
|---|---|---|---|
| `g23five` | 0.3 | MANIFEST `683b30c3a74c62bc875e1aada51674d4d2135fe0842fdea33d3386f7241a8a18` ; verdict.py `a751680d…` | à auditer (R02) |
| règle, positions, coûts, témoin | — | ceux de la fiche pilote G2-3 v0.6 | ancrés |
| `cpmmpilot` | 0.2.8 | `7251d4fe27355d066d33e08f0c9e42dffa04f890646cc50de07e2a0acc442058` | PASS R02 |

- **À faire par R03** (pas encore écrit) : un pilote de collecte de la fenêtre de confirmation [T0_C ; T0_C + D_c j).
  - Il faut aussi les positions à 10 slots (c5) et à (1, 1, 1) échec (A1).
  - Il n'est lancé QUE si le pilote est GO_PILOTE.
- **Texte de collecte du propriétaire** pour la confirmation : à coller dans la session R03 ; son sha est ancré par R02
  avant la collecte.

## 6. Portée

- Ces 4 pools seulement, cette règle seulement, aucune généralisation.
- CONFIRMÉ ne fait pas de G2-3 un trade du Master. Il n'engage ni capital, ni ordre réel, ni armement LIVE.
- Le mot est publié pool par pool, avec « sous la cible » si c'est le cas.
