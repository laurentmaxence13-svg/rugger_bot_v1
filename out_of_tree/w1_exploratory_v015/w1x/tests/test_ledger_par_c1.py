"""w1x.ledger_par 0.1.5, ``step --resumable --c1`` (owner decision 20/11, C1-b + D2): declared rule, failed ledger kept."""
import hashlib
import io
import json
import shutil

import pytest

from w1aux import ledger_c1 as C1
from w1x import explore as X
from w1x import ledger_par as LPR
from w1x.tests.test_explore import REFERENCE, chain  # noqa: F401  (fixture)
from w1x.tests.test_ledger_par import EXPLORE_012, _tree, _until_trials


def _failed_ledger(tmp_path):
    kept = tmp_path / 'ledger_fail_kept' / 'ledger.json'
    kept.parent.mkdir()
    kept.write_text('{"verdict": "FAIL"}')
    return kept, hashlib.sha256(kept.read_bytes()).hexdigest()


@REFERENCE
def test_c1_step_gives_the_sequential_state_and_declares_the_rule(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    out2 = tmp_path / 'explo_c1'
    shutil.copytree(out, out2)
    root2 = out2 / X.STAMP_DIR
    state = json.loads((root2 / X.STATE).read_text())
    argv = ['--step', 'ledger', '--out', str(out2), '--s0', str(state['s0']), '--expect-sha', state['steps']['trials']['digest']]
    step('ledger')                                                    # sequential v7.4 reference (no relabelled row)
    kept, sha = _failed_ledger(tmp_path)
    buffer = io.StringIO()
    assert LPR.main(['step', '--resumable', '--c1', '--failed-ledger', str(kept), '--failed-ledger-sha256', sha, '--',
                     *argv], out=buffer) == 0
    seq, res = json.loads((root / X.STATE).read_text()), json.loads((root2 / X.STATE).read_text())
    assert seq['steps']['ledger']['digest'] == res['steps']['ledger']['digest'] and seq['identities'] == res['identities']
    assert _tree(root / 'ledger') == _tree(root2 / 'ledger')
    record = json.loads((root2 / LPR.RECORD).read_text())
    assert record['mode'] == 'resumable_one_process_c1' and record['code_sha256']['w1x/explore.py'] == EXPLORE_012
    c1 = record['c1']
    assert c1['module'] == 'w1aux/ledger_c1.py' and c1['sha256'] == C1.module_sha256() == record['code_sha256']['w1aux/ledger_c1.py']
    assert c1['outcomes'] == ['open_at_window_end', 'migrated_unpriced'] and 'l. 337' in c1['replaced'] and c1['by']
    assert c1['failed_ledger_kept'] == dict(path=str(kept.resolve()), sha256=sha) and kept.is_file()
    assert json.loads(buffer.getvalue().splitlines()[-1])['ledger_parallel']['c1']['sha256'] == c1['sha256']


@REFERENCE
def test_c1_step_refusals(chain, tmp_path):
    _tmp, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    state = json.loads((root / X.STATE).read_text())
    base = ['--step', 'ledger', '--out', str(out), '--s0', str(state['s0']), '--expect-sha', state['steps']['trials']['digest']]
    kept, sha = _failed_ledger(tmp_path)
    with pytest.raises(LPR.LedgerParError, match='c1_runs_only_with_the_resumable_ledger'):
        LPR.step(2, base, c1=True, failed_ledger=kept, failed_ledger_sha256=sha, out=io.StringIO())
    with pytest.raises(LPR.LedgerParError, match='c1_needs_the_failed_ledger_and_its_anchored_sha256'):
        LPR.main(['step', '--resumable', '--c1', '--', *base], out=io.StringIO())
    with pytest.raises(LPR.LedgerParError, match='failed_ledger_is_not_the_anchored_one'):
        LPR.main(['step', '--resumable', '--c1', '--failed-ledger', str(kept), '--failed-ledger-sha256', '0' * 64, '--', *base],
                 out=io.StringIO())
    (root / 'ledger').mkdir()
    (root / 'ledger' / 'ledger.json').write_text('{"verdict": "FAIL"}')
    with pytest.raises(LPR.LedgerParError, match='move_the_failed_ledger_out_of_ledger_first'):
        LPR.main(['step', '--resumable', '--c1', '--failed-ledger', str(kept), '--failed-ledger-sha256', sha, '--', *base],
                 out=io.StringIO())
    assert 'ledger' not in json.loads((root / X.STATE).read_text())['steps'] and not (root / LPR.RECORD).exists()
