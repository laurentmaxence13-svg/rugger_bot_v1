"""w1x.explore: the exploratory chain runs the frozen steps, never the evaluation, and marks everything it writes."""
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import backfill_export as bx
from bot.market import w1_collection
from bot.master_v2 import w1_eval
from bot.master_v2 import w1_run as run
from bot.p4 import sol_usd_series as sus
from w1aux import dayj as D
from w1x import explore as X

PACK = Path('tests/fixtures/launchlab_sol_pools')
S0 = 464661843 - w1_collection.WARMUP_SLOTS
FROZEN = (D.STATE, run.evaluate, w1_eval.evaluate_w1, bx.export_pools, bf.read_segment)
REFERENCE = pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason='W1 reference interpreter is CPython 3.12')


@pytest.fixture
def chain(tmp_path, monkeypatch):
    """Collection-side frozen functions replaced by recording doubles (they have their own tests)."""
    monkeypatch.setattr(D, 'FROZEN_TREE', subprocess.run(['git', 'rev-parse', 'HEAD^{tree}'], capture_output=True,
                                                         text=True, check=True).stdout.strip())
    calls, ctl = {}, dict(verify=[dict(ok=True, complete=True, problems=[], manifest_sha256='s' * 64)])

    def export(window_dir, pools_dir, s0, *, pilot_dir, other_runs=()):
        calls['export'] = dict(args=(window_dir, pools_dir, s0, pilot_dir, other_runs),
                               streaming=bx.export_pools is not FROZEN[3], state=D.STATE)
        try:
            run.evaluate(pools_dir, pools_dir, s0, registry_paths=[], registry_path=None, sensitivity_registry_path=None)
        except X.ExploreError as exc:
            calls['evaluate_inside_a_step'] = str(exc)
        shutil.copytree(PACK, pools_dir)
        return dict(pools=len(list(Path(pools_dir).glob('*.json.gz'))))

    def pyth_entries(run_dir, s0):
        calls['pyth_entries'] = dict(args=(run_dir, s0), streaming=getattr(bf.read_segment, 'w1x_streaming', False))
        return []

    def sol_usd_series(entries, study_report, study_sha, out):
        D._selfcheck_series(tmp_path / 'series_doc.json')
        Path(out).write_bytes(gzip.compress((tmp_path / 'series_doc.json').read_bytes(), mtime=0))
        Path(str(out) + '.decoding.json').write_text('{}')
        return sus.load_series(out)

    def verify(window_dir):
        calls.setdefault('verify', []).append(window_dir)
        return dict(ctl['verify'][min(len(calls['verify']), len(ctl['verify'])) - 1])
    monkeypatch.setattr(w1_collection, 'export', export)
    monkeypatch.setattr(run, 'pyth_entries', pyth_entries)
    monkeypatch.setattr(run, 'sol_usd_series', sol_usd_series)
    monkeypatch.setattr(bf, 'verify', verify)
    (tmp_path / 'win').mkdir()
    (tmp_path / 'win' / 'manifest.json').write_text('{"complete": true}')
    (tmp_path / 'study.json').write_text('{"verdict": "ACCEPTED"}')
    gate = dict(launchlab_verify=dict(ok=True, complete=True, problems=[]), coverage_compare=dict(verdict='PASS'),
                launchlab_manifest_sha256=hashlib.sha256((tmp_path / 'win' / 'manifest.json').read_bytes()).hexdigest())
    (tmp_path / 'GATE.json').write_text(json.dumps(gate))
    out = tmp_path / 'explo'
    root = out / X.STAMP_DIR

    def args(name):
        gate_sha = hashlib.sha256((tmp_path / 'GATE.json').read_bytes()).hexdigest()
        return dict(selfcheck=['--workers', '2'], trials=['--workers', '2'],
                    export=['--window-dir', str(tmp_path / 'win'), '--pilot-dir', str(tmp_path / 'pilot'),
                            '--other-run', str(tmp_path / 'sol'), '--gate-json', str(tmp_path / 'GATE.json'),
                            '--gate-json-sha256', gate_sha],
                    series=['--sol-usd-dir', str(tmp_path / 'sol'), '--study-report', str(tmp_path / 'study.json')]).get(name, [])

    def step(name, expect='auto', s0=S0, extra=None):
        argv = ['--step', name, '--out', str(out), '--s0', str(s0), *(args(name) if extra is None else extra)]
        if expect == 'auto' and name in X.STEPS and name != 'selfcheck':
            state = json.loads((root / X.STATE).read_text())
            expect = state['steps'][X.STEPS[X.STEPS.index(name) - 1]]['digest']
        if expect not in (None, 'auto'):
            argv += ['--expect-sha', expect]
        buffer = io.StringIO()
        assert X.main(argv, out=buffer) == 0
        return buffer.getvalue()

    def seed(*names):
        """Pretend the given steps are done (empty outputs), to reach a later step quickly."""
        root.mkdir(parents=True, exist_ok=True)
        state = json.loads((root / X.STATE).read_text()) if (root / X.STATE).exists() else dict(steps={})
        for name in names:
            state['steps'][name] = dict(outputs={}, digest=D.digest({}), details={})
        (root / X.STATE).write_text(json.dumps(state))
    yield tmp_path, out, root, calls, ctl, step, seed
    assert (D.STATE, run.evaluate.__name__, w1_eval.evaluate_w1, bx.export_pools, bf.read_segment) == (
        FROZEN[0], 'evaluate', FROZEN[2], FROZEN[3], FROZEN[4])            # every guard is removed after every test


