# Can genuine Master inputs be reconstructed causally from LaunchLab TradeEvents?

Status: offline audit, nothing executed. No Master was run, no score, strategy parameter or capital changed.

## References reviewed (read-only)

- Decision engine `SignalFeatures`, `bot/p4_experiment.py` `_features`, `bot/master_decision.py`: branch `feat/prepurchase-bitquery-official-sample-proof-20261102` (PR 88 head, ancestor of PR 89 `cf9a084`) at `ce0f76d2353c93fe7c5b73a3e6576b483c09d6d2`. On the integration branch these files are present unchanged.
- TradeEvents and fixtures: `claude/launchlab-trade-events` at `4f2875d943f970983ee6198cc35931c3f31d380d`.

Inventory and classification live in `tools/master_feature_inventory.py` (`python tools/master_feature_inventory.py`).

## Result (demonstrated by code and test)

Revision 2026-11-03 (integration review): `depth_usd` reclassified from DERIVABLE_FROM_TRADE_EVENTS to NEEDS_EXTRA_READS. Its SOL capacity is exact, but the field is USD and needs a rate absent from events. Counts changed from 14/5/15/3 to 13/5/16/3.

| Class | Count | Meaning |
|---|---|---|
| DERIVABLE_FROM_TRADE_EVENTS | 13 | Needs only decoded events (prices in SOL, windows, fee rate, slippage at a fixed size, same-slot wallets, buy/sell counts). |
| DERIVABLE_WITH_TRANSACTION_DATA | 5 | Needs full transactions: mint, creator, dev sales, relay transfers, relevant transactions. |
| NEEDS_EXTRA_READS | 16 | Token-account scan, creator history, cross-pool wallet graph, USD rate (including `depth_usd`), windows longer than pool life. |
| UNKNOWN | 3 | `quote_count`, `market_data_quality`, `quote_source`: defined by an external market source, not by chain events. |

Key findings:

1. **No USD field is reconstructible from events.** Events carry SOL amounts. `price_usd`, `liquidity_usd`, `depth_usd`, `market_cap_usd`, `fdv_usd`, `funding_usd` and the 5 min / 24 h USD volumes need a SOL/USD rate that is not in the data. `price_usd` and `liquidity_usd` are mandatory in `_features`, so a genuine Master frame cannot be built from events alone.
2. **The committed fixtures cannot feed any windowed feature.** The three pools span 16, 31 and 29 seconds. `momentum_60s`, `momentum_300s`, `price_change_5m_pct` and `price_change_1h_pct` must be `None` there, not 0; `tx_buys_5m` and `tx_sells_5m` are partial-window counts, not 5 min values. Only **7** `SignalFeatures` are fully computable on these fixtures (`signal_time`, `observed_at`, `fee_bps`, `slippage_bps_est`, `bundle_transactions`, `bundle_wallets`, `same_slot_wallets`), plus 2 partial counts (`computable_on_span`, tested). Any Master run on these fixtures is a truncated Master and must be labelled as such.
3. **Holder, wallet-graph and creator-history inputs are not in the data.** Defaults (`holder_count=0`, `linked_wallets=0`, `wallet_link_count=0`, `wallet_graph_transactions=0`, `holder_data_known=False`) look like observations but are absence of information. Treating them as zero would bias risk checks toward "clean".
4. **Frame timing is local, not chain.** `available_at_ms` and `slot_available_at_ms` are receipt times; a replay can only assume a latency (2 slots, unverified).
5. **`independent_buyers` has no event definition.** Distinct `fee_payer` is only an upper bound.

## Lookahead risks

- A USD rate, creator history (`prior_launches`) or holder snapshot taken after the decision time leaks the future.
- Windows must end at the decision time; partial windows must be reported as unavailable.
- Slippage must use a size fixed before the decision, on the reserves of the last event at or before the decision slot.

## Conclusion

A genuine Master (all `SignalFeatures` plus frame timing and research evidence) is **not** reconstructible from committed TradeEvents. A subset can be (SOL-denominated price path, fee rate, curve depth in SOL, slippage at a fixed size, same-slot wallets). A Master run on that subset would be a truncated Master, and results must not be presented as the genuine one.

## Limits

Classification of some fields (relay transfers, bundle rules) depends on definitions in PR 89 that were read but not exercised. Not tested: any real RPC data.
