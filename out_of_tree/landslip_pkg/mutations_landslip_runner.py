import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
SRC = {f: (D / 'landslip' / f).read_text() for f in ('measure.py', 'guard.py')}
MUT = [
 ("stack and stack[-1] == LAUNCHLAB and not named[-1]:", "LAUNCHLAB in stack and not named[-1]:", 'any_frame_inside_launchlab'),
 ("stack and stack[-1] == LAUNCHLAB and not named[-1]:", "stack and stack[-1] == LAUNCHLAB:", 'several_names_per_frame'),
 ("            failed = 'failed' if tx['meta'].get('err') is not None else 'ok'", "            failed = 'ok'", 'failures_not_counted'),
 ("        if len(raw) == 9 and raw[0] == 3:", "        if len(raw) == 9 and raw[0] == 2:", 'wrong_discriminator'),
 ("    if price == 0:\n        return '0'", "    if price == 0:\n        return '1-10000'", 'zero_price_bucket'),
 ("        if price <= bound:", "        if price < bound:", 'bucket_edges'),
 ("        if event.side == 'buy':", "        if True:", 'sells_counted'),
 ("    if gap <= 4:", "    if gap < 4:", 'gap_edges'),
 ("    if type(manifest_sha256) is not str or manifest_sha256.startswith(HOLDOUT_PREFIX):", "    if type(manifest_sha256) is not str:", 'holdout_accepted'),
 ("    if found != manifest_sha256:", "    if False:", 'manifest_unchecked'),
 ("    events.sort(key=lambda e: (e.slot, e.signature, e.event_index))", "    events.reverse()", 'events_not_ordered'),
 ("        events.extend(e for e in LE.extract_trade_events(tx) if e.pool == archive.pool)", "        events.extend(list(LE.extract_trade_events(tx))[1:])", 'events_dropped'),
]
MUT = [(o, n, name, 'measure.py') for o, n, name in MUT] + [
 ("    return expected * (PPM - guard_ppm) // PPM", "    return -(-expected * (PPM - guard_ppm) // PPM)", 'minimum_rounded_up', 'guard.py'),
 ("    fill = min((buy_exact_in(state, amount, rate) for state in landing_states), key=lambda f: f.amount_out)", "    fill = max((buy_exact_in(state, amount, rate) for state in landing_states), key=lambda f: f.amount_out)", 'buy_best_landing', 'guard.py'),
 ("    if fill.amount_out < minimum(expected, guard_ppm):", "    if fill.amount_out < minimum(expected, BUY_GUARD_SENSITIVITY_PPM):", 'buy_guard_always_5pct', 'guard.py'),
 ("    if fill.amount_out < minimum(expected, guard_ppm):\n        return 'failed', None", "    if False:\n        return 'failed', None", 'buy_guard_never_fails', 'guard.py'),
 ("        if floor is None or failures == SELL_MAX_FAILURES or sale.amount_out >= floor:", "        if floor is None or sale.amount_out >= floor:", 'sale_retries_forever', 'guard.py'),
 ("        if floor is None or failures == SELL_MAX_FAILURES or sale.amount_out >= floor:", "        if True:", 'sale_guard_ignored', 'guard.py'),
 ("        sale = min((sell_exact_in(state, tokens, rate) for state in states), key=lambda s: s.amount_out)", "        sale = max((sell_exact_in(state, tokens, rate) for state in states), key=lambda s: s.amount_out)", 'sale_best_landing', 'guard.py'),
 ("ALLOWED_BUY_GUARDS = (None, BUY_GUARD_PPM, BUY_GUARD_SENSITIVITY_PPM)", "ALLOWED_BUY_GUARDS = (None, 0, 10_000, 30_000, BUY_GUARD_PPM, BUY_GUARD_SENSITIVITY_PPM)", 'any_buy_threshold', 'guard.py'),
 ("BUY_GUARD_PPM = 20_000", "BUY_GUARD_PPM = 30_000", 'primary_not_2pct', 'guard.py'),
]
out = []
for old, new, name, f in MUT:
    src = SRC[f]
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'landslip', work / 'landslip')
    (work / 'landslip' / f).write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'landslip' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
