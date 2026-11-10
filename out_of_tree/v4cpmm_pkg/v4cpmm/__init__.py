"""v4cpmm: EXPERIMENTAL bridge between the V4 simulator (v4sim 0.2, unchanged) and a Raydium CPMM pool (cpmmx).

Status: experimental, not anchored, not validated on real swaps (criterion A-12 of the V4 protocol
is not passed). It adds one thing to a v4sim result: the sale, on the real CPMM pool, of a position
v4sim leaves ``migrated_unpriced``. v4sim is imported and called, never modified.
"""
VERSION = '0.1-experimental'
