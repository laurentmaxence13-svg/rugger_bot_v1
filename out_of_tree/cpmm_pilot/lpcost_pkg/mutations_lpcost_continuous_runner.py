import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'lpcost' / 'continuous.py').read_text()
MUT = [
 ("    stake = dq * stake_ppm // 1_000_000", "    stake = 10 ** 8", 'stake_fixed'),
 ("    db, dq = CC._state(line, fees, time_limit=start_time)", "    db, dq = CC._state(line, fees, time_limit=start_time - 3_600)", 'stake_read_earlier'),
 ("    if type(stake_ppm) is not int or not 0 < stake_ppm <= MAX_STAKE_PPM:", "    if type(stake_ppm) is not int or not 0 < stake_ppm:", 'stake_cap_dropped'),
 ("STAKE_PPM = 5_000 ", "STAKE_PPM = 4_000 ", 'stake_0_4_percent'),
 ("    bought, (b0, q0) = min(buys, key=lambda pair: pair[0].output_amount)", "    bought, (b0, q0) = max(buys, key=lambda pair: pair[0].output_amount)", 'entry_best_state'),
 ("        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:", "        if tokens < expected * (1_000_000 - 2 * buy_guard_ppm) // 1_000_000:", 'guard_doubled'),
 ("            charged = (1 + failures.buy) * M.TX", "            charged = M.TX", 'guard_ignores_failures'),
 ("    dep_b, dep_q = min(M._ceil(share0 * b0), tokens), min(M._ceil(share0 * q0), keep)", "    dep_b, dep_q = min(M._floor(share0 * b0), tokens), min(M._floor(share0 * q0), keep)", 'deposit_rounded_down'),
 ("    entry_cost = half - tokens * p_start", "    entry_cost = 0", 'entry_cost_dropped'),
 ("    exit_cost = 2 * share_end * q1 + left_b * p_end + left_q - received", "    exit_cost = 0", 'exit_cost_dropped'),
 ("    costs = entry_cost + exit_cost + tx_cost + rent_lost", "    costs = entry_cost + exit_cost + tx_cost", 'rent_not_a_cost'),
 ("    b1, q1 = min(exits, key=lambda s: Fraction(s[1], s[0]))", "    b1, q1 = max(exits, key=lambda s: Fraction(s[1], s[0]))", 'withdraw_on_best_state'),
 ("    wd_b, wd_q = M._floor(share_end * b1), M._floor(share_end * q1)", "    wd_b, wd_q = M._ceil(share_end * b1), M._ceil(share_end * q1)", 'withdrawal_rounded_up'),
 ("    received = wd_q + left_q + min(candidates)", "    received = wd_q + left_q + max(candidates)", 'sale_best_candidate'),
 ("    share_end = M.share_after_others(line, share0, low_key, M._last_key(line, land_out))", "    share_end = share0", 'others_ignored_at_exit'),
 ("    return M.share_after_others(line, share0, low_key, below), nxt.base_before, nxt.quote_before", "    return share0, nxt.base_before, nxt.quote_before", 'others_ignored_at_marks'),
 ("    nxt = next((s for s in line.swaps if t < s.block_time <= land_out), None)", "    nxt = next((s for s in reversed(line.swaps) if s.block_time <= t), None)", 'mark_before_the_boundary'),
 ("    return 2 * share * quote - Fraction(dep_b * quote, base) - dep_q", "    return share * quote - Fraction(dep_b * quote, base) - dep_q", 'lp_value_not_doubled'),
 ("                 gap_lamports=marks[k + 1] - marks[k] - costs / n_days) for k in range(n_days)]", "                 gap_lamports=marks[k + 1] - marks[k] - (costs if k == 0 else 0)) for k in range(n_days)]", 'costs_on_day_0'),
 ("    gap = marks[-1] - marks[0] - costs", "    gap = marks[-1] - costs", 'gap_without_start_mark'),
 ("    net_abs = received - stake - tx_cost - rent_lost", "    net_abs = received - stake - tx_cost", 'net_without_rent'),
 ("        or (end_time - start_time) % DAY_S:", "        or False:", 'partial_days'),
 ("    half = stake // 2", "    half = stake // 3", 'third_swapped'),
 ("    for k in range(1, n_days):", "    for k in range(2, n_days + 1):", 'marks_shifted'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'lpcost' / 'tests' / 'test_continuous.py'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'lpcost', base / 'lpcost', ignore=shutil.ignore_patterns('__pycache__'))
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'lpcost', work / 'lpcost', ignore=shutil.ignore_patterns('__pycache__'))
    (work / 'lpcost' / 'continuous.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
