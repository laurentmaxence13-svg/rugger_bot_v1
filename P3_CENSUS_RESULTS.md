# P3 LaunchLab Baseline Census — results note

3 November 2026. Protocol `launchlab-baseline-census-001`, SHA256
`b7d1c842f3cae2cf8e6570e286eaa27a67a8bd38edab32a1d2ba9d90d31ff2bb`, frozen in
commit `766207547956059ea5a6b90cde24933f320bfa8e` before any network call.
Details: [P3_CENSUS_PROTOCOL.md](P3_CENSUS_PROTOCOL.md). Machine-readable record:
[validation/P3_CENSUS_RESULTS.json](validation/P3_CENSUS_RESULTS.json).
This note gives no economic verdict.

## Run status: NOT RUN

The mission's quota field is still `[TO BE FILLED]`. Without an approved quota there is
no authorization (AGENTS.md: no network without explicit owner approval), so the
census made **zero market requests**:

- no RPC, Raydium index or quote call;
- no wallet, signing, spend or subscription.

The committed authorization template holds nulls, and the runner refuses it before
creating a run directory (tested). As a result, there is **no run report and no
census evidence archive yet.** The commands that will produce them are in the
protocol, under "Owner authorization".

Network actually used in this mission: GitHub (git push), and PyPI for a scratch
virtualenv outside the repository. That virtualenv holds the declared
`requirements*.txt` plus pytest. No dependency was added to the project.

## Measured facts

**Software, reproduced by test on isolated copies.** Each copy came from
`git archive` of the freeze commit, with no `.git`, `.env` or database. The suite
ran through `tests/p16h_isolated_runner.py` (sockets and dotenv blocked):

```bash
python -B tests/p16h_isolated_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rfEs -W error
```

| Interpreter | Before (main `d9b950e`) | After (freeze commit) |
|---|---|---|
| Python 3.12.3 | 1 358 passed, 1 skipped, 242 subtests, exit 0 | **1 398 passed, 1 skipped, 242 subtests, exit 0, stderr empty** |
| Python 3.13.18 | 1 352 passed, 5 failed, 1 error | 1 392 passed, 6 failed |

- The 40 new tests are in `tests/test_p3_census.py`. The skip is the existing
  "base utilisateur absente" test.
- Python 3.13 failures are all `ResourceWarning: unclosed database`, raised at
  garbage-collection time. The test that fails depends on GC timing, so the list
  moves as tests are added.
- To attribute the leaks, I added a scratch-only `conftest.py` that forces
  `gc.collect()` after every test. All 1 398 tests pass. 12 **pre-existing** tests
  leak connections: paper_engine ×3, research_pipeline ×3, mint_audit ×2,
  paper_pipeline ×2, dashboard_evidence ×1, p3_evidence ×1. **No census test leaks.**
- These leaks were left out of scope: fixing them touches PAPER/ledger test
  modules.

The census tests cover:

- frozen protocol and template refusal;
- authorization limits, and spend/signing always `false`;
- git preflight;
- the inherited read-only method and destination policy;
- per-provider budget, token bucket and 429 backoff, counted before transport;
- an end-to-end synthetic census in which all 52 tasks are terminal;
- categories that sum to the population;
- exact −0.2 gross ratio;
- refused sells and a 429-induced missed buy;
- late detection, curve exit and quota stop;
- failed-poll gap closing and index flood staying open;
- crash/resume with no retry, `interrupted_in_flight` and `missed:run_interrupted`;
- refusal of tampered, missing or relinked bundles;
- byte-identical report on re-analysis.

**Archived v2 evidence, re-read offline in this mission (documented historically,
not re-observed):** `evidence/p3/launchlab_002` holds 100 index rows whose
creation claims span 188.5 min, about 0.53 rows/min. For both verified creations,
the index `createAt` claim equals block time × 1 000. Both provider sells came back
`provider_rejected` (HTTP 200). This sample sizes the suggested quota and supports
the claim-based schedule anchor. It is not a forecast of creation rate.

```bash
python -B -c "from pathlib import Path; from bot.p3.evidence import verify_bundle; ev=verify_bundle(Path('evidence/p3/launchlab_002'))['events']; c=[r['creation_time_claim_ms'] for e in ev if e['kind']=='discovery' for r in e['payload']['rows'] if r['creation_time_claim_ms']]; print(len(c),(max(c)-min(c))/60000); print([(e['mint'][:6],e['payload']['creation_block_time_ms']) for e in ev if e['outcome']=='creation_matched'])"
```

## Coverage limits (by design, before any data)

- **There is no independent universe reference.** Coverage of all LaunchLab
  creations is `null` / unknown. Discovery depends on one anonymous index whose
  completeness, ordering and caching are not certified.
- **Continuity gaps detect missed creations but cannot prove that none were
  missed.**
- **The schedule is relative to the index claim.** If index lag exceeds 90 s, the
  +60 s state and the buys are missed (`missed:detected_after_tolerance`). That loss
  is counted, not hidden.
- **Quotes have no provider source time or slot.** They are route estimates, not
  fills. Gross ratios exclude network, priority and account costs.
- **The local-curve secondary only covers states that pass the
  `published_metadata_v1` qualification.** It is a conditional estimate on observed
  states.

## What could not be, or will not be, retained

- **Index bodies:** only the identity and claim fields of every row plus a digest
  are kept; metadata is never followed.
- **Bodies refused by the evidence policy:** digest and failure receipt only.
- **SQLite segments:** local only, never archived.
- **Provider redistribution rights:** not certified.

## Still unknown

Every census measurement:

- the creation counts and verification rate;
- state availability per offset;
- the +60 s buy-quote availability and implied prices;
- sellable-exit fractions by offset and size;
- the primary and secondary distributions;
- migration rates;
- detection latency;
- throttling behaviour over hours.

Also unknown: the real index lag, and whether public endpoints sustain a
multi-hour run within the quotas. The next step belongs to the owner: fill and
commit `authorization.json`, then run the commands listed in the protocol.
