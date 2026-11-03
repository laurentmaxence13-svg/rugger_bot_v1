# Run record: launchlab-cost-audit-v1 (scheduled START, 2026-11-03)

Planner: START, no overlap with open dev branches. Base: `origin/claude/launchlab-trade-events`.

Criteria and how they were met:
1. Two baseline entries from committed SOL fixtures, 0.05 SOL, 2-slot latency, inferred fee rate: `tools/launchlab_cost_audit.py` (pools 5pZ6Md…, C7F9Kb…; DVP426… has no entry).
2. Separated curve input/output, assumed network cost vs observed fees, entry/exit amounts, migration and liquidation flags; unknowns listed in `not_exposed`.
3. Auditable calculation, zero differences from the existing baseline report, a fee sensitivity; no profitability claim (`docs/research/LAUNCHLAB_COST_AUDIT.md`).
4. Offline tests in `tests/test_launchlab_cost_audit.py` (5 tests); no change to live trading, thresholds or financial parameters.

Commands: `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`, `python -B tools/launchlab_cost_audit.py`.
Suite: before 1404 passed, 1 skipped; after 1409 passed, 1 skipped.
Limits: two entries only; network fee is an assumption. Not changed: replay engine, baseline report, strategy parameters.
