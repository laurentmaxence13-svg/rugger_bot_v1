"""Mutants of the cap v2 (cpmmpilot 0.2.8.2 budget/rpc, driver g23_collect 0.2, g23_complete) on R02's four points:
python3 mutations_plafond_v2_runner.py ROOT PYTHON CWD WORKDIR PATHS   (ROOT = this plafond_v2 directory; PATHS: the
dependencies of cpmmpilot, colon-separated, WITHOUT the package). Each mutant replaces ONE exact string (count == 1)
and must make the tests fail. EQUIVALENT, not listed: dropping 'ADDENDUM_TEXT_SHA256 is None or' in the driver
(auth != None is always true, the run is refused all the same). The PENDING test (test_the_addendum_is_inscribed) is deselected: it fails on purpose."""
import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUD = 'cpmmpilot0282_pkg/cpmmpilot/budget.py'
RPC = 'cpmmpilot0282_pkg/cpmmpilot/rpc.py'
DRV = 'cpmmpilot_run/g23_collect_v0_2.py'
CMP = 'cpmmpilot_run/g23_complete.py'
MUT = [
 (BUD, "G23_CAP = 88_200 ", "G23_CAP = 88_210 ", 'cap_88210'),
 (BUD, "G23_CAP = 88_200 ", "G23_CAP = 32_340 ", 'cap_old'),
 (BUD, "        if self.credits + cost > self.max_credits:", "        if self.credits > self.max_credits:", 'charge_after_the_call'),
 (BUD, "        if self.credits + cost > self.max_credits:", "        if self.credits + cost >= self.max_credits:", 'cap_exclusive'),
 (RPC, "                                   | ({ADDENDUM_TEXT_SHA256} if ADDENDUM_TEXT_SHA256 else set()))",
  "                                   | {'0' * 64})", 'authorized_gets_another_sha'),
 (DRV, "CAP = 88_200 ", "CAP = 32_340 ", 'driver_cap_old'),
 (DRV, "    if B.G23_CAP != CAP:", "    if False:", 'package_cap_unchecked'),
 (DRV, "    if G23_TEXT_SHA256 is None or base != G23_TEXT_SHA256:", "    if G23_TEXT_SHA256 is None:", 'base_text_unchecked'),
 (DRV, " or auth == G23_TEXT_SHA256 or auth != ADDENDUM_TEXT_SHA256:", " or auth != ADDENDUM_TEXT_SHA256:", 'base_accepted_as_addendum'),
 (DRV, " or auth == G23_TEXT_SHA256 or auth != ADDENDUM_TEXT_SHA256:", " or auth == G23_TEXT_SHA256:", 'any_addendum_accepted'),
 (DRV, "    if ADDENDUM_TEXT_SHA256 is None or auth in NOT_COVERING or", "    if ADDENDUM_TEXT_SHA256 is None or", 'not_covering_dropped'),
 (DRV, "    for k in ('--pkg', '--u2', '--out', '--authorization', '--base-text'):",
  "    p.add_argument('--base-text', type=Path, default=Path('/dev/null'))\n    for k in ('--pkg', '--u2', '--out', '--authorization'):",
  'base_text_optional'),
 (DRV, "               authorization_sha256=live.authorization_sha256, base_text_sha256=base)",
  "               authorization_sha256=live.authorization_sha256)", 'base_sha_not_recorded'),
 (DRV, "    res = dict(schema='g23-collect-v2',", "    res = dict(schema='g23-collect-v1',", 'schema_v1'),
 (CMP, "    if res.get('verdict_run') != 'DONE' or", "    if", 'complete_ignores_stop'),
 (CMP, "            if json.loads(st.read_text()).get('done') is not True:", "            if False:", 'complete_ignores_states'),
 (CMP, " or sorted(res.get('pools') or []) != sorted(pools):", ":", 'complete_ignores_pools'),
 (CMP, "    except (OSError, ValueError):\n        return False\n    if res", "    except (OSError, ValueError):\n        return True\n    if res",
  'complete_true_without_result'),
]


def run(root, python, cwd, paths, f):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH='%s:%s' % (Path(root) / 'cpmmpilot0282_pkg', paths))
    tests = [str(Path(root) / 'cpmmpilot_run' / 'test_g23_collect_v0_2.py')]
    if f in (BUD, RPC):
        tests.append(str(Path(root) / 'cpmmpilot0282_pkg' / 'cpmmpilot' / 'tests'))
    cmd = ['unshare', '-rn', 'env', '-i'] + ['%s=%s' % kv for kv in env.items()] + [
        python, '-B', '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider'] + tests
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).returncode


def one(args):
    root, python, cwd, work, paths, (f, old, new, name) = args
    m = work / name
    shutil.copytree(root, m, ignore=shutil.ignore_patterns('__pycache__', 'mutants*'))
    p = m / f
    p.write_text(p.read_text().replace(old, new))
    got = dict(mutant=name, file=f, detected=run(str(m), python, cwd, paths, f) != 0)
    shutil.rmtree(m)
    return got


if __name__ == '__main__':
    root, python, cwd, work, paths = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    bad = [name for f, old, new, name in MUT if (Path(root) / f).read_text().count(old) != 1]
    print(len(bad), bad)
    if bad or '--check' in sys.argv:
        sys.exit(3 if bad else 0)
    if run(root, python, cwd, paths, BUD) != 0:
        print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
    with ThreadPoolExecutor(3) as ex:
        out = list(ex.map(one, [(root, python, cwd, work, paths, m) for m in MUT]))
    print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
