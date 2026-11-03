# LaunchLab exact-in curve parity (offline)

Tool: `tools/launchlab_curve_parity.py`. Tests: `tests/test_launchlab_curve_parity.py`.
Input: only the three committed SOL pool fixtures in `tests/fixtures/launchlab_sol_pools/`. No RPC, no new data.

## Method

For each decoded `TradeEvent` the tool classifies the event. It is **supported** when it carries no arithmetic violation, is exact-in, and the pool status is 0 (curve phase). Events rejected by the pool timeline (violations or another pool) are counted as unsupported. For supported events, output, fee and post-state reserves are recomputed from the signed pre-state with `buy_exact_in` / `sell_exact_in` and compared to the event as exact integers.

## Denominator and fee schedule

Denominator: `FEE_DENOMINATOR = 1_000_000` ppm. Fee is the ceil of rate times basis (buy: input; sell: gross output). Each pool keeps one exact total rate (the compatible interval collapses to a single value).

| Pool | SHA-256 of fixture (MANIFEST) | Rate ppm | Events | Supported | Unsupported | Matched | Mismatches |
|---|---|---|---|---|---|---|---|
| 5pZ6MdyX…Ldy2 | 975f9912…843f | 10000 | 11 | 11 | 0 | 11 | 0 |
| C7F9KbS3…SpC | dcbda4e4…9063 | 12500 | 100 | 100 | 0 | 100 | 0 |
| DVP426ot…4r | 3661667f…86fc | 18000 | 2 | 2 | 0 | 2 | 0 |
| **Total** | | | **113** | **113** | **0** | **113** | **0** |

Result: all 113 observed events in these fixtures are exact-in, in curve phase, and reproduced exactly (output, fee, post-state).

## Limitations

- Demonstrated only for these 3 pools and 113 events, one short window (about 16 to 39 s each). The sample is tiny and says nothing about profitability.
- The fee rate is taken from the manifest, which was itself derived from these same events; it is a consistency check, not an independent proof of the on-chain schedule.
- Exact-out instructions, pool status other than 0, migration-boundary buys and any event with violations are reported as unsupported, never approximated. None occur in the fixtures, so those branches are exercised only by synthetic unit tests.
- Parity of arithmetic says nothing about execution latency, priority fees, or MEV.
