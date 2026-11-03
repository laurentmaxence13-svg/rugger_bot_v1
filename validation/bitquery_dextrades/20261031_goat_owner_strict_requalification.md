# GOAT — prior 18-signer profit claim vs strict token ownership evidence

Recalculation from the two Bitquery JSON pages delivered 2026-10-31,
using `flat_signer_cycles.csv` in the reproducible merged archive
`RUGGER_BITQUERY_GOAT_FUSION_2_EXPORTS_20261031.zip`.

The full 18 signer-closed gross subset is **+2.665953517 SOL**,
but **15/18** do not have observed GOAT token-account owner matching
the signer on *every* transaction of the modeled cycle. The incomplete
owner evidence is almost entirely because the first export lacked
`Trade.Buy.Account.Owner` and `Trade.Sell.Account.Owner`.

## Owner-complete cases only

| Signer prefix | Gross observed GOAT/WSOL flows |
|---|---:|
| `Hdf53xBD...` | −0.004057095 SOL |
| `3QDBnr4A...` | −0.010669628 SOL |
| `BeLocgBw...` | −0.043418789 SOL |
| **Sum, 3 owner-complete signer cases** | **−0.058145512 SOL** |

The other 15 signer-complete cases contribute **+2.724099029 SOL
gross**, but they **cannot be presented as fully owner-verified
wallet-level realized P&L** on the provided evidence.

Neither figure accounts for network costs or possible external token
transfers. A matching token-account owner alone cannot establish all
wallet economics; read-only token balance history and transfer checks
would be required.

In particular, the evidence does **not** support saying
"the Master earned +2.66 SOL". True Master P&L and Master-reference edge
remain **unknown**. A sole GOAT token is one creator cluster,
not an independent holdout.

This stricter qualification supersedes *any* loose characterization
in earlier signer-only research notes; the underlying arithmetic remains
correct for the selected signer-based subset.

**Repro**: `python -m unittest -q test_merge.py`; then sum
`pnl_sol` for `all_rows_owner_verified == True` in
`flat_signer_cycles.csv`. Nine reconciliation tests pass.
