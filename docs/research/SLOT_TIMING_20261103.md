# Seconds per slot, measured on the committed SOL pool archives

Source: `tests/fixtures/launchlab_sol_pools/*.json.gz` (signature listings: `slot`, `blockTime`). Code: `bot/market/timing.py`. Offline, no network.

## Result

| Scope | Distinct slots | Slot span | Seconds span | Seconds per slot | Quantisation bound |
|---|---|---|---|---|---|
| Pool 5pZ6Md... | 17 | 72 | 16 | 0.2222 | ±0.0139 |
| Pool C7F9Kb... | 53 | 145 | 31 | 0.2138 | ±0.0069 |
| Pool DVP426... | 2 | 136 | 29 | 0.2132 | ±0.0074 |
| All three merged | 64 | 181 | 39 | 0.2155 | ±0.0055 |

Pairs: 173 signature rows, 64 distinct (slot, block_time) pairs after deduplication. Measured range across pools: **0.213 to 0.222 s/slot**. These are the numbers computed from the archives, nothing more.

**Unexplained discrepancy.** The sources checked give a slot time of about 400 ms (for example https://www.helius.dev/blog/alpenglow). The measured 0.213 to 0.222 s/slot contradicts that, and **its cause is not established**. It must not be read as a property of the network. Candidate causes, none verified: the `blockTime` clock of the RPC provider; a protocol change not confirmed on an official page; sampling (three short pools, each under 3 minutes).

## Limits

- `blockTime` is a whole number of seconds, so each endpoint is off by less than 1 s. The bound is 1 / (slot span); per-interval rates between adjacent slots are meaningless (they come out 0 or 1).
- Pool DVP426 contributes only two distinct slots, so its figure is only an endpoint estimate.
- This is a property of the chain's clock. It is **not** a measurement of our own orders' latency, landing or inclusion.

## Replay latency assumption

`bot/market/replay.py` `ExecutionModel.latency_slots = 2`; the default is **not changed** by this note and a test pins it. Conditional arithmetic only, **unvalidated**: if the measured rate were correct, 2 slots would be about 0.43 to 0.44 s; at 0.4 s/slot it would be 0.8 s. Because the discrepancy above is open, no seconds figure should be used for the replay.

## Next check (not run)

Cross-check `blockTime` against `getBlockTime` for a few recent slots on two independent RPC providers. Proposed budget: 5 slots x 2 providers = 10 `getBlockTime` calls (plus 1 `getSlot` per provider, 12 calls in total). Needs the owner's approval of the providers and budget; no RPC is called by this routine.
