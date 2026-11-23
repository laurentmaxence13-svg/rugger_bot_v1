import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'w1decomp' / 'decomp.py').read_text()
MUT = [
 ("RENT_LAMPORTS = 2_039_280", "RENT_LAMPORTS = 2_000_000", 'rent_changed'),
 ("    with_rent = [(p['pnl'] - RENT_LAMPORTS) / p['cost'] for p in group]", "    with_rent = [p['pnl'] / p['cost'] for p in group]", 'rent_not_subtracted'),
 ("    total = sum(share[k] for k in COST_ITEMS)", "    total = sum(share[k] for k in COST_ITEMS[1:])", 'impact_left_out_of_total'),
 ("    return dict(gross=p['gross'], impact=p['impact'], curve_fees=p['fees'],", "    return dict(gross=p['gross'], impact=p['slippage'] * 0, curve_fees=p['fees'],", 'impact_zero'),
 ("        if not evaluation_min <= pool['creation_slot'] < evaluation_max:", "        if not evaluation_min <= pool['creation_slot'] <= evaluation_max + 10:", 'range_widened'),
 ("        if row.get('trial') != A.TRIAL or row.get('arm') not in out or row.get('outcome') != 'closed':", "        if row.get('arm') not in out or row.get('outcome') != 'closed':", 'any_trial'),
 ("        if row.get('verified') is not True or 'decomposition' not in row", "        if 'decomposition' not in row", 'unverified_accepted'),
 ("    if ledger.get('verdict') != 'PASS' or ledger.get('mismatches') or ledger.get('w1_report') is not None:", "    if False:", 'ledger_verdict_unchecked'),
 ("        if target > p['sell_slot']:\n            continue", "        if target > p['sell_slot'] + 100:\n            continue", 'profile_after_sale'),
 ("        last = max(i for i in held if events[i].slot <= target)", "        last = min(i for i in held if events[i].slot >= target) if any(events[i].slot >= target for i in held) else held[-1]", 'profile_looks_ahead'),
 ("    ref = _spot(events[k0])", "    ref = _spot(events[k0 - 1 if k0 else 0])", 'reference_before_landing'),
 ("    adverse = next((i for i in held if i > k0 and _spot(events[i]) < ref), None)", "    adverse = next((i for i in held if i > k0 and _spot(events[i]) <= ref), None)", 'adverse_non_strict'),
 ("    peak = max(held, key=lambda i: (_spot(events[i]), -i))", "    peak = max(held, key=lambda i: (_spot(events[i]), i))", 'peak_latest_tie'),
 ("    held = [i for i in range(k0, len(events)) if events[i].slot <= p['sell_slot']]", "    held = [i for i in range(k0, len(events))]", 'held_past_sale'),
 ("    if not 0 <= k0 < len(events) or events[k0].slot > p['buy_slot'] or not k0 <= p['sell_index'] < len(events):", "    if not 0 <= k0 < len(events):", 'indices_unchecked'),
 ("lambda p: trade_class(p['buy_index'] + 1)", "lambda p: trade_class(p['buy_index'])", 'events_before_entry_off_by_one'),
 ("        h = (timelines[p['pool']]['creation_block_time'] // 3600) % 24", "        h = (timelines[p['pool']]['creation_block_time'] // 3600 + 1) % 24", 'hour_shifted'),
 ("    if _sha_file(ledger_path) != ledger_sha256:", "    if False:", 'ledger_sha_unchecked'),
 ("    if _sha_file(bundle_path) != (ledger.get('bundles_sha256') or {}).get('L1'):", "    if False:", 'bundle_sha_unchecked'),
 ("    if manifest_sha != manifest_sha256:", "    if False:", 'manifest_unchecked'),
 ("    if set(wanted) - set(out):", "    if False:", 'missing_pool_accepted'),
 ("    if out.exists():", "    if False:", 'overwrite_allowed'),
 ("        if missing:\n            raise DecompError('pool_without_timeline:%d' % len(missing))", "        if False:\n            pass", 'timeline_missing_accepted'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'w1decomp' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'w1decomp', base / 'w1decomp')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w1decomp', work / 'w1decomp')
    (work / 'w1decomp' / 'decomp.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
