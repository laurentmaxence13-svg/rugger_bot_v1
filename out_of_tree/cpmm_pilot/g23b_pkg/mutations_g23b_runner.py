"""Mutants of g23b 0.1: python3 mutations_g23b_runner.py PKG PYTHON CWD WORKDIR PATHS [JOBS] (PATHS: g23five 0.1.1 and its dependencies). Each mutant replaces ONE exact string (count == 1) and
must make the tests fail; JOBS mutants run at a time (default 3)."""
import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

F = 'b.py'
MUT = [
 (F, "    if status == ENTERED:\n        d = row.get", "    if status != 'x':\n        d = row.get", 'gross_for_every_status'),
 (F, "        return d['price_move']", "        return d['price_move'] + d['price_impact']", 'gross_includes_impact'),
 (F, "    if status in NO_GROSS:\n        return 0.0", "    if status in NO_GROSS:\n        return row['net_return']", 'no_gross_is_net'),
 (F, "    raise BError('unknown_status:%s' % status)", "    return 0.0", 'unknown_status_tolerated'),
 (F, "        if not d or 'price_move' not in d:", "        if not d:", 'missing_price_move_tolerated'),
 (F, "    if report.get('decision') == 'STOP':", "    if False:", 'stop_tolerated'),
 (F, "    if report['seed'] != seed:", "    if False:", 'seed_unchecked'),
 (F, "    if len(rows) != report['n']:", "    if False:", 'row_count_unchecked'),
 (F, "    if (low, high) != (report['lower_bound_95'], report['upper_bound_95']):", "    if False:", 'control_dropped'),
 (F, "    b_low, b_high = V.stratified_bounds(V.blocks(g_rows, t0, d_days), seed=seed, draws=draws)",
  "    b_low, b_high = V.stratified_bounds(V.blocks(g_rows, t0, d_days), seed=seed + 1, draws=draws)", 'b_other_seed'),
 (F, "    b_low, b_high = V.stratified_bounds(V.blocks(g_rows, t0, d_days), seed=seed, draws=draws)",
  "    b_low, b_high = V.stratified_bounds(V.blocks(rows, t0, d_days), seed=seed, draws=draws)", 'b_on_net'),
 (F, "    rows = G1.counted(rows_doc['primary'])", "    rows = list(rows_doc['primary'])", 'k01_unchecked'),
 (F, "            got += by_day[days[rng.randrange(len(days))]]", "            got += by_day[_k]", 'p4_no_resampling'),
 (F, "        by_day.setdefault(V.day_of(r, t0, d_days), []).append(r)",
  "        by_day.setdefault((r['pool'], V.day_of(r, t0, d_days)), []).append(r)", 'p4_by_pool_day'),
 (F, "    k = max(0, int(V.ALPHA * draws) - 1)", "    k = max(0, int(V.ALPHA * draws))", 'p4_tail_index'),
 (F, "    p4_b = common_day_bounds(g_rows, t0, d_days, seed=seed, draws=draws)",
  "    p4_b = common_day_bounds(rows, t0, d_days, seed=seed, draws=draws)", 'p4_b_on_net'),
 (F, "    p4_net = common_day_bounds(rows, t0, d_days, seed=seed, draws=draws)",
  "    p4_net = common_day_bounds(rows, t0, d_days, seed=seed + 1, draws=draws)", 'p4_other_seed'),
 (F, "               cost=dict(mean=_mean([g['net_return'] - r['net_return'] for g, r in zip(g_rows, rows)]),",
  "               cost=dict(mean=_mean([g['net_return'] for g, r in zip(g_rows, rows)]),", 'cost_is_gross'),
 (F, "{k: _mean([-r['decomposition_share_of_stake'][k] for r in entered])", "{k: _mean([r['decomposition_share_of_stake'][k] for r in entered])", 'cost_sign'),
 (F, "    entered = [r for r in rows if r.get('status') == ENTERED]", "    entered = [r for r in rows if r.get('entered')]", 'zero_sale_as_entered'),
 (F, "    return G1.check_vocabulary(doc)", "    return doc", 'vocabulary_unchecked'),
 (F, "    if a.out.exists():", "    if False:", 'out_overwritten'),
 (F, "    if not days:\n        return None, None", "    if not days:\n        return 0.0, 0.0", 'p4_empty_zero'),
]


def run(pkg, python, cwd, paths):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH='%s:%s' % (pkg, paths))
    cmd = ['unshare', '-rn', 'env', '-i'] + ['%s=%s' % kv for kv in env.items()] + [
        python, '-B', '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', str(Path(pkg) / 'g23b' / 'tests')]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).returncode


def one(args):
    pkg, python, cwd, work, paths, (f, old, new, name) = args
    m = work / name
    shutil.copytree(pkg, m, ignore=shutil.ignore_patterns('__pycache__'))
    p = m / 'g23b' / f
    p.write_text(p.read_text().replace(old, new))
    got = dict(mutant=name, file=f, detected=run(str(m), python, cwd, paths) != 0)
    shutil.rmtree(m)
    return got


if __name__ == '__main__':
    pkg, python, cwd, work, paths = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    jobs = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6].isdigit() else 3
    bad = [name for f, old, new, name in MUT if (Path(pkg) / 'g23b' / f).read_text().count(old) != 1]
    print(len(bad), bad)
    if bad:
        sys.exit(3)
    if '--check' in sys.argv:
        sys.exit(0)
    base = work / 'base'
    shutil.copytree(pkg, base, ignore=shutil.ignore_patterns('__pycache__'))
    if run(str(base), python, cwd, paths) != 0:
        print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
    shutil.rmtree(base)
    with ThreadPoolExecutor(jobs) as ex:
        out = list(ex.map(one, [(pkg, python, cwd, work, paths, m) for m in MUT]))
    print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
