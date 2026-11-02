# CLAUDE — Rugger Master PAPER continuation (2026-11-02)

This is a verified, safety-first handoff for the **private** repository
`laurentmaxence13-svg/rugger_bot_v1`. This file is not an authorization to
execute any blockchain transaction, access secrets or buy a subscription.
Read `AGENTS.md`, `LIVE_READINESS_MANDATE.md`, and the actual current code.
Where they conflict, the current owner mandate is: **PAPER only, no financial
mainnet orders, no merge to main, no key disclosure, no payment**.

## Proven code and CI checkpoints

- Signed LaunchLab research: PR #56 (OPEN/DRAFT, **not** a proven Master
  trade); https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/56
- Render signed Helius source: PR #64 merged **only into the Render feature
  branch**, not `main`;
  https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/64
- Stacked Render hardening PRs #65–#72 are OPEN/DRAFT. Their commits are not on
  the service branch's latest deployed commit.
- PR #73 adds the read-only signed-source build preflight, passing isolated
  CI #41403748899: 3,772 passed / 1 skipped / 242 subtests.
  https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/73
  https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41403748899
- PR #74 adds a separate **NO-GO** Master PAPER readiness API/panel and
  offline safety tests. Verify its **latest** CI/head SHA before relying on it:
  https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/74
- The pre-existing signed integration
  `bot/live/helius_signed_master_paper.py` intentionally freezes
  WAIT/NO_TRADE and does not implement genuine Master BUY/SELL fills.
  Its `PaperLedger` is read-only and cost-aware but currently has zero
  genuinely qualified executed Master PAPER cycles.

Never infer profitable/operational execution from thousands of unit tests,
conditional reserve models, observed DexScreener trades, or a Render HTTP 200.

## Operational state (verify again on handoff)

Existing Render service:
- Name: `rugger-master-readonly`
- Dashboard: https://dashboard.render.com/web/srv-dbjplme7bikc7386ug20
- URL: https://rugger-master-readonly.onrender.com
- Branch deployed: `feat/render-readonly-master-service-20261101`
- Deploy: `de73d4d86a308889ae2c799743a843f55c5d4bf2`, last verified live.
- Configured build command: `python -m compileall -q render_status_service.py`
- Start command: `python render_status_service.py`
- Auto-deploy: OFF; Render Free; may sleep and loses ephemeral state.
- **Critical deployment dependency**: The reviewed #73/#74 build helper is
  NOT on the currently deployed branch. Changing only the build command
  would fail; the service must also point to a reviewed feature branch
  containing that helper, or a separately reviewed deployment branch.
- Proposed build command, *only after reviewed branch selected*:
  `python -B -m bot.ops.render_readonly_build`
- The available Render connector cannot edit an existing service's
  build command or branch. Do not claim this has been performed. Do not
  trigger a redeploy of the old unchanged branch as a substitute.

Separate Vercel project:
- `rugger-wallet-master` is a DIFFERENT deployment/project from Render:
  https://rugger-wallet-master.vercel.app
- Project ID: `prj_3T2oHr5FHyyMkfcx7DstRIt3XKZQ`
- Latest inspected production deployment READY:
  `dpl_8v4BjRJELd1Kp4RXjgHwJ59DBRt1`.
- Deployment tree includes `src/terminal/index.html`,
  `src/index.html`, `src/paper/app.js`, `src/api/paper-feed.js`.
  These files are NOT in the GitHub repository root tree. Changing
  `render_status_service.py` does **not** automatically update this
  independently deployed Vercel terminal. Audit its actual integration
  before claiming the user sees the new readiness panel in Rugger Wallet.
- Render's existing CORS origin is
  `https://rugger-wallet-master.vercel.app`; only GET is permitted.
  Never put `HELIUS_API_KEY` into public Vercel assets.

## Actual source and boundaries

- `render_status_service.py`: HTTP UI + `/api/status` (DexScreener
  experimental PAPER) + `/api/helius` (signed read-only observer).
  On #74 additionally `/api/master-readiness`: strictly a NO-GO report.
- `bot/ops/render_readonly_service.py`: bounded signed-source runner,
  source sanitization, freshness and safe refusal. OFF by default.
- `bot/ops/render_master_readiness.py`: source-specific NO-GO diagnostics
  only, NEVER a trade or readiness assertion.
- `bot/ops/render_readonly_build.py`: explicit opt-in requirements install,
  Ed25519 import and read-only pipeline import, then compilation. No network
  market capture in the build preflight itself (package installation uses
  Python package index).
