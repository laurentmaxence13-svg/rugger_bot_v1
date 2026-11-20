import shutil, subprocess, sys, json
from pathlib import Path
D, V, M = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
src = (D / 'w1loss' / 'analysis.py').read_text()
MUT = [
 ("if p['rate'] > rate else 0", "if p['rate'] >= rate else 0", 'cf_threshold_inclusive'),
 ("        if row['pool'] not in inside:\n            continue\n", "", 'range_filter_dropped'),
 ("row.get('trial') != TRIAL or ", "", 'trial_filter_dropped'),
 ("or row.get('outcome') != 'closed'", "", 'closed_filter_dropped'),
 ("max(1, math.ceil(q * len(ordered))) - 1", "min(len(ordered) - 1, math.ceil(q * len(ordered)))", 'quantile_rank'),
 ("cost = spent + d['tx_costs'] + d['failed_attempt_costs']", "cost = spent", 'cost_denominator'),
 ("gross_return=d['market_move'] / spent", "gross_return=d['market_move'] / cost", 'gross_on_cost'),
 ("age=row['buy']['slot'] - pool['creation_slot']", "age=row['buy']['slot'] - pool['creation_slot'] + 1", 'age_off_by_one'),
 ("if low <= age < high", "if low < age <= high", 'age_bounds'),
 ("cuts = [0, n // 3, 2 * n // 3, n]", "cuts = [0, n // 3, n // 3 * 2 + 1, n]", 'thirds_cut'),
 ("identical = sorted(map(key, positions['master'])) == sorted(map(key, positions[REFERENCE]))", "identical = True", 'identity_forced'),
 ("if row.get('verified') is not True or", "if False or", 'unverified_accepted'),
 ("if hashlib.sha256(raw).hexdigest() != ledger_sha256:", "if False:", 'ledger_sha_ignored'),
 ("if ledger.get('verdict') != 'PASS' or", "if False or", 'verdict_ignored'),
 ("for r in sorted(tiers)[:-1]]", "for r in sorted(tiers)]", 'cf_includes_highest_tier'),
 ("SEED, DRAWS, MIN_INTERPRETABLE = 20261120, 2_000, 30", "SEED, DRAWS, MIN_INTERPRETABLE = 20261115, 2_000, 30", 'seed_changed'),
 ("SEED, DRAWS, MIN_INTERPRETABLE = 20261120, 2_000, 30", "SEED, DRAWS, MIN_INTERPRETABLE = 20261120, 1_000, 30", 'draws_changed'),
 ("interpretable=len(positions) >= MIN_INTERPRETABLE", "interpretable=len(positions) >= 1", 'interpretable_always'),
 ("cluster=pool.get('creator') or row['pool']", "cluster=row['pool']", 'cluster_is_pool'),
 ("return dict(low=quantile(means, 0.025), high=quantile(means, 0.975)", "return dict(low=min(means), high=max(means)", 'ci_min_max'),
 ("shifted = [dict(p, net_return=r) for p, r in zip(positions, returns)]", "shifted = positions", 'cf_interval_not_shifted'),
 ("raise BreakdownError('position_without_spent_or_rate:' + row['pool'])", "pass", 'rate_guard_dropped'),
 ("fees = d['launchlab_buy_fee'] + d['launchlab_sell_fee']", "fees = d['launchlab_buy_fee'] * 2", 'sell_fee_ignored'),
 ("common = sorted(set(m) & set(p))", "common = sorted(set(m))", 'pairs_not_common'),
 ("if out.exists():", "if False:", 'overwrite_allowed'),
]
results = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w1loss', work / 'w1loss')
    (work / 'w1loss' / 'analysis.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', 'w1loss/tests', '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=work, env={'PYTHONPATH': str(work), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
    results.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(results, indent=0))
print(sum(r['detected'] for r in results), '/', len(results))
