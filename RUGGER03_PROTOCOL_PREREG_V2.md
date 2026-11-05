# RUGGER 03 — protocole v2 CANDIDAT (issue #164)

Statut : **CANDIDAT, NON FIGÉ.** Seul le propriétaire fige (enregistrement du SHA de commit avant toute collecte). Aucun réseau, trade, secret, abonnement, merge.
**Rentabilité de MASTER : NON DÉMONTRÉE (INSUFFICIENT DATA).** Spécification : `benchmarks/rugger03_prereg_v2/protocol.json`. Tests : `tests/test_rugger03_protocol_v2.py`. Reprend le brouillon `RUGGER03_PROTOCOL_PREREG.md` (#158).

## Chiffres revérifiés localement (lecture seule de `evidence/p3`, démontré par code)
397 enregistrements / 5 bundles ; 81 transactions dont **79 signatures distinctes** (2 présentes dans plusieurs bundles) ; 214 `candidate_decision` pour **135 mints distincts** (136 mints tous types) ; 3 `launch` ; 378/397 `source_time_unknown` ; aucun kind `cycle`/`fill` ; aucun kind de migration. Note : l'audit #160 citait 136 mints pour les 214 décisions ; le recomptage donne 135 pour les décisions seules (136 tous kinds).

## Matrice de traçabilité des 8 exigences #160
| # | Exigence #160 | Où dans le protocole | Test(s) |
|---|---|---|---|
| 1 | Pré-enregistrement, SHA, N minimal | `req1_preregistration`, `targets` | `test_targets_and_freeze_declared`, `test_owner_values_left_null` |
| 2 | Unité = mint, dédup signature inter-bundles | `req2_deduplication` | `test_mint_dedup_counts`, `test_cross_bundle_signature_duplicates`, `test_dedup_synthetic` |
| 3 | `source_time` vs `available_at`, replay causal | `req3_time_and_causality` | `test_source_time_unknown_counted`, `test_causal_view_synthetic` |
| 4 | Même journal, mêmes coûts, paramètres figés, hors-échantillon | `req4_causal_criteria` | `test_causal_criteria_declared` |
| 5 | Devis achat+vente, frais complets, P&L en SOL | `req5`, `req8` | `test_net_pnl_lamports`, `test_transaction_count_81` |
| 6 | Capture migration LaunchLab→CPMM | `req6_migration` | `test_no_migration_kind_in_evidence` |
| 7 | Tests non vacuants, kinds réels, 81 | `req7_non_vacuous_tests` | `test_kinds_closed_schema`, `test_zero_cycles_is_non_vacuous` |
| 8 | IC, comparaison, INSUFFICIENT DATA, frais/seuils préenregistrés | `req8_costs_thresholds`, `insufficient_data_rule` | `test_profit_gate`, `test_insufficient_data_rule` |

## Limites
Valeurs à fixer par le propriétaire (fenêtre, lookback de financement, latence en slots, graine, plafond de requêtes) laissées à `null`/non inventées. Suite complète et pytest natif : non exécutés ici (voir issue). Le moteur MASTER reste hors de cette branche. Support des états de migration dans `bot/p3/launchlab.py` : non démontré. Réseau et Helius : non utilisés.
