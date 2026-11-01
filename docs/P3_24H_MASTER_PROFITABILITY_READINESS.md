# Rugger Bot — 24h prospective PAPER: strict go/no-go (2026-11-01)

## Status

**NO-GO for an exact Master profitability verdict.**

A duration of 24 hours cannot turn incomplete source events, missing simulated fills,
invalid migration routes or non-independent candidates into an exact economic return.
The existing 24h supervisor is a *sampled-market source readiness experiment*,
not a complete economic simulator. It must NEVER authorize live trades.

## What the new 24h sampled supervisor does

- Registers **one immutable 24h UTC horizon**, the exact Git revision, a separate
  strict LaunchLab-only research protocol and a finite request cap.
- Schedules 96 local **15-minute sample windows**, with each bounded P3 collection
  limited to 60 seconds and 20 public read-only calls.
- Captures the same initial and follow-up pool reserve snapshots per sampled cohort.
- Freezes actual Master and reference shadow decisions *before* S2, with missing
  authenticated features represented as missing, and preserves all WAITs.
- Saves all four preset 0.05/0.10/0.25/1 SOL LaunchLab research sizes **before** S2.
- Records conditional S1→S2 curve markouts, failures and full denominators
  separately from executable fills/P&L.
- Publishes independent, hash-chained SQLite captures, local SHA-256 file
  integrity records, periodic progress, network/request gap evidence, caps
  and explicit incomplete statuses. Restarts use **--resume** without
  overwriting previous local captures or replaying missed windows.
- Stops on a changed Git revision, exhausted request cap or repeated failures.
  A failed/incomplete worker reserves all 20 possible requests from the quota.
- Records **no executable buys/sells, no filled inventory, no realized profits,
  and no actual Master-reference net edge**.

**Limitations:** 96 snapshots are NOT continuous event or swap capture.
An observed 15-minute gap can hide a launch, manipulation, migration, exit
or liquidity shock. The availability of a curve model is not evidence of a
trade executable at that price. Hashed captures prove *local consistency*,
not independent blockchain authenticity.

## Read-only local commands (Windows PowerShell, in the isolated worktree)

Refresh tested branch:

```powershell
git fetch origin
git switch --detach origin/fix/p3-fail-closed-liquidity-screen-20261101
python -m bot.p3.observation24h --preflight
```

**Do not initiate the 24h test to prove exact profitability** before the
following gates are separately implemented and tested. For a separately
approved *observation-only* 24h run, the explicit, not-automatic command is:

```powershell
python -m bot.p3.observation24h --network --accept-observation-only --session-dir paper_artifacts\observation24h_trial
```

Monitor without network:

```powershell
python -m bot.p3.observation24h --status --session-dir paper_artifacts\observation24h_trial
```

After a confirmed interruption (and no other copy running):

```powershell
python -m bot.p3.observation24h --network --accept-observation-only --resume --session-dir paper_artifacts\observation24h_trial
```

Keep PC awake, on power, with sufficient storage and network. A closed laptop
or broken Web connection produces explicit missing windows, not backfilled
trades. No additional subscription or charge is automatically purchased;
provider billing/quota conditions have NOT been verified.

## Mandatory GO criteria for a real-like 24h Master/reference economic experiment

1. **Authenticated creator + inception:** Helius finalized raw transaction,
   Ed25519 signature verification, verified LaunchLab program instructions,
   pool/mint/platform identity and stable creation time, without reusing
   self-attested creator claims. Log hints alone are never creation proofs.
2. **Continuous causal signal feed:** trade-by-trade events and quote-clock
   provenance with durable reconnect/backfill plus explicit unfillable gaps.
   All usable S1 SignalFeatures must be computed from information available
   before each frozen decision.
3. **Two genuinely comparable policies:** run the actual Master and frozen
   reference over the SAME as-of tape, capital budget, entry/exit horizon,
   execution eligibility and evidence. Distinguish risk-policy WAIT from
   strategy NO-ENTRY; never inject future price into features.
4. **Phase-correct two-sided executable price:** LaunchLab curve buys and
   complete-sellability, then signed LaunchLab→CPMM migration identities,
   CPMM vault reserves, frozen source slot, phase-specific swap constraints,
   minimum outputs, slippage, ATA/Token-2022 limitations and route failure.
5. **PAPER fill/ledger mechanics:** explicit order delays, market impact of
   counterfactual buys/sells, actual source liquidity, transaction failures,
   priority/network/ATA fees, pool/platform/creator fees (no double-counting),
   position aging and mark-to-market of unclosed positions. Do not treat
   quote availability as a guaranteed fill.
6. **Creator-disjoint out-of-sample evidence:** at least the policy's
   minimum 50 qualified cycles and 20 independent creator groups for
   Master's internal gate; design for >=50 independently signed creators
   for the prospective evaluation cohort where feasible. These minimums
   do not ensure adequate statistical power, which must be assessed on
   observed outcomes and clustering.
7. **Auditable economic verdict:** net SOL per arm, active inventory,
   censored exits, fees, loss tails, fixed-capital exposure and paired
   Master minus reference with uncertainty intervals, preregistered
   eligibility, all rejections preserved, independent code review and
   replayable capture files. No exact expected profitability claim based
   on one 24h observation interval.

## Operational gate

Current state: **observational sampling infrastructure prepared**;
**economic proof gates 1–7 not independently passed**. The proper
result today is `NOT_READY_VERIFIED_NET_PROFITABILITY`.

No real on-chain transfers, wallet access, LIVE arming, paid API
plan purchase or credit card details are requested or authorized.
