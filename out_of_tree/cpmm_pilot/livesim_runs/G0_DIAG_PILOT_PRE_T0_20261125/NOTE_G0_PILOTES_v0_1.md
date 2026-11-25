# Diagnostic G-0 sur les pages pré-T0 des 4 pools pilotes (R01, 25/11/2026) — DESCRIPTIF

- Données : pages pré-T0 d'A2r, [T0 − 7 j ; T0), commit R03 ecd1098, STEP1A2R_20261124T164909Z/pre_pages. Les sommes
  SHA256SUMS_PRE_PAGES.txt sont vérifiées.
- Ce ne sont PAS des données de fenêtre. Aucune position et aucun P&L ne sont calculés.
- Code : fonctions gelées appelées telles quelles (cpmmcost.pool_gate, cpmmx.timeline.reproduce), hors réseau. Config :
  D4FPEr (be8d13d1), creator_fee_rate = 500.
- La variante « creator_fee_rate = 0 » est un DIAGNOSTIC. Ce n'est pas la config ancrée.

| Pool | Swaps | Exacts (config ancrée) | Exacts (créateur 0) | Swaps avec frais créateur journalisé | Non décodées | G-0 ancré | G-0 si créateur 0 |
|---|---|---|---|---|---|---|---|
| AEZjoU | 37 690 | 0 | 37 690 | 0 | 79 | undecoded, swaps_not_reproduced, reserves_chain_broken | undecoded, reserves_chain_broken |
| Gms3Ma | 804 | 0 | 804 | 0 | 0 | token_transfer_fee, swaps_not_reproduced | token_transfer_fee |
| G8kgi7 | 37 396 | 130 | 37 396 | 0 | 1 282 | undecoded, swaps_not_reproduced, reserves_chain_broken | undecoded, reserves_chain_broken |
| GdxFyc | 8 157 | 0 | 8 157 | 0 | 24 | undecoded, swaps_not_reproduced, reserves_chain_broken | undecoded, reserves_chain_broken |

## Constats

1. Aucun swap ne journalise de frais créateur. Avec un taux créateur de 0, 100 % des swaps sont reproduits. La config
   U-1 seule (500 ppm) ne décrit donc pas ces pools : le frais créateur semble désactivé au niveau du pool (PoolState),
   ce qui est **À VÉRIFIER** sur le compte du pool. Le même constat vaut pour les 8 pools livesim.
2. Même avec ce taux, G-0 refuserait les 4 pools pilotes :
   - 3 pools pour transactions non décodées, la chaîne de réserves étant alors rompue ;
   - Gms3Ma pour frais de transfert du jeton.
3. Conséquences au 06/12, si les pages de fenêtre présentent les mêmes traits (NM tant qu'elles ne sont pas lues) :
   - g23run 0.1 (G2-3) : tous les pools exclus par G-0, planchers manqués, INCONCLUSIF, sans lien avec l'hypothèse ;
   - N1 : « G-0 non passé → STOP », si G-0 est jugé par pool_gate.
4. Coûts : cpmmcost applique des frais créateur de 500 ppm qui ne sont pas prélevés sur ces pools. Les coûts sont donc
   surévalués d'environ 0,05 % par swap, un biais prudent.

Rien n'est modifié. Toute correction (taux créateur effectif par pool, traitement des transactions non décodées)
serait un erratum de règle à décider et à auditer AVANT la lecture du 06/12.
