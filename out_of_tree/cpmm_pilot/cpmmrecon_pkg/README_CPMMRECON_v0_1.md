# cpmmrecon 0.1 — décodeur complémentaire des swaps CPMM à journal tronqué (voie (ii))

RUGGER 01, 25/11/2026.
- Voie (ii) de R02 (12:20Z), décision R04-14.
- **Module séparé.** cpmmx, cpmmcost et toutes les règles sont INTACTS. **G-0 est inchangé** : la ligne reconstituée
  est jugée par `cpmmcost.pool_gate` (0.3.1), qui exige une reproduction exacte et aucune rupture de réserves.
- Statut : livré pour audit. Son usage au pilote demande l'audit de R02 et le texte du propriétaire (R04).
- Hors ligne, 0 crédit. Seules des pages pré-T0 et pré-départ sont lues ; aucune donnée de fenêtre, aucun P&L.

## Méthode (`rebuild(line, txs, wsol_vault, fees, on_input)`)

Elle s'applique à chaque transaction du pool non décodée pour cause `log_truncated`, et non échouée :
1. **Swaps du pool** : ce sont les instructions CPMM dont les comptes contiennent le pool, avec les discriminants
   Anchor `swap_base_input` et `swap_base_output`, dans l'ordre d'exécution (instruction de premier niveau, puis ses
   instructions internes). Toute AUTRE instruction CPMM sur le pool (dépôt, retrait, …) laisse la transaction non
   décodée.
2. **Montants de chaque swap** : ses transferts de jetons enfants (hauteur de pile + 1, `transfer` ou
   `transferChecked`). Il faut exactement un transfert ENTRANT dans un coffre et un SORTANT de l'autre. Cela sépare
   aussi les transactions qui contiennent plusieurs swaps du même pool.
3. **Contrôle croisé** : la somme de ces transferts doit égaler la variation des soldes pré/post des deux coffres.
   Le coffre WSOL vient de LIST_L ; le coffre de base est le compte du même propriétaire (l'autorité).
4. **Réserves avant** : celles qui suivent le swap précédent du pool, journalisé ou reconstitué. Après un événement
   LP, ou après un échec, il n'y a pas d'état connu, et la transaction reste non décodée.
5. **Recalcul exact** par `cpmmx.curve`, dans le mode de l'instruction, avec les taux cpmmcost 0.3.1 (drapeau créateur
   0, ancré 6c3ed74). Les montants recalculés doivent égaler les montants transférés EXACTEMENT.

Une transaction est reconstituée en entier ou pas du tout. Rien n'est deviné : tout échec la laisse dans `skipped`,
et G-0 refuse alors le pool comme avant.

## Preuve sur les données réelles

- Script : `verify_rebuild_real_pages.py`, sortie `VERIFY_REBUILD_REAL_PAGES.json`.
- Chaque ligne donne G-0 (cpmmcost 0.3.1, inchangé) sur la ligne cpmmx, puis sur la ligne reconstituée.

