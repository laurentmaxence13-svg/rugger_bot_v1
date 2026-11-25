# Preuve E-G0 sur les pages pré-T0 des pilotes (R01, 25/11/2026) — DIAGNOSTIC SEULEMENT

- Demande R02 (b) et R04 (12:00Z).
- Données : pages pré-T0 d'A2r, R03 ecd1098. Décodeur gelé cpmmx ; cpmmcost 0.3.1 (E-CF) pour les parts protocole et
  fonds.
- Hors ligne, 0 crédit. Aucune position, aucun P&L, aucune donnée de fenêtre. Aucun code de règle n'est modifié.

| Pool | Swaps | Non décodées | Cause | Versions des non décodées | Tx en échec | Part des tx du pool | Ruptures (hors LP) | Ruptures adjacentes à une non décodée | Non décodées adjacentes à une rupture | Soldes du coffre WSOL pré/post présents |
|---|---|---|---|---|---|---|---|---|---|---|
| AEZjoU | 37 690 | 79 | log_truncated (79) | v1 : 78, v0 : 1 | 0 | 0,57 % | 77 | 77 (100 %) | 79 (100 %) | 79 / 79 |
| G8kgi7 | 37 396 | 1 282 | log_truncated (1 282) | v1 : 1 205, v0 : 77 | 0 | 1,22 % | 1 142 | 1 142 (100 %) | 1 282 (100 %) | 1 282 / 1 282 |
| GdxFyc | 8 157 | 24 | log_truncated (24) | v1 : 24 | 0 | 0,71 % | 20 | 20 (100 %) | 24 (100 %) | 24 / 24 |
| Gms3Ma | 804 | 0 | — | — | 0 | 0 % | 0 | — | — | — |

- « Adjacente » : au moins une transaction non décodée a une position (slot, index) strictement comprise entre celles
  des deux swaps de la rupture.
- Il y a plus de non décodées que de ruptures, parce que certaines ruptures en encadrent plusieurs.

## Lecture

1. Chaque rupture de réserves des 3 pools est expliquée par une transaction non décodée entre les deux swaps. Aucune
   rupture n'est inexpliquée.
2. La cause est unique : le journal du programme est tronqué (« Log truncated »), ce qui fait perdre l'événement de
   swap. Ces transactions sont surtout de version 1, et aucune n'a échoué.
3. Part des non décodées : de 0,57 % à 1,22 %, sous la tolérance de 2 % proposée (E-G0).
4. Récupération possible SANS journal : dans les 1 385 cas, les soldes de jetons du coffre WSOL avant et après sont
   présents dans les métadonnées de la transaction. Le montant WSOL du swap manquant peut donc en principe se
   reconstituer. Ce n'est pas codé (diagnostic seulement) ; un nouveau décodeur serait à auditer.
5. Gms3Ma reste exclu par G-0 pour frais de transfert Token-2022 (exclusion U-4), sans lien avec E-G0.

**Conséquence si E-G0 est autorisé** (tolérance ≤ 2 %, ruptures adjacentes, vente nulle K01 pour toute position
touchée) : AEZjoU, G8kgi7 et GdxFyc seraient admis par G-0, soit 3 pools, exactement le plancher de G2-3 ; Gms3Ma ne
le serait pas.

Tout cela vaut pour les pages PRÉ-T0. Le même constat est NM sur la fenêtre, qui n'est pas lue.
