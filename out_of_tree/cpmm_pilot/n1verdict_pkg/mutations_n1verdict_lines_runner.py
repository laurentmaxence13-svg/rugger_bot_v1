import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'n1verdict' / 'lines.py').read_text()
MUT = [
 ("            if side == 'pre' and when >= t0:", "            if side == 'pre' and when > t0:", 'pre_t0_second_allowed'),
 ("            if side == 'window' and not t0 <= when < t0 + d_days * N.DAY_S:", "            if side == 'window' and not t0 <= when <= t0 + d_days * N.DAY_S:", 'window_end_included'),
 ("            if side == 'window' and not t0 <= when < t0 + d_days * N.DAY_S:", "            if side == 'window' and not t0 - 3_600 <= when < t0 + d_days * N.DAY_S:", 'window_start_earlier'),
 ("    if set(pre) & set(window):", "    if False:", 'both_sides_allowed'),
 ("    if not pages:\n        raise LinesError('no_%s_page' % side)", "    if False:\n        raise LinesError('no_%s_page' % side)", 'empty_side_allowed'),
 ("            if type(when) is not int:\n                raise LinesError('transaction_without_block_time')", "            if when is None:\n                when = t0 - 1", 'missing_time_tolerated'),
 ("            for p in pools]", "            for p in sorted(pools)]", 'order_not_the_sheet'),
 ("    if missing:\n        raise LinesError('a_named_pool_is_missing_from_the_selection')", "    if False:\n        raise LinesError('a_named_pool_is_missing_from_the_selection')", 'missing_pool_tolerated'),
 ("    if a.result.exists():\n        raise LinesError('result_exists')", "    if False:\n        raise LinesError('result_exists')", 'result_overwritten'),
 ("    if u2.get('t0_time') != T0:", "    if False:", 't0_unchecked'),
 ("    if hashlib.sha256('\\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:", "    if False:", 'list_sha_unchecked'),
 ("g0_passed=a.g0 == 'passed'", "g0_passed=True", 'g0_ignored'),
 ("    lines = lines_for(rows, a.pre_root, a.window_root, pools=POOLS, t0=T0, d_days=D_DAYS)", "    lines = lines_for(rows, a.pre_root, a.window_root, pools=POOLS, t0=T0, d_days=D_DAYS + 2)", 'window_length_wrong'),
 ("    return TL.build(pool, {**pre, **window}, base_mint=base_mint)", "    return TL.build(pool, window, base_mint=base_mint)", 'pre_t0_dropped'),
 ("    print(hashlib.sha256(text.encode()).hexdigest(), a.result)", "    print(hashlib.sha256(text[:-1].encode()).hexdigest(), a.result)", 'printed_sha_wrong'),
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
    (work / 'n1verdict' / 'lines.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
