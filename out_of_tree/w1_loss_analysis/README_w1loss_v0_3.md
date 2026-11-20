# w1loss 0.3 — ventilation descriptive des positions W1 (phase « rentabilité »)

**Écrit, non exécuté.** Exécution par RUGGER 03 seulement après trois conditions :
- l'ancrage par RUGGER 02 de la liste fermée des 7 ventilations ;
- son PASS sur le code ;
- l'accord du propriétaire pour la lecture.

## Conditions de R02 (877da7b6) et où elles sont appliquées

| Condition | Dans le code | Testée par |
|---|---|---|
| Liste fermée de 7 ventilations, comptées à part (E = 7) | T1 à T7 ; T0 donne les totaux et la distribution du brut, ce n'est pas une ventilation | `doc['breakdowns']`, `doc['E'] = 7` |
| Pare-feu HW1 : aucun déclencheur ni aucune variable d'état HW1 ; âge borné à ≥ 450 slots | `READ_FIELDS` (liste blanche des champs lus) ; `AGE_EDGES` | `test_firewall_only_the_whitelisted_fields_are_read` (espion sur chaque clé lue) ; `test_firewall_no_hw1_state_variable_is_named_in_the_module` |
| Seuls les cycles MASTER, référence et placebo du ledger ancré sont lus ; la référence, identique au MASTER, n'a qu'une colonne | essai `L1`, bras fixés ; `reference_identical_to_master` vérifié ; `reference_column` | `test_placebo_pairs_and_the_firewall` ; `test_a_reference_that_differs_from_the_master_is_flagged` |
| Intervalles bootstrap par créateur, graine 20261120, 2 000 tirages, par classe, avec n ; classe < 30 « non interprétable » | `bootstrap`, `_interval` | `test_interval_is_the_creator_cluster_bootstrap...` ; `test_bootstrap_takes_the_ranks...` |
| Contrefactuel étiqueté « approximation au premier ordre (sans effet sur le prix ni sur la décision d'entrée) » ; r′ = paliers observés à l'entrée seulement | `CF_LABEL` ; r′ = paliers observés du bras sous le plus haut | `test_known_answers_for_the_master_arm` |
| Sortie en liste blanche : aucun pool, créateur ni signature | — | `test_output_whitelist_no_pool_creator_or_signature` |
| Tout est EXPLORATOIRE ; rien ne touche au verdict officiel ni à la lecture HW1 | `STAMP`, `flags` | — |
| (5c4e0ae8 L2-3, 141155dd) T0 contrôlé DANS l'outil contre la lecture ancrée : `--reading` avec son sha (ea152a32). n = 128 / 343 et sommes du net, du brut, des frais, des transactions, du glissement et des échecs égales au lamport près (écart < 1), sinon refus et rien n'est écrit | `check_against_reading` | `test_t0_must_equal_the_anchored_reading...` |
| IC du BRUT moyen par classe et de la différence appariée brute (T6) | `interval_95_mean_gross_return` | `test_interval_is_the_creator_cluster_bootstrap...` |
| Phrase finale du .md : « Intervalles descriptifs, aucun test, aucune sélection » ; E = 7 publié | `markdown` | `test_intervals_are_reproducible_and_the_gross_interval_and_e_are_published` (dont la reproductibilité à l'octet près) |

## Commande (R03)

    PYTHONPATH=<w1_loss_analysis> python -B -m w1loss.analysis --ledger <ledger.json ancré 4da5fbfb…> \
        --ledger-sha256 <ancré> --l1-bundle <run/bundles/L1.json.gz> \
        --evaluation-min 467678545 --evaluation-max 469291345 \
        --reading <LECTURE_PRELIMINAIRE.json ancrée> --reading-sha256 <ea152a32…> --out <OUT>

Le contrôle de T0 contre la lecture ancrée est fait par l'outil lui-même (refus sinon).

## Preuves

- 13 tests sous CPython 3.12.3 avec `-W error`.
- Défauts volontaires : 32 détectés sur 33 (`MUTATIONS_w1loss_v0_3.json`). Le seul non détecté,
  `cf_threshold_inclusive`, est équivalent au code d'origine : à r = r′, le facteur (1 − r′/r) vaut 0.
