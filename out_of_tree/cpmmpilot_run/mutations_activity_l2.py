"""Mutants of activity_l2.py (v2) (R02 18:02Z): each must make test_activity_l.py FAIL. Offline.
Usage: PYTHONPATH=<deps incl. cpmmpilot 0.2.6> python -B mutations_activity_l.py <out.json>"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = [
    ('threshold_49', "N50_THRESHOLD = 50", "N50_THRESHOLD = 49"),
    ('p_low_0_5', "P_POINT, P_LOW, P_HIGH = (24, 44), 0.388, 0.696", "P_POINT, P_LOW, P_HIGH = (24, 44), 0.5, 0.696"),
    ('p_high_0_8', "P_POINT, P_LOW, P_HIGH = (24, 44), 0.388, 0.696", "P_POINT, P_LOW, P_HIGH = (24, 44), 0.388, 0.8"),
    ('point_ratio_1', "    point = av + au * P_POINT[0] // P_POINT[1]", "    point = av + au"),
    ('invalid_counted', "    point = av + au * P_POINT[0] // P_POINT[1]", "    point = av + ai + au * P_POINT[0] // P_POINT[1]"),
    ('verdict_high_le', "'INFAISABLE' if high < VERDICT_LIMIT", "'INFAISABLE' if high <= VERDICT_LIMIT - 10"),
    ('verdict_low_gt', "else 'U2BIS_A_PROPOSER' if low >= VERDICT_LIMIT", "else 'U2BIS_A_PROPOSER' if low > VERDICT_LIMIT + 50"),
    ('tested_not_crosschecked', "    if set(tested) != set(gtfa_names) or len(tested) != 44:", "    if len(tested) != 44:"),
    ('valid_not_checked', "    if len(valid) != 24 or not set(valid) <= set(tested):", "    if False:"),
    ('single_run_guard_removed', "    if (a.out / RESULT).exists():\n        raise SystemExit('t2_already_run')\n", ""),
    ('stop_swallowed', "        res.update(verdict_run='STOP', error=type(exc).__name__, tag=str(exc)[:120],",
     "        res.update(verdict_run='DONE', error=type(exc).__name__, tag=str(exc)[:120],"),
    ('cap_not_cumulative', "    cap = B.T2_CAP - prior_credits", "    cap = B.T2_CAP"),
    ('partial_not_published', "        if (a.out / PARTIAL).exists():", "        if False:"),
    ('checkpoint_not_passed', "t0_time=t0p, checkpoint=a.out / PARTIAL)", "t0_time=t0p)"),
    ('prior_not_checked', "        raise SystemExit('prior_t2_not_the_anchored_stop')", "        pass"),
    ('retry_twice', "            return self.client.call(method, params)          # a second truncation propagates: STOP",
     "            try:\n                return self.client.call(method, params)\n            except rpc.RpcError:\n                return self.client.call(method, params)"),
    ('retry_on_429', "            if self.retry != 1 or str(exc) != 'response_truncated':", "            if self.retry != 1:"),
    ('retry_not_charged', "            return self.client.call(method, params)          # a second truncation propagates: STOP",
     "            return self.client.transport.request(method, params)          # re-read NOT charged"),
    ('retry_default_1', "RETRY_ON_TRUNCATED = 0\n", "RETRY_ON_TRUNCATED = 1\n"),
    ('verdict_from_180', "                   n50=n_eff(per_pool, valid, invalid, untested),", "                   n50=n_eff(per_pool, valid, invalid, untested, threshold=180),"),
    ('descriptive_verdict_kept', "        d.pop('verdict')\n", ""),
    ('descriptive_missing', "                   descriptive_thresholds=descriptive_thresholds(per_pool, valid, invalid, untested),\n", ""),
]


def run(d):
    return subprocess.run([sys.executable, '-B', '-m', 'pytest', str(d / 'test_activity_l2.py'), '-p', 'no:cacheprovider',
                           '-q', '-x', '-W', 'error'], capture_output=True, text=True).returncode


res = {}
with tempfile.TemporaryDirectory() as tmp:
    for name, old, new in [('_base', None, None)] + M:
        d = Path(tmp) / name
        d.mkdir()
        for f in ('activity_l2.py', 'test_activity_l2.py'):
            shutil.copy(HERE / f, d / f)
        for sub in ('TIME1R_20261124T102126Z', 'TIME2_20261124T102839Z', 'T2_20261124T182222Z'):
            (d / sub).symlink_to(HERE / sub)
        (Path(tmp) / 'cpmmpilot_pkg').exists() or (Path(tmp) / 'cpmmpilot_pkg').symlink_to(HERE.parent / 'cpmmpilot_pkg')
        if old is not None:
            text = (d / 'activity_l2.py').read_text()
            if text.count(old) != 1:
                res[name] = 'INVALID (%d)' % text.count(old)
                continue
            (d / 'activity_l2.py').write_text(text.replace(old, new))
        rc = run(d)
        res[name] = ('PASS' if rc == 0 else 'FAIL') if old is None else ('KILLED' if rc != 0 else 'SURVIVED')
base = res.pop('_base')
killed = sum(v == 'KILLED' for v in res.values())
Path(sys.argv[1]).write_text(json.dumps(dict(base_guard=base, mutants=len(M), killed=killed, results=res), indent=1) + '\n')
print(json.dumps(dict(base=base, killed=killed, mutants=len(M), survived=[k for k, v in res.items() if v != 'KILLED'])))
