# Out-of-tree W1 tooling (kept OUTSIDE the frozen tree on purpose)

This branch sits on the frozen W1 commit (tree `aff97638`) and only ADDS this
`out_of_tree/` directory, so its own tree is NOT the frozen tree. To run day J,
check out the frozen commit in a clean worktree and point `PYTHONPATH` here:

    git worktree add ../w1_frozen claude/r01-w1-frozen-tree-aff97638
    cd ../w1_frozen
    RUGGER_NO_DOTENV=1 PYTHONPATH=<this checkout>/out_of_tree/w1aux_v73:. \
        python3.12 -B -m w1aux.dayj --step selfcheck --out <dir> --s0 467275745

| Directory | Content | Anchor (RUGGER 02) |
|---|---|---|
| `w1aux_v73/` | day-J orchestrator, lazy/parallel replay helpers, ledger, descriptive metrics, tests | `MANIFEST_v73.txt` sha256 `63eb3412…` |
| `cloud_d1_v25/` | D1 cloud fallback scripts (run by the owner only, after an explicit GO) | `MANIFEST_v25.txt` sha256 `f4384f17…` |
| `notes/` | metric definitions fixed before the data (note J), operational plan, policy gap | note J sha256 `cc615a2a…` |

CPython 3.12 only (3.11 differs in the last float digit). Offline, no secret is
read, research only (`HISTORICAL_REPLAY`): never an operational Master trade,
no LIVE arming. Do not merge to `main`.
