# Rugger Master: continuity record

This file is the resumption point for every autonomous or human session. Each fact was verified against GitHub, a cloud run log or the local repository on the date shown. Anything not verified is marked as such.

Last update: 2026-11-02 23:28 UTC (2026-11-03 00:28 Europe/Paris), by the owner's supervised session.

## 1. Canonical state

| Item | Value |
|---|---|
| Default branch | `main` = `d9b950e4708a3d0fc9c955f852144ec1fd893867`. Never pushed by automation. |
| Coordination branch (where development accumulates) | `claude/launchlab-trade-events` = PR #90, draft, head `7bd4fad267cf4c5ee7669ce30f53000215f55b8c` |
| Protocol branch (read by the routines) | `claude/autonomy-framework-20261103`, stacked on PR #90, draft PR |
| Not merged, do not merge without owner approval | PR #88, PR #89, PR #90 |

PR #89 is stacked on the branch of PR #88 (`feat/prepurchase-bitquery-official-sample-proof-20261102`), not on `main`.

## 2. Verified checks

- **Offline suite on GitHub Actions, Ubuntu, Python 3.13.** Workflow `offline-tests.yml`, run `41544313745`, succeeded on `7bd4fad`: 1401 passed, 1 skipped, 242 subtests passed. No secret referenced.
- **Cloud validation run 1.** Routine `trig_01FCseiBnoeNVFPHggcy5DMA`, session `cse_016VkauDnhqSZRZYPCt53Q73`. Status PASS on Python 3.11.18, same counts. Report pushed to `claude/cloud-validation-20261103` as `6b82c05`, file `docs/cloud-runs/2026-11-03-validation-run1.md`. `main` identical before and after.
- **Local Windows runs** show 3 failures (SQLite file lock, symlink privilege, CRLF). They do not reproduce on Linux, so they are environment-specific.
- **Cloud connectivity, verified.** Clone, `git ls-remote`, fetch and checkout of a pinned SHA, and push to a `claude/` branch all work with the connected GitHub identity. No MCP connector is needed.

## 3. Scheduled tasks and triggers

All three routines are disabled. Connectors were removed from each. Automation never enables them.

| Name | ID | State | Notes |
|---|---|---|---|
| Validation (manual) | `trig_01FCseiBnoeNVFPHggcy5DMA` | disabled | Cron `0 6 * * *` is stored but inert. Expected: no run. Check that `last_fired_at` does not change after 06:07 UTC. |
| Dev agent (scheduled) | `trig_019Zqz5ax6uqmJQZKnKB2VVX` | disabled | Cron `30 1 * * *`, model `claude-sonnet-5-5`. Protocol: `docs/autonomy/DEV_ROUTINE.md`. |
| Independent reviewer (GitHub trigger) | `trig_01Xu5G5fnfE2Zq26232UbqE6` | disabled, no GitHub trigger attached | One-off date `2027-01-01T00:00Z`, model `claude-sonnet-5-5`. Protocol: `docs/autonomy/REVIEW_ROUTINE.md`. |

## 4. Owner actions pending

1. **Extra usage.** Open https://claude.ai/settings/usage and confirm that usage credits (extra usage) are OFF. Automation cannot read this setting.
2. **Helius schedules in PR #89.** Before merging #89, decide on two workflows that run every 6 hours once they reach `main`: `helius-launchlab-sampled-creations.yml` (`43 */6 * * *`) and `helius-s1-capacity-s2.yml` (`17 */6 * * *`). Both use `HELIUS_API_KEY`. Today nothing runs them: `main` has no cron file, and GitHub recorded no scheduled run.
3. **Protection of `main`.** The GitHub API returns HTTP 403 for branch protection on this private repository without GitHub Pro. Without it, the only guard is the routine prompt, and the connected identity is the repository administrator. Decide: accept this residual risk, or approve GitHub Pro, which is a paid service.
4. **Claude GitHub App.** Install it on the repository if it is not already. Required before a GitHub trigger can be attached to the reviewer.
5. **Activation.** Approve or refuse activation of the dev agent and of the reviewer, after reading their protocols. Nothing is activated before that.
6. **Cleanup.** Optionally delete the validation routine at https://claude.ai/code/routines. The API cannot delete routines.

## 5. Backlog (ranked, one bounded pull request each)

1. **Slot timing from archived block times** (offline). Convert the replay's 2-slot latency assumption into seconds, using the spread observed in `data/launchlab_trades`. Acceptance: a test and a short note.
2. **Compare the Master decision on archived pools** (offline). Adapt the decision logic from PR #89 to the replay engine, with the same costs and timestamps. Acceptance: a reproducible report, labelled INSUFFICIENT_DATA unless the evidence supports more.
3. **Offline gate with warnings as errors.** Run the suite with `-W error`, as the repository's documented resume command does. Fix only real warnings. Acceptance: green run on the coordination branch.
4. **Legacy copies: document, do not delete.** `bot/bot/` and `tests/tests/` must not be deleted without demonstration (AGENTS.md).

Blocked, needs an owner decision: a broader LaunchLab sample (requires an RPC budget), and any merge order for PRs #88, #89 and #90.

## 6. Rules every session follows

- Never merge. Never push to `main`. Never force-push. Never delete a branch or a pull request.
- No secret is read, printed or committed. No Helius, RPC, market, price or trading API is called by tests or routines without an owner-approved budget.
- No signing, no transaction, no live trading, no spending, no change to the paid plan.
- A routine writes this file only inside the pull request it opens. One writer per branch.
- Each commit ends with a `Co-Authored-By` line naming the model that actually produced it.

## 7. Log

- 2026-11-02 23:17 UTC: PR #90 gains the offline test workflow (`7bd4fad`). The run succeeded.
- 2026-11-02 23:22 UTC: cloud validation run 1, PASS. Report on `claude/cloud-validation-20261103` (`6b82c05`).
- 2026-11-02 23:28 UTC: dev agent and independent reviewer created, both disabled, connectors removed.
