"""statelab: descriptive state study of LaunchLab pool paths (forward liquidation value from causal
decision points). Out of the frozen tree. No policy, no promotion.

Reads a visible-only pack through ``v3lab.pack.Pack`` (anchored manifest, sealed files and W1 slots
refused) and values every probe with ``v4sim`` unchanged (mode M-P, per-actor ledgers, exact
liquidation). Imports the frozen tree, v3lab (pack, features) and v4sim; modifies none of them.

0.2 (RUGGER 02 audit bfb18f0a, framework 243e2cca): the main value of a horizon is the frozen CLOCK
EXIT (sale landing after the frozen clock latency), the reference cell and the placebo are declared
here, the screening rule is declared in ``statelab.table`` and the table counts K trials.
0.2.1 (R02 E-S1 of 63817ac9): a placebo under the sample floors is said automatically in the table;
no rule, no value and no row changes.
0.3 (R02 decision c2157372, Q1): the population is every replayable pool; a pool whose creator is not
signed keeps its declared creator as cluster, else the fee payer of its creation transaction; the
signed-creator sub-population is a sensitivity (``--population signed``) and serves no choice.
"""
VERSION = '0.3'
SCHEMA = 'statelab-rows-v3'
