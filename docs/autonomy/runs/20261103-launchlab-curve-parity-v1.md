# Run record: launchlab-curve-parity-v1 (2026-11-03, scheduled START)

Criteria:
1. Read only committed SOL fixtures: tool loads `tests/fixtures/launchlab_sol_pools` via `load_archive`; no network.
2. Classification and exact recompute: `classify`, `recompute`, `check_pool`; 113/113 supported events match.
3. Documentation: `docs/research/LAUNCHLAB_CURVE_PARITY.md` (denominator, fee per pool, counts, SHAs, limits). Unsupported count is 0 here and stated as such.
4. Offline focused tests: 5 new tests; no existing test touched.

Commands: `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`; `python -B tools/launchlab_curve_parity.py`.
Suite before: 1404 passed, 1 skipped. After: 1409 passed, 1 skipped (recorded by the final run).
Not changed: curve module, event decoder, fixtures, risk limits, thresholds, strategy.
Limits: see the research document.
