# Rugger Bot — GO on Helius free research + Trawl quote, NO financial GO

Date: 2026-10-30. Branch: `fix/current-launchlab-migration-abi-20261030` (PR #48).

## Actions performed

1. Sent a **non-binding inquiry** to `contact@trawl.run` from the user's
   connected Outlook, asking for a free example, supported LaunchLab & CPMM
   fields, complete historical coverage, at-decision data, failed/closed
   pools, a free firm per-program quote and the smallest joint export.
   No x402 request, USDC payment or data subscription was made.
2. The earlier inquiry to `sales@bitquery.io` is still a separate
   alternative. Neither vendor has supplied a response in this run.
3. Added a **public-only** local evidence archive:
   `bot/p3/readonly_evidence_archive.py`. Emits canonical observation
   payload SHA256, action run ID, commit and UTC timestamp. Forbids
   private keys, bearer tokens, API keys and signed transactions.
4. Added a deduplicator `bot/p3/readonly_evidence_rollup.py` that counts
   each (pool, unverified creator claim) once across observations, preserves
   rejected S2 outcomes and NEVER upgrades historical readings to filled
   trades or profitability.
5. Updated **three** Helius read-only workflows to upload observations as
   per-run GitHub Actions artifacts (`paper_artifacts/`), 30-day retention,
   zero write permissions and no wallet or financial operations.
6. Prepared low-frequency schedules `17 */6 * * *` and
   `43 */6 * * *` on S1-capacity and historical-creation sampling workflows.
   **GitHub scheduled workflows execute only on the repository default
   branch. They are NOT active while PR #48 remains unmerged.** Avoid
   merging the entire stacked PR merely to activate monitoring without
   security and code review.
7. On the prior initial validation of the archive workflow, GitHub produced
   separate hashed evidence artifacts for the S1-capacity study and the
   historical LaunchLab sample. An artifact is proof of captured public data,
   not proof of a trade or creator independence.

## Historical source strategy

- **Helius Free:** official pricing describes 1M credits/month, standard
  websocket streams and read-only RPC. We are doing bounded calls, with
  no transaction submission. The free plan does not by itself guarantee a
  complete creation universe or historical pre-trade point-in-time coverage.
- **Trawl:** official October 2026 prices indicate $2/TB scanned at launch,
  $4 minimum/job, firm free x402 quote before payment, and separate
  Raydium LaunchLab and CPMM presets. Total price depends on the epoch
  range and the number of jobs, not on a generic "two scans = $8" promise.
  Vendor confirmation of exact coverage and post-migration continuation
  is required.
- **Bitquery:** another possible paid historical source. Compare
  coverage, fee/loss/error history and licensing before any purchase.

## Financial and evidence gates

To test the Master Trader vs reference economically, we still require:
a contiguous historical/prospective LaunchLab creation cohort including
failures and defunct pools, independent creator-confirming signed records,
all live-available decision features and identical decisions recorded
BEFORE observing outcomes, exact BUY and SELL lot quotes and all fees,
migration→CPMM pool mapping and post-migration exits, a creator-disjoint
held-out sample of 50+ creators, blocked/unknown exits accounted as losses or
unknown under a declared censoring policy, and positive cost-adjusted
out-of-sample advantage with defensible statistical uncertainty.

Active-pool scans introduce survivorship bias and free sample tables are
independently truncated; neither is a valid stand-in for that dataset.
No income or trading profitability can be honestly certified yet.

`LIVE_READY_TO_ARM=false` ; `ECONOMIC_EDGE_VALIDATED=false` ;
`LIVE_EXECUTION_VERIFIED=false`. No real funds involved.