@REFERENCE
def test_full_exploratory_chain_then_reading(chain, capsys):
    tmp_path, out, root, calls, ctl, step, seed = chain
    printed = {name: step(name) for name in X.STEPS}
    assert capsys.readouterr() == ('', '')                               # nothing but what main writes to its stream
    state = json.loads((root / X.STATE).read_text())
    assert set(state['steps']) == set(X.STEPS) and state['stamp'] == X.STAMP and state['schema'] == X.SCHEMA
    assert sorted(p.name for p in out.iterdir()) == [X.STAMP_DIR]         # everything is under the stamped directory
    assert not list(out.rglob(D.STATE))                                   # and nothing is named like a day-J state
    for name, text in printed.items():
        line = json.loads(text)
        assert set(line) == {'stamp', 'step', 'digest', 'seconds', 'details'} and line['stamp'] == X.STAMP
        assert line['digest'] == state['steps'][name]['digest'] == D.digest(state['steps'][name]['outputs'])
        assert not any(word in text.lower() for word in ('pnl', 'return', 'lamports', 'net_', 'gross', 'win_rate'))
    assert not any(word in json.dumps(state).lower() for word in ('pnl', 'net_return', 'win_rate'))
    # the collection-side steps ran inside the streaming blocks, with the evaluation refused
    assert calls['export']['streaming'] and calls['export']['state'] == X.STATE and calls['pyth_entries']['streaming']
    assert calls['evaluate_inside_a_step'] == 'evaluate_is_refused_this_is_not_the_official_w1_chain'
    assert calls['export']['args'][2] == S0 and calls['export']['args'][4] == (tmp_path / 'sol',)
    assert state['steps']['export']['details']['streaming_export'] and state['steps']['series']['details']['streaming_series']
    assert state['steps']['export']['details']['gate']['gate_json_sha256'] == hashlib.sha256((tmp_path / 'GATE.json').read_bytes()).hexdigest()
    # the trials are the day-J ones: same bundles as the reference selfcheck (same pack, same series)
    trials = state['steps']['trials']['details']
    assert trials['lazy'] and trials['parallel'] and trials['memory_override_anchored'] is None
    assert D._sha_file(root / 'run' / 'bundles' / 'SHA256SUMS.json') == D.SELFCHECK_SUMS_SHA256
    assert not (root / 'run' / 'w1_report.json').exists() and not (root / 'DOSSIER_W1.json').exists()
    ledger = json.loads((root / 'ledger' / 'ledger.json').read_text())
    assert ledger['verdict'] == 'PASS' and ledger['w1_report'] is None
    # the reading, on the frozen pack: the master never enters; one placebo cycle
    doc = json.loads((root / 'lecture' / 'LECTURE_PRELIMINAIRE.json').read_text(encoding='utf-8'))
    start, end = w1_collection.bounds(S0)['evaluation']
    assert doc['stamp'] == X.STAMP and doc['population']['evaluation_min'] == start and doc['population']['evaluation_max'] == end
    assert doc['master']['Q1_positions'] == dict(eligible_manifest_pools=3, excluded_pools=0, replayed_pools=3,
                                                 evaluation_pools=3, pools_outside_the_evaluation_range=0, opened=0,
                                                 cycles_with_entry=0, closed=0, not_closed={}, no_entry=3)
    assert doc['master']['Q2_result_lamports']['net_sum'] is None
    placebo = doc['others']['placebo_random']
    assert (placebo['closed_cycles'], placebo['mean_net_pnl_lamports']) == (1, -3777601.0)
    assert placebo['decomposition_lamports']['identity_residual'] == pytest.approx(0, abs=1e-3)
    assert doc['others']['reference']['closed_cycles'] == 0
    assert doc['inputs']['l1_bundle_sha256'] == ledger['bundles_sha256']['L1'] == D._sha_file(root / 'run' / 'bundles' / 'L1.json.gz')
    # every output and its sha256, stamped
    sums = json.loads((root / X.SUMS).read_text(encoding='utf-8'))
    assert sums['stamp'] == X.STAMP and set(sums['digests']) == set(X.STEPS)
    assert sums['outputs'] == {rel: D._sha_file(root / rel) for rel in sums['outputs']} and len(sums['outputs']) > 15
    assert {'ledger/ledger.json', 'lecture/LECTURE_PRELIMINAIRE.json', 'run/bundles/L1.json.gz', 'sol_usd_series.json.gz',
            'SELFCHECK.json', 'EXCLUSIONS.json'} <= set(sums['outputs'])
    # nothing more can be run, and a changed output is seen
    with pytest.raises(X.ExploreError, match='step_already_done:reading'):
        step('reading')
    (root / 'ledger' / 'ledger.md').write_text('changed')
    state['steps'].pop('reading')
    (root / X.STATE).write_text(json.dumps(state))
    shutil.rmtree(root / 'lecture')
    with pytest.raises(X.ExploreError, match='output_changed_since_its_step:ledger/ledger.md'):
        step('reading')


