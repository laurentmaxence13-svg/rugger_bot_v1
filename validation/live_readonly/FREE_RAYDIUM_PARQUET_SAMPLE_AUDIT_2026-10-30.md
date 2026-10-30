# Rugger Bot — free Raydium Launchpad Parquet sample integrity and join audit
**Date:** 2026-10-30. **Source:** user-supplied `raydium-launchpad-free-samples.zip` (`sampleVersion=2026-09-08-v4`, 23 tables, up to 100 rows/table). **Status:** historical ingestion technically supported; P4 Master edge **NOT VALIDATED**, financial LIVE **NO-GO**.

## Audited data and reproducible joins

ZIP manifest byte-size + SHA256 checks for **23/23 Parquet files** passed.
The Parquet sample uses ZSTD dictionary-compressed pages and typed timestamps/slots, explicit signatures, fees, event payloads, program role addresses and pools. A restricted local Parquet decoder extracted and compared simple top-level fields without inventing missing values.

- `pool-create-event`: **100 records**, **100 pools**, **76 distinct creator claims**.
- By exact signature **and** `pool_state`, **100/100 creation events** link to `initialize-v2` (2) or `initialize-with-token2022` (98).
- `trade-event`: **100 records**, **66 Buy and 34 Sell**, across **34 pools**. It includes four explicit protocol/platform/creator/share fee fields.
- Joined instruction→TradeEvent by signature, pool and direction: **92 matches** (**58 BUY, 34 SELL**). Source tables individually sampled: do not treat unmatched rows as invalid or trades as missing on chain.
- Joined historical BUY→SELL with the **same payer, pool**, increasing slot, and event-receipt matches: **two pairs**. **One** has identical bought and sold atomic token units; **one** sells roughly 98.01% of the earlier bought quantity.
- A source-sampled difference in SOL legs is not reliable realized P&L until network fees, any other transfers or trades and TradeEvent fee inclusion have been independently reconciled. Some positions may have existed before the sampled buy.

## Sampled paired trading events (source records)

| Source pair | Pool | BUY slot | SELL slot | Bought token atomic | Sold token atomic | BUY SOL reported | SELL SOL reported |
|---|---|---:|---:|---:|---:|---:|---:|
| Matched lot | `4B8fFhma9rW26qisMsb7bgwPUT1wZtV4hRt7ug8MaRbc` | 445316414 | 445316611 | 33207397256443 | 33207397256443 | 0.096987772 | 0.109827011 |
| Partial lot | `2LGqW7dj2rQtTRwLzUBKRNgxQ5m9eD8VtJJoKToPe6zN` | 445316568 | 445316589 | 25873956133366 | 25359064406311 | 0.080474356 | 0.084059924 |

**Crypto evidence:** four pinned transactions verified independently by Helius with **exact compiled-message Ed25519 signatures, finalized source claims, exact slots, public pool account, claimed payer in the signed account set**:
https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41078730561

The verification did **not** independently parse event amount log bytes or prove the transaction full net native-SOL delta. It does **not** imply a strategy decision by Rugger Bot or operator approval.

## What this sample cannot validate

1. The per-table 100-row cuts are sampled independently and cover **different time ranges**. The event subset is not the complete trading universe. Matching creation rows out of 100 is *schema/linkage validation*, not a prospective complete creator cohort.
2. Although 76 creator addresses exist in `pool-create-event`, these do not satisfy the **50 independent creator holdout** criterion. Source coverage and temporal, creator-disjoint partitioning have not been established.
3. There is a `migrate-to-cpswap` instruction sample but no associated CPMM BUY/SELL market-history tables. The sample **cannot track actual exits after graduation**.
4. Neither complete available-at-decision features, strategy health/latency measurements nor Master-vs-current-engine decisions are present. Consequently **a proper P4 comparison cannot yet be run**.
5. The two source-matched historical pairs are not a representative performance sample. Favorable examples, selected a posteriori, cannot establish edge. Additional trades or holdings may be absent from the ZIP.

## Paid-data purchase gate

**Do not purchase a LaunchLab-only historical export on the assumption that CPMM exits are included.** Request a narrowly scoped, ideally free, *contiguous* test time window with all creations (including failed/closed), trade events and instruction receipts, signed transaction IDs, pool/creator identities, fee and balance details, and post-graduation CPMM swaps. Verify availability of that exact schema and the right to replay/research it before accepting pricing.

The sample **passes** integrity, basic joins, and four onchain signature checks. It does **not** pass comprehensive economic ledger, true 50-creator holdout, post-migration exit coverage, net profitability, or live authorization.

`LIVE_READY_TO_ARM=false` · `ECONOMIC_EDGE_VALIDATED=false` · `MASTER_VS_BASELINE_OOS_VALIDATED=false` · No real orders.
