import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'n1rot' / 'rotation.py').read_text()
MUT = [
 ("        tvl = 2 * mine[0].quote_before", "        tvl = 2 * mine[-1].quote_before", 'tvl_from_last_swap'),
 ("        tvl = 2 * mine[0].quote_before", "        tvl = mine[0].quote_before", 'tvl_not_doubled'),
 ("    return swap.event.input_amount if swap.side == 'buy' else swap.event.output_amount", "    return swap.event.input_amount", 'sell_counted_on_token_side'),
 ("        mine = [s for s in line.swaps if low <= s.block_time < high]", "        mine = [s for s in line.swaps if low <= s.block_time <= high]", 'day_end_included'),
 ("        mine = [s for s in line.swaps if low <= s.block_time < high]", "        mine = [s for s in line.swaps if low < s.block_time < high]", 'day_start_excluded'),
 ("    return sorted(d['rotation'] for d in days)[DAYS // 2]", "    return sorted(d['rotation'] for d in days)[DAYS // 2 - 1]", 'median_lower'),
 ("    return sorted(d['rotation'] for d in days)[DAYS // 2]", "    return sum(d['rotation'] for d in days) / DAYS", 'mean_not_median'),
 ("        ok = med >= bar", "        ok = med > bar", 'threshold_strict'),
 ("DAY_S, DAYS, MIN_POOLS = 86_400, 7, 3", "DAY_S, DAYS, MIN_POOLS = 86_400, 7, 2", 'min_pools_2'),
 ("    if any(s.block_time >= t0 for s in line.swaps):", "    if False:", 'after_t0_unchecked'),
 ("    if set(pools) != set(NAMED_POOLS):", "    if not set(pools) <= set(NAMED_POOLS):", 'fewer_pools_allowed'),
 ("    if len(set(pools)) != len(pools):", "    if False:", 'twice_allowed'),
 ("(fees.trade_fee_rate + fees.creator_fee_rate)", "(fees.trade_fee_rate)", 'break_even_without_creator_fee'),
 ("    swap_fees = Fraction(2 * LP.HALF", "    swap_fees = Fraction(LP.HALF", 'break_even_one_swap_leg'),
 ("        curve.FEE_DENOMINATOR - fees.protocol_fee_rate - fees.fund_fee_rate, curve.FEE_DENOMINATOR)", "        curve.FEE_DENOMINATOR - fees.protocol_fee_rate, curve.FEE_DENOMINATOR)", 'fund_share_kept_by_lp'),
 ("        return Fraction(15, 100)", "        return Fraction(10, 100)", 'dossier_10'),
 ("    rows = [r for r in u2['selected'] if r['pool'] in NAMED_POOLS]", "    rows = list(u2['selected'])", 'cli_reads_every_pool'),
 ("    lines = PILOT.timelines(out, 'pre', rows)", "    lines = PILOT.timelines(out, 'window', rows)", 'cli_reads_the_window'),
 ("rotation=Fraction(0)))", "rotation=Fraction(1)))", 'empty_day_not_zero'),
 ("    for pool in NAMED_POOLS:                                   # the sheet's order", "    for pool in sorted(NAMED_POOLS):", 'order_not_the_sheet'),
 ("    if type(t0) is not int:", "    if False:", 't0_type_unchecked'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'n1rot' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'n1rot', base / 'n1rot')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'n1rot', work / 'n1rot')
    (work / 'n1rot' / 'rotation.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
