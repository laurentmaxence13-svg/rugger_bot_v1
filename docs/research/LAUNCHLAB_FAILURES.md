# LaunchLab failed vs successful signatures (offline)

Source: `tests/fixtures/launchlab_sol_pools` (3 complete SOL-quoted pools). Reproduce: `python -B tools/launchlab_failure_report.py`. Status: demonstrated by code and reproduced by test; no network, no archive modified.

## Results

| Pool | Signatures | Failed (`err != null`) | Failure rate |
|---|---|---|---|
| `5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2` | 38 | 27 | 0.7105 |
| `C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC` | 133 | 32 | 0.2406 |
| `DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r` | 2 | 0 | 0.0 |
| **All** | 173 | 59 | 0.341 |

## By slot age from the earliest listed signature

| Pool | Age (slots) | Total | Failed | Rate |
|---|---|---|---|---|
| `5pZ6Md…` | slots>=0 | 3 | 0 | 0.0 |
| `5pZ6Md…` | slots>=10 | 34 | 27 | 0.7941 |
| `5pZ6Md…` | slots>=50 | 1 | 0 | 0.0 |
| `C7F9Kb…` | slots>=0 | 17 | 2 | 0.1176 |
| `C7F9Kb…` | slots>=10 | 57 | 29 | 0.5088 |
| `C7F9Kb…` | slots>=50 | 59 | 1 | 0.0169 |
| `DVP426…` | slots>=0 | 1 | 0 | 0.0 |
| `DVP426…` | slots>=50 | 1 | 0 | 0.0 |

Failures are counted, never excluded, so there is no survivorship filter. Error kinds per pool are in the JSON output (`error_kinds`); the most frequent custom codes are 7, 11, 4 and 6000 (not decoded here).

## Limits: do not read this as our own failure probability

- The listing holds every transaction touching the pool address from any wallet (bots, retail, creator setup). It is not the bot's order attempts.
- Failed transactions of other actors reflect their slippage limits, compute budgets and account errors, not ours.
- Early-age rates are high on two pools, but with 3 pools and 173 rows this is descriptive only, not an estimate.
- Age is measured from the earliest listed signature, which equals creation only when `signatures_complete` is true (true for all three fixtures). Slot age, not wall-clock time.
- Estimating our own failure probability needs our own submitted orders, which this PAPER-only project does not have.
