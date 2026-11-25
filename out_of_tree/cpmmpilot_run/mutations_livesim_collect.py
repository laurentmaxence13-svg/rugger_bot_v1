"""Mutants of livesim_collect.py (R04-10, R02 08:43-08:45Z): each must make test_livesim_collect.py FAIL. Offline.
Usage: PYTHONPATH=<deps incl. cpmmpilot 0.2.8.1> python -B mutations_conf_collect.py <out.json>"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
D, A = 'livesim_collect.py', 'activity_l2.py'
M = [
    ('forbidden_unchecked', D, "    if FORBIDDEN & set(pools) or len(set(pools)) != len(pools):", "    if False:"),
    ('universe_file_unchecked', D, "    if sha_of(path) != UNIVERSE_FILE_SHA256:", "    if False:"),
    ('universe_list_unchecked', D, "    if list_sha(pools) != UNIVERSE_LIST_SHA256 or doc.get('ordered_list_sha256') != UNIVERSE_LIST_SHA256:", "    if False:"),
    ('list_l_unchecked', D, "    if sha_of(a.list_l) != LIST_L_SHA256:", "    if False:"),
    ('k_9', D, "K = 8\n", "K = 9\n"),
    ('valid_rechecked_skip', D, "        if r['group'] == 'valid':", "        if False:"),
    ('creation_age_from_now', D, "u2.creation_check((page.get('data') or [None])[0], t0_time=t_start)", "u2.creation_check((page.get('data') or [None])[0], t0_time=t_start + 30 * 86_400)"),
    ('creation_ignored', D, "        if ok:\n            kept.append(r['pool'])", "        if True:\n            kept.append(r['pool'])"),
    ('history_6d', D, "HISTORY_S = 7 * 86_400", "HISTORY_S = 6 * 86_400"),
    ('history_end_shift', D, "start_time=t_start - HISTORY_S, end_time=t_start, phase='pre'", "start_time=t_start - HISTORY_S, end_time=t_start + 1, phase='pre'"),
    ('live_25h', D, "LIVE_S = 24 * 3_600", "LIVE_S = 25 * 3_600"),
    ('poll_1h', D, "POLL_S = 2 * 3_600 ", "POLL_S = 1 * 3_600 "),
    ('margin_0', D, "MARGIN_S = 120", "MARGIN_S = 0"),
    ('open_chunk_not_resumed', D, "        if polls and not polls[-1]['done']:", "        if False:"),
    ('no_catch_up', D, "        done_now.append(chunk['name'])", "        done_now.append(chunk['name'])\n        break"),
    ('min_eligible_2', D, "MIN_ELIGIBLE = 3", "MIN_ELIGIBLE = 2"),
    ('eligible_subset_unchecked', D, "            if not set(el) <= set(pools) or len(set(el)) != len(el):", "            if False:"),
    ('eligible_not_frozen', D, "            if el_cfg.exists() and _read(el_cfg) != dict(pools=el, sha256=list_sha(el)):", "            if False:"),
    ('eligible_not_required', D, "            if a.eligible is None:\n                raise LiveSimStop('poll_needs_eligible')", "            if a.eligible is None:\n                el = pools"),
    ('eligible_sha_unchecked', D, "            if a.eligible_sha is None or sha_of(a.eligible) != a.eligible_sha:", "            if False:"),
    ('history_order_unchecked', D, "        if a.phase == 'poll' and not (a.out / 'HISTORY_DONE.json').exists():", "        if False:"),
    ('history_twice', D, "        if a.phase == 'history' and (a.out / 'HISTORY_DONE.json').exists():", "        if False:"),
    ('qualify_twice', D, "    if (out / 'QUALIFIED.json').exists():\n        raise LiveSimStop('already_qualified')", "    if False:\n        raise LiveSimStop('already_qualified')"),
    ('config_unchecked', D, "        if _read(cfg_path) != cfg:", "        if False:"),
    ('t_start_future', D, "    if a.t_start > now or a.phase == 'qualify' and a.t_start < now - 3_600:", "    if a.phase == 'qualify' and a.t_start < now - 3_600:"),
    ('t_start_old', D, "    if a.t_start > now or a.phase == 'qualify' and a.t_start < now - 3_600:", "    if a.t_start > now:"),
    ('cap_max_25000', D, "CAP_MAX = 20_000", "CAP_MAX = 25_000"),
    ('cap_check_removed', D, "    if not 1_000 <= a.cap <= CAP_MAX:", "    if False:"),
    ('hard_stop_100', D, "HARD_STOP_PCT = 98", "HARD_STOP_PCT = 100"),
    ('stage_g23', D, "stage='livesim', max_credits=cap)", "stage='g23', max_credits=cap)"),
    ('package_guard_removed', D, "    if 'livesim' not in B.STAGES:", "    if False:"),
    ('text_guard_removed', D, "    if LIVESIM_TEXT_SHA256 is None or auth in NOT_COVERING or auth != LIVESIM_TEXT_SHA256:", "    if False:"),
    ('old_texts_accepted', D, "LIVESIM_TEXT_SHA256 is None or auth in NOT_COVERING or auth != LIVESIM_TEXT_SHA256", "LIVESIM_TEXT_SHA256 is None or auth != LIVESIM_TEXT_SHA256"),
    ('wrong_text_accepted', D, "LIVESIM_TEXT_SHA256 is None or auth in NOT_COVERING or auth != LIVESIM_TEXT_SHA256", "LIVESIM_TEXT_SHA256 is None or auth in NOT_COVERING"),
    ('stop_marker_ignored', D, "    if (a.out / 'STOP.json').exists():", "    if False:"),
    ('stop_not_written', D, "        _write(a.out / 'STOP.json', rec)", "        pass"),
    ('retry_off', D, "RETRY_ON_TRUNCATED = 1\n", "RETRY_ON_TRUNCATED = 0\n"),
    ('retry_on_429', A, "            if self.retry != 1 or str(exc) != 'response_truncated':", "            if self.retry != 1:"),
    ('tx_format_removed', D, "        step1.require_tx_format(out, chunk['name'], sel)\n", ""),
]


def run(d):
    return subprocess.run([sys.executable, '-B', '-m', 'pytest', str(d / 'test_livesim_collect.py'), '-p', 'no:cacheprovider',
                           '-q', '-x', '-W', 'error'], capture_output=True, text=True).returncode


res = {}
with tempfile.TemporaryDirectory() as tmp:
    for name, f, old, new in [('_base', None, None, None)] + M:
        d = Path(tmp) / name
        d.mkdir()
        for g in (D, A, 'test_livesim_collect.py', 'AUTORISATION_G23.txt', 'LIVESIM_UNIVERSE.json'):
            shutil.copy(HERE / g, d / g)
        for sub in ('TIME1R_20261124T102126Z',):
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
