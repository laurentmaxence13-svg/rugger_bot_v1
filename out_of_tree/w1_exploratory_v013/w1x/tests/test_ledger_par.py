"""w1x.ledger_par (0.1.3, R02 0c51450f P1): the explore ledger step in parallel gives the same state and files."""
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

from w1aux import dayj as D
from w1aux import ledger as L
from w1aux import ledger_parallel as LP
from w1x import explore as X
from w1x import ledger_par as LPR
from w1aux.tests.test_ledger import PACK, rehearsal  # noqa: F401  (fixture)
from w1x.tests.test_explore import REFERENCE, chain  # noqa: F401  (fixture)

EXPLORE_012 = 'a182c148af7d33b28b8442fc6d977c4d0cc7f10fa6ccb5e5cef02929be96ad84'


def _tree(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(Path(directory).rglob('*')) if p.is_file()}


def _until_trials(step):
    for name in ('selfcheck', 'export', 'series', 'trials'):
        step(name)


@REFERENCE
def test_parallel_ledger_step_gives_the_same_state_files_and_reading(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    out2 = tmp_path / 'explo_par'
    shutil.copytree(out, out2)
    root2 = out2 / X.STAMP_DIR
    trials = json.loads((root / X.STATE).read_text())['steps']['trials']['digest']
    step('ledger')                                                    # sequential 0.1.2 step
    buffer = io.StringIO()
    argv = ['--step', 'ledger', '--out', str(out2), '--s0', str(json.loads((root2 / X.STATE).read_text())['s0']),
            '--expect-sha', trials]
    assert LPR.main(['step', '--ledger-workers', '2', '--', *argv], out=buffer) == 0
    seq, par = json.loads((root / X.STATE).read_text()), json.loads((root2 / X.STATE).read_text())
    assert seq['steps']['ledger']['digest'] == par['steps']['ledger']['digest']
    assert seq['steps']['ledger']['outputs'] == par['steps']['ledger']['outputs']
    assert _tree(root / 'ledger') == _tree(root2 / 'ledger') and (root / 'ledger' / 'ledger.json').exists()
    assert seq['identities'] == par['identities']                     # explore.py untouched: identities unchanged
    record = json.loads((root2 / LPR.RECORD).read_text())
    assert record['workers'] == 2 and record['calls'] > 0 and record['explore_digest'] == par['steps']['ledger']['digest']
    assert record['code_sha256']['w1x/explore.py'] == EXPLORE_012 and record['memory_guard']['fits']
    assert not (root2 / 'ledger' / LPR.RECORD).exists()
    lines = buffer.getvalue().strip().splitlines()
    assert json.loads(lines[0])['digest'] == par['steps']['ledger']['digest'] and 'ledger_parallel' in json.loads(lines[1])
    for word in ('pnl', 'net_return', 'mean', 'profit'):
        assert word not in buffer.getvalue()
    step('reading')                                                   # the reading follows either ledger alike
    reading_digest = json.loads((root / X.STATE).read_text())['steps']['reading']['digest']
    argv = ['--step', 'reading', '--out', str(out2), '--s0', str(par['s0']), '--expect-sha', par['steps']['ledger']['digest']]
    assert X.main(argv, out=io.StringIO()) == 0
    assert json.loads((root2 / X.STATE).read_text())['steps']['reading']['digest'] == reading_digest
    assert _tree(root / 'lecture') == _tree(root2 / 'lecture')


@REFERENCE
def test_runner_refusals_and_its_memory_guard(chain, monkeypatch):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    trials = json.loads((root / X.STATE).read_text())['steps']['trials']['digest']
    s0 = str(json.loads((root / X.STATE).read_text())['s0'])
    base = ['--out', str(out), '--s0', s0, '--expect-sha', trials]
    for workers in ('1', '0'):
        with pytest.raises(LPR.LedgerParError, match='ledger_workers_must_be_an_integer_of_at_least_2'):
            LPR.main(['step', '--ledger-workers', workers, '--', '--step', 'ledger', *base], out=io.StringIO())
    with pytest.raises(LPR.LedgerParError, match='this_runner_only_runs_the_ledger_step'):
        LPR.main(['step', '--ledger-workers', '2', '--', '--step', 'reading', *base], out=io.StringIO())
    monkeypatch.setattr(D, '_memory_available_mb', lambda: 1)        # the workers guard stops before the step
    with pytest.raises(LPR.LedgerParError, match='parallel_ledger_memory_exceeds_available_no_override'):
        LPR.main(['step', '--ledger-workers', '2', '--', '--step', 'ledger', *base], out=io.StringIO())
    assert not (root / 'ledger').exists() and not (root / LPR.RECORD).exists()
    monkeypatch.undo()
    (root / LPR.RECORD).write_text('{}')
    with pytest.raises(LPR.LedgerParError, match='ledger_parallel_record_exists'):
        LPR.main(['step', '--ledger-workers', '2', '--', '--step', 'ledger', *base], out=io.StringIO())
    assert not (root / 'ledger').exists() and 'ledger' not in json.loads((root / X.STATE).read_text())['steps']


def test_workers_memory_guard_adds_one_largest_pool_per_worker(tmp_path, monkeypatch):
    (tmp_path / 'MANIFEST.json').write_text(json.dumps(dict(pools=[dict(signatures=1000), dict(signatures=40_000)])))
    monkeypatch.setattr(D, '_memory_available_mb', lambda: 100_000)
    memory = LPR.workers_memory_guard(tmp_path, 4)
    sequential = D.BASE_MB + 41_000 * D.KB_PER_SIGNATURE['ledger'] / 1024
    per_worker = D.BASE_MB + 40_000 * D.KB_PER_SIGNATURE['ledger'] / 1024
    assert memory['largest_pool_signatures'] == 40_000 and memory['projected_mb'] == round(round(sequential) + 4 * per_worker)
    monkeypatch.setattr(D, '_memory_available_mb', lambda: int(1.5 * memory['projected_mb']) - 1)
    with pytest.raises(LPR.LedgerParError, match='no_override'):
        LPR.workers_memory_guard(tmp_path, 4)
    monkeypatch.setattr(D, '_memory_available_mb', lambda: None)
    with pytest.raises(LPR.LedgerParError, match='no_override'):
        LPR.workers_memory_guard(tmp_path, 4)


def test_prove_compares_both_ledgers_in_fresh_processes_without_any_result_on_stdout(rehearsal, tmp_path, monkeypatch):
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    buffer = io.StringIO()
    code = LPR.main(['prove', '--pools', str(PACK), '--bundles', str(rehearsal / 'out' / 'bundles'),
                     '--series', str(rehearsal / 'sol_usd.json'), '--workers', '2', '--out', str(tmp_path / 'p')], out=buffer)
    line = json.loads(buffer.getvalue())
    assert code == 0 and line['identical'] is True and line['rc_equal'] is True and line['calls'] > 0
    assert set(line) == set(LPR.PROVE_PRINTED) and line['sequential_sha256'] == line['parallel_sha256']
    assert line['peak_rss_mb']['parent_mb'] > 0 and line['probe_peak_rss_mb'] > 0 and line['recorded_events'] > 0
    assert line['worker_peak_rss_mb'] and set(line['worker_peak_rss_mb']) <= {'worker_0', 'worker_1'} and all(v > 0 for v in line['worker_peak_rss_mb'].values())
    for word in ('pnl', 'return', 'verdict', 'cycles', 'PASS'):
        assert word not in buffer.getvalue()
    with pytest.raises(LPR.LedgerParError, match='output_directory_already_exists'):
        LPR.main(['prove', '--pools', str(PACK), '--bundles', str(rehearsal / 'out' / 'bundles'), '--workers', '2',
                  '--out', str(tmp_path / 'p')], out=io.StringIO())


def test_explore_is_the_0_1_2_file_and_identities_do_not_cover_the_runner():
    assert hashlib.sha256(Path(X.__file__).read_bytes()).hexdigest() == EXPLORE_012
    assert set(X.identities()['w1x']) == {'explore.py', 'reading.py', 'stream_export.py', 'stream_series.py'}
    assert LPR.code_sha256()['w1aux/ledger.py'] == LP.LEDGER_SHA256 == hashlib.sha256(Path(L.__file__).read_bytes()).hexdigest()


def test_needs_no_dotenv(monkeypatch):
    monkeypatch.delenv('RUGGER_NO_DOTENV', raising=False)
    with pytest.raises(LPR.LedgerParError, match='set_RUGGER_NO_DOTENV_1'):
        LPR.main(['prove', '--pools', 'x', '--bundles', 'y', '--workers', '2', '--out', 'z'])


@REFERENCE
def test_control_outside_the_chain_then_byte_comparison_with_the_ledger_step(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    with pytest.raises(LPR.LedgerParError, match='control_must_be_written_outside_the_exploratory_root'):
        LPR.main(['control', '--root', str(root), '--ledger-workers', '2', '--out', str(root / 'ctl')], out=io.StringIO())
    with pytest.raises(LPR.LedgerParError, match='not_an_exploratory_root'):
        LPR.main(['control', '--root', str(out), '--ledger-workers', '2', '--out', str(tmp_path / 'x')], out=io.StringIO())
    before = _tree(root)
    buffer = io.StringIO()
    assert LPR.main(['control', '--root', str(root), '--ledger-workers', '2', '--out', str(tmp_path / 'ctl')], out=buffer) == 0
    assert _tree(root) == before and not (root / 'ledger').exists()  # nothing of the chain is written or changed
    line = json.loads(buffer.getvalue())
    assert set(line) == {'control_ledger_digest', 'rc', 'workers', 'calls', 'peaks', 'seconds', *LPR.MEASURES} and line['rc'] == 0
    assert line['probe_peak_rss_mb'] > 0 and 1 <= len(line['worker_peak_rss_mb']) <= 2 and line['recorded_events'] > 0
    with pytest.raises(LPR.LedgerParError, match='the_chain_ledger_step_is_not_done_yet'):
        LPR.main(['compare', '--root', str(root), '--control', str(tmp_path / 'ctl')], out=io.StringIO())
    step('ledger')                                                    # the chain's own 0.1.2 step, sequential
    buffer = io.StringIO()
    assert LPR.main(['compare', '--root', str(root), '--control', str(tmp_path / 'ctl')], out=buffer) == 0
    result = json.loads(buffer.getvalue())
    assert result['identical'] is True and result['chain_ledger_digest'] == result['control_ledger_digest'] == line['control_ledger_digest']
    (tmp_path / 'ctl' / 'ledger' / 'ledger.md').write_text('changed')
    with pytest.raises(LPR.LedgerParError, match='control_ledger_changed_since_it_was_written'):
        LPR.main(['compare', '--root', str(root), '--control', str(tmp_path / 'ctl')], out=io.StringIO())
    state = json.loads((root / X.STATE).read_text())
    state['identities'] = dict(state['identities'], w1x=dict(state['identities']['w1x'], **{'reading.py': '0' * 64}))
    (root / X.STATE).write_text(json.dumps(state))
    with pytest.raises(LPR.LedgerParError, match='code_identities_differ_from_the_chain'):
        LPR.main(['control', '--root', str(root), '--ledger-workers', '2', '--out', str(tmp_path / 'ctl2')], out=io.StringIO())


@REFERENCE
def test_control_refuses_a_changed_earlier_output(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    _until_trials(step)
    bundle = next((root / 'run' / 'bundles').glob('*.json.gz'))
    bundle.write_bytes(bundle.read_bytes() + b'\0')
    with pytest.raises(LPR.LedgerParError, match='output_changed_since_its_step:run/bundles/'):
        LPR.main(['control', '--root', str(root), '--ledger-workers', '2', '--out', str(tmp_path / 'ctl')], out=io.StringIO())
    assert not (tmp_path / 'ctl').exists()
