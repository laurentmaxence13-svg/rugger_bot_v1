# Run record: launchlab-priority-fee-v1 (2026-11-03, scheduled START)

Baseline suite (before): 1404 passed, 1 skipped. Main at d9b950e.

| Acceptance criterion | How met |
|---|---|
| Committed metadata only, no network | Reads gz fixtures in `tests/fixtures/launchlab_sol_pools/`; stdlib only |
| Fee distribution by pool and slot-age bins; decode compute budget | `fee_by_slot_age`, `unit_price_micro_lamports`, base58 decoder; limits in the doc |
| No winning-fee inference, no default change | Output states "not a winning-fee estimate"; no bot code touched |
| Reproducible command, counts, offline tests | `python -B tools/launchlab_priority_fee_report.py`; 7 new tests |

Commands: `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`; `python <protocol>/tools/dev_state.py scope launchlab-priority-fee-v1 --base origin/claude/launchlab-trade-events`.
Limits: 3 pools, 114 transactions; only 14 have a decodable unit price. Not changed: any bot module, risk, threshold, sizing or execution default.
