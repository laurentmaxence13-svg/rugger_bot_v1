# dryrun — offline rehearsal of the LaunchLab BUY → hold → SELL chain

Out-of-tree package. It imports the frozen source tree and modifies nothing in it.

## What it does

`DryRunHarness` (`dryrun/harness.py`) runs one cycle on synthetic pool state:

1. **BUY** — builds the unsigned order with the existing `build_launchlab_order`,
   runs the existing `check_unsigned_order` on it, then records a **shadow fill**
   computed with `bot.market.launchlab_curve.buy_exact_in` (amount out, fee, state after).
2. **HOLD** — advances the pool with exact-in trades "by others" (pure curve arithmetic).
3. **SELL** — builds and preflights the unsigned SELL of the whole shadow position on the
   advanced pool, records the shadow fill, closes the position and itemises the net P&L:
   curve fees, base fee, priority fee (parameter), failed attempts (parameter), rent
   (opened / recovered / written off).

Every step is a record of a hash-chained JSONL journal (`dryrun/journal.py`). Each record
carries `dry_run=true, signed=false, submitted=false, funds_used=false,
master_operational_trade=false, live_ready_to_arm=false, live_execution_verified=false,
economic_edge_validated=false`; a record with any other value fails verification.
The shadow position lives only in that journal. It is not a position of
`bot.live.journal.ExecutionJournal`, which the harness never opens.

The journal is the single commit point: bank, position and simulated wallet change only by
applying an appended record, so re-opening a journal on the same initial bank replays to
the same state (and refuses a journal whose amounts do not replay).

## What it proves

- The frozen builder produces BUY and SELL orders on a pool state that really moves between
  them, and its expected output equals the exact curve arithmetic at each step (the harness
  refuses otherwise).
- The controls below hold in the harness, each with a test.
- A full cycle calls no signer, no send function, opens no live journal, builds no
  authorization envelope or arming state, and in a fresh interpreter never even imports
  `bot.live.signer`, `engine`, `rpc`, `submission`, `safety`, `journal` or `runtime`.

## What it does NOT prove

Nothing about real execution on mainnet.

- **No simulation by an RPC node.** `check_unsigned_order` talks to `FixtureRpc`, which
  returns a canned success. `simulated_by_rpc_node` is `false` in every preflight record.
- **No inclusion, no fill.** A shadow fill is arithmetic on the very state the order was
  built on, so slippage, competing transactions, reverts and landing are never observed.
- **No real fees.** Priority fee and failed attempts are parameters, not measurements.
- **No real pool.** Accounts are the synthetic bytes of the frozen tests. Fee routing to
  protocol/platform/creator accounts is not modelled; "others" have no holder ledger.
- **No real balance.** The wallet is a public address with a *simulated balance, no funds*.
- **No edge.** A P&L here is a rehearsal figure on invented trades.

`LIVE_READY_TO_ARM`, `LIVE_EXECUTION_VERIFIED` and `ECONOMIC_EDGE_VALIDATED` stay FALSE.
This is not a Master trade and not evidence towards the Master promotion thresholds.

## Run the tests (offline, from the frozen tree)

```
cd <wt_frozen> && PYTHONPATH=<dryrun_pkg> unshare -rn <venv312>/bin/python -B -m pytest -q \
    <dryrun_pkg>/dryrun/tests -p no:cacheprovider -W error
```

`-B` and `-p no:cacheprovider` keep the frozen tree clean. To write one sample journal:
`cd <wt_frozen> && PYTHONPATH=<dryrun_pkg> unshare -rn <venv312>/bin/python -B -m dryrun NEW.jsonl`.

## Controls and their tests

| | Control | Test |
|---|---|---|
| a | duplicate decision id refused | `test_duplicate_buy_for_the_same_decision_id_is_refused` |
| b | resume does not double the position | `test_resume_between_buy_build_and_shadow_fill_does_not_double_position`, `test_resume_right_after_the_fill_was_committed_counts_it_exactly_once` |
| c | maximum exposure, loss limit | `test_maximum_exposure_refuses_a_new_buy`, `test_loss_limit_refuses_a_new_buy_once_the_realised_loss_reaches_it` |
| d | emergency stop, no reset | `test_emergency_stop_refuses_everything_and_cannot_be_cleared` |
| e | hash chain, tamper detection | `test_every_record_carries_the_sha256_of_the_previous_one`, `test_tampered_journal_is_detected` |
| f | never signs, never sends | `test_full_cycle_and_every_other_operation_trip_no_signer_or_send`, `test_a_cycle_in_a_fresh_interpreter_never_loads_signing_or_sending_modules` |
| g | amounts against pool liquidity | `test_buy_crossing_the_migration_boundary_is_refused_with_a_reason`, `test_sell_larger_than_the_curve_can_pay_is_refused_with_a_reason` |

## The six gaps

| # | Gap | Status |
|---|---|---|
| 1 | No inventory in a dry run | **Addressed, in the harness only.** Shadow position in the dry-run journal. The live journal still creates positions only in `finalize`. |
| 2 | No LaunchLab account loader from RPC | **Not addressed.** The bank is built from fixture bytes; nothing reads a pool from a node. |
| 3 | SHADOW mode never builds or simulates | **Partly.** Orders are built and preflighted by the harness, outside `LiveRuntime`; the "simulation" is a fixture answer. `runtime.py` is unchanged and not wired to the harness. |
| 4 | A wallet without funds cannot build | **Addressed as specified.** Simulated balance supplied through the fixture account mapping; the builder is not patched and still refuses a zero balance. |
| 5 | Cost model incomplete | **Partly.** Priority fee and failed attempts are parameters; rent is itemised. No fee estimate from a network. Share fee is 0 because the built instruction carries a zero share-fee argument. Rent is always written off: the frozen SELL builder has no instruction closing the token account. |
| 6 | CPMM leg needs a verified migration receipt | **Not addressed.** `cpmm_exit_probe` builds and preflights the frozen tests' CPMM fixture, bound to nothing: the shadow position is not sold through it. |

## Limits worth knowing

- A hash chain cannot see that its last records were removed together. Note
  `journal.head` elsewhere and pass it as `verify_journal(path, expected_head=...)`.
- One process per journal. Two writers break the chain; the next open refuses it.
- Sample fixture figures are deterministic (logical clock): the same inputs write the same
  journal bytes. That is reproducibility of a rehearsal, not a market result.
