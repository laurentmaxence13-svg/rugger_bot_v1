# Rugger Master: continuity record (v2)

## Authority

- This file is authoritative **only** on branch `claude/autonomy-framework-20261103` (PR #91). Do not copy it to other branches. PR #90 deliberately does not contain it.
- Only the owner's sessions edit it. Routines never edit it.
- It is a **snapshot** written at the time shown below. The live state (branches, claims, corrections, checks) comes from git and GitHub. To see it, run `python tools/dev_state.py fetch` and `python tools/dev_state.py plan`, from the protocol branch.
- The backlog is `docs/autonomy/BACKLOG.json`, not this file.

## Snapshot: 2026-11-02 23:40 UTC (2026-11-03 00:40 Europe/Paris)

| Item | Value |
|---|---|
| Default branch | `main` = `d9b950e4708a3d0fc9c955f852144ec1fd893867`. Never pushed by automation. |
| Coordination branch (dev work accumulates here) | `claude/launchlab-trade-events`, PR #90, draft, head `4f2875d`. Holds the offline CI workflow and the committed SOL fixture pack. |
| Protocol branch (routines read this) | `claude/autonomy-framework-20261103`, PR #91, draft, stacked on PR #90. Holds this file, the protocols, the planner and the backlog. |
| Not merged, do not merge without owner approval | PR #88, PR #89, PR #90, PR #91 |

PR #89 is stacked on the branch of PR #88 (`feat/prepurchase-bitquery-official-sample-proof-20261102`), not on `main`.

## Verified results

- **Offline CI, Ubuntu, Python 3.13.** Run `41544313745` succeeded on `7bd4fad`: 1401 passed, 1 skipped, 242 subtests passed.
- **Cloud validation run 1.** Routine `trig_01FCseiBnoeNVFPHggcy5DMA`, session `cse_016VkauDnhqSZRZYPCt53Q73`. PASS on Python 3.11.18, same counts. Report on `claude/cloud-validation-20261103` at `6b82c05`. `main` unchanged.
- **Local Windows failures** (SQLite file lock, symlink privilege, CRLF) do not reproduce on Linux. They are environment-specific.
- **Cloud connectivity.** Clone, `git ls-remote`, fetch and checkout of a pinned SHA, and push to a `claude/` branch all work with the connected GitHub identity. No MCP connector is needed.
- **Data reality.** Git tracks nothing under `data/`, which is git-ignored. A cloud checkout receives only tracked files. The three complete SOL-quoted pool archives are now tracked as fixtures in `tests/fixtures/launchlab_sol_pools/` (commit `4f2875d`), with SHA-256 digests in `MANIFEST.json`. The non-SOL pool is left out.
- **Planner on live state.** At the snapshot time: no `claude/dev-*` branch exists, and the plan is START `slot-timing-v1`.

## Scheduled tasks and triggers

All three routines are disabled. Connectors were removed from each. Automation never enables them.

| Name | ID | State | Notes |
|---|---|---|---|
| Validation (manual) | `trig_01FCseiBnoeNVFPHggcy5DMA` | disabled | Cron `0 6 * * *` is stored but inert. Expected: no run. `last_fired_at` must stay unchanged after 06:07 UTC. |
| Dev agent (scheduled) | `trig_019Zqz5ax6uqmJQZKnKB2VVX` | disabled | Cron `30 1 * * *`, model `claude-sonnet-5-5`. Protocol: `docs/autonomy/DEV_ROUTINE.md`. |
| Independent reviewer (GitHub trigger) | `trig_01Xu5G5fnfE2Zq26232UbqE6` | disabled, no GitHub trigger attached | One-off date `2027-01-01T00:00Z`, model `claude-sonnet-5-5`. Protocol: `docs/autonomy/REVIEW_ROUTINE.md`. |

## Owner actions pending

1. **Extra usage.** Open https://claude.ai/settings/usage and confirm that usage credits (extra usage) are OFF. Automation cannot read this setting.
2. **Helius schedules in PR #89.** Before merging #89, decide on two workflows that run every 6 hours once they reach `main`: `helius-launchlab-sampled-creations.yml` (`43 */6 * * *`) and `helius-s1-capacity-s2.yml` (`17 */6 * * *`). Both use `HELIUS_API_KEY`. Today nothing runs them: `main` has no cron file and GitHub recorded no scheduled run.
3. **Protection of `main`.** The GitHub API returns HTTP 403 for branch protection on this private repository without GitHub Pro. Without it, the only guard is the routine prompt, and the connected identity is the repository administrator. Decide: accept this residual risk, or approve GitHub Pro (paid).
4. **Claude GitHub App.** Install it on the repository if it is not already. Required before a GitHub trigger can be attached to the reviewer.
5. **Activation.** Approve or refuse activation of the dev agent and the reviewer, after reviewing the second manual run and its pull request. Nothing is activated before that.
6. **Cleanup.** Optionally delete the validation routine at https://claude.ai/code/routines. The API cannot delete routines.

## Rules every session follows

- Never merge. Never push to `main`. Never force-push. Never delete a branch or a pull request.
- No secret is read, printed or committed. No Helius, RPC, market, price or trading API is called by tests or routines without an owner-approved budget.
- No signing, no transaction, no live trading, no spending, no change to the paid plan.
- A routine writes only its own branch and its own run record. This file and `BACKLOG.json` are owner-only.
- Each commit ends with a `Co-Authored-By` line naming the model that actually produced it.

## Log

- 2026-11-02 23:17 UTC: PR #90 gains the offline test workflow (`7bd4fad`). Run succeeded.
- 2026-11-02 23:22 UTC: cloud validation run 1, PASS (`6b82c05`).
- 2026-11-02 23:28 UTC: development agent and independent reviewer created, both disabled, connectors removed.
- 2026-11-02 23:40 UTC: SOL fixture pack committed to PR #90 (`4f2875d`). Planner, backlog and protocol v2 committed to PR #91.