- `bot/ops/render_readiness_http_smoke.py`: **opt-in**, three bounded GETs
  to the existing public Render service (`/healthz`, `/api/helius`,
  `/api/master-readiness`) with strict NO-GO consistency checks. Without
  `--network` it does not request anything. It never contacts Helius.
  Manual one-shot command **only after safe deployment**:
  `python -B -m bot.ops.render_readiness_http_smoke --network`.
  A PR-labeled one-shot GitHub Action is also available via label
  `run-render-master-readiness-smoke-once`; do not apply before deploying
  the matching reviewed branch or the old Render API will return 404.
- `bot/live/helius_signed_master_paper.py`: signed creation + S1/S2
  evidence capture, paired shadow WAIT, hashes, no actual fills.
- `bot/p4/live_like_paper_ledger.py`: exact lot, causal independent quote,
  fee & migration checks, dual Master/reference books. The existence of a
  ledger is not an executed Master buy or sell.
- `bot/p4/native_asof_signal_bridge.py` and
  `bot/p4/master_research_paper_intent.py`: causal feature bridge and
  research-only intent; research intents are NOT operational Master orders.
- Existing PR #56 explicitly documents missing causally complete
  SignalFeatures, exact independently executable BUY and SELL quotes,
  verified migrated CPMM sell routes, a representative qualified cohort,
  and genuine Master economic edge.

## Safe priority sequence

1. Re-check #74 current head, diff and GitHub Actions. Fix any offline
   regressions in its own branch, keep DRAFT. Run:
   `python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error`
   This harness copies safe code to a disposable directory; do not read .env,
   keys, SQLite user data, or change the test isolation allowlist casually.
2. Re-check the precise Render and Vercel deployment metadata; explicitly
   distinguish a proposed branch from actual deployment. Do not change
   Render config or Vercel production until safe review and authorization.
3. Verify read-only source prerequisites and signed provenance on an
   isolated test environment first. Live network sampling requires an
   explicit, quota-bounded protocol and existing provider rights; never
   assume free unlimited Helius credits or access. No paid provider.
4. Capture actual causal LaunchLab SOL quoted seven-account graphs and
   independent signed receipts; reject unknown creators, mint supply
   inconsistencies, missing clocks, missing platform accounts, non-SOL
   quote pairs, and migration uncertainty. A signed creation alone is
   NOT a qualified Master signal.
5. On separately reviewed PAPER-only code, connect complete as-of
   `SignalFeatures` to the **unchanged genuine Master decision
   and reference policy**; freeze decisions before the outcome. Do not
   force ENTER or relax anti-rug gates to make the bot appear active.
6. Only if a genuine Master ENTER occurs with admissible evidence, feed
   the exact-lot dual-arm `PaperLedger` a same-size, independently
   time-stamped entry quote and full fee evidence. Observe SELL via
   verified curve or signed CPMM migration, freeze the true exit logic,
   reconcile inventory, costs and net result. Keep incomplete cycles
   censored, edge/P&L NULL until actual valid closed pairs.
7. Display those **actual Master PAPER** states in the independent
   Vercel Rugger Wallet project, with evidence provenance and stale
   flags, distinctly from DexScreener simulation. Persist audit receipts
   on durable, approved storage before claiming 24/7 operation; Render
   Free ephemeral disk cannot establish it.
8. Compare Master/reference on paired, causally fair out-of-sample
   observations, including actual costs. No claim of profitability from
   simulated fixtures, conditional overlays or unqualified survivors.

## Exact go/no-go acceptance

- A new independently signed SOL-quoted LaunchLab creation or a suitably
  qualified historical replay, supported by reproducible receipt artifacts.
- Genuine Master and reference S1 decisions fixed before S2; no leakage.
- A genuine non-forced Master ENTER, an exact-lot PAPER BUY and a costed
  SELL on admissible quotes; if the policy properly abstains, record WAIT
  and keep the milestone NOT VERIFIED.
- Fully traceable Master cash/inventory/P&L and provenance, all on-chain
  activity **read-only**; no swap submission, no signer.
- Vercel Wallet visually displays only the genuine Master records under
  the Master label, with DexScreener clearly experimental.
- All CI green on the exact head commit. Branches remain DRAFT and
  unmerged unless owner explicitly changes the mandate.

## Working contract for Claude

Work in a separate branch based on the **latest reviewed stacked PR**,
not `main`. Review and test every change. Open a draft PR and verify its
GitHub Actions. Report only exact commit SHA, PR URL, CI URL/result,
measured evidence and the *next real blocker*. Keep the system in PAPER
NO-GO if source quality, money arithmetic or provenance is unproven.
Do not initiate real transactions, expose any key, alter risk gates for
convenience, subscribe to a service, or silently modify production.
