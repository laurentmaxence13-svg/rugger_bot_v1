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

**Reconciled reference (Solana Foundation).** The official Solana network-upgrade record confirms that the target mainnet slot duration changed from 400 ms to **200 ms** at epoch 1053 on **2026-10-09**: https://solana.com/upgrades/reduced-slot-times . The observed 0.213 to 0.222 s/slot is therefore *compatible with* the current ~200 ms target; comparison with older 400 ms documentation was inappropriate. This does **not** establish a network-wide realized slot average, nor the latency, landing position or inclusion time of any Rugger Master order. This is a narrow historical sample (three pools, each under three minutes) based on integer-second `blockTime`. The measured 0.2155 s/slot is an empirical span estimate, not a protocol parameter. Alpenglow's roughly 150 ms target *finality* is a different quantity from slot duration: https://solana.com/upgrades/alpenglow .

## Limits

- `blockTime` is a whole number of seconds, so each endpoint is off by less than 1 s. The bound is 1 / (slot span); per-interval rates between adjacent slots are meaningless (they come out 0 or 1).
- Pool DVP426 contributes only two distinct slots, so its figure is only an endpoint estimate.
- This is a property of the chain's clock. It is **not** a measurement of our own orders' latency, landing or inclusion.

## Replay latency assumption

`bot/market/replay.py` `ExecutionModel.latency_slots = 2`; the default is **not changed** by this note and a test pins it. Conditional arithmetic only: two slots at the historical observed span rate amount to about 0.43 to 0.44 s, and two slots at the *current target* 0.20 s amount to 0.40 s. **Neither figure measures bot execution latency**; the replay's two-slot assumption remains unvalidated. Do not replace a latency model with a network slot-duration measurement.

## Next check (not run)

**Optional independent timestamp check**, not required to confirm the already-official 200 ms upgrade: compare archived `blockTime` with `getBlockTime` for matching historical slots if the providers retain those slots, and investigate timestamp provenance or systematic bias. A fresh-slot comparison instead validates current provider timing, not the historical archive. Previously proposed budget: 5 slots x 2 providers plus one `getSlot` per provider (12 RPC calls). Only run with explicit owner authorization and an appropriate free RPC budget; no RPC is called by this note.
