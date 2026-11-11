"""statelab: descriptive state study of LaunchLab pool paths (forward liquidation value from causal
decision points). Out of the frozen tree. No policy, no trial, no evaluation of a strategy, no promotion.

Reads a visible-only pack through ``v3lab.pack.Pack`` (anchored manifest, sealed files and W1 slots
refused) and values every probe with ``v4sim`` unchanged (mode M-P, per-actor ledgers, exact
liquidation). Imports the frozen tree, v3lab (pack, features) and v4sim; modifies none of them.
"""
VERSION = '0.1'
SCHEMA = 'statelab-rows-v1'
