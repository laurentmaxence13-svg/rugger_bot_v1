# Claude Code entrypoint — Rugger Master

**Read these documents first, in order:**
0. `PROJECT_STATUS.md` — **single source of truth** for the current state,
   PR graph, last tested results, blockers and owner decisions. Where any
   other document below disagrees with it, `PROJECT_STATUS.md` wins.
1. `AGENTS.md` — repository safety and development requirements.
2. `docs/CLAUDE_MASTER_PAPER_HANDOFF_20261102.md` — historical checkpoint
   (GitHub, Render, Vercel, CI) of 2026-11-02; not the current state.
3. `LIVE_READINESS_MANDATE.md` — development roadmap; no live transaction
   authorization follows from permission to develop live components.

## Current owner mandate

Advance the **genuine** Master to autonomous Solana PAPER observation and
eventually genuine costed PAPER BUY/SELL, visible in Rugger Wallet. Never
confuse the separate DexScreener demonstrator with a Master trade.

- No merge to `main`, no real blockchain orders, no LIVE arming.
- No reading/exposing credentials, no paid subscriptions, no unapproved
  provider quota usage, no changes to operational risk gates for convenience.
- Work on independent branches/PRs and verify CI before claiming success.
- If the Master abstains, record a real WAIT and the missing evidence;
  do not invent fills, positions or financial returns.
- Genuine operational Master entry has protected historical thresholds
  of 50 qualified economic cycles and 20 independent creators. Independent
  `MASTER_RESEARCH_PAPER` policy intents are NOT operational Master trades.
  Never lower the limits or relabel research/DEX fills to bypass them.

## Resume command

`python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error`

Read the exact current PR heads and deployment metadata rather than relying
on stale prose. The #73 build helper and #74 readiness panel are not on the
old Render branch. Render and Vercel are separate deployments. Make no
production change based only on passing unit tests.

In each update give: verified PR + SHA, GitHub Actions run/result, deployment
state, whether genuine Master PAPER BUY/SELL is proven, and next blocker.
