# Run record: launchlab-failure-analysis-v1 (2026-11-03, scheduled START)

Criteria:
1. Read-only fixture listings, `err != null` counts and rates per pool and slot age: `tools/launchlab_failure_report.py` (173 signatures, 59 failed, 0.341).
2. Address-level vs order-attempt caveat: in the tool output (`caveat`), docstring and `docs/research/LAUNCHLAB_FAILURES.md`.
3. Empty/partial/malformed/unreadable tests and reproducible report: `tests/test_launchlab_failure_report.py` (5 tests).
4. No transaction, no archive written: the tool only opens files for reading.

Commands: `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`; `python -B tools/launchlab_failure_report.py`; `dev_state.py scope`.
Suite: before 1404 passed, 1 skipped; after 1409 passed, 1 skipped.
Limits: descriptive only (3 pools); error codes not decoded. Not changed: strategy, risk, thresholds, existing code.
