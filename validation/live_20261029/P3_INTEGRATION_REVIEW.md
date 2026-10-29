# P3-012 — reconciliation of PR29, PR30 and recovered Cloud edits

Reviewed 29 October 2026. This review does not certify LIVE readiness, market
profitability, an executed transaction or a completed P3 acquisition.

## Exact source and reproducible validation

- Original PR29 head: `d8771ae8043dad587b3fb1c690c480de7036b634`.
- Exact imported local tree: `e4e31ea09f9520de2a8e2f231aee83057e1fdae3`.
- PR30 reviewed head: `54f153e198b0c2bbf617607d395329783f7f60ab`.
- Recovered corrections tested here: local commit
  `c9a6652bff56f14fa3efdc1d4282530fb023cc68`, tree
  `581bda3288c9c992555f7f2a177dbd5434a8be78`.
- The disposable runner copied **228** Python/JSON source and fixture files.
  Only PR31 documentation was modified at capture; these documents are excluded
  from the test runner. New LIVE modules written later were not in this copy.
- Canonical sorted manifest of `{path,sha256}` entries:
  `1cc02e5fd4e917127d6c9ce9d025b1c3dfd3ed87158d55e3fb8ea109b9cf9f23`.
  Full manifest: `/workspace/work/live-20261029/p3-source-manifest.json`.

Command, run with the project virtual environment:

```sh
python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

**2166 passed, 1 skipped, 242 subtests passed in 16.99 seconds; stderr empty.**
The only skip is `tests/test_research_pipeline.py:17`, the deliberately absent
user database. The runner performs no network access and copies no `.env`,
database or Git metadata. This is the pre-LIVE integration result; the final
combined source requires another complete validation after new modules settle.

Logs are retained at `/workspace/work/live-20261029/p3-full-before-live.txt` and
`p3-full-before-live.stderr`. Their SHA256 values are respectively
`874280749844329000a855f074b6e34e01f2c0fffd9ff7579086d27903f9f179`
and `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The earlier exact PR29 suite had **2104 passed and 1 failed**. Its actual-decoder
S2 markout failed on JSON-safe numeric strings. The recovered focused suite
has **126 passed**. These are distinct runs, not additional independent market
observations.

## All thirteen PR30 files reconciled

Every complete remote file was read at the pinned PR30 head and compared with
the recovered local implementation. No Cloud edit was reset or replaced.

| File | Reconciliation decision |
| --- | --- |
| `bot/p3/asof_flow_selection.py` | Keep recovered 30-second S0 window and recomputation of the original strict selection. |
| `bot/p3/asof_protocol_012.py` | Keep recovered JSON-roundtrippable plan, 30-second S0 window, explicit request/cost/clock/watchdog budgets. |
| `bot/p3/asof_slot_markout.py` | Same correction intent as PR30; keep canonical uint64 conversion plus the stronger full safety/immutable-term transition checks and refused-lot residue. |
| `bot/p3/asof_wide_selection.py` | Keep 30-second S0 window, fixed first-twelve prefix and complete denominator. |
| `bot/p3/observed_activity.py` | Both correct the buy direction; local additionally requires base inventory conservation, source pins, full identity checks and unchanged security terms. |
| `bot/p3/platform_admin_history.py` | Keep local signature/role/PDA/as-of refinement checks; add the residual string bounds described below before final validation. |
| `tests/test_p3_asof_flow_selection.py` | Keep runnable local tests. The PR30 version has an unclosed `['Mint2'` bracket at line 87 and fails Python parsing. |
| `tests/test_p3_asof_protocol_012.py` | Keep JSON list/roundtrip regressions; PR30 still expects a tuple that does not survive JSON serialization. |
| `tests/test_p3_asof_real_decoder_integration.py` | Keep real decoder tests for corrected buy direction, delayed S1, both exact sizes, malformed terms, numeric bounds and refused residues. |
| `tests/test_p3_asof_slot_markout.py` | Keep local structure using real decoder fixture facts; fee and immutable-term mutations are also tested through the real integration suite. |
| `tests/test_p3_observed_activity.py` | Keep local direction, inventory-conservation and adversarial identity/permission regressions. |
| `tests/test_p3_platform_admin_history.py` | Keep local real public-key/PDA fixtures and negative signature, account-reference, Borsh truncation and signer-role cases. |
| `tests/test_p3_platform_real_pda_integration.py` | Keep local real canonical-PDA integration and before/after-decision refinement cases. |

