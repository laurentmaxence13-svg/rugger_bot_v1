# Cloud validation run 1 — offline suite on the PR 90 head

## STATUS

**PASS**

## UTC start and end times

- Start: 2026-11-02 23:21:27 UTC (`date -u`)
- End: 2026-11-02 23:22:28 UTC (`date -u`, captured when this report was written)

## Expected SHA

`7bd4fad267cf4c5ee7669ce30f53000215f55b8c`

## Actual SHA

`7bd4fad267cf4c5ee7669ce30f53000215f55b8c` (`git rev-parse HEAD` after `git checkout -B claude/cloud-validation-20261103 7bd4fad...`). Match confirmed.

## Tool versions

- Python: 3.11.18 (`python --version`)
- git: 2.43.0 (`git --version`)
- pip: 24.0 (`python -m pip --version`, system install at /usr/lib/python3/dist-packages/pip)
- Dependency install: `python -m pip install --disable-pip-version-check -r requirements.txt -r requirements-dashboard.txt pytest` — exit code 0. Includes pytest 9.2.0 and streamlit 1.66.1, pandas 2.3.3, numpy 2.3.4.

## pytest

- Command: `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`
- Exit code: **0**
- Final summary line: `1401 passed, 1 skipped, 242 subtests passed in 16.05s`
- Failed tests: none (no FAILED or ERROR lines in the output).

## Remote main

- MAIN_BEFORE (`git ls-remote origin refs/heads/main` at step 1): `d9b950e4708a3d0fc9c955f852144ec1fd893867`
- MAIN_AFTER (same command after the tests): `d9b950e4708a3d0fc9c955f852144ec1fd893867`
- MAIN_AFTER equals MAIN_BEFORE: **yes**

## Safety statement

No secret, token, API key, .env file or credential was read, printed, created or copied. No Solana RPC, Helius, Bitquery, Raydium, price, market or trading API was called. No transaction was built, signed or submitted. The only network access was git operations against the GitHub remote and pip installs from PyPI.
