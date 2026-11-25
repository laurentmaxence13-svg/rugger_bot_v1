# cpmmcost 0.3.1 — ERRATUM E-CF : frais créateur effectif par pool

RUGGER 01, 25/11/2026.
- Défaut confirmé par R02 et ancré au registre à 11:51:11Z ; correction décidée par R02 et approuvée par R04 (R04-13).
- **Paquet séparé** (`cpmm_pilot/cpmmcost031_pkg`, module `cpmmcost`). La 0.3 ancrée (`cpmmcost_pkg`, MANIFEST
  a0bd2adb) reste INTACTE.
- Aucune règle, aucun seuil, aucun critère ne change. Aucune donnée de fenêtre n'est lue.

## Le défaut

- En 0.3, `fees_from_amm_config` appliquait le taux créateur de l'AmmConfig (500 ppm pour D4FPEr) à TOUT pool.
- Dans Raydium CPMM, le frais créateur n'est prélevé que par un pool qui l'active dans SON état. Le champ est
  `enable_creator_fee`, à l'octet 390 du PoolState ; il est déjà décodé par `cpmmpilot.layout.decode_pool`, avec
  `creator_fee_on` à l'octet 389.
- Sur nos pools, aucun swap ne journalise de frais créateur. La 0.3 ne les reproduisait donc pas, et G-0 les refusait.

## La correction (une seule ligne de code)

```python
creator = config.get('creator_fee_rate', 0) if config.get('pool_creator_fee_enabled') is True else 0   # E-CF 0.3.1
```

- **Taux effectif** : le taux de l'AmmConfig s'applique SEULEMENT si la config porte
  `pool_creator_fee_enabled = True`. Cette valeur se lit dans l'état du pool, dans une donnée ancrée. Sinon, le taux
  effectif vaut 0.
- **Pourquoi ce choix plutôt qu'une table par pool** :
  - `fees_from_amm_config(config)` est appelée sans le pool par 7 paquets gelés (cpmmprereg, lpcost, n1rot, cpmmgen2,
    cpmmgen3, cpmmb1, cpmmpilot) ;
  - un choix par pool à l'intérieur de cpmmcost obligerait à modifier tous ces appelants ;
  - le choix au niveau de la config ne modifie aucun appelant.
- **Sûreté** : un pool qui prélève vraiment le frais, sans que son drapeau soit fourni, n'est jamais mal valorisé.
  G-0 le refuse (« swaps_not_reproduced »). C'est testé sur un pool synthétique.
- **Source du drapeau** : aucune donnée ANCRÉE dans git ne le contient. La photo U2 a lu les PoolState avec un
  dataSlice de 0 à 413 octets, qui contient l'octet 390, mais seuls les sha des réponses sont dans `calls_u2.jsonl`.
  La question est posée à R03, à qui l'on demande si les pages brutes existent chez lui. Faute de drapeau, on applique
  la règle de R04 : taux 0, car aucun swap pré-T0 ne journalise de frais créateur.

## Preuve sur données réelles (hors ligne, 0 crédit)

- Script : `verify_real_pages.py`, sortie `VERIFY_ECF_REAL_PAGES.json`.
- Les 32 jeux de pages sont : les 24 pools A2r pré-T0 (R03 ecd1098) et les 8 pools livesim pré-départ (R03 c581e9f).
  Cela fait 31 pools distincts, CXgcuE figurant dans les deux.
- 125 522 swaps au total : aucun ne journalise de frais créateur, et TOUS sont reproduits exactement en 0.3.1.
- Non-régression de R02 : AEZjoU passe de 0 / 37 690 (taux créateur prélevé, comme en 0.3) à 37 690 / 37 690 (0.3.1).

