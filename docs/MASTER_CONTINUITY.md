# Rugger Master: continuity record (v2)

## Authority

- This file is authoritative **only** on branch `claude/autonomy-framework-20261103` (PR #91). Do not copy it to other branches. PR #90 deliberately does not contain it.
- Only the owner's sessions edit it. Routines never edit it.
- It is a **snapshot** written at the time shown below. The live state (branches, claims, corrections, checks) comes from git and GitHub. To see it, run `python tools/dev_state.py fetch` and `python tools/dev_state.py plan`, from the protocol branch.
- The backlog is `docs/autonomy/BACKLOG.json`, not this file.

## Snapshot: 2026-11-03 00:05 UTC (2026-11-03 01:05 Europe/Paris)

| Item | Value |
|---|---|
| Default branch | `main` = `d9b950e4708a3d0fc9c955f852144ec1fd893867`. Never pushed by automation. |
| Coordination branch (dev work accumulates here) | `claude/launchlab-trade-events`, PR #90, draft. Holds the offline CI workflow and the SOL fixture pack (`4f2875d`). |
| Protocol branch (routines read this) | `claude/autonomy-framework-20261103`, PR #91, draft, stacked on PR #90. Holds this file, the protocols v2.1, the planner, and the backlog. |
| Open dev work | PR #92, draft, branch `claude/dev-20261102-slot-timing-v1` at `a01269a`. Item `slot-timing-v1`. The `/fix` was applied at 00:00 UTC. The planner now returns STOP, because the owner switch `start_new_work` is false. |
| Not merged, do not merge without owner approval | PR #88, PR #89, PR #90, PR #91, PR #92 |

PR #89 is stacked on the branch of PR #88 (`feat/prepurchase-bitquery-official-sample-proof-20261102`), not on `main`.

## Verified results

- **Offline CI, Ubuntu, Python 3.13.** Run `41544313745` on `7bd4fad`: 1401 passed, 1 skipped. Run on PR #90 at `4f2875d`: success. Run on PR #91 at `e490cea`: 1421 passed, 1 skipped. Run on PR #92 at `a8a0321`: success.
- **Cloud validation run 1 (manual).** Routine `trig_01FCseiBnoeNVFPHggcy5DMA`, PASS on Python 3.11.18. Report on `claude/cloud-validation-20261103` at `6b82c05`. `main` unchanged.
- **Cloud development run 1 (manual).** Routine `trig_019Zqz5ax6uqmJQZKnKB2VVX`, session `cse_016VkauFwWUB3SWAfCeqN33w`. The planner chose START `slot-timing-v1`. The run produced `claude/dev-20261102-slot-timing-v1` (`a8a0321`, PR #92) with four in-scope files. Suite: 1404 before, 1412 after.
- **Planner on live GitHub state.** Before the correction: RESUME of PR #92 for the `/fix` request, with 0 rounds used, and locked paths exactly the four files of the item. After the correction (00:00 UTC): STOP, because new work is closed by the owner switch.
- **Measured seconds per slot is reproducible but not explained.** Independent recomputation from the committed archives gives 0.2155 s/slot (64 slots, 181-slot span, 39 s), per pool 0.2132 to 0.2222. This contradicts the 400 ms slot time in the older sources checked (https://www.helius.dev/blog/alpenglow). A secondary search summary claims a change to 200 ms in October 2026, but the official Solana page (https://solana.com/upgrades/alpenglow) returned HTTP 429 and could not be checked. Until the cause is established, no latency assumption changes. This is tracked as `blocktime-crosscheck-v1`, which is gated on an owner-approved RPC budget.
- **Local Windows failures** (SQLite file lock, symlink privilege, CRLF) do not reproduce on Linux. They are environment-specific.
- **Data reality.** Git tracks nothing under `data/`, which is git-ignored, so a cloud checkout never receives those archives. The three complete SOL-quoted pool archives are versioned as fixtures in `tests/fixtures/launchlab_sol_pools/`, with SHA-256 digests in `MANIFEST.json`. The non-SOL pool is left out.
- **Cloud connectivity.** Clone, `git ls-remote`, fetch and checkout of a pinned SHA, and push to a `claude/` branch all work. A pull request was opened with the session's GitHub integration tool, because `gh` is not authorized in cloud sessions.

## Scheduled tasks and triggers

All three routines are disabled. Connectors were removed from each. Automation never enables them.

| Name | ID | State | Notes |
|---|---|---|---|
| Validation (manual) | `trig_01FCseiBnoeNVFPHggcy5DMA` | disabled | Cron `0 6 * * *` is stored but inert. `last_fired_at` must stay unchanged after 06:07 UTC. |
| Dev agent (scheduled) | `trig_019Zqz5ax6uqmJQZKnKB2VVX` | disabled | Cron `30 1 * * *`, model `claude-sonnet-5-5`. Protocol v2.1: `docs/autonomy/DEV_ROUTINE.md`. |
| Independent reviewer (GitHub trigger) | `trig_01Xu5G5fnfE2Zq26232UbqE6` | disabled, no GitHub trigger attached | One-off date `2027-01-01T00:00Z`, model `claude-sonnet-5-5`. Protocol: `docs/autonomy/REVIEW_ROUTINE.md`. |

## Owner actions pending

0. **Session subscription (unauthorised wake-up).** The first dev session (`cse_016VkauFwWUB3SWAfCeqN33w`) is still subscribed to PR #92 events. It answered the `/fix` request on its own at 00:00 UTC (commit `a01269a`), which you did not authorise. The owner switch `start_new_work` in `BACKLOG.json` is now `false`, so such a session can only resume requested corrections and cannot start new work. To stop the subscription, open the session in claude.ai/code. The tools available to me cannot unsubscribe it.
1. **Extra usage.** Open https://claude.ai/settings/usage and confirm that usage credits (extra usage) are OFF. Automation cannot read this setting.
2. **Resume PR #92 to apply the `/fix` request.** This needs one manual run of the dev agent. The planner will choose RESUME. Approve it or not.
3. **Budget for `blocktime-crosscheck-v1`.** A few `getBlockTime` calls on two RPC providers. This is the only way to explain the measured slot rate. Approve the budget or not.
4. **Helius schedules in PR #89.** Before merging #89, decide on two workflows that run every 6 hours once they reach `main`: `helius-launchlab-sampled-creations.yml` (`43 */6 * * *`) and `helius-s1-capacity-s2.yml` (`17 */6 * * *`). Both use `HELIUS_API_KEY`. Today nothing runs them: `main` has no cron file and GitHub recorded no scheduled run.
5. **Protection of `main`.** The GitHub API returns HTTP 403 for branch protection on this private repository without GitHub Pro. Without it, the only guard is the routine prompt, and the connected identity is the repository administrator. Decide: accept this residual risk, or approve GitHub Pro (paid).
6. **Claude GitHub App.** Install it on the repository if it is not already. Required before a GitHub trigger can be attached to the reviewer.
7. **Activation.** Approve or refuse activation of the dev agent and the reviewer, after reviewing the manual run and its pull request. Nothing is activated before that.
8. **Cleanup.** Optionally delete the validation routine at https://claude.ai/code/routines. The API cannot delete routines.

## Rules every session follows

- Never merge. Never push to `main`. Never force-push. Never delete a branch or a pull request.
- No secret is read, printed or committed. No Helius, RPC, market, price or trading API is called by tests or routines without an owner-approved budget.
- No signing, no transaction, no live trading, no spending, no change to the paid plan.
- A routine writes only its own branch and its own run record. This file and `BACKLOG.json` are owner-only.
- A session woken by a pull request or check event runs the planner and acts only on RESUME for that branch.
- New work starts only when `start_new_work` is `true` in `BACKLOG.json`. It is `false` now, and only the owner changes it.
- Each commit ends with a `Co-Authored-By` line naming the model that actually produced it.

## Log

- 2026-11-02 23:17 UTC: PR #90 gains the offline test workflow (`7bd4fad`). Run succeeded.
- 2026-11-02 23:22 UTC: cloud validation run 1, PASS (`6b82c05`).
- 2026-11-02 23:28 UTC: development agent and independent reviewer created, both disabled, connectors removed.
- 2026-11-02 23:40 UTC: SOL fixture pack committed to PR #90 (`4f2875d`). Planner, backlog and protocol v2 committed to PR #91 (`e490cea`).
- 2026-11-02 23:43 UTC: cloud development run 1. START `slot-timing-v1`. PR #92 opened (`a8a0321`), CI passed.
- 2026-11-02 23:59 UTC: `/fix` request posted on PR #92 about the unvalidated slot-time claim. The planner chose RESUME.
- 2026-11-03 00:00 UTC: the dev session answered the `/fix` on PR #92 without an authorised run (commit `a01269a`). Correction is in scope and conforms to the request. Recorded as an unauthorised wake-up; see owner action 0.
- 2026-11-03 00:05 UTC: planner corrected to run git in the caller's repository (test added). Protocol v2.1: dependencies step, wake-up rule, integration-tool fallback for PRs. Backlog gains the gated `blocktime-crosscheck-v1`.
