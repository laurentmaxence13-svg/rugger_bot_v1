# RUGGER 03 — Contrat de données pour lever les WAIT MASTER (issue #177)

Hors réseau, fixtures uniquement. Aucun seuil MASTER modifié (les minimums 50 cycles / 20 groupes sont recopiés en lecture seule de `bot/master_decision.py`), aucun BUY forcé, aucune collecte Helius/Bitquery, aucun LIVE.
Code : `bot/master_data_contract.py` ; tests : `tests/test_master_data_contract.py`. S'appuie sur le diagnostic #173 (`MASTER_WAIT_DIAGNOSTIC_173.md`).

## Matrice champ → motif WAIT → source → validation
| Champ | Motif levé | Source attendue | Validation |
|---|---|---|---|
| `fees.entry_extra_lamports` | additional_costs_unknown | BUY tx meta.fee + priority/tip | int>=0 |
| `fees.exit_extra_lamports` | additional_costs_unknown | SELL tx meta.fee + priority/tip (needs executed or simulated SELL) | int>=0 |
| `fees.failed_attempt_lamports` | additional_costs_unknown | chain_failed tx meta.fee attributed to owner wallet | list[int>=0] |
| `fees.quote_amounts_net_of_pool_fees` | additional_costs_unknown | quote semantics from pool math | is True |
| `fees.extra_fees_exclude_pool_fees` | additional_costs_unknown | fee decomposition | is True |
| `fees.provenance` | additional_costs_unknown | collector tag | in observed|estimate|synthetic |
| `research_evidence.qualified_economic_cycles` | qualified_past_edge_evidence_unavailable | complete BUY/SELL cycles | int>=50 |
| `research_evidence.independent_creator_groups` | qualified_past_edge_evidence_unavailable | creator clustering | int>=20 |
| `research_evidence.training_end_ms<=available_at_ms<=decision_at_ms` | qualified_past_edge_evidence_unavailable | report publication time | causal order |
| `research_evidence.policy_sha256/report_sha256` | qualified_past_edge_evidence_unavailable | frozen policy + report digest | 64 lowercase hex |
| `bank_state.identity_qualified` | source_identity_supply_creation_unqualified | creator identity check | is True |
| `bank_state.supply_verified` | source_identity_supply_creation_unqualified | mint supply / authorities from chain | is True |
| `bank_state.creation_verified` | source_identity_supply_creation_unqualified | creation tx matched to launch | is True |
| `event.source_time_ms<=received_at_ms<=available_at_ms` | causal timestamps | source clock, receiver clock, availability | ints, ordered |
| `event.source_slot` | causal timestamps | RPC slot | int>0 |
| `trade.side/signature/mint/amounts/status` | buys, sells, migrations | swap tx on LaunchLab/CPMM | side in BUY|SELL, status in ok|chain_failed |
| `migration.launchlab_pool -> cpmm_pool` | buys, sells, migrations | migrate event | same mint, cpmm after launchlab |
| `coverage.venues` | LaunchLab/CPMM coverage | per-venue event counts | both venues present |

## Limites
- Un contrat satisfait prouve seulement qu'un enregistrement est bien formé, pas qu'il est authentique ni rentable.
- Les validateurs ne vérifient pas la source réelle (supply/identité) : cela exige une collecte autorisée (non faite).
- Les données actuelles (#173) ne satisfont aucune ligne : 0 cycle, 5 créateurs, `creation_verified` 0/45.
- Rentabilité : **NON démontrée**.