The recovered `own_fee_bounds` changes, although outside PR30's thirteen files,
also passed the complete suite. They separate fee expense, refundable ATA
capital, unknown rent, failed-attempt ceilings and uint64 overflow.

## Why S0 is 30 seconds, not PR30's 45 seconds

The previous 15-second maximum was incompatible with a minimum 15-second wait
plus a positive RPC/processing delay. Thirty seconds admits that delay without
extending the preregistered observation span to 45 seconds. S1 must still be
received at most 5 seconds before the decision. The campaign remains globally
bounded to 60 seconds, with another minimum 15-second interval before S2.

Thirty seconds is a conservative research protocol choice, not an estimate of a
profitable feature horizon. Slow historical lookups or a slow block-time read
may still cause refusal; this is retained, not rescued by widening a window
after observing the outcome. Selectors allow an explicit registered window;
the collector must pass and verify the exact immutable plan value.

## Residual counter-review findings requiring correction

`platform_admin_history._create_params` at the tested checkpoint decodes the
three Borsh strings but does not bound their lengths. The pinned IDL's
`PlatformConfig` allocates 64, 256 and 256 bytes for `name`, `web` and `img`.
PR30 included these bounds; the recovered stronger verifier omitted them.
An offline direct check reproduced acceptance of lengths `(65,0,0)`,
`(0,257,0)` and `(0,0,257)`. Add these bounds and rejection tests, then revalidate.

The official IDL was independently reread once through GitHub at commit
`e7e0c96fe77bcf6a020b84a44c47a722aac8e359`, blob
`70186e3f02c2bead7e5a9a92453104df853683ed`. This was a documentation read,
not a market/RPC acquisition. Its CreatePlatformConfig instruction confirms
the discriminator, eight roles, system program and original admin PDA seed.

Second finding: PR30 checked equality of `share_fee_assumption_ppm` across S1
and S2, but the recovered `snapshot_transition_reason` does not. A direct
offline actual-decoder fixture with S1 share assumption `0` and S2 assumption
`100` still returned `CONDITIONAL_BANK_MARKOUT`. This is a route hypothesis,
not a newly observed market fee; changes must be refused, with both assumptions
bounded by the corresponding configured maximum. Add a regression before the
final combined suite.

Third finding: the plan validator compares Python dictionaries using ordinary
equality. Consequently `max_requests=20.0`, `provider_quotes_authorized=0` and
`primary_model_input_lamports=100000000.0` are accepted as equal to their integer
or boolean fixed fields. This is not evidence of a request-budget bypass, but it
violates the exact JSON-type protocol contract. Compare recursive JSON types
as well as values, and test numeric/boolean aliases before preregistration.

## Boundaries that remain explicit

- A source-pinned JSON analysis is not, by itself, proof of transport provenance
  or a verified deployed program binary. The caller must replay retained raw
  account responses and verify the hash chain and request bindings.
- Historical jsonParsed transaction checks validate encoding, signer flags,
  discriminator and canonical PDA. They do not verify an Ed25519 signature over
  an unavailable serialized message. Those flags remain explicitly false.
- `snapshot_safety_reason` accepts the single historical-admin UNKNOWN for
  research. This is not sufficient admission for a LIVE route.
- Conditional S1-to-S2 markouts do not model our own entry's effect on the actual
  future bank. They remain neither fills nor qualified strict economic cycles.
- No P3-012 acquisition, wallet access, mainnet signature, order, spend, policy
  promotion or PR merge was performed by this review.
