import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'livesim' / 'sim.py').read_text()
MUT = [
 ('    if PILOT_POOLS & set(pools):', '    if False:', 'pilot_pools_allowed'),
 ('    if not pools or len(set(pools)) != len(pools):', '    if False:', 'duplicates_allowed'),
 ('    swaps = tuple(s for s in line.swaps if s.block_time <= now)', '    swaps = tuple(line.swaps)', 'future_data_seen'),
 ('    idx = [i for i in G2.decisions_g23(known, txs, b3) if known.swaps[i].block_time >= start]', '    idx = list(G2.decisions_g23(known, txs, b3))', 'signals_before_start'),
 ('            if _slot is None and clock is not None and clock > now:', '            if False:', 'open_positions_valued'),
 ('            if _slot is None and clock is not None and clock > now:', '            if _slot is None and clock is not None and clock > now + 3_600:', 'open_threshold_shifted'),
 ("        return gross, gross - row['net_lamports']", "        return gross, -row['net_lamports']", 'costs_wrong'),
 ("    return 0.0, -row['net_lamports']", '    return 0.0, 0.0', 'refusal_costs_dropped'),
 ("    rows = sorted(closed, key=lambda r: (r['exit_time'], r['pool'], r['decision_index']))", '    rows = list(closed)', 'curve_not_by_exit_time'),
 ('        worst = max(worst, (peak - equity) / peak)', '        worst = max(worst, (peak - equity) / capital)', 'drawdown_on_initial_capital'),
 ('        peak = max(peak, equity)', '        pass', 'peak_never_updated'),
 ("    wins = sum(1 for r in entered if r['net_lamports'] > 0)", "    wins = sum(1 for r in entered if r['net_lamports'] >= 0)", 'zero_counted_as_win'),
 ("    entered = [r for r in rows if r.get('status') in ('entered', 'unpriced_zero_sale')]", '    entered = list(rows)', 'refusals_are_entries'),
 ('CAPITAL_LAMPORTS = 10 * 10 ** 9', 'CAPITAL_LAMPORTS = 1 * 10 ** 9', 'capital_1_sol'),
 ('        days = max(1, math.ceil((t - start) / DAY_S))', '        days = 1', 'n1_one_day_only'),
 ('            pos = K.continuous_position(truncated(line, t), config, start_time=start, end_time=start + days * DAY_S)', '            pos = K.continuous_position(line, config, start_time=start, end_time=start + days * DAY_S)', 'n1_sees_the_future'),
 ('    t = start + step_s\n', '    t = start\n', 'n1_mark_at_start'),
 ("        if not gates[sim.pool]['admitted']:\n            continue", '        if False:\n            continue', 'gate_ignored'),
 ('    if not start < now:', '    if False:', 'now_unchecked'),
 ("    if doc['g23']['primary']['signals'] == 0:", '    if False:', 'zero_message_dropped'),
 ('    return G1.check_vocabulary(doc)\n', '    return doc\n', 'vocabulary_unchecked'),
 ('        union = replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)),', '        union = replace(sim, swaps=tuple(sorted(sim.swaps, key=lambda s: s.key)),', 'n1_without_pre_state'),
 ('    if a.out.exists():', '    if False:', 'out_overwritten'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'livesim' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'livesim', base / 'livesim', ignore=shutil.ignore_patterns('__pycache__'))
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
for old, new, name in MUT:
    assert src.count(old) == 1, name
def one(m):
    old, new, name = m
    work = M / name
    shutil.copytree(D / 'livesim', work / 'livesim', ignore=shutil.ignore_patterns('__pycache__'))
    (work / 'livesim' / 'sim.py').write_text(src.replace(old, new))
    return dict(mutant=name, detected=run(work).returncode != 0)
with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(one, MUT))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
