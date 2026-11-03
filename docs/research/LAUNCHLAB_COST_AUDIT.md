# LaunchLab baseline cost audit (offline, 2 entries)

Tool: `python -B tools/launchlab_cost_audit.py [--markdown]`. Source: the three committed SOL fixtures. Assumptions fixed by the baseline report: entry 0.05 SOL after the 3rd observed trade, exit after 30 slots, 2-slot assumed latency, each pool's inferred total fee rate. **This audits bookkeeping on two entries. It shows no profitable Master and no edge.**

## Results (lamports; demonstrated by code, reproduced by `tests/test_launchlab_cost_audit.py`)

| Pool | Fee rate | Entry in | Entry fee | Tokens out | Exit gross | Exit fee | Net received | Tx costs (2 tx, assumed) | P&L |
|---|---|---|---|---|---|---|---|---|---|
| 5pZ6Md… | 10000 ppm | 50,000,000 | 500,000 | 228,654,306,199 | 45,495,095 | 454,951 | 45,040,144 | 80,334 | -5,040,190 (-0.100642) |
| C7F9Kb… | 12500 ppm | 50,000,000 | 625,000 | 120,248,701,460 | 53,659,503 | 670,744 | 52,988,759 | 62,168 | +2,926,591 (+0.058459) |
| DVP426… | 18000 ppm | no entry (only 2 trades, baseline needs 3) | | | | | | | |

No pool migrated; no position was left open (no marked-not-executed liquidation); no counterfactual divergence.

## Separation of costs

- Curve input/output and curve fees (entry fee + exit fee) are exact integer curve arithmetic. The exit gross is recovered by inverting `net = gross - ceil(gross*rate/1e6)` (checked in tests).
- Network cost is **assumed**, not actual: median of other traders' successful fees in the pool (40,167 and 31,084 lamports), priority fee 0, applied to our entry and exit.
- Differences from the existing baseline report: none (spent, received, tx costs, P&L and net return match to 1e-9). The audit adds the leg decomposition, the fee-sensitivity and the explicit list of unknowns.

## Sensitivity: the sign of the second result depends on the network-fee assumption

If both our transactions paid the highest fee observed in the pool (2,205,001 and 5,005,000 lamports), P&L would be -0.00937 SOL and -0.00702 SOL. The +0.0029 SOL result flips to a loss. The observed fee range is wide (5,000 to over 5,000,000 lamports), so network costs are a first-order unknown.

## Not exposed by the current replay (reported, not invented)

Priority fee and compute-budget price; Jito or other tips; token-account rent (assumed refunded); WSOL wrap/unwrap; slippage tolerance and failed transactions; our own transaction fee (proxied by others' median); CPMM exit after migration.

## Limits

Two entries from three pools, all public data from one short window. No statistical conclusion is possible.
