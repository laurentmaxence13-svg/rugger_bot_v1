# jointlab 0.1 — joint measure of token selection x buy timing x sell timing

Research only: reads recorded pools, never builds, signs or sends an order. Separate package: nothing in
`statelab` (frozen for the W1 hypotheses) is modified; `jointlab` imports its triggers, exit rules and
probes and checks their frozen fingerprints in its tests.

- **S (selection)**: every pool; lowest third of the causal fee rate; lowest third of curve progress;
  highest third of payers of the first two slots; declared creator not a signer of the creation.
  Thirds are cut on a reference rows file (discovery part) and applied unchanged elsewhere; no outcome is read.
- **A (entry)**: frozen placebo, age 0, age 5 s, DIP and PURGE triggers, progress 65 %, age 600 s.
  One position per pool and entry (first occurrence).
- **V (exit)**: clock 25 s (base), clock 60 s, first real sale, curve flow negative (clock 60 s).
- Base cell: (every pool, placebo, clock 25 s). Plans: `star` (14 cells: each engine alone),
  `combined` (one pre-chosen cell + interaction), `full` (140 cells, descriptive).
- Floors: 30 positions from 20 creator clusters. Holm over the evaluable cells of the plan.
  Each evaluable cell of an analysis adds one trial to the cumulative count N.
- `rows`, `cutoffs`, `counts` print sample sizes only; `analysis` reads the values.
- Reading W1 needs the sha256 of the anchored official verdict AND of the anchored verdict of the frozen
  hypotheses. There is no reader for the P0 visible pack (its 159 trials are closed).

NOT EXECUTED on any real data. To be audited by RUGGER 02 before any use.

Tests (18, offline): `python -B -m pytest -q jointlab/tests -p no:cacheprovider -W error` from the frozen
tree, with `statelab_pkg`, `v3lab_pkg` and v4sim 0.2 on `PYTHONPATH`.
