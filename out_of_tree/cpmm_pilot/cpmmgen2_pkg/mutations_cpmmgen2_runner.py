import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmgen2' / 'rule.py').read_text()
MUT = [
 ("    refs = [j for j in range(i) if line.swaps[j].block_time <= t - R.LOOKBACK_S]", "    refs = [j for j in range(i) if line.swaps[j].block_time < t - R.LOOKBACK_S]", 'ref_boundary'),
 ("    if not refs or len(_window(line, i, R.LOOKBACK_S)) < R.MIN_SWAPS_IN_LOOKBACK:", "    if not refs:", 'activity_ignored'),
 ("    return R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 <= R.DROP", "    return R.spot_after(line, i, fees) / R.spot_after(line, refs[0], fees) - 1 <= R.DROP", 'oldest_reference'),
 ("    return R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 <= R.DROP", "    return R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 <= R.DROP / 2", 'drop_1_5pct'),
 ("    return sum(s.event.output_amount for s in sells if s.depth > 1) / total", "    return sum(s.event.output_amount for s in sells if s.depth >= 1) / total", 'routed_all'),
 ("    sells = [line.swaps[k] for k in _window(line, i, R.LOOKBACK_S) if line.swaps[k].side == 'sell']", "    sells = [line.swaps[k] for k in _window(line, i, R.LOOKBACK_S)]", 'routed_share_counts_buys'),
 ("            if share is not None and share <= m1:", "            if share is not None and share < m1:", 'm1_strict'),
 ("            if share is not None and share <= m1:", "            if share is not None and share >= m1:", 'm1_inverted'),
 ("        if last is not None and swap.block_time - last < R.COOLDOWN_S:\n            continue\n        if drop_event(line, i, fees):", "        if False:\n            continue\n        if drop_event(line, i, fees):", 'g21_cooldown_ignored'),
 ("            if swap.block_time >= start and drop_event(line, i, fees):", "            if drop_event(line, i, fees):", 'm1_before_the_7_days'),
 ("        raise PreregError('no_drop_event_before_t0_non_evaluable')", "        return 0.5", 'm1_default_when_empty'),
 ("        if pending is not None and t > pending + WAIT_S:", "        if pending is not None and t > pending + 2 * WAIT_S:", 'wait_doubled'),
 ("        if not before or sum(quote_flow(line.swaps[k]) for k in recent) <= 0:", "        if not before:", 'flow_ignored'),
 ("        if min(R.spot_after(line, k, fees) for k in recent) >= low_before:", "        if True:", 'new_low_ignored'),
 ("            if (last is None or t - last >= R.COOLDOWN_S) and drop_event(line, i, fees):", "            if drop_event(line, i, fees):", 'g22_cooldown_ignored'),
 ("    if pending is not None:\n        empty += 1", "    if False:\n        empty += 1", 'last_empty_wait_uncounted'),
 ("    return swap.event.input_amount if swap.side == 'buy' else -swap.event.output_amount", "    return swap.event.input_amount if swap.side == 'buy' else swap.event.output_amount", 'flow_sign'),
 ("    candidates = [i for i, s in enumerate(line.swaps) if any(t0 < s.block_time <= t0 + WAIT_S for t0 in triggers)]", "    candidates = list(range(len(line.swaps)))", 'placebo_anywhere'),
 ("    key = key.get('pubkey') if isinstance(key, dict) else key", "    key = key if isinstance(key, str) else None", 'payer_dict_form_lost'),
 ("    return [fee_payer(txs[s.signature]) if s.side == 'buy' else None for s in line.swaps]", "    return [fee_payer(txs[s.signature]) for s in line.swaps]", 'sellers_counted_as_buyers'),
 ("        counts.append(len({payer[i] for i, s in enumerate(line.swaps) if payer[i] and low <= s.block_time < high}))", "        counts.append(len([payer[i] for i, s in enumerate(line.swaps) if payer[i] and low <= s.block_time < high]))", 'b3_not_distinct'),
 ("    return statistics.median(counts)", "    return statistics.mean(counts)", 'b3_mean'),
 ("    if b3 == 0:\n        return []", "    if False:\n        return []", 'b3_zero_entered'),
 ("        if len(distinct) >= BUYERS_MULTIPLIER * b3:", "        if len(distinct) > BUYERS_MULTIPLIER * b3:", 'multiplier_strict'),
 ("BUYERS_MULTIPLIER = 2", "BUYERS_MULTIPLIER = 3", 'multiplier_3'),
 ("        per_pool[line.pool] = sum(1 for i in decide(line) if line.swaps[i].block_time >= start)", "        per_pool[line.pool] = len(decide(line))", 'count_before_7_days'),
 ("    if type(n_before) is not int or n_before < TRIALS_BEFORE_GEN2 or n_before + 1 > TRIAL_CAP_GEN2:", "    if type(n_before) is not int or n_before + 1 > TRIAL_CAP_GEN2:", 'trials_before_170_accepted'),
 ("CONFIRMATION = dict(holm=dict(alpha_family=0.025, first_step=0.025 / 3)", "CONFIRMATION = dict(holm=dict(alpha_family=0.025, first_step=0.025 / 2)", 'holm_first_step_wrong'),
 ("        if p > alpha / (k - rank):\n            break", "        if p > alpha / (k - rank):\n            continue", 'holm_no_stop'),
 ("    full = {name: (1.0 if p is None else p) for name, p in p_values.items()}", "    full = {name: p for name, p in p_values.items() if p is not None}", 'holm_drops_missing_p_R02'),
 ("        return {name: p <= alpha / max(k, 1) for name, p in full.items()}", "        return {name: p <= alpha for name, p in full.items()}", 'bonferroni_uncorrected'),
 ("        low += (sum(rows) / len(rows)) <= 0", "        low += (sum(rows) / len(rows)) < 0", 'p_strict'),
 ("    if r_cp1_verdict == 'NO-GO' and b1_verdict == 'NO-GO':", "    if r_cp1_verdict == 'NO-GO' or b1_verdict == 'NO-GO':", 'elimination_or'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmgen2' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'cpmmgen2', base / 'cpmmgen2')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cpmmgen2', work / 'cpmmgen2')
    (work / 'cpmmgen2' / 'rule.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
