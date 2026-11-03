# Run record: legacy-copies-doc-v1 (2026-11-03)

- Item: legacy-copies-doc-v1. Origin: scheduled, planner action START.
- Criterion 1, "lists each legacy copy, its size, whether anything imports it": met in docs/autonomy/LEGACY_COPIES.md (file list with sizes derived from find/stat, identical/different counts by byte comparison, grep for imports and config references).
- Criterion 2, "nothing is deleted or moved": met; only two new documentation files were added.
- Commands: git ls-remote, pip install, tools/dev_state.py fetch/plan, find, grep, python ast/filecmp checks, pytest.
- Suite before: 1404 passed, 1 skipped. After: 1404 passed, 1 skipped.
- Content commit: baf7d62141a3b3bb1f162137dc27d631db0af4e9
- Limits: no execution of the legacy code; external use outside the repository is unknown.
- Not changed: code, tests, bot/bot, tests/tests, backups, BACKLOG.json, MASTER_CONTINUITY.md.
