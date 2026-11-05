# Prospectively registered PAPER cohort — 1 November 2026

**Registration artifact:** `validation/prospective/20261101_public_creator_holdout_protocol.json`
**First protocol Git commit:** `cd102ca803f2c173fa0f4681a65038bf33c170a2`
**Earliest eligible decision:** strictly **after 2026-11-01 06:00:00 UTC** (07:00 Europe/Paris).
All earlier launches, quotes and decisions remain exploratory/historical and **cannot** be reclassified as prospective holdout by rerunning this audit.

This is a **public PAPER-only methodological pre-registration**, not a GitHub-server attestation of the first eligible decision's clock. The offline checker `bot/p4/creator_disjoint_shadow_audit.py` enforces the protocol timestamp but cannot authenticate the Git server time or completeness of market observations. The first commit is an externally inspectable anchor. Do not change the protocol to fit outcomes; if a revision is necessary, create a new version and apply it only to later decisions.

## Admission and grouping

1. Keep every observed LaunchLab log signature, including uninspected, failed and non-creation events, with an append-only capture hash, window boundaries and reason for exclusion. A non-inspected signature is **unknown**, not verified negative. Count distinct signed creator public keys and mint–pool pairs separately; multiple mints from one creator are **one** creator group. This does not prove different keys belong to different economic actors.
2. A creator enters the *authenticated* denominator only after a finalized outer instruction has been cryptographically reverified against the exact signed transaction bytes, matching creator, mint, pool and creation slot. A provider's index `creator_claim`, a claimed timestamp or an upstream Boolean is not sufficient.
3. The public deterministic split is `SHA256(split_salt_sha256 + ":" + creator_public_key)`, first eight bytes mod 10. Buckets 0–6 are HOLDOUT (70%), buckets 7–9 DEVELOPMENT (30%). It must be assigned before any outcome, and **never** changed for a creator. The public salt makes assignments reproducible, but permits potential adversarial key grinding; this is a residual threat to independence and cannot be claimed resolved.
4. Capture a causal feature prefix with its first-seen local clock, source slot, source receipt hash, source provider time and any delayed availability separately. Invoke **actual** Master and reference scorers on the same prefix before S2. Freeze their actions, policy hashes and the exact 0.1 SOL hypothetical lot; record the hash and commit/Actions artifact independently of future S2. A reference score intent is not an operationally admitted order.
5. At S2 (within 300 seconds) retain exact-lot BUY/SELL public quote provenance, source slots, availability clocks, token decimals, pool state, route and program IDs, migrations, unsupported extensions and reasons an exit could not be obtained. Record wallet/network/priority/ATA/route costs and failed-attempt costs separately. **Unknown is null, never zero.** A provider quote is not an executable fill.
6. Preserve OPEN_UNPRICED, FAILED_EXIT, MIGRATED_NO_QUOTE and MISSING_FOLLOWUP as censored positions. Report hypothetical entry notional at risk **for each arm**, complete-case conditional returns separately, and missing/censored denominator. Never compute a net winner by dropping censored positions.

## Economic decision rule

Require at least **50 independently authenticated holdout creator groups**, **50 complete and independently evidenced economic cycles**, a prospectively anchored denominator, no future features, and an explicit executable cost model. Compare Master versus reference on identical eligible observations and horizons, including no-trade decisions. A positive *conditional* quote markout does not prove an executable net edge; zero live orders mean realized net P&L and real Master-minus-reference advantage remain **null**. No strategy activation or LIVE gate change is authorized.

**Known evidence before registration:** three distinct public creator IDs across archived sources (two pinned finalized and one Helius prospectively captured, not cryptographically replayed in the cross-source join); zero complete economic Master/reference cycles; no validated positive net advantage. Those IDs are **not** prospective holdout entrants under this protocol.

## Verification commands (read-only)

`python -m pytest -q tests/test_cross_campaign_signed_cohort.py tests/test_cross_source_creator_overlap.py tests/test_p4_creator_disjoint_shadow_audit.py`

`python -m bot.p4.creator_disjoint_shadow_audit --protocol validation/prospective/20261101_public_creator_holdout_protocol.json --records <future_frozen_records.json> --output <fresh_report.json>`

The latter command must **not** be run on older archived records as evidence of future holdout profitability. No paid provider query or financial order is part of this protocol.
