import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'plbench' / 'bench.py').read_text()
MUT = [
 ("    if record['status'] == RT.COMPLETE:\n        return gate.trade.result", "    if True:\n        return gate.trade.result", 'incomplete_pool_priced'),
 ("        result.outcome = 'counterfactual_divergence'          # open position in an INCOMPLETE pool: valued at 0", "        pass", 'incomplete_position_not_zeroed'),
 ("        self.trade = PC.CostedTrade(pool, strategy, model, quote_mint=quote_mint, options=options)", "        pass", 'costs_not_behind_the_gate'),
 ("passed=s1 >= S1_MIN_COMPLETE,", "passed=s1 >= 0.5,", 's1_threshold'),
 ("        S2_rerun_identical=dict(passed=_sha([records, rows]) == _sha([records2, rows2]) and fingerprint() == start),", "        S2_rerun_identical=dict(passed=True),", 's2_not_checked'),
 ("    s3 = None if not latency_slots else dict(p95=percentile(latency_slots, 95), p99=percentile(latency_slots, 99))", "    s3 = None if not latency_slots else dict(p95=percentile(latency_slots, 50), p99=percentile(latency_slots, 99))", 's3_median'),
 ("                        passed=bool(s3 is not None and s3['p95'] <= S3_P95_MAX_SLOTS)),", "                        passed=bool(s3 is None or s3['p95'] <= S3_P95_MAX_SLOTS)),", 's3_not_fail_closed'),
 ("        S4_no_signer=dict(passed=not [m for m in FORBIDDEN_MODULES if m in sys.modules]),", "        S4_no_signer=dict(passed=True),", 's4_not_checked'),
 ("passed=s5 <= S5_MAX_STALE),", "passed=True),", 's5_not_checked'),
 ("    passed = all(checks[k]['passed'] for k in ('S1_coverage', 'S2_rerun_identical', 'S3_latency', 'S4_no_signer',", "    passed = all(checks[k]['passed'] for k in ('S2_rerun_identical', 'S3_latency', 'S4_no_signer',", 'success_ignores_s1'),
 ("    if state.get('fingerprint') != fingerprint_t0:", "    if False:", 'stop0_removed'),
 ("    if state['credits_used'] >= STOP_CREDITS_SHARE * state['credits_cap']:", "    if state['credits_used'] > state['credits_cap']:", 'stop1_at_100_percent'),
 ("    if scan_for_secrets(state.get('log_lines', ())):", "    if False:", 'stop3_removed'),
 ("    if state['incomplete_share_24h'] > STOP_INCOMPLETE_24H:", "    if False:", 'stop4_removed'),
 ("    if abs(state['clock_drift_s']) > STOP_CLOCK_DRIFT_S:", "    if state['clock_drift_s'] > STOP_CLOCK_DRIFT_S:", 'stop6_one_sided'),
 ("SECRET_MARKERS = ('api-key=', 'api_key=', 'apikey=', 'authorization:', 'bearer ', 'private_key', 'secret_key',", "SECRET_MARKERS = ('api_key=', 'apikey=', 'private_key', 'secret_key',", 'secret_markers_missing'),
 ("        if i in drop:\n            continue", "        if False:\n            continue", 'drop_fault_ignored'),
]
base = subprocess.run([V, '-B', '-m', 'pytest', str(D / 'plbench' / 'tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                      cwd=W, env={'PYTHONPATH': f'{PP}:{D}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                      capture_output=True, text=True, timeout=900)
if base.returncode != 0:
    print(base.stdout[-2000:], base.stderr[-2000:])
    raise SystemExit('baseline_does_not_pass: no mutant is run')
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'plbench', work / 'plbench')
    (work / 'plbench' / 'bench.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'plbench' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=900)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
