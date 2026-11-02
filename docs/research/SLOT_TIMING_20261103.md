# Seconds per slot, measured on the committed SOL pool archives

Source: `tests/fixtures/launchlab_sol_pools/*.json.gz` (signature listings: `slot`, `blockTime`). Code: `bot/market/timing.py`. Offline, no network.

## Result

| Scope | Distinct slots | Slot span | Seconds span | Seconds per slot | Quantisation bound |
|---|---|---|---|---|---|
| Pool 5pZ6Md... | 17 | 72 | 16 | 0.2222 | ±0.0139 |
| Pool C7F9Kb... | 53 | 145 | 31 | 0.2138 | ±0.0069 |
| Pool DVP426... | 2 | 136 | 29 | 0.2132 | ±0.0074 |
| All three merged | 64 | 181 | 39 | 0.2155 | ±0.0055 |

Pairs: 173 signature rows, 64 distinct (slot, block_time) pairs after deduplication. Measured range across pools: **0.213 to 0.222 s/slot** (about 4.5 slots per second). The usual textbook figure is about 0.4 s/slot; these archives show faster slots. Three short pools (each under 3 minutes) are a small sample: demonstrated by the code on this data only, not a general property of the network.

## Limits

- `blockTime` is a whole number of seconds, so each endpoint is off by less than 1 s. The bound is 1 / (slot span); per-interval rates between adjacent slots are meaningless (they come out 0 or 1).
- Pool DVP426 contributes only two distinct slots, so its figure is only an endpoint estimate.
- This is a property of the chain's clock. It is **not** a measurement of our own orders' latency, landing or inclusion.

## Replay latency assumption

`bot/market/replay.py` `ExecutionModel.latency_slots = 2`. At 0.213 to 0.222 s/slot this is **about 0.43 to 0.44 s** (at the textbook 0.4 s/slot it would be 0.8 s). The default is **not changed** by this note; a test pins it at 2.
