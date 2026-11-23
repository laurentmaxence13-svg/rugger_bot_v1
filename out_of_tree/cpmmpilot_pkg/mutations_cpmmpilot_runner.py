"""Mutation runner of cpmmpilot (K-1 of R02 audit 0b3a3033): base guard (the unmutated copy must pass), then every
mutant must make the test suite FAIL. Each mutant replaces exactly one occurrence of a code fragment.

  PYTHONPATH=<frozen deps without cpmmpilot_pkg> python -B mutations_cpmmpilot_runner.py --deps-pythonpath <...> --out <json>
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUTANTS = [
    # R02's four survivors of 0.1
    ('charge_after', 'rpc.py', '        self.budget.charge(method, params)              # ledger on disk before the request leaves\n        result = self.transport.request(method, params)\n',
     '        result = self.transport.request(method, params)\n        self.budget.charge(method, params)\n'),
    ('seed_changed', 'u2.py', 'random.Random(int(sha_l[:8], 16)).shuffle(order)', 'random.Random(int(sha_l[:7], 16)).shuffle(order)'),
    ('reserve_50', 'u2.py', 'MIN_RESERVE_LAMPORTS = 100 * 10 ** 9', 'MIN_RESERVE_LAMPORTS = 50 * 10 ** 9'),
    ('floor_ignored', 'u2.py', "verdict = 'INCONCLUSIF' if len(valid) < FLOOR else 'U2_OK'", "verdict = 'U2_OK'"),
    # budget and stop rules
    ('reserve_strict', 'u2.py', 'amount < MIN_RESERVE_LAMPORTS', 'amount <= MIN_RESERVE_LAMPORTS'),
    ('hard_stop_50000', 'budget.py', 'STEP1_HARD_STOP = 49_000', 'STEP1_HARD_STOP = 50_000'),
    ('point2_ge', 'budget.py', 'stop=need > POINT2_LIMIT', 'stop=need >= POINT2_LIMIT + 100'),
    ('gtfa_cost_1', 'budget.py', "'getTransactionsForAddress': 10}", "'getTransactionsForAddress': 1}"),
    ('ledger_not_resumed', 'budget.py', "            self.requests, self.credits = data['requests'], data['credits']\n", ''),
    ('gtfa_limit_unchecked', 'budget.py', "            if type(limit) is not int or not 1 <= limit <= GTFA_MAX_LIMIT:\n                raise BudgetError('gtfa_limit_must_be_1_to_100')\n", ''),
    # U-2
    ('gtfa_fallback', 'u2.py', "        except MethodRefused as exc:\n            raise U2Stop('gtfa_refused_no_fallback:%s' % exc) from exc\n",
     "        except MethodRefused:\n            continue\n"),
    ('launchlab_ignored', 'u2.py', "        if LAUNCHLAB_PROGRAM in parts:\n            return False, 'launchlab_in_creation_transaction'\n", ''),
    ('depth_ignored', 'u2.py', "    if init_depth != 1:\n        return False, 'initialize_not_at_depth_1'\n", ''),
    ('age_6_days', 'u2.py', 'MIN_AGE_S = 7 * 86_400', 'MIN_AGE_S = 6 * 86_400'),
    ('target_25', 'u2.py', 'TARGET, FLOOR = 24, 20', 'TARGET, FLOOR = 25, 20'),
    ('token2022_excluded_again', 'u2.py', "                elif pool in exclude:", "                elif L.TOKEN_2022 in (p['token_0_program'], p['token_1_program']):\n                    continue\n                elif pool in exclude:"),
    ('status_not_checked', 'u2.py', "                if p['status'] & 4:", "                if False:"),
    # step 1
    ('anchor_not_checked', 'step1.py', "            raise Step1Stop('freeze_sheet_not_anchored:%s' % name)", '            pass'),
    ('resume_from_zero', 'step1.py', "        state = read_json(state_path) if state_path.exists() else dict(", "        state = dict("),
    ('g0_forced_true', 'step1.py', 'g0_passed=g0_passed, freeze_sheet_sha256', 'g0_passed=True, freeze_sheet_sha256'),
    ('count_window_wide', 'step1.py', 'if t0_time - DAY <= (s.get(\'blockTime\') or 0) < t0_time', 'if t0_time - 2 * DAY <= (s.get(\'blockTime\') or 0) < t0_time'),
    # live RPC
    ('live_allowed', 'rpc.py', "        raise RpcError('live_rpc_disabled_in_cpmmpilot_0_1')", '        pass'),
]


def run_tests(pkg_root, deps):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH=deps + ':' + str(pkg_root))
    r = subprocess.run([sys.executable, '-B', '-m', 'pytest', str(pkg_root / 'cpmmpilot' / 'tests'), '-p',
                        'no:cacheprovider', '-q', '-x', '-W', 'error'], env=env, capture_output=True, text=True,
                       cwd=os.getcwd())
    return r.returncode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--deps-pythonpath', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / 'base'
        shutil.copytree(HERE, base, ignore=shutil.ignore_patterns('__pycache__'))
        results['_base_guard'] = 'PASS' if run_tests(base, a.deps_pythonpath) == 0 else 'FAIL'
        if results['_base_guard'] != 'PASS':
            raise SystemExit('base_guard_failed')
        for name, fname, old, new in MUTANTS:
            d = Path(tmp) / name
            shutil.copytree(HERE, d, ignore=shutil.ignore_patterns('__pycache__'))
            f = d / 'cpmmpilot' / fname
            text = f.read_text()
            if text.count(old) != 1:
                results[name] = 'INVALID (fragment found %d times)' % text.count(old)
                continue
            f.write_text(text.replace(old, new))
            results[name] = 'KILLED' if run_tests(d, a.deps_pythonpath) != 0 else 'SURVIVED'
    killed = sum(v == 'KILLED' for v in results.values())
    doc = dict(schema='cpmmpilot-mutations-v0.1.1', base_guard=results.pop('_base_guard'), mutants=len(MUTANTS),
               killed=killed, results=results)
    a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')
    print(json.dumps(dict(killed=killed, mutants=len(MUTANTS), survived=[k for k, v in results.items() if v != 'KILLED'])))
    return 0 if killed == len(MUTANTS) else 1


if __name__ == '__main__':
    raise SystemExit(main())
