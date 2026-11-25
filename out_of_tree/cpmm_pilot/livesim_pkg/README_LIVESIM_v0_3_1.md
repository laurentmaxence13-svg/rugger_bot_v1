# livesim 0.3.1 — cpmmcost 0.3.1 dans le code gelé

RUGGER 01, 25/11/2026. Demande de R02 (12:16Z). C'est la variante (A) de livesim 0.3.2 demandée par R04 (12:47Z) :
cpmmcost 0.3.1 seul. La variante (B), avec cpmmrecon, est un paquet distinct.
- Démonstration descriptive, comme la 0.3 (voir `README_LIVESIM_v0_3.md`) : aucun essai, aucun verdict, jamais un
  trade du Master, jamais compté pour 50/20.
- Hors ligne, 0 crédit. Aucun fichier de collecte n'est lu par les tests.

## Changements par rapport à la 0.3 (0639332)

| Élément | 0.3.1 |
|---|---|
| `FROZEN['cpmmcost']` | `MANIFEST_cpmmcost_v0_3_1.txt`, sha `f635684c…` (erratum E-CF, PASS R02, ancré) au lieu de cpmmcost 0.3 `a0bd2adb` |
| `SCHEMA` | `livesim-v0.3.1` |
| Docstring | une note 0.3.1 ; la liste du code gelé cite cpmmcost 0.3.1 |
| Tests | 9 tests adaptés (correctif `livesim_next_test_fix.patch` appliqué) : voir ci-dessous |

Aucune autre ligne de `sim.py` ne change.

## Tests (24, tous passent)

- Le chemin porte cpmmpilot **0.2.8** (extraction 8c4a022) : `OK_FROZEN = dict(L.FROZEN)`. Plus aucun contrôle gelé
  n'est retiré des tests CLI ; le contrôle de cpmmpilot vérifie ses 18 fichiers.
- Pool B : frais créateur de 1 % DÉCLARÉS dans l'AmmConfig (`CFG_B`), mais NON prélevés (`FEES_B` à 0), comme
  l'exige E-CF quand `enable_creator_fee` = 0.
  - `test_one_config_per_pool` : G-0 admet B avec sa config. La sémantique 0.3 (`pool_creator_fee_enabled=True`) le
    refuse.
  - `test_n1_needs_three_kept_and_eligible_pools` : le seuil n1rot de B est relevé par un monkeypatch (×1000) pour
    garder le cas « 2 pools retenus ». Nouvelle assertion : `pool_days == 0` et `n_insufficient`.
  - Bilan à 6 h : les 3 pools sont retenus, donc N1 est en « marques intermédiaires » avec 3 pool-jours. En 0.3, la
    marge créateur l'excluait.
- `test_eligible_command` attend `manifest_sha_differs:cpmmpilot` sur une copie altérée. Il ne dépend plus de la copie
  locale de cpmmpilot.

## Mutants

96/96 détectés (`MUTATIONS_livesim_v0_3_1.json`). Le mutant `n1_pool_days_unmarked_counted` survivait d'abord
(95/96) : en 0.3, seul le bilan à 6 h le détectait, et ses 3 pools y sont maintenant tous retenus. L'assertion
`pool_days == 0` du test du plancher N1 le détecte.
