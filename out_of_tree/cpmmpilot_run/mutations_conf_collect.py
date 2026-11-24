"""Mutants of conf_collect.py (R04-8, erratum C-169 R02 23:15Z, R04-9): each must make test_conf_collect.py FAIL. Offline.
Usage: PYTHONPATH=<deps incl. cpmmpilot 0.2.8.1> python -B mutations_conf_collect.py <out.json>"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
D, A = 'conf_collect.py', 'activity_l2.py'
M = [
    # time guard and window
    ('time_guard_removed', D, "    if now < end:\n        raise SystemExit('window_not_closed')", "    if False:\n        raise SystemExit('window_not_closed')"),
    ('time_guard_minus_1', D, "    if now < end:", "    if now < end - 1:"),
    ('t1_shift', D, "T1 = T0 + D_DAYS * 86_400 ", "T1 = T0 + D_DAYS * 86_400 + 1 "),
    ('start_plus_1', D, "start_time=T1, end_time=end", "start_time=T1 + 1, end_time=end"),
    ('end_minus_1', D, "start_time=T1, end_time=end", "start_time=T1, end_time=end - 1"),
    ('end_fixed_12', D, "    end = T1 + a.d_days * step1.DAY\n", "    end = T1 + D_DAYS * step1.DAY\n"),
    # durations
    ('c170_not_12', D, "    if a.mode == 'c170' and a.d_days != D_DAYS:", "    if False:"),
    ('dc_bounds_removed', D, "    if a.mode != 'c170' and not DC_MIN <= a.d_days <= DC_MAX:", "    if False:"),
    ('dc_max_31', D, "DC_MIN, DC_MAX = 12, 30 ", "DC_MIN, DC_MAX = 12, 31 "),
    ('dc_min_11', D, "DC_MIN, DC_MAX = 12, 30 ", "DC_MIN, DC_MAX = 11, 30 "),
    # cap
    ('cap_max_1e6', D, "CAP_MAX = 60_000 ", "CAP_MAX = 1_000_000 "),
    ('cap_max_60001', D, "CAP_MAX = 60_000 ", "CAP_MAX = 60_001 "),
    ('cap_check_removed', D, "    if not 1_000 <= a.cap <= CAP_MAX:", "    if False:"),
    ('hard_stop_100', D, "HARD_STOP_PCT = 98 ", "HARD_STOP_PCT = 100 "),
    ('cap_not_used', D, "stage='g23', max_credits=cap)", "stage='g23', max_credits=a.cap)"),
    ('package_guard_removed', D, "    if B.G23_CAP != G23_CAP:", "    if False:"),
    # GO requirement
    ('go_check_removed', D, "    if PILOT_OF_MODE[a.mode] - go_pilots(a.pilot_result):", "    if False:"),
    ('both_needs_one', D, "'both': {'C-169', 'C-170'}}", "'both': {'C-169'}}"),
    ('c170_needs_169', D, "'c170': {'C-170'},", "'c170': {'C-169'},"),
    ('any_verdict_is_go', D, "        if doc.get('verdict') == 'GO_PILOTE':", "        if True:"),
    ('unknown_pilot_accepted', D, "        if doc.get('pilot') not in ('C-169', 'C-170'):", "        if False:"),
    # pools
    ('c170_uses_g23', D, "MODES = {'c169': G23_POOLS, 'c170': N1_POOLS, 'both': G23_POOLS}", "MODES = {'c169': G23_POOLS, 'c170': G23_POOLS, 'both': G23_POOLS}"),
    ('both_uses_n1', D, "MODES = {'c169': G23_POOLS, 'c170': N1_POOLS, 'both': G23_POOLS}", "MODES = {'c169': G23_POOLS, 'c170': N1_POOLS, 'both': N1_POOLS}"),
    ('n1_sha_unchecked', D, " or _pool_sha(N1_POOLS) != N1_LIST_SHA256 or \\\n", " or \\\n"),
    ('g23_sha_unchecked', D, "    if _pool_sha(G23_POOLS) != G23_POOLS_SHA256 or", "    if False or"),
    ('u2_check_removed', D, "    if sha_of(a.u2) != U2_SHA256:", "    if False:"),
    # owner text
    ('text_guard_removed', D, "    if CONF_TEXT_SHA256 is None or auth in NOT_COVERING or auth != CONF_TEXT_SHA256:", "    if False:"),
    ('g23_text_accepted', D, "CONF_TEXT_SHA256 is None or auth in NOT_COVERING or auth != CONF_TEXT_SHA256", "CONF_TEXT_SHA256 is None or auth != CONF_TEXT_SHA256"),
    ('wrong_text_accepted', D, "CONF_TEXT_SHA256 is None or auth in NOT_COVERING or auth != CONF_TEXT_SHA256", "CONF_TEXT_SHA256 is None or auth in NOT_COVERING"),
    # re-read, partial, format
    ('retry_off', D, "RETRY_ON_TRUNCATED = 1\n", "RETRY_ON_TRUNCATED = 0\n"),
    ('retry_on_429', A, "            if self.retry != 1 or str(exc) != 'response_truncated':", "            if self.retry != 1:"),
    ('partial_not_published', D, "        s = json.loads(st.read_text()) if st.exists() else dict(pages=0, transactions=0, done=False)", "        s = dict(pages=0, transactions=0, done=False)"),
    ('stop_not_caught', D, "    except Exception as exc:                          # STOP", "    except KeyboardInterrupt as exc:                  # STOP"),
    ('tx_format_removed', D, ", tx_format=step1.require_tx_format(a.out / 'window', 'window', sel))", ")"),
    ('out_exists_removed', D, "    if a.out.exists():\n        raise SystemExit('out_exists')", "    if False:\n        raise SystemExit('out_exists')"),
    ('anchor_sha_unchecked', D, "        if not re.fullmatch('[0-9a-f]{64}', h):", "        if False:"),
]


def run(d):
    return subprocess.run([sys.executable, '-B', '-m', 'pytest', str(d / 'test_conf_collect.py'), '-p', 'no:cacheprovider',
                           '-q', '-x', '-W', 'error'], capture_output=True, text=True).returncode


res = {}
with tempfile.TemporaryDirectory() as tmp:
    for name, f, old, new in [('_base', None, None, None)] + M:
        d = Path(tmp) / name
        d.mkdir()
        for g in (D, A, 'g23_collect.py', 'test_conf_collect.py', 'AUTORISATION_G23.txt'):
            shutil.copy(HERE / g, d / g)
        for sub in ('TIME2_20261124T102839Z', 'N1ROT_20261124T215521Z'):
            (d / sub).symlink_to(HERE / sub)
        (Path(tmp) / 'cpmmpilot_pkg').exists() or (Path(tmp) / 'cpmmpilot_pkg').symlink_to(HERE.parent / 'cpmmpilot_pkg')
        if old is not None:
            text = (d / f).read_text()
            if text.count(old) != 1:
                res[name] = 'INVALID (%d)' % text.count(old)
                continue
            (d / f).write_text(text.replace(old, new))
        rc = run(d)
        res[name] = ('PASS' if rc == 0 else 'FAIL') if old is None else ('KILLED' if rc != 0 else 'SURVIVED')
base = res.pop('_base')
killed = sum(v == 'KILLED' for v in res.values())
Path(sys.argv[1]).write_text(json.dumps(dict(base_guard=base, mutants=len(M), killed=killed, results=res), indent=1) + '\n')
print(json.dumps(dict(base=base, killed=killed, mutants=len(M), survived=[k for k, v in res.items() if v != 'KILLED'])))
