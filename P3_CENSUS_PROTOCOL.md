# P3 LaunchLab Baseline Census — pre-registered protocol

**Status: FROZEN, NOT RUN.** PAPER ONLY: no order, wallet, signing, ledger write,
spend or subscription. The census builds the *denominator* later evaluations need;
it computes no score, makes no selection, writes no hypothetical P&L to any ledger
and gives no economic verdict.

| Item | Value |
|---|---|
| Protocol file | [`benchmarks/p3_launchlab_census_v1/protocol.json`](benchmarks/p3_launchlab_census_v1/protocol.json) |
| Protocol SHA256 (canonical compact sorted JSON) | `b7d1c842f3cae2cf8e6570e286eaa27a67a8bd38edab32a1d2ba9d90d31ff2bb` |
| `registered_at_ms` | `1793732458773` (2026-11-03 19:00:58 UTC) |
| Code that enforces it | [`bot/p3/census.py`](bot/p3/census.py) (`PROTOCOL_V1`), [`bot/p3/census_report.py`](bot/p3/census_report.py) |
| Owner quota | **[TO BE FILLED]**: [`authorization.template.json`](benchmarks/p3_launchlab_census_v1/authorization.template.json) holds nulls and is refused |

The committed JSON must equal `PROTOCOL_V1` in code, value and type, plus
`registered_at_ms`. Any change is a new protocol, never an edit. The protocol is
committed before any network call. The owner's quota is a **separate** file that
names this protocol hash. The runner refuses to start unless both files are
tracked and unmodified at `HEAD` and `bot/p3` is clean (`git_preflight`).
`run.json` records the source revision, protocol hash, authorization hash and the
combined pre-registration hash. Every bundle manifest carries that combined hash.

## Universe and coverage

- **Source:** Raydium LaunchLab index `get/list?sort=new`, ≤100 rows per poll, every
  15 s, anonymous. The index is a lead, not a creation proof.
- **Baseline:** valid identities in the first successful poll are pre-window and
  are never enrolled. The window starts at that poll's receipt time.
- **Enrollment (no selection):** every valid identity (mint + pool) first seen after
  the baseline, while enrollment is open, is enrolled. There is no price, volume,
  score or quote-currency filter; non-SOL-quote pools are enrolled too. Rows whose
  creation claim predates window start − 120 s are `pre_window_late_listed`. When
  one poll brings several new rows, they are processed oldest-claim first, so a stop
  rule never favours the newest. Rows refused after a stop stay in the universe as
  `not_enrolled_after_stop:<reason>`. A second pool for a known mint is recorded as
  an identity conflict and is not enrolled.
- **Continuity:** a successful poll must overlap the previous successful one, or
  return fewer than 100 rows. Otherwise `discovery_continuity_not_established` opens
  a gap. A failed poll opens `discovery_poll_failed_continuity_unknown`, which
  closes only when overlap is proven again.
- **Independent universe reference: none. Coverage of all LaunchLab creations is
  UNKNOWN** and is reported as `null`. Continuity gaps show that creations were
  missed. Their absence does not prove completeness, because the index's own
  completeness and ordering are not verified.

## Window, stop rules, deadline

Enrollment closes at the first of: authorized duration elapsed; authorized N
creations enrolled; remaining quota cannot reserve one more creation's full
schedule; index quota exhausted; ≥3 throttle responses (HTTP 403/429) within
10 min; 40 consecutive failed polls. At ≥10 throttles in total, every pending task
ends as `aborted:throttle_abort`. Observation continues until every task is
terminal, or until the run deadline (enrollment close + 4 080 s) marks the rest
`missed:run_deadline`. Authorization caps: duration ≤12 h, N ≤1 000.

## Fixed schedule per enrolled creation (13 tasks, no retries)

Anchor = index creation claim (ms) when positive and not after receipt; otherwise
first receipt (flagged). Archived v2 evidence showed the claim equals the verified
block time. Offsets are measured afterwards against the verified creation.

| Task | Due | Tolerance | Requests (reserved) |
|---|---|---|---|
| Verify creation: pool signature page (≤1 000), oldest successful tx, `maxSupportedTransactionVersion=1`, mint/pool/instruction match (v2 `_creation`) | at enrollment | run deadline | RPC 2 |
| Pool/curve state: address graph, then one `getMultipleAccounts` (7 accounts, `minContextSlot` non-decreasing) + `getBlockTime` (v2 `_snapshot`) | +60, +300, +900, +3 600 s | 30, 60, 90, 180 s | RPC ≤3 each |
| Buy quote SOL→token, Raydium `compute/swap-base-in`, 100 bps | +60 s | 30 s | quote 1 per size |
| Sell quote token→SOL of the **+60 s buy's expected output, same size** | +300, +900, +3 600 s | 60, 90, 180 s | quote 1 per size |

- **Sizes:** 0.5 SOL and 1 SOL (instrumental only). Same-due order: state, buy, sell.
- **Dispatch:** a single sequential dispatcher, earliest-deadline-first among ready
  tasks, never before due.
- **Pacing:** a token bucket per provider waits *before* a task, so journaled
  latencies exclude local pacing. Limits: RPC 1 per 500 ms, burst 3 (documented
  public limit is 40 per method per 10 s); quote 1/s, burst 1 (Raydium advises
  their own engine above 120/min); index 1 per 5 s.
- **Backoff:** a 403/429 starts provider backoff for max(30 s, Retry-After ≤600 s),
  restored on resume. A task that cannot run inside its tolerance is terminal with
  its reason: `missed:detected_after_tolerance` / `dispatch_after_tolerance` /
  `provider_backoff` / `local_rate_limit_backlog` / `run_interrupted`.
