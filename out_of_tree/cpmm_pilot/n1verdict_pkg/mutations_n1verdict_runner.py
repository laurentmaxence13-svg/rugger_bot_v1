import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'n1verdict' / 'verdict.py').read_text()
MUT = [
 ("        start, end = t0 + k * DAY_S, t0 + (k + 1) * DAY_S", "        start, end = t0 + k * DAY_S, t0 + (k + 2) * DAY_S", 'two_day_positions'),
 ("        start, end = t0 + k * DAY_S, t0 + (k + 1) * DAY_S", "        start, end = t0 + k * DAY_S + 1, t0 + (k + 1) * DAY_S", 'start_shifted'),
 ("    return -(LP.STAKE + tx + rent)", "    return -(LP.STAKE + tx)", 'rent_not_lost'),
 ("    return -(LP.STAKE + tx + rent)", "    return -(LP.STAKE)", 'loss_without_transactions'),
 ("            net = total_loss_lamports(failures)", "            net = total_loss_lamports()", 'loss_ignores_failures'),
 ("            row = dict(pool=line.pool, start_time=start, end_time=end, status='unpriced_total_loss', entered=True,", "            row = dict(pool=line.pool, start_time=start, end_time=end, status='unpriced_total_loss', entered=False,", 'unpriced_not_an_entry'),
 ("            if not _unpriced(err):\n                raise\n", "            if False:\n                raise\n", 'every_error_is_a_loss'),
 ("    return any(isinstance(err, kind) and str(err) == reason for kind, reason in UNPRICED)", "    return any(str(err) == reason for kind, reason in UNPRICED)", 'kind_ignored'),
 ("    (LP.LpCostError, 'exit_state_empty'),\n", "", 'exit_state_empty_not_unpriced'),
 ("    (TL.TimelineError, 'no_pool_state_at_the_landing_point'),\n", "", 'no_state_not_unpriced'),
 ("    if not any(s.block_time < t0 for s in line.swaps):", "    if not line.swaps:", 'pre_t0_unchecked'),
 ("    if [line.pool for line in lines] != list(pools):", "    if set(line.pool for line in lines) != set(pools):", 'order_unchecked'),
 ("    elif high is not None and high < 0:", "    elif high is not None and high < -1:", 'no_go_never'),
 ("    elif low is not None and low > 0 and low_wo is not None and low_wo > 0:", "    elif low is not None and low > 0:", 'no_leave_top_out'),
 ("    if not fl['passed']:\n        decision = 'INCONCLUSIF'\n    elif high is not None and high < 0:\n        decision = 'NO-GO'", "    if high is not None and high < 0:\n        decision = 'NO-GO'\n    elif not fl['passed']:\n        decision = 'INCONCLUSIF'", 'no_go_before_floors'),
 ("    low_wo, high_wo = V.stratified_bounds(V.blocks([r for r in rows if r['pool'] != top], t0, d_days), seed=seed,", "    low_wo, high_wo = V.stratified_bounds(V.blocks(list(rows), t0, d_days), seed=seed,", 'top_pool_kept'),
 ("    seed = int(freeze_sheet_sha256[:8], 16)", "    seed = int(freeze_sheet_sha256[-8:], 16)", 'seed_not_the_sheet_head'),
 ("    if g0_passed is not True:", "    if g0_passed is False:", 'g0_truthy'),
 ("    if type(d_days) is not int or not V.MIN_D <= d_days <= V.MAX_D:", "    if type(d_days) is not int:", 'd_unchecked'),
 ("    if len(pools) < V.MIN_SELECTED or len(set(pools)) != len(pools):", "    if len(pools) < V.MIN_SELECTED:", 'duplicate_pools'),
 ("    use = [dict(r, net_return=r['decomposition_lamports'][field] / LP.STAKE) for r in rows", "    use = [dict(r, net_return=r['decomposition_lamports']['hold_pnl'] / LP.STAKE) for r in rows", 'descriptive_field_fixed'),
 ("guard_50000=dict(buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM)", "guard_50000=dict(buy_guard_ppm=CC.BUY_GUARD_PPM)", 'guard_sensitivity_frozen'),
 ("                     rent_lost=dict(failures=CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)))", "                     rent_lost=dict(failures=CC.Failures(0, 0, 1)))", 'rent_lost_one_cleanup'),
 ("               power=dict(n_entered=len(entered), n_required=target,\n                          flag=V.G1.UNDER_TARGET if len(entered) < target else None))", "               power=dict(n_entered=len(entered), n_required=target, flag=None))", 'power_flag_dropped'),
 ("    return V.G1.check_vocabulary(doc)\n", "    return doc\n", 'vocabulary_unchecked'),
 ("               meaning=MEANING, limits=dict(LIMITS),", "               meaning=MEANING, limits={},", 'limits_dropped'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'n1verdict' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'n1verdict', base / 'n1verdict')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'n1verdict', work / 'n1verdict')
    (work / 'n1verdict' / 'verdict.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
