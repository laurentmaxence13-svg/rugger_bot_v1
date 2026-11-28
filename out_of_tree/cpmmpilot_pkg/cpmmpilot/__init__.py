"""cpmmpilot 0.1 (R03) -- runner of the CPMM pilot: step 0 -> U-2 -> step 1, OFFLINE-first.

Owner texts: AUTORISATIONS_CPMM_TEXTES_INTEGRAUX_R02 v1.2 (5c6e8fc1); method U-2 v0.2.1 (ebc9e45f).
Version 0.1 runs ONLY against an in-memory fake chain (``rpc.FakeChain``): the live RPC is refused by construction
(``rpc.LiveRpc`` raises), so nothing in this package can reach the network before an audited 0.2 enables it.

Frozen rules of R01 are imported and NEVER modified: cpmmx (decoder / timeline), cpmmprereg (R-CP1), cpmmb1 (B1),
cpmmcost (costs, fees_from_amm_config). The CPMM program id is imported from cpmmx.events, never retyped.
"""
VERSION = '0.1'
