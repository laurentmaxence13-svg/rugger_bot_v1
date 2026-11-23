import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'dashx' / 'board.py').read_text()
MUT = [
 ("    if n is None or n < A.MIN_INTERPRETABLE or not interpretable:", "    if n is None or n < 20 or not interpretable:", 'min_n_20'),
 ("    if n is None or n < A.MIN_INTERPRETABLE or not interpretable:", "    if n is None or n < A.MIN_INTERPRETABLE:", 'interpretable_ignored'),
 ("    if high is not None and high < 0:", "    if high is not None and high <= 0:", 'high_bound_non_strict'),
 ("    if placebo:\n        return None", "    if False:\n        return None", 'placebo_gets_a_verdict'),
 ("    for p in sorted(positions, key=lambda q: (q['sell_slot'], q['slot'], q['pool'])):", "    for p in positions:", 'drawdown_unsorted'),
 ("        worst = max(worst, peak - cumulative)", "        worst = max(worst, -cumulative)", 'drawdown_from_zero'),
 ("        profit_factor=(gain / loss) if loss else NM,", "        profit_factor=(gain / (gain + loss)) if loss else NM,", 'profit_factor_wrong'),
 ("    losses = [p['net_return'] for p in positions if p['pnl'] <= 0]", "    losses = [p['net_return'] for p in positions if p['pnl'] < -10 ** 9]", 'losses_empty'),
 ("        robustness=dict(first_half_mean=A._mean([p['net_return'] for p in ordered[:half]]),", "        robustness=dict(first_half_mean=A._mean([p['net_return'] for p in ordered[:half + 1]]),", 'halves_shifted'),
 ("                        mean_without_5_best=A._mean(best[5:]) if n > 5 else NM,", "                        mean_without_5_best=A._mean(best[5:]) if n > 0 else NM,", 'without_best_on_small_n'),
 ("        tier = ventilation['arms']['master']['T1_fee_tiers'].get('12500')", "        tier = ventilation['arms']['master']['T1_fee_tiers'].get('17500')", 'c_a_wrong_tier'),
 ("    interpretable = s.get('interpretable', interval.get('interpretable', True))", "    interpretable = True", 'aggregate_interpretable_forced'),
 ("    if 'mean_fee_return' in s:\n        row['mean_curve_fees'] = s['mean_fee_return']", "    if False:\n        pass", 'c_a_fees_dropped'),
 ("        rows.append(aggregate_row('placebo du palier bas', place, placebo=True,", "        rows.append(aggregate_row('placebo du palier bas', place, placebo=False,", 'low_tier_placebo_verdict'),
 ("        if row['verdict'] not in VERDICTS + (None,):", "        if False:", 'vocabulary_unchecked'),
 ("        raise DashError('input_is_not_the_anchored_one:' + Path(path).name)", "        pass", 'sha_unchecked'),
 ("        if bundle is None or _sha(bundle) != (docs['ledger'].get('bundles_sha256') or {}).get('L1'):", "        if bundle is None:", 'bundle_sha_unchecked'),
 ("    if out.exists():", "    if False:", 'overwrite_allowed'),
 ("        rows.append(blank(name, positions=0, status='aucune position', verdict=None))", "        pass", 'no_position_rows_dropped'),
 ("                      net_at_10_slots=s.get('mean_net_return_latency_10_slots', NM))", "                      net_at_10_slots=NM)", 'latency10_dropped'),
 ("        mean_curve_fees=A._mean([p['fee_return'] for p in positions]), mean_tx=A._mean([p['tx_return'] for p in positions]),", "        mean_curve_fees=A._mean([p['fee_return'] for p in positions]), mean_tx=NM,", 'ledger_tx_dropped'),
 ("        latency_slots=latency if latency is not None else NM,", "        latency_slots=4,", 'latency_hardcoded'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'dashx' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'dashx', base / 'dashx')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'dashx', work / 'dashx')
    (work / 'dashx' / 'board.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