| Pages | Pool | Non décodées | Issue | Restent | Ruptures (avant → après) | G-0 (avant → après) |
|---|---|---|---|---|---|---|
| A2r pré-T0 | 4NX5P7 | 1 | kept:no_state_before 1 | 1 | 0 → 0 | undecoded_transactions → undecoded_transactions |
| A2r pré-T0 | 5ML6Tk | 1 | rebuilt 1 | 0 | 1 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| A2r pré-T0 | 68vHUS | 53 | rebuilt 53 | 0 | 46 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| A2r pré-T0 | AEZjoU | 79 | rebuilt 79 | 0 | 77 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| A2r pré-T0 | B9jg8F | 7 | kept:base_vault_not_identified 7 | 7 | 6 → 6 | undecoded_transactions, reserves_chain_broken → undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | CXgcuE | 20 | kept:base_vault_not_identified 12, rebuilt 8 | 12 | 18 → 11 | undecoded_transactions, token_transfer_fee, reserves_chain_broken → undecoded_transactions, token_transfer_fee, reserves_chain_broken |
| A2r pré-T0 | EonJQh | 4 | kept:base_vault_not_identified 4 | 4 | 2 → 2 | undecoded_transactions, reserves_chain_broken → undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | FBePpA | 50 | kept:amounts_not_reproduced 7, kept:base_vault_not_identified 24, kept:no_state_before 5, rebuilt 14 | 36 | 18 → 13 | undecoded_transactions, reserves_chain_broken → undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | G8kgi7 | 1282 | rebuilt 1282 | 0 | 1142 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| A2r pré-T0 | GdxFyc | 24 | rebuilt 24 | 0 | 20 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| A2r pré-T0 | GfApkU | 20 | rebuilt 20 | 0 | 19 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| livesim pré-départ | 4D17GN | 55 | kept:amounts_not_reproduced 1, kept:base_vault_not_identified 32, rebuilt 22 | 33 | 50 → 32 | undecoded_transactions, reserves_chain_broken → undecoded_transactions, reserves_chain_broken |
| livesim pré-départ | 5zk4vh | 39 | rebuilt 39 | 0 | 35 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| livesim pré-départ | 6CQSpR | 1 | rebuilt 1 | 0 | 1 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| livesim pré-départ | 7SJ5UK | 103 | rebuilt 103 | 0 | 82 → 0 | undecoded_transactions, reserves_chain_broken → admis |
| livesim pré-départ | CXgcuE | 19 | kept:base_vault_not_identified 12, rebuilt 7 | 12 | 17 → 11 | undecoded_transactions, token_transfer_fee, reserves_chain_broken → undecoded_transactions, token_transfer_fee, reserves_chain_broken |
| livesim pré-départ | FAn5gz | 156 | rebuilt 156 | 0 | 136 → 0 | undecoded_transactions, reserves_chain_broken → admis |

**Les 3 pools pilotes de N1 et de G2-3** :
- AEZjoU : 79 / 79 reconstituées ;
- G8kgi7 : 1 282 / 1 282 transactions, soit 1 285 swaps, y compris la transaction à 4 swaps ;
- GdxFyc : 24 / 24.

Pour les trois, il ne reste plus AUCUNE rupture, la reproduction est exacte (37 769 / 37 769, 38 681 / 38 681,
8 181 / 8 181), et **G-0 inchangé les admet**. Gms3Ma n'a aucune transaction non décodée : il reste exclu pour frais
de transfert (U-4).

**Limites observées sur d'autres pools** :
- « base_vault_not_identified » (Token-2022 ou propriétaire différent) ;
- quelques « amounts_not_reproduced » et « no_state_before ».

Ces transactions restent non décodées, et G-0 refuse ces pools comme avant. Rien n'est forcé.

## Validation

- 10 tests :
  - synthétiques :
    - reconstitution exacte et fermeture de la chaîne ;
    - plusieurs swaps dans une transaction ;
    - sortie exacte ;
    - événements identiques aux vrais ;
    - chaque refus (autre instruction CPMM, transferts ≠ soldes, transferts non identifiés, hauteur de pile absente,
      montants non reproduits, transaction échouée, pas d'état avant, autre cause, état perdu après un échec) ;
    - identification des coffres ;
  - RÉELS : 64 transactions tronquées pré-T0 des 3 pilotes, avec leurs voisines (`tests/data_real`, sha vérifiés,
    1,8 Mo), dont la transaction de G8kgi7 à 4 swaps.
- 24 mutants sur 24 détectés (`MUTATIONS_cpmmrecon_v0_1.json`).
- Pas encore écrite : l'intégration dans g23run et n1verdict, c'est-à-dire appeler `rebuild` avant G-0 et avant les
  positions. Elle attend ton audit et le texte du propriétaire.