| Pages | Pool | Swaps | Avec frais créateur journalisé | Exacts (0.3, frais prélevé) | Exacts (0.3.1) | G-0 en 0.3.1 |
|---|---|---|---|---|---|---|
| A2r pré-T0 | 2yLFom | 1600 | 0 | 0 | 1600 | admis |
| A2r pré-T0 | 3oUDg6 | 5 | 0 | 0 | 5 | token_transfer_fee |
| A2r pré-T0 | 4NX5P7 | 1 | 0 | 0 | 1 | undecoded_transactions |
| A2r pré-T0 | 5H1z2z | 1 | 0 | 0 | 1 | admis |
| A2r pré-T0 | 5ML6Tk | 17 | 0 | 0 | 17 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | 68vHUS | 724 | 0 | 6 | 724 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | 8AdPiZ | 2 | 0 | 0 | 2 | token_transfer_fee |
| A2r pré-T0 | AEZjoU | 37690 | 0 | 0 | 37690 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | AFeg9y | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | B9jg8F | 84 | 0 | 0 | 84 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | BDZZ2X | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | BGH7QT | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | BKZSLD | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | CXgcuE | 446 | 0 | 0 | 446 | undecoded_transactions, token_transfer_fee, reserves_chain_broken |
| A2r pré-T0 | CjZWsA | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | EJYg54 | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | EonJQh | 29 | 0 | 0 | 29 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | FBePpA | 83 | 0 | 0 | 83 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | FL8dqw | 0 | 0 | — | — | no_swap |
| A2r pré-T0 | G8kgi7 | 37396 | 0 | 130 | 37396 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | GdxFyc | 8157 | 0 | 0 | 8157 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | GfApkU | 202 | 0 | 0 | 202 | undecoded_transactions, reserves_chain_broken |
| A2r pré-T0 | Gms3Ma | 804 | 0 | 0 | 804 | token_transfer_fee |
| A2r pré-T0 | HBrBDK | 8 | 0 | 0 | 8 | admis |
| livesim pré-départ | 4D17GN | 2796 | 0 | 0 | 2796 | undecoded_transactions, reserves_chain_broken |
| livesim pré-départ | 5zk4vh | 4186 | 0 | 23 | 4186 | undecoded_transactions, reserves_chain_broken |
| livesim pré-départ | 6CQSpR | 5785 | 0 | 0 | 5785 | undecoded_transactions, reserves_chain_broken |
| livesim pré-départ | 7SJ5UK | 857 | 0 | 1 | 857 | undecoded_transactions, reserves_chain_broken |
| livesim pré-départ | A3URwh | 1534 | 0 | 0 | 1534 | token_transfer_fee |
| livesim pré-départ | CXgcuE | 445 | 0 | 0 | 445 | undecoded_transactions, token_transfer_fee, reserves_chain_broken |
| livesim pré-départ | FAn5gz | 3472 | 0 | 16 | 3472 | undecoded_transactions, reserves_chain_broken |
| livesim pré-départ | GaPTvX | 19198 | 0 | 0 | 19198 | admis |

**Ce qui reste refusé par G-0 en 0.3.1, sans lien avec le frais créateur** : les transactions non décodées
(log_truncated), les ruptures de réserves qui les accompagnent, et les frais de transfert Token-2022. C'est le sujet
d'E-G0, qui relève de la décision du propriétaire.

## Validation

- 25 tests :
  - les 22 de la 0.3 ; le test du frais créateur synthétique porte maintenant le drapeau du pool ;
  - 3 nouveaux tests E-CF :
    - la règle du taux effectif (drapeau strictement `True`) ;
    - les premières pages RÉELLES des 4 pools pilotes et des 8 pools livesim, sha vérifiés, dans
      `tests/data_real` (1,6 Mo) : avec le frais prélevé, 0 swap exact ; en 0.3.1, tous exacts ; G-0 pool par pool ;
    - un pool qui prélève le frais (synthétique : aucun pool réel de nos données ne le fait) : il est admis avec le
      drapeau, refusé sans.
- 52 mutants sur 52 détectés (`MUTATIONS_cpmmcost_v0_3_1.json`), dont 5 propres à E-CF.
- Les tests de cpmmcost lisent les pages réelles avec `cpmmpilot.store` ; cpmmpilot 0.2.8 (8c4a022) doit être sur le
  chemin.
