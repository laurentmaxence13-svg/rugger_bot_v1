# $50 Bitquery historical data — Rugger Master pre-purchase evidence gate (2 Nov 2026)

## Decision scope
The owner authorizes research and PAPER only, NOT any financial order or payment.
The merchant has offered a custom one-time $50 Raydium LaunchLab + CPMM 24–48h export. No invoice paid, and no keys or cards shared. Do not mistake the custom sales proposal for an automatically available subscription or historical profitability proof.

## Real verified checks (not simulated)
1. Existing private repo source already audited 23/23 separately sampled LaunchLab Parquet tables (2026-10-30); none contained an unambiguous SOL-denominated same-wallet BUY→SELL trajectory suitable for Master.
2. Official live vendor public Parquet links, four tables, **actually downloaded and parsed** on [GitHub Actions #41497563095](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41497563095). Repeated and checked with atomic-value intake in [#41498355220](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41498355220). Program IDs matched and transaction signatures were present.
3. Exact sampled values: LaunchLab trades 745 rows and pools 745 (slots 423635600–699), CPMM trades 70 and pools 70 (slots 423500008–099); each trades file has 82 vendor columns, each pools file 64. **Direct SOL-quoted trades: 0 LaunchLab vs 60 CPMM.** These are DIFFERENT 100-slot windows, not a continuous 48-hour cohort or a linked migration.
4. Observed `Block_Time` in these free files is **June 1, 2026**, despite the vendor page's more recent sample-update publication label. Treat the records' actual slots and time as authoritative, not the sample-file update date.
5. The code `bot/p3/bitquery_atomic_finance.py` performs exact Decimal→integer lamport/token conversion, refuses floats, nonfinite values, fractional atoms, wrong programs, unqualified SOL legs, and claims zero genuine Master orders. In the **actual free CPMM sample**, `Transaction_Result_Success` is **VARCHAR literal `"true"`** (not the published Boolean type), and some reserve decimals are `VARCHAR`; the intake now requires exact recognized `true`/`false` strings and never relies on truthiness. On [vendor sample CI #41499795823](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41499795823), **20/20 sampled direct-SOL CPMM source records** passed strict atomic normalization. They are source-reported historical DEX rows, not the Master’s own fills.
6. A different, genuinely prospective free public Solana campaign [#41497727289](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41497727289) observed 300 program notifications, 1 native SOL signed creator, 2 frozen Master S1 WAIT decisions and **one** conditional S1/S2 quote-only pair. One sidecar conditional difference was +16,350,186 lamports before unknown fees and availability. **Actual Master PAPER BUY=0, SELL=0, independent executable quotes not established, P&L=NULL.**
7. Read-only Render Master diagnosis is independently [HTTPS verified](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41494384478), but returns `SIGNED_OBSERVER_DISABLED`. The running Render service does NOT have an authorized live Helius signed capture configuration or build dependency installation. GitHub prospective bounded captures are NOT a 24/7 paid-service substitute.

## Vendor confirmation required BEFORE $50 purchase
- Invoice explicitly says full, contiguous **2026-10-28 00:00 UTC to 2026-10-30 00:00 UTC**, all four tables (`raydium_launchpad_trades`, `raydium_launchpad_pools`, `raydium_cpmm_trades`, `raydium_cpmm_pools`), plus how token initialization events and creator signer/migration identities are supplied. Official swap/reserve tables by themselves do not guarantee independently verifiable creation ancestry.
- Migrations near the 48-hour boundary need at least 24h of extra **post-graduation CPMM swap/reserve history**; if not included, report the limits and any price separately.
- **SOL-quoted eligible population counts** specifically for the dates requested: how many direct WSOL launches, distinct verified creator signers, and eligible quote-mint-matched CPMM continuations? Total 8,600 launches or 1,000 migrations does not establish that many are SOL-quoted or tradeable by our engine.
- Delivery via **Cloudflare R2 without additional egress/Requester Pays S3 transfer bills**, JSON manifest, per-file SHA256, coverage and gaps. Vendor website shows that ordinary S3 deliveries may incur AWS charges for buyers.
- Clear protocol/platform/creator/transfer/priority/network/ATA fee fields, failure status, token transfer restrictions and potential missing records. Do not assume `Transaction_Fee` alone includes every execution cost.
- Realizable historical data-at-decision `SignalFeatures` and S1 timing are NOT guaranteed by 82+64 source columns. Venue swaps and reserves can support historical markouts, but cannot alone reconstruct anti-rug wallet history, private WebSocket latency, submitted/failed execution, independent exact-lot quotes and unavailable metadata. Any missing feature is marked UNKNOWN, never imputed to make the Master trade.
- Obtain the secure checkout link and review terms before paying. **No new spend authorized automatically.**

## Research/acceptance contract once delivered
1. Download only approved vendor HTTPS endpoints; verify hashes/manifest, timestamps/slots, known programs, four complete tables and any explicit trailing CPMM history.
2. Reject truncated/filtered creation universes, ambiguous identities, non-SOL quotes, missing failed events, overlapping/double-counted multi-instruction fees, negative/invalid amounts, binary floating-point rounding and nonchronological joins.
3. Independently verify a bounded, prespecified set of source-signed creations and migration mappings through finalized receipts; preserve creator-disjoint cohort and blocked transactions.
4. Freeze original Master/reference decisions with strictly historical available-at-S1 feature clocks. Missing features => WAIT/NO_TRADE. No forced decisions based on S2.
5. Only if executable own-entry and exact-lot own-exit costs can be conservatively reconstructed, use the actual PAPER ledger with token decimals, fees, failed orders and censored holdings; report P&L in lamports and distinguish historical counterfactuals from executed fills.
6. Admission requires >=50 qualified economic cycles and >=20 independent creators and genuine out-of-sample Master superiority, with uncertainty reported. A $50 export **may still fail** those gates.

## Safety flags
`MASTER_NET_PROFITABILITY_VALIDATED=false`
`FINANCIAL_ORDER_SUBMITTED=false`
`LIVE_TRADING_ENABLED=false`
`BITQUERY_50USD_PAID=false`
`OUT_OF_SAMPLE_MASTER_EDGE_VERIFIED=false`

This document is evidence and an explicit purchasing decision gate, not financial advice or a promise of a positive return.