@pytest.mark.parametrize('name', ['evaluate', 'dossier', 'gate'])
def test_the_official_steps_are_refused(chain, name):
    tmp_path, out, root, calls, ctl, step, seed = chain
    with pytest.raises(X.ExploreError, match=f'{name}_is_refused_this_is_not_the_official_w1_chain'):
        step(name, expect=None)
    assert not out.exists()


def test_no_memory_override_no_dotenv_and_no_day_j_directory(chain, monkeypatch):
    tmp_path, out, root, calls, ctl, step, seed = chain
    with pytest.raises(SystemExit):                                       # the option does not exist here
        step('trials', expect=None, extra=['--memory-override-anchored', 'r02-anchor'])
    monkeypatch.delenv('RUGGER_NO_DOTENV')
    with pytest.raises(X.ExploreError, match='set_RUGGER_NO_DOTENV_1'):
        step('selfcheck')
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    out.mkdir()
    (out / D.STATE).write_text('{}')
    with pytest.raises(X.ExploreError, match='out_is_a_day_j_directory_use_a_separate_one'):
        step('selfcheck')
    with pytest.raises(X.ExploreError, match='workers_must_be_a_positive_integer'):
        step('selfcheck', extra=['--workers', '0'])


def test_export_needs_the_anchored_gate_of_this_window(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    seed('selfcheck')
    good = json.loads((tmp_path / 'GATE.json').read_text())
    with pytest.raises(X.ExploreError, match='export_needs:--gate-json,--gate-json-sha256'):
        step('export', extra=['--window-dir', str(tmp_path / 'win'), '--pilot-dir', str(tmp_path / 'pilot')])
    with pytest.raises(X.ExploreError, match='gate_json_is_not_the_anchored_one'):
        step('export', extra=['--window-dir', str(tmp_path / 'win'), '--pilot-dir', str(tmp_path / 'pilot'),
                              '--gate-json', str(tmp_path / 'GATE.json'), '--gate-json-sha256', '0' * 64])
    for change, error in ((dict(coverage_compare=dict(verdict='FAIL')), 'gate_is_not_a_pass'),
                          (dict(launchlab_verify=dict(ok=True, complete=False)), 'gate_is_not_a_pass'),
                          (dict(launchlab_verify=dict(ok=False, complete=True)), 'gate_is_not_a_pass'),
                          (dict(launchlab_manifest_sha256='1' * 64), 'gate_is_for_another_launchlab_window')):
        (tmp_path / 'GATE.json').write_text(json.dumps(dict(good, **change)))
        with pytest.raises(X.ExploreError, match=error):
            step('export')
    assert 'export' not in calls and not (root / 'pools').exists()
    (tmp_path / 'GATE.json').write_text(json.dumps(good))
    assert json.loads(step('export'))['details']['exclusions']['excluded'] == 0 and calls['export']['streaming']


def test_series_needs_the_same_verification_on_slim_rows(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    seed('selfcheck', 'export')
    ctl['verify'] = [dict(ok=True, complete=True, problems=[], manifest_sha256='s' * 64),
                     dict(ok=True, complete=True, problems=[], manifest_sha256='t' * 64)]
    with pytest.raises(X.ExploreError, match='sol_usd_verification_differs_on_slim_rows'):
        step('series')
    assert 'pyth_entries' not in calls and not (root / 'sol_usd_series.json.gz').exists()
    ctl['verify'] = ctl['verify'][:1]
    assert json.loads(step('series'))['details']['series_sha256'] and calls['pyth_entries']['streaming']
    assert json.loads((root / X.STATE).read_text())['steps']['series']['details']['sol_usd_manifest_sha256'] == 's' * 64


def test_steps_follow_each_other_with_the_previous_digest(chain):
    tmp_path, out, root, calls, ctl, step, seed = chain
    with pytest.raises(X.ExploreError, match='previous_step_not_done:selfcheck'):
        step('export', expect='0' * 64)
    seed('selfcheck')
    with pytest.raises(X.ExploreError, match='export_needs:--expect-sha'):
        step('export', expect=None)
    with pytest.raises(X.ExploreError, match='expect_sha_is_not_the_digest_of:selfcheck'):
        step('export', expect='0' * 64)
    with pytest.raises(X.ExploreError, match='previous_step_not_done:export'):
        step('series', expect='0' * 64)
    step('export')
    with pytest.raises(X.ExploreError, match='step_already_done:export'):
        step('export')
    with pytest.raises(X.ExploreError, match='s0_changed_between_steps'):
        step('series', s0=S0 + 1)
    state = json.loads((root / X.STATE).read_text())
    state['steps']['export']['digest'] = '0' * 64
    (root / X.STATE).write_text(json.dumps(state))
    with pytest.raises(X.ExploreError, match='state_digest_changed:export'):
        step('series', expect='0' * 64)


def test_the_memory_guard_is_never_overridden(chain, monkeypatch):
    tmp_path, out, root, calls, ctl, step, seed = chain
    seed('selfcheck')
    step('export')
    step('series')
    monkeypatch.setattr(D, '_memory_available_mb', lambda: 1)
    with pytest.raises(D.DayJError, match='memory_projection_exceeds_available_owner_decision_needed'):
        step('trials')
    assert not (root / 'run').exists()
    seed('trials')
    with pytest.raises(D.DayJError, match='memory_projection_exceeds_available_owner_decision_needed'):
        step('ledger')
    assert not (root / 'ledger').exists()


def test_identities_cover_this_package(chain, monkeypatch):
    tmp_path, out, root, calls, ctl, step, seed = chain
    ids = X.identities()
    assert set(ids['w1x']) == {'explore.py', 'reading.py', 'stream_export.py', 'stream_series.py'}
    assert ids['w1x']['stream_export.py'] == '38cc82354bcef8ad8be816ec38f8863214b53dbd8c12d9ccdae96c50d399cbf5'
    assert ids['git_tree'] == D.FROZEN_TREE and ids['frozen'] == D.FROZEN
    seed('selfcheck')
    state = json.loads((root / X.STATE).read_text())
    state['identities'] = dict(ids, w1x=dict(ids['w1x'], **{'reading.py': '0' * 64}))
    (root / X.STATE).write_text(json.dumps(state))
    with pytest.raises(X.ExploreError, match='code_identities_changed_between_steps'):
        step('export')


def test_only_listed_technical_details_reach_the_standard_output(tmp_path, monkeypatch):
    record = dict(digest='d' * 64, seconds=1.0, details=dict(verdict='PASS', workers=2, net_return=0.5, pnl_lamports=7,
                                                               summary=dict(mean_pnl_lamports=1), bundles_sha256={}))
    monkeypatch.setattr(X, 'run_step', lambda step, a: record)
    buffer = io.StringIO()
    assert X.main(['--step', 'ledger', '--out', str(tmp_path), '--s0', '1'], out=buffer) == 0
    line = json.loads(buffer.getvalue())
    assert line['details'] == dict(verdict='PASS', workers=2) and 'pnl' not in buffer.getvalue() and '0.5' not in buffer.getvalue()
    assert not {'pnl', 'return', 'net', 'gross', 'mean', 'sum', 'win', 'profit'} & {w for k in X.PRINTED for w in k.split('_')}


def test_a_ledger_that_fails_or_quotes_a_report_stops_the_chain(chain, monkeypatch):
    from w1aux import ledger
    tmp_path, out, root, calls, ctl, step, seed = chain
    seed('selfcheck')
    step('export')
    seed('series', 'trials')
    seen = {}

    def fake(code, verdict, report):
        def main(argv, *, out):
            seen['argv'] = argv
            target = Path(argv[argv.index('--out') + 1])
            target.mkdir(exist_ok=True)
            (target / 'ledger.json').write_text(json.dumps(dict(verdict=verdict, w1_report=report)))
            out.write(json.dumps(dict(verdict=verdict, mismatches=0 if verdict == 'PASS' else 3)) + '\n')
            return code
        return main
    for code, verdict, report, error in ((1, 'FAIL', None, 'ledger_verdict_not_pass'), (0, 'FAIL', None, 'ledger_verdict_not_pass'),
                                         (1, 'PASS', None, 'ledger_verdict_not_pass'),
                                         (0, 'PASS', dict(decision='NO_GO'), 'ledger_quotes_a_w1_report')):
        monkeypatch.setattr(ledger, 'main', fake(code, verdict, report))
        with pytest.raises(X.ExploreError, match=error):
            step('ledger')
        assert 'ledger' not in json.loads((root / X.STATE).read_text())['steps']
        shutil.rmtree(root / 'ledger')
    assert '--report' not in seen['argv'] and seen['argv'][:2] == ['--pools', str(root / 'pools')]
    (root / 'ledger').mkdir()
    with pytest.raises(D.DayJError, match='output_exists:ledger'):
        step('ledger')
