# cpmmpilot 0.2.3 — règle D de R02 dans les fiches de gel (R03), HORS LIGNE

Cette version répond à la note R02 e294655a, qui fixe la règle D avant tout appel de l'étape 1, et à la demande de R02 de 10:31Z : un test montrant qu'aucune signature postérieure à T0 n'est écrite. Aucun appel réseau n'a été fait.

## Changements (`step1.py` uniquement, plus les tests et le runner)

**`step1.d_rule(trigger_count_rcp1, d_max_days)`**
- Entrée : T, le nombre de déclencheurs R-CP1 sur [T0 − 7 j ; T0).
- D_155 = ⌈155 × 7 / T⌉. C'est le plus petit entier D tel que ⌊T × D / 7⌋ ≥ 155. Si T = 0, D_155 est infini.
- D = min(max(D_155, 7), ⌊D_max⌋, 60). Si D < 1 : `Step1Stop('d_below_one_day')`.
- attendu = `cpmmprereg.expected_entries(compte, D)`, puis `power_stop` de cpmmprereg. Les deux fonctions sont gelées.
- La fonction renvoie T, D_155, D_max, D, attendu et `power_stop`.

**`step1.freeze_sheets(..., d_rule=None)`**
- Les deux fiches portent `d_rule` en plus des champs existants.
- Si `d_rule['d_days']` diffère de `d_days` : `Step1Stop`.

Le reste du paquet est inchangé par rapport à 0.2.2 (PASS R02 7e57b7e2).

## Vérifications (hors ligne, `unshare -rn`, g1ind 0.6.1)

**Tests : 41 sur 41, dont 3 nouveaux.**
- Règle D, sur ces cas :
  - T = 70 avec D_max = 30,5 : D = 16, attendu 160 ;
  - ⌊D_max⌋, minimum 7, plafond 60 ;
  - T = 0 : infini, puis UNDERPOWERED ;
  - minimalité de D_155 pour 7 valeurs de T.
- `d_rule` présent dans les deux fiches, et refus en cas d'incohérence avec `d_days`.
- `count_24h` sur une chaîne qui continue après T0 : les comptes sont exacts, et aucune signature n'apparaît dans la sortie.

**Mutants : 62 sur 62 tués** (`MUTATIONS_cpmmpilot_v0_2_3.json`). Sept sont nouveaux : `d_min_7_ignored`, `d_cap_60_ignored`, `d_max_ignored`, `d155_floor_not_ceil`, `d155_target_150`, `d_rule_not_in_sheets`, `d_rule_mismatch_unchecked`. Un premier mutant, `d155_not_minimal`, a survécu parce qu'il était équivalent : les boucles d'ajustement étaient du code mort, puisque ⌈1 085 / T⌉ est déjà minimal. Ces boucles ont été retirées.

**Répétition :** journal cf26fbba….
