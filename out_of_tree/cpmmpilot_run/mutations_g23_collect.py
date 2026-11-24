"""Mutants of g23_collect.py (R02 20:42Z list): each must make test_g23_collect.py FAIL. Offline.
Usage: PYTHONPATH=<deps incl. cpmmpilot 0.2.8> python -B mutations_g23_collect.py <out.json>"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
D, A = 'g23_collect.py', 'activity_l2.py'
M = [
    # time guard
    ('time_guard_removed', D, "    if now < end:\n        raise SystemExit('window_not_closed')", "    if False:\n        raise SystemExit('window_not_closed')"),
    ('time_guard_le', D, "    if now < end:", "    if now < end - 1:"),
    ('time_guard_one_day_early', D, "    if now < end:", "    if now < end - 86_400:"),
    # owner-text guard
    ('text_guard_removed', D, "    if G23_TEXT_SHA256 is None or auth in NOT_COVERING or auth != G23_TEXT_SHA256:", "    if False:"),
    ('text_none_accepted', D, "G23_TEXT_SHA256 is None or auth in NOT_COVERING or auth != G23_TEXT_SHA256", "auth in NOT_COVERING or (G23_TEXT_SHA256 is not None and auth != G23_TEXT_SHA256)"),
    ('text_wrong_accepted', D, "G23_TEXT_SHA256 is None or auth in NOT_COVERING or auth != G23_TEXT_SHA256", "G23_TEXT_SHA256 is None or auth in NOT_COVERING"),
    ('old_texts_accepted', D, "G23_TEXT_SHA256 is None or auth in NOT_COVERING or auth != G23_TEXT_SHA256", "G23_TEXT_SHA256 is None or auth != G23_TEXT_SHA256"),
    # pool list
    ('pool_removed', D, "         'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh', 'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')", "         'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh')"),
    ('pool_added', D, "'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')", "'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A', '4NX5P7V8gEJydHias47cjUv173FA9pzfDfJNNo2AigJv')"),
    ('pool_check_removed', D, "    if sorted(r['pool'] for r in sel) != sorted(POOLS) or doc['t0_time'] != T0:", "    if doc['t0_time'] != T0:"),
    ('pool_sha_check_removed', D, "    if len(POOLS) != 4 or hashlib.sha256('\\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:", "    if False:"),
    ('u2_check_removed', D, "    if sha_of(a.u2) != U2_SHA256:", "    if False:"),
    # window bounds
    ('start_plus_1', D, "start_time=T0, end_time=end", "start_time=T0 + 1, end_time=end"),
    ('start_minus_1', D, "start_time=T0, end_time=end", "start_time=T0 - 1, end_time=end"),
    ('end_minus_1', D, "start_time=T0, end_time=end", "start_time=T0, end_time=end - 1"),
    ('end_plus_1', D, "start_time=T0, end_time=end", "start_time=T0, end_time=end + 1"),
    ('d_11', D, "D_DAYS = 12 ", "D_DAYS = 11 "),
    ('t0_shift', D, "T0 = 1795515686 ", "T0 = 1795515687 "),
    # cap
    ('cap_33000', D, "CAP = 32_340 ", "CAP = 33_000 "),
    ('stage_step1', D, "stage='g23', max_credits=CAP", "stage='step1', max_credits=CAP"),
    ('package_guard_removed', D, "    if B.G23_CAP != CAP:", "    if False:"),
    # re-read
    ('retry_off', D, "RETRY_ON_TRUNCATED = 1 ", "RETRY_ON_TRUNCATED = 0 "),
    ('retry_twice', A, "            return self.client.call(method, params)          # a second truncation propagates: STOP",
     "            try:\n                return self.client.call(method, params)\n            except rpc.RpcError:\n                return self.client.call(method, params)"),
    ('retry_on_429', A, "            if self.retry != 1 or str(exc) != 'response_truncated':", "            if self.retry != 1:"),
    ('retry_client_bypassed', D, "    client = _retry_client()(inner, RETRY_ON_TRUNCATED)", "    client = inner\n    client.retries = 0"),
    # partial publication
    ('partial_not_published', D, "        s = json.loads(st.read_text()) if st.exists() else dict(pages=0, transactions=0, done=False)", "        s = dict(pages=0, transactions=0, done=False)"),
    ('missing_pools_dropped', D, "        s = json.loads(st.read_text()) if st.exists() else dict(pages=0, transactions=0, done=False)\n        states[pool]",
     "        if not st.exists():\n            continue\n        s = json.loads(st.read_text())\n        states[pool]"),
    ('stop_not_caught', D, "    except Exception as exc:                          # STOP", "    except KeyboardInterrupt as exc:                  # STOP"),
    # 'error_text_echoed' (draft) dropped: equivalent mutant (it added nothing to the output)
    # format guard
    ('tx_format_removed', D, ", tx_format=step1.require_tx_format(a.out / 'window', 'window', sel))", ")"),
    ('out_exists_removed', D, "    if a.out.exists():\n        raise SystemExit('out_exists')", "    if False:\n        raise SystemExit('out_exists')"),
    ('anchor_sha_unchecked', D, "        if not re.fullmatch('[0-9a-f]{64}', h):", "        if False:"),
]


def run(d):
    return subprocess.run([sys.executable, '-B', '-m', 'pytest', str(d / 'test_g23_collect.py'), '-p', 'no:cacheprovider',
                           '-q', '-x', '-W', 'error'], capture_output=True, text=True).returncode


res = {}
with tempfile.TemporaryDirectory() as tmp:
    for name, f, old, new in [('_base', None, None, None)] + M:
        d = Path(tmp) / name
        d.mkdir()
        for g in (D, A, 'test_g23_collect.py', 'AUTORISATION_T1_T2.txt', 'AUTORISATION_T2_BIS.txt'):
            shutil.copy(HERE / g, d / g)
        (d / 'TIME2_20261124T102839Z').symlink_to(HERE / 'TIME2_20261124T102839Z')
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
