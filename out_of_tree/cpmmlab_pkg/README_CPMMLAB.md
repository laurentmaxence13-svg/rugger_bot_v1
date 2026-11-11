# cpmmlab 0.1-experimental — the "after migration" probe on a Raydium CPMM pool

Research only, offline: values one buy of 0.1 SOL sent `delay_s` after the creation of the CPMM pool of a
migrated token and its clock sale `hold_s` later, with the program's integer arithmetic (`cpmmx.curve`) on
the reserves the program logged (`cpmmx.timeline`). Both orders are clock orders with a landing latency.

Conservative choices: sale valued on the real reserves (own impact not carried), lower of the two orders
inside each landing second, worse bound for an unknown creator-fee side or unknown protocol / fund shares.
Anything that cannot be established gives an `unpriced_*` status and no number (pool creation unknown,
token transfer fee, undecoded transaction, liquidity change, fee rate not observable yet, outside the window).

NOT VALIDATED on a real sample (criterion A-12 open): nothing here can be credited to a strategy.
No CPMM data has been collected; no collection is authorized. Tests (9, synthetic pools only):
`python -B -m pytest -q cpmmlab/tests -p no:cacheprovider -W error` with `cpmmx_pkg` on `PYTHONPATH`.
