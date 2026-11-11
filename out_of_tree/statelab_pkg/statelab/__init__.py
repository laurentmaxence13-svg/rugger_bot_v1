"""statelab: descriptive state study of LaunchLab pool paths (forward liquidation value from causal
decision points). Out of the frozen tree. No policy, no promotion.

Reads a visible-only pack through ``v3lab.pack.Pack`` (anchored manifest, sealed files and W1 slots
refused) and values every probe with ``v4sim`` unchanged (mode M-P, per-actor ledgers, exact
liquidation). Imports the frozen tree, v3lab (pack, features) and v4sim; modifies none of them.

0.2 (RUGGER 02 audit bfb18f0a, framework 243e2cca): the main value of a horizon is the frozen CLOCK
EXIT (sale landing after the frozen clock latency), the reference cell and the placebo are declared
here, the screening rule is declared in ``statelab.table`` and the table counts K trials.
"""
VERSION = '0.2'
SCHEMA = 'statelab-rows-v2'
