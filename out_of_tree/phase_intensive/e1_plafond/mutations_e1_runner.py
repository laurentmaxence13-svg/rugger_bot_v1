"""Mutants of e1plafond 0.1: python3 mutations_e1_runner.py ROOT PYTHON CWD WORKDIR FROZEN_TREE
Each mutant replaces ONE exact string (count == 1) of e1plafond/e1.py and must make the tests fail."""
import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

F = 'e1plafond/e1.py'
MUT = [
 ("    if HOLDOUT_PREFIX in str(pools_dir) or sha.startswith(HOLDOUT_PREFIX):", "    if False:", 'holdout_unchecked'),
 ("    if sha != W1_MANIFEST:", "    if False:", 'manifest_unchecked'),
 ("    return no_rent + RENT_LAMPORTS / STAKE, no_rent, convention", "    return no_rent, no_rent, convention", 'rent_dropped'),
 ("        out, convention = min(after, without), 'B'", "        out, convention = after, 'B'", 'convention_A_only'),
 ("    no_rent = (STAKE - out + tx_lamports) / STAKE", "    no_rent = (STAKE - out) / STAKE", 'tx_dropped'),
 ("            if t + h > end:", "            if t + h > end + 3600:", 'censoring_late'),
 ("    if migration_time is not None and migration_time <= end:", "    if False:", 'migration_ignored'),
 ("            row['plafond'] = 'OUVERT' if row['ci_simultaneous'][0] > 0 and share >= OPEN_SHARE else 'FERMÉ'",
  "            row['plafond'] = 'OUVERT' if row['ci_simultaneous'][0] > 0 else 'FERMÉ'", 'open_without_share'),
 ("            row['plafond'] = 'OUVERT' if row['ci_simultaneous'][0] > 0 and share >= OPEN_SHARE else 'FERMÉ'",
  "            row['plafond'] = 'OUVERT' if row['ci95'][0] > 0 and share >= OPEN_SHARE else 'FERMÉ'", 'open_on_ci95'),
 ("        if len(pools) < MIN_POOLS:", "        if len(pools) < 1:", 'min_pools_dropped'),
 ("    if len(costed) < MIN_POOLS:", "    if len(costed) < 1:", 'min_pools_costed_dropped'),
 ("        t = start + b * BLOCK_S + rng.random() * DRAW_S", "        t = start + b * BLOCK_S + rng.random() * BLOCK_S", 'spacing_broken'),
 ("        return self.events[0].state_before() if i < 0 else self.events[i].state_after()",
  "        return self.events[0].state_after() if i < 0 else self.events[i].state_after()", 'before_first_uses_after'),
 ("    return int(hashlib.sha256(declaration_bytes).hexdigest()[:8], 16)",
  "    return int(hashlib.sha256(declaration_bytes).hexdigest()[:7], 16)", 'seed_prefix'),
 ("    z = statistics.NormalDist().inv_cdf(1 - ALPHA / (2 * max(big_k, 1)))",
  "    z = statistics.NormalDist().inv_cdf(1 - ALPHA / 2)", 'no_bonferroni'),
 ("        age = classify(t - facts['start'], AGE) if facts['creation_known'] else 'inconnu'",
  "        age = classify(t - facts['start'], AGE)", 'age_unknown_dropped'),
 ("            moves[h] = dict(m=m, exc=exc, flat=i1 == i0)", "            moves[h] = dict(m=m, exc=abs(m), flat=i1 == i0)", 'excursion_dropped'),
 ("    if len(blocks) > MAX_BLOCKS:", "    if False:", 'no_block_cap'),
]


def run(root, python, cwd, frozen):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH='%s:%s' % (root, frozen))
    cmd = ['unshare', '-rn', 'env', '-i'] + ['%s=%s' % kv for kv in env.items()] + [
        python, '-B', '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', '-W', 'error', str(Path(root) / 'e1plafond' / 'tests')]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).returncode


def one(args):
    root, python, cwd, work, frozen, (old, new, name) = args
    m = work / name
    shutil.copytree(root, m, ignore=shutil.ignore_patterns('__pycache__', 'mutants*'))
    p = m / F
    p.write_text(p.read_text().replace(old, new))
    got = dict(mutant=name, detected=run(str(m), python, cwd, frozen) != 0)
    shutil.rmtree(m)
    return got


if __name__ == '__main__':
    root, python, cwd, work, frozen = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    bad = [name for old, new, name in MUT if (Path(root) / F).read_text().count(old) != 1]
    print(len(bad), bad)
    if bad or '--check' in sys.argv:
        sys.exit(3 if bad else 0)
    if run(root, python, cwd, frozen) != 0:
        print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
    work.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(3) as ex:
        out = list(ex.map(one, [(root, python, cwd, work, frozen, m) for m in MUT]))
    print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