- **No buy quote:** sells end as `not_attempted:no_plus60_buy_quantity`. A refused
  or absent sell quote is a first-class outcome. **Nothing is imputed.**
- **Quota:** per creation, RPC 14 and quote 8 are reserved at enrollment. Index
  polls are counted separately. Every attempt is counted before transport.

Each measurement keeps **source time** (chain block-time estimate; quotes: `null`,
since Raydium provides neither time nor slot), **receipt time**, **availability time**
(journal ingestion barrier), **analysis time** (in-run analysis for states; quotes
equal availability), and **slot** (bank context slot; creation slot).

## Checkpoints, archive, resume

- **Segments:** the journal is cut into `CaptureStore` segments (≤2 000 records,
  8 MiB or 30 min). Each is closed, exported with `export_capture` into a portable
  bundle, verified, and anchored in a separate `anchors/NNNNNN.json` before the next
  segment opens. The next segment's first record links the previous tail hash.
- **Archive:** `run.json`, `anchors/` and `bundles/` are archived. SQLite never is.
  Pushing to the private repository is an operator action after the run.
- **Resume** (same run dir, protocol, authorization and revision):
  - the interrupted segment is closed, exported and anchored first;
  - a task in flight at the crash is terminal `interrupted_in_flight` (never retried);
  - expired tasks are `missed:run_interrupted`;
  - an open `run_interrupted` gap is never closed;
  - requests used = last journaled cumulative counters + one operation allowance
    (RPC 3, quote 1, index 1).

## Fixed analysis outputs (`census_report.py`, offline, deterministic)

Population = all enrolled creations. Each enrolled creation appears in exactly one
category per size; missing categories are counted, not dropped.

1. **Primary:** the distribution of gross `R = sell(+900 s) / buy_input(+60 s) − 1`,
   both legs from provider quotes. Buy input is the provider's actual input if
   reported. Gross means network, priority and account costs are excluded. The
   output gives category counts, plus nearest-rank quantiles (0, .1, .25, .5, .75,
   .9, 1) and a fixed histogram (edges −1, −0.9, −0.5, −0.2, −0.05, 0, 0.05, 0.2,
   0.5, 1, 3) conditional on `observed`.
2. **Secondary (labelled conditional):** the same ratio from pinned local curve
   arithmetic. The +60 s observed-state counterfactual buy quantity is sold against
   the observed +900 s state (`published_metadata_v1`; virtual reserves and accrued
   fees never fund exits).
3. **Sellable exit fraction** by offset × size: provider sell `quoted`, against three
   denominators (all enrolled; +60 s buy quoted; sell dispatched).
4. **Buy quote at +60 s:** availability and implied price, in lamports per atomic
   unit and SOL per whole token.
5. **State availability per offset**, actual offset against verified creation time,
   and within-tolerance counts.
6. **Curve change against +60 s:** counts of `real_b` lower/equal/higher, and
   quantiles of the `real_b` and spot ratios. No "death" label is inferred.
7. **Migration within window:** raw pool status ≠0 at any observed offset; pool
   account absent.
8. **Detection latency:** verified creation block time (1 s resolution) to the first
   locally available price (a decodable reserve state or a quoted buy), plus slot
   lag and index detection latency.
9. **Coverage, gaps, universe dispositions, budget, throttles, resumes, refused
   bodies, protocol deviations** (for example, segment limits changed in tests).

All numbers are exact rationals rounded half-even to 9 decimals. The report holds
no wall-clock values, so the same archive gives byte-identical JSON. `economic_verdict`
is always `not_part_of_census`.

## Owner authorization (to be filled, committed, then run)

Copy the template to `benchmarks/p3_launchlab_census_v1/authorization.json`, then:

- fill `approved_by` (a label, not an email), `approved_at_ms`,
  `max_enrollment_duration_ms`, `max_creations` and the three `request_budgets`;
- keep `spend_authorized`, `subscriptions_authorized` and
  `wallet_or_signing_authorized` set to `false`;
- commit the file.

A *suggestion only*, based on the v2 index sample (100 rows over 188.5 min, about
0.53/min; historically documented, not a forecast):

| Field | Suggestion | Basis |
|---|---|---|
| `max_enrollment_duration_ms` | 14 400 000 (4 h) | about 127 creations at the v2 rate |
| `max_creations` | 150 | headroom over that rate |
| RPC | 2 200 | 150 × 14 reserved |
| Raydium quote | 1 300 | 150 × 8 reserved |
| Index | 1 000 | 961 polls in 4 h |

Expected wall time is at most 4 h + 68 min.

```bash
python -B -m bot.p3.census hash --protocol benchmarks/p3_launchlab_census_v1/protocol.json --authorization benchmarks/p3_launchlab_census_v1/authorization.json
```

```bash
python -B -m bot.p3.census run --network --protocol benchmarks/p3_launchlab_census_v1/protocol.json --authorization benchmarks/p3_launchlab_census_v1/authorization.json --run-dir /path/outside/repo/census_001
```

```bash
python -B -m bot.p3.census resume --network --protocol benchmarks/p3_launchlab_census_v1/protocol.json --authorization benchmarks/p3_launchlab_census_v1/authorization.json --run-dir /path/outside/repo/census_001
```

```bash
python -B -m bot.p3.census_report --evidence /path/outside/repo/census_001 --output /path/outside/repo/census_001_report.json
```

To archive, copy `run.json`, `anchors/` and `bundles/` to `evidence/p3/census_001/`,
re-run `census_report --evidence evidence/p3/census_001` and record the printed
`report_sha256`.

## Out of scope

`decide()`, TP/SL, position sizing, the PAPER ledger, the currency convention,
thresholds, and any strategy or "Master vs reference" comparison. None of these
modules is imported or modified by the census.
