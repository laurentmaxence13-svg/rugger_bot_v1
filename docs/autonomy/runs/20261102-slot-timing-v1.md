# Run record: slot-timing-v1 (2026-11-02, UTC date of run)

Item: `slot-timing-v1`. Coordination base: `origin/claude/launchlab-trade-events`.

## Acceptance
1. Pure functions, no network: `bot/market/timing.py` (`unique_pairs`, `span_rate`, `consecutive_rates`, `slots_to_seconds`). No I/O.
2. Tests read only `tests/fixtures/launchlab_sol_pools` and synthetic samples; `python -W error -m pytest tests/test_launchlab_timing.py`: 8 passed.
3. Note `docs/research/SLOT_TIMING_20261103.md`: range 0.213-0.222 s/slot, 64 distinct pairs (173 rows), 1-second quantisation, not a measurement of our orders.
4. 2-slot latency shown only as unvalidated conditional arithmetic (about 0.43-0.44 s if the measured rate were right); default unchanged and pinned by a test.

## Commands
- `python -m pip install -r requirements.txt streamlit pytest` (PyPI only; the environment lacked them).
- `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`

## Suite counts
Before: 1404 passed, 1 skipped, 242 subtests. After: 1412 passed, 1 skipped, 242 subtests (+8 new tests).

## Commit
The commit carrying this file; its SHA is in the pull request comment and the branch head.

## Limits
Three short pools; DVP426 has two distinct slots. Block times are whole seconds.

## Not changed
`ExecutionModel` defaults, risk limits, thresholds, TP/SL, sizing, BACKLOG.json, MASTER_CONTINUITY.md.

## Round 1 correction (owner comment on PR #92)
Note edited only: removed the "faster slots" reading and the validated-looking seconds conversion; stated the unexplained discrepancy with the 400 ms figure and its unverified candidate causes; added a "Next check" section (12 calls, not run). `bot/market/timing.py` untouched. Suite after: see PR comment.
