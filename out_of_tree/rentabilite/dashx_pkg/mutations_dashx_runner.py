import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'dashx' / 'board.py').read_text()
MUT = [
 ("    if n is None or n < A.MIN_INTERPRETABLE or not interpretable:", "    if n is None or n < 20 or not interpretable:", 'min_n_20'),
 ("    if n is None or n < A.MIN_INTERPRETABLE or not interpretable:", "    if n is None or n < A.MIN_INTERPRETABLE:", 'interpretable_ignored'),
 ("    if high is not None and high < 0:", "    if high is not None and high <= 0:", 'high_bound_non_strict'),
 ("    if placebo:\n        return None", "    if False:\n        return None", 'placebo_gets_a_verdict'),
 ("    for p in sorted(positions, key=lambda q: (q['sell_slot'], q['slot'], q['pool'])):", "    for p in sorted(positions, key=lambda q: (q['slot'], q['pool'])):", 'dd_entry_order_R02'),
 ("        worst_s, worst_l = max(worst_s, peak_s - stakes), max(worst_l, peak_l - sol)", "        worst_s, worst_l = max(worst_s, -stakes), max(worst_l, -sol)", 'drawdown_from_zero'),
 ("    return dict(stakes=worst_s, sol=worst_l / LAMPORTS_PER_SOL)", "    return dict(stakes=worst_s, sol=worst_l / 10 ** 8)", 'drawdown_sol_units'),
 ("    losses = [r for r in nets if r <= 0]", "    losses = [r for r in nets if r < 0]", 'zero_not_loss_R02'),
 ("    wins = [r for r in nets if r > 0]", "    wins = [r for r in nets if r >= 0]", 'zero_is_a_win'),
 ("        profit_factor=(sum(wins) / negative) if negative else NM,", "        profit_factor=(gain_l / loss_l) if loss_l else NM,", 'pf_in_lamports'),
 ("        profit_factor=(sum(wins) / negative) if negative else NM,", "        profit_factor=(sum(wins) / negative) if negative else 0,", 'pf_no_loss_zero'),
 ("        mean_gross_return=A._mean([(p['gross'] - p['slippage']) / p['spent'] for p in positions]),", "        mean_gross_return=A._mean([p['gross_return'] for p in positions]),", 'gross_without_own_impact'),
 ("        half_1_half_2=dict(first=A._mean([p['net_return'] for p in ordered[:half]]),", "        half_1_half_2=dict(first=A._mean([p['net_return'] for p in ordered[:half + 1]]),", 'halves_shifted'),
 ("    rent_lost = [(p['pnl'] - RENT_LAMPORTS) / p['cost'] for p in positions]", "    rent_lost = [p['pnl'] / p['cost'] for p in positions]", 'rent_not_subtracted'),
 ("    same = (interval.get('low') is not None and interval.get('high') is not None", "    same = (True", 'concordance_always'),
 ("            and abs(interval['high'] - reading['high']) <= reading['rounding'])", "            )", 'concordance_high_ignored'),
 ("        tier = ventilation['arms']['master']['T1_fee_tiers'].get('12500')", "        tier = ventilation['arms']['master']['T1_fee_tiers'].get('17500')", 'c_a_wrong_tier'),
 ("    interpretable = s.get('interpretable', interval.get('interpretable', True))", "    interpretable = True", 'aggregate_interpretable_forced'),
 ("        if row['verdict'] not in VERDICTS + (None,):", "        if False:", 'vocabulary_unchecked'),
 ("    if name is not None and sha256 != EXPECTED_SHA256[name]:", "    if False:", 'expected_sha_unchecked'),
 ("        raise DashError('input_is_not_the_anchored_one:' + Path(path).name)", "        pass", 'file_sha_unchecked'),
 ("        if bundle is None or _sha(bundle) != (docs['ledger'].get('bundles_sha256') or {}).get('L1'):", "        if bundle is None:", 'bundle_sha_unchecked'),
 ("    if out.exists():", "    if False:", 'overwrite_allowed'),
 ("        rows.append(blank(name, positions=0, status='aucune position', verdict=None))", "        pass", 'no_position_rows_dropped'),
 ("    robustness.update(latency_10_slots=s.get('mean_net_return_latency_10_slots', NM),", "    robustness.update(latency_10_slots=NM,", 'latency10_dropped'),
 ("        latency_slots=latency if latency is not None else NM,", "        latency_slots=4,", 'latency_hardcoded'),
 ("    lines = [f'# Tableau de bord étendu — {doc[\"stamp\"]}', '', f'**{doc[\"warning\"]}**', '', '| ' + ' | '.join(head) + ' |',", "    lines = [f'# Tableau de bord étendu — {doc[\"stamp\"]}', '', '| ' + ' | '.join(head) + ' |',", 'md_warning_dropped'),
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
