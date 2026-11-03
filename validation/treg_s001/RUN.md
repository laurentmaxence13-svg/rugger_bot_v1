# T-REG S-001 — T-0002 (RUGGER 01)

- Input: `tests/fixtures/launchlab_sol_pools/MANIFEST.json` at `4f2875d943f970983ee6198cc35931c3f31d380d`,
  SHA-256 `3224686db130e6b8e0c96a0a8e4bc19ad2cb5f62484ae7c0ae5707716b497e5e` (certified PASS by RUGGER 03 in T-0001, #104).
- Command: `python -B validation/treg_s001/run_baseline.py > validation/treg_s001/baseline_report.jsonl`
- Output: `validation/treg_s001/baseline_report.jsonl`, 3 lines, SHA-256 `e9fb617a1038279e08e0d3985c2712d84a72a31019c432f548bd6c66b125c083`.
- Tests: `python -m pytest -q tests/test_launchlab_*.py -p no:cacheprovider -W error` → `53 passed in 0.45s`.
- No network, no provider call, no key. The baseline (buy 0.05 SOL after the 3rd trade, exit after 30 slots)
  is a pipeline check on 3 pools, **not** evidence of an economic edge.

To audit (RUGGER 02): rerun the command at this commit and compare the output SHA-256.
