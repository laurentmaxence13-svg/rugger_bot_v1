# LaunchLab observed network fees (offline, observational)

Command (no network, no key, read-only):

    python -B tools/launchlab_priority_fee_report.py [archive_dir]

Default input: `tests/fixtures/launchlab_sol_pools/` (3 SOL-quoted pools, 114 archived transactions: 11 + 101 + 2, none failed).

## What is measured
- `meta.fee` (lamports, total paid) per pool and per slot-age bin (slots since the pool's first archived transaction: 0-4, 5-19, 20-99, 100+).
- Declared ComputeBudget `SetComputeUnitPrice` (micro-lamports/CU) and `SetComputeUnitLimit`, decoded from base58 instruction data. Only 14 of 114 transactions carry a decodable unit price (3, 9 and 2 per pool); the rest show a fee above 5000 lamports with no decodable price, so the fee cannot be split into base, priority and any other component for them.

## Observed (medians, lamports)
| Pool | n | median fee | 0-4 | 5-19 | 20-99 | 100+ |
|---|---|---|---|---|---|---|
| 5pZ6Md… | 11 | 40167 | 2205001 | 51345 | 40167 | none |
| C7F9Kb… | 101 | 31084 | 15000 | 21509 | 31744 | 31663 |
| DVP426… | 2 | 610000 | 610000 | none | none | 605000 |

Nearly every transaction paid more than the 5000-lamport base fee (112 of 114).

## Limits (read before using)
- Observational and survivorship-biased: these transactions landed. They do not show the fee needed to win a slot or to be included.
- Three pools, one day: the sample is tiny and the age bins hold a handful of points (some are empty). No inference about a pool population.
- **Not** a recommendation: no execution default, latency assumption, risk limit, threshold or sizing was changed.
- A small gap between implied priority (price x limit) and paid fee is possible because the limit is a cap, not usage; the report only counts the case where paid fee is below the implied priority (0 here).
