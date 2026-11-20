"""w1x.ledger_par 0.1.4, ``step --resumable`` (R02 bac856e7, P1-bis): killed then resumed, same state and files."""
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap

import pytest

from w1aux import dayj as D
from w1x import explore as X
from w1x import ledger_par as LPR
from w1x.tests.test_explore import REFERENCE, chain  # noqa: F401  (fixture)
from w1x.tests.test_ledger_par import EXPLORE_012, _tree, _until_trials

_KILLED_STEP = textwrap.dedent('''
    import os, signal, sys
    from w1aux import ledger as L
    from w1x import ledger_par
    original, count = L.derive_l1_plans, [0]
    def derive(*a):
        count[0] += 1
        if count[0] == int(sys.argv[1]):
            os.kill(os.getpid(), signal.SIGKILL)
        return original(*a)
    L.derive_l1_plans = derive
    ledger_par.main(['step', '--resumable', '--', *sys.argv[2:]])
''')


@REFERENCE
def test_resumable_step_killed_then_resumed_gives_the_same_state_files_and_reading(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    out2 = tmp_path / 'explo_res'
    shutil.copytree(out, out2)
    root2 = out2 / X.STAMP_DIR
    state = json.loads((root2 / X.STATE).read_text())
    argv = ['--step', 'ledger', '--out', str(out2), '--s0', str(state['s0']), '--expect-sha', state['steps']['trials']['digest']]
    step('ledger')                                                    # sequential 0.1.2 step, the reference
    done = subprocess.run([sys.executable, '-B', '-c', _KILLED_STEP, '3', *argv], env=dict(os.environ),
                          capture_output=True, text=True)
    assert done.returncode == -signal.SIGKILL, done.stderr[-500:]
    assert not (root2 / 'ledger').exists() and not (root2 / LPR.RECORD).exists()
    assert 'ledger' not in json.loads((root2 / X.STATE).read_text())['steps']
    assert len((root2 / LPR.RESUME_DIR / 'INDEX.jsonl').read_text().splitlines()) == 2
    buffer = io.StringIO()
    assert LPR.main(['step', '--resumable', '--', *argv], out=buffer) == 0          # the same command resumes
    seq, res = json.loads((root / X.STATE).read_text()), json.loads((root2 / X.STATE).read_text())
    assert seq['steps']['ledger']['digest'] == res['steps']['ledger']['digest']
    assert seq['steps']['ledger']['outputs'] == res['steps']['ledger']['outputs'] and seq['identities'] == res['identities']
    assert _tree(root / 'ledger') == _tree(root2 / 'ledger')
    record = json.loads((root2 / LPR.RECORD).read_text())
    assert record['mode'] == 'resumable_one_process' and record['workers'] is None and record['memory_guard'] is None
    assert record['reused'] == 2 and record['computed'] == 2 and record['rejected'] == 0 and record['calls'] == 4
    assert record['resumes'] == 1 and record['resume_dir'].startswith(LPR.RESUME_DIR + '/')
    assert record['code_sha256']['w1x/explore.py'] == EXPLORE_012 and 'w1aux/ledger_resume.py' in record['code_sha256']
    assert record['probe_peak_rss_mb'] > 0 and record['recorded_events'] > 0
    for word in ('pnl', 'net_return', 'mean', 'profit'):
        assert word not in buffer.getvalue()
    argv = ['--step', 'reading', '--out', str(out2), '--s0', str(res['s0']), '--expect-sha', res['steps']['ledger']['digest']]
    step('reading')
    assert X.main(argv, out=io.StringIO()) == 0
    assert _tree(root / 'lecture') == _tree(root2 / 'lecture')
    final = json.loads((root2 / X.STATE).read_text())              # the resume directory is in no digest (R02 95c5e9e7)
    assert (root2 / LPR.RESUME_DIR / 'INDEX.jsonl').is_file()
    hashed = [rel for record in final['steps'].values() for rel in record['outputs']]
    assert hashed and not [rel for rel in hashed if LPR.RESUME_DIR in rel]
    sums = json.loads((root2 / X.SUMS).read_text())
    assert not [rel for rel in sums['outputs'] if LPR.RESUME_DIR in rel] and LPR.RESUME_DIR not in json.dumps(sums)
    assert {k: v['digest'] for k, v in final['steps'].items()} == {
        k: v['digest'] for k, v in json.loads((root / X.STATE).read_text())['steps'].items()}


@REFERENCE
def test_resumable_step_refusals_and_the_explore_memory_guard(chain, monkeypatch):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    state = json.loads((root / X.STATE).read_text())
    base = ['--step', 'ledger', '--out', str(out), '--s0', str(state['s0']), '--expect-sha', state['steps']['trials']['digest']]
    with pytest.raises(SystemExit):                                   # one process or workers, never both
        LPR.main(['step', '--resumable', '--ledger-workers', '2', '--', *base], out=io.StringIO())
    with pytest.raises(LPR.LedgerParError, match='resumable_runs_one_process_without_workers'):
        LPR.step(2, base, resumable=True, out=io.StringIO())
    monkeypatch.setattr(D, '_memory_available_mb', lambda: 1)        # the explore step's own guard, no override
    with pytest.raises(D.DayJError, match='memory_projection_exceeds_available_owner_decision_needed'):
        LPR.main(['step', '--resumable', '--', *base], out=io.StringIO())
    assert not (root / 'ledger').exists() and not (root / LPR.RECORD).exists()
    monkeypatch.undo()
    from w1aux import ledger_resume as LR
    LR.Cache(root / LPR.RESUME_DIR, 'trials:' + '0' * 64)            # a cache left by another trials run
    with pytest.raises(LR.LedgerResumeError, match='resume_dir_is_for_another_run_or_code'):
        LPR.main(['step', '--resumable', '--', *base], out=io.StringIO())
    assert not (root / 'ledger').exists() and not (root / LPR.RECORD).exists()
    assert 'ledger' not in json.loads((root / X.STATE).read_text())['steps']
