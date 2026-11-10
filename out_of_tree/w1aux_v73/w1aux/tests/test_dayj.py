"""w1aux.dayj (R02 E1-E9): selfcheck -> gate -> export -> series -> trials -> evaluate -> ledger -> dossier."""
import ast
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
from bot.market import w1_collection
from bot.master_v2 import registry
from bot.master_v2 import w1_run as run
from bot.p4 import sol_usd_series as sus
from w1aux import coverage
from w1aux import dayj as D

PACK = Path('tests/fixtures/launchlab_sol_pools')


def _p0_registry(path, n=25):
    """A registry standing for the P0 one: n distinct pre-registrations on another MANIFEST."""
    for i in range(n):
        registry.register(path, dict(preregistration_sha256=f'{i:064x}', manifest_sha256='p0-manifest',
                                     code_sha256='p0'), registered_at='2026-11-01T00:00:00+00:00')
    return path
S0 = 464661843 - w1_collection.WARMUP_SLOTS
REFERENCE = pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason='W1 reference interpreter is CPython 3.12')


@pytest.fixture
def chain(tmp_path, monkeypatch):
    """Collection-side frozen functions replaced by recording doubles (they have their own frozen tests)."""
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    monkeypatch.setattr(D, 'FROZEN_TREE', subprocess.run(['git', 'rev-parse', 'HEAD^{tree}'], capture_output=True,
                                                         text=True, check=True).stdout.strip())
    calls, ctl = {}, dict(pack=PACK, compare=('PASS', 0), verify=dict(ok=True, complete=True, problems=[]))

    def export(window_dir, pools_dir, s0, *, pilot_dir, other_runs=()):
        calls['export'] = (window_dir, pools_dir, s0, pilot_dir, other_runs)
        shutil.copytree(ctl['pack'], pools_dir)
        return dict(pools=len(list(Path(pools_dir).glob('*.json.gz'))))

    def pyth_entries(run_dir, s0):
        calls['pyth_entries'] = (run_dir, s0)
        return []

    def sol_usd_series(entries, study_report, study_sha, out):
        calls['sol_usd_series'] = (entries, study_report, study_sha, out)
        D._selfcheck_series(tmp_path / 'series_doc.json')
        Path(out).write_bytes(gzip.compress((tmp_path / 'series_doc.json').read_bytes(), mtime=0))
        Path(str(out) + '.decoding.json').write_text('{}')
        return sus.load_series(out)

    def verify(window_dir):
        calls['verify'] = window_dir
        return dict(ctl['verify'])

    def coverage_main(argv, *, out):
        calls['compare'] = argv
        out.write(json.dumps(dict(verdict=ctl['compare'][0])) + '\n')
        return ctl['compare'][1]
    monkeypatch.setattr(w1_collection, 'export', export)
    monkeypatch.setattr(run, 'pyth_entries', pyth_entries)
    monkeypatch.setattr(run, 'sol_usd_series', sol_usd_series)
    monkeypatch.setattr(bf, 'verify', verify)
    monkeypatch.setattr(coverage, 'main', coverage_main)
    (tmp_path / 'win').mkdir()
    (tmp_path / 'win' / 'manifest.json').write_text('{"complete": true}')
    (tmp_path / 'study.json').write_text('{"verdict": "ACCEPTED"}')
    (tmp_path / 'after.json').write_text('{"uuid": "reading-1", "remaining": 1}')
    p0 = _p0_registry(tmp_path / 'p0_registry.jsonl')
    monkeypatch.setattr(D, 'OTHER_REGISTRIES_SHA256', (hashlib.sha256(p0.read_bytes()).hexdigest(),))
    args = dict(selfcheck=['--workers', '2'],
                gate=['--window-dir', str(tmp_path / 'win'), '--coverage-summary', str(tmp_path / 'summary.json'),
                      '--summary-sha256', 'a' * 64, '--after-reading', str(tmp_path / 'after.json')],
                export=['--window-dir', str(tmp_path / 'win'), '--pilot-dir', str(tmp_path / 'pilot'),
                        '--other-run', str(tmp_path / 'sol')],
                series=['--sol-usd-dir', str(tmp_path / 'sol'), '--study-report', str(tmp_path / 'study.json')],
                trials=['--workers', '2'], evaluate=['--n-boot', '200', '--registry', str(tmp_path / 'p0_registry.jsonl')])
    out = tmp_path / 'w1'

    def step(name, expect='auto', s0=S0, extra=None):
        argv = ['--step', name, '--out', str(out), '--s0', str(s0), *(args.get(name, ()) if extra is None else extra)]
        if expect == 'auto' and name != 'selfcheck':
            state = json.loads((out / D.STATE).read_text())
            expect = state['steps'][D.STEPS[D.STEPS.index(name) - 1]]['digest']
        if expect not in (None, 'auto'):
            argv += ['--expect-sha', expect]
        buffer = io.StringIO()
        assert D.main(argv, out=buffer) == 0
        return buffer.getvalue()
    return tmp_path, out, calls, ctl, step


@REFERENCE
def test_full_chain_one_step_at_a_time_then_dossier(chain):
    tmp_path, out, calls, ctl, step = chain
    printed = {name: step(name) for name in D.STEPS}
    state = json.loads((out / D.STATE).read_text())
    assert set(state['steps']) == set(D.STEPS)
    for name in D.STEPS:
        record = state['steps'][name]
        assert json.loads(printed[name])['digest'] == record['digest'] == D.digest(record['outputs'])
    selfcheck = json.loads((out / 'SELFCHECK.json').read_text())
    assert selfcheck['sha256sums_sha256'] == D.SELFCHECK_SUMS_SHA256 and selfcheck['workers'] == 2
    gate = json.loads((out / 'GATE.json').read_text())
    assert gate['coverage_compare']['verdict'] == 'PASS' and gate['owner_after_reading']['content']['uuid'] == 'reading-1'
    assert calls['compare'][calls['compare'].index('--summary-sha256') + 1] == 'a' * 64
    assert calls['export'][2] == S0 and calls['export'][4] == (tmp_path / 'sol',)
    assert calls['pyth_entries'] == (tmp_path / 'sol', S0)
    assert calls['sol_usd_series'][2] == hashlib.sha256((tmp_path / 'study.json').read_bytes()).hexdigest()
    assert json.loads((out / 'EXCLUSIONS.json').read_text())['excluded'] == 0
    trials = state['steps']['trials']['details']
    assert trials['lazy'] and trials['parallel'] and trials['stats']['computed'] == 39 and trials['stats']['reused'] == 0
    assert 'pnl' not in printed['trials'].lower() and 'pnl' not in json.dumps(trials).lower()      # E6: no P&L
    assert state['steps']['evaluate']['details']['decision'] == 'WAIT_INSUFFICIENT_DATA'
    assert state['steps']['evaluate']['details']['n_trials'] == D.N_FOR_DSR == 32
    assert state['steps']['ledger']['details']['verdict'] == 'PASS'
    dossier = json.loads((out / 'DOSSIER_W1.json').read_text())
    assert dossier['cycle_receipt'] == 'PENDING_R02' and dossier['w1_decision'] == 'WAIT_INSUFFICIENT_DATA'
    assert dossier['profitability_demonstrated'] is False                                          # R02 D-3
    assert dossier['profitability_source'] == 'absent_from_frozen_report'
    assert dossier['flags']['master_operational_trade'] is False
    assert not any(k.startswith(('checkpoint/', 'selfcheck/')) for k in dossier['files'])
    # bundles and registry: those of the plain frozen run_trials with the same inputs
    plain = tmp_path / 'plain'
    plain.mkdir()
    run.run_trials(PACK, out / 'sol_usd_series.json.gz', registry_path=plain / 'r.jsonl',
                   sensitivity_registry_path=plain / 's.jsonl', registered_at=trials['registered_at'], out=plain)
    assert (plain / 'bundles' / 'SHA256SUMS.json').read_bytes() == (out / 'run' / 'bundles' / 'SHA256SUMS.json').read_bytes()
    assert (plain / 'r.jsonl').read_bytes() == (out / 'registry_w1.jsonl').read_bytes()


@REFERENCE
def test_expect_sha_gate_order_and_tamper_guards(chain):
    tmp_path, out, calls, ctl, step = chain
    with pytest.raises(D.DayJError, match='previous_step_not_done:selfcheck'):
        step('gate', expect='0' * 64)
    step('selfcheck')
    with pytest.raises(D.DayJError, match=r'gate_needs:--expect-sha'):
        step('gate', expect=None)
    with pytest.raises(D.DayJError, match='expect_sha_is_not_the_digest_of:selfcheck'):
        step('gate', expect='0' * 64)
    ctl['compare'] = ('FAIL', 4)
    with pytest.raises(D.DayJError, match='coverage_compare_not_pass'):
        step('gate')
    ctl['compare'], ctl['verify'] = ('PASS', 0), dict(ok=True, complete=False, problems=[])
    with pytest.raises(D.DayJError, match='launchlab_run_not_verified_or_incomplete'):
        step('gate')
    assert not (out / 'GATE.json').exists()
    ctl['verify'] = dict(ok=True, complete=True, problems=[])
    step('gate')
    with pytest.raises(D.DayJError, match='step_already_done:gate'):
        step('gate', expect=json.loads((out / D.STATE).read_text())['steps']['selfcheck']['digest'])
    step('export')
    victim = out / 'pools' / 'MANIFEST.json'
    victim.write_bytes(victim.read_bytes() + b' ')
    with pytest.raises(D.DayJError, match='output_changed_since_its_step:pools/MANIFEST.json'):
        step('series')
    with pytest.raises(D.DayJError, match='s0_changed'):
        step('series', s0=S0 + 1)


def _pack_with_missing_transaction(root):
    pack = root / 'bad_pack'
    shutil.copytree(PACK, pack)
    manifest = json.loads((pack / 'MANIFEST.json').read_text())
    entry = manifest['pools'][0]
    doc = json.loads(gzip.decompress((pack / entry['file']).read_bytes()))
    doc['transactions'].pop(sorted(doc['transactions'])[-1])
    blob = gzip.compress(json.dumps(doc, sort_keys=True).encode(), mtime=0)
    (pack / entry['file']).write_bytes(blob)
    entry['sha256'] = hashlib.sha256(blob).hexdigest()
    (pack / 'MANIFEST.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return pack


@REFERENCE
def test_more_than_5_percent_excluded_stops_after_export(chain):
    tmp_path, out, calls, ctl, step = chain
    ctl['pack'] = _pack_with_missing_transaction(tmp_path)
    step('selfcheck')
    step('gate')
    with pytest.raises(D.DayJError, match='stop_more_than_5_percent_of_pools_excluded_for_data_defects'):
        step('export')
    excl = json.loads((out / 'EXCLUSIONS.json').read_text())
    assert (excl['pools'], excl['excluded'], excl['stop']) == (3, 1, True)
    assert excl['by_reason']['transactions_missing'] == 1      # reasons counted per pool, several per pool possible
    assert 'export' not in json.loads((out / D.STATE).read_text())['steps']
    assert D.exclusions(PACK) == dict(pools=3, excluded=0, share=0.0, by_reason={}, max_share=0.05, stop=False)


@REFERENCE
def test_selfcheck_refuses_bundles_that_differ_and_identity_guards(chain, monkeypatch):
    tmp_path, out, calls, ctl, step = chain
    with monkeypatch.context() as m:
        m.setattr(D, 'SELFCHECK_SUMS_SHA256', '0' * 64)
        with pytest.raises(D.DayJError, match='selfcheck_bundles_differ_from_the_reference'):
            step('selfcheck')
    assert 'selfcheck' not in D._load_state(out)['steps']
    shutil.rmtree(out / 'selfcheck')
    for attr, value, match in (('FROZEN_TREE', '0' * 40, 'checkout_is_not_the_frozen_tree'),
                               ('PYTHONS', (), 'python_must_be_cpython_3_12')):
        with monkeypatch.context() as m:
            m.setattr(D, attr, value)
            with pytest.raises(D.DayJError, match=match):
                step('selfcheck')
    with monkeypatch.context() as m:
        m.setitem(D.FROZEN, 'w1_run_py', '0' * 64)
        with pytest.raises(D.DayJError, match='frozen_code_is_not_the_anchored_one:w1_run_py'):
            step('selfcheck')
    with monkeypatch.context() as m:
        m.setitem(D.W1AUX_ANCHORED, 'parallel.py', '0' * 64)
        with pytest.raises(D.DayJError, match='w1aux_module_is_not_the_anchored_one:parallel.py'):
            step('selfcheck')
    with pytest.raises(D.DayJError, match='workers_must_be_a_positive_integer'):
        D.main(['--step', 'selfcheck', '--out', str(out), '--s0', str(S0), '--workers', '0'], out=io.StringIO())
    monkeypatch.delenv('RUGGER_NO_DOTENV')
    with pytest.raises(D.DayJError, match='RUGGER_NO_DOTENV'):
        step('selfcheck')


@REFERENCE
def test_identities_change_between_steps_is_refused(chain):
    tmp_path, out, calls, ctl, step = chain
    out.mkdir()
    D._save_state(out, dict(schema='rugger-w1-dayj-v2', steps={}, s0=S0, identities=dict(dayj_py='0' * 64)))
    with pytest.raises(D.DayJError, match='code_identities_changed_between_steps'):
        step('selfcheck')


def test_dayj_imports_no_network_module():
    tree = ast.parse(Path(D.__file__).read_text())
    names = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {(node.module or '').split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not names & {'socket', 'urllib', 'http', 'requests', 'aiohttp', 'websockets', 'ssl'}


@pytest.mark.skipif(sys.version_info[:2] != (3, 11), reason='documents the 3.11 difference')
def test_python_3_11_is_refused_and_its_l1_bundles_differ(chain, monkeypatch):
    """CPython 3.12 sums floats with compensation: 3.11 changes features_sha256 in the L1 bundles."""
    tmp_path, out, calls, ctl, step = chain
    with pytest.raises(D.DayJError, match='python_must_be_cpython_3_12'):
        step('selfcheck')
    monkeypatch.setattr(D, 'PYTHONS', ((3, 11),))
    with pytest.raises(D.DayJError, match='selfcheck_bundles_differ_from_the_reference'):
        step('selfcheck')


@REFERENCE
def test_memory_guard_stops_before_trials_and_slim_documents_restore(chain, monkeypatch):
    """T-1: trials refuses when MemAvailable < 1.5 x the projection from the exported signatures."""
    from bot.master_v2 import w1_eval
    tmp_path, out, calls, ctl, step = chain
    for name in ('selfcheck', 'gate', 'export', 'series'):
        step(name)
    projection = D.memory_projection(out / 'pools')
    assert projection['signatures'] == 173 and projection['projected_mb'] == round(D.BASE_MB + 173 * D.KB_PER_SIGNATURE['trials'] / 1024)
    monkeypatch.setattr(D, '_memory_available_mb', lambda: 100)
    with pytest.raises(D.DayJError, match='memory_projection_exceeds_available_owner_decision_needed'):
        step('trials')
    assert not (out / 'run').exists() and 'trials' not in json.loads((out / D.STATE).read_text())['steps']
    originals = (w1_eval.run_l1_trials, w1_eval.run_l1_sensitivity, w1_eval.run_l1_descriptive)
    with D.slim_l1_trial_documents():
        assert w1_eval.run_l1_trials is not originals[0]
    assert (w1_eval.run_l1_trials, w1_eval.run_l1_sensitivity, w1_eval.run_l1_descriptive) == originals


@REFERENCE
def test_d2_pinned_p0_registry_and_n_for_dsr_32(chain, monkeypatch):
    tmp_path, out, calls, ctl, step = chain
    for name in ('selfcheck', 'gate', 'export', 'series', 'trials'):
        step(name)
    with pytest.raises(D.DayJError, match='evaluate_needs:--registry'):
        step('evaluate', extra=['--n-boot', '200'])
    other = _p0_registry(tmp_path / 'other.jsonl', 24)
    with pytest.raises(D.DayJError, match='registry_paths_are_not_the_pinned_ones'):
        step('evaluate', extra=['--n-boot', '200', '--registry', str(other)])
    monkeypatch.setattr(D, 'OTHER_REGISTRIES_SHA256', (hashlib.sha256(other.read_bytes()).hexdigest(),))
    with pytest.raises(D.DayJError, match='n_for_dsr_is_not_32:31'):
        step('evaluate', extra=['--n-boot', '200', '--registry', str(other)])
    monkeypatch.setattr(D, 'OTHER_REGISTRIES_SHA256', ())
    with pytest.raises(D.DayJError, match='p0_registry_not_pinned_yet'):
        step('evaluate', extra=['--n-boot', '200', '--registry', str(other)])
    assert not (out / 'run' / 'w1_report.json').exists()


@REFERENCE
def test_d1_trials_resume_after_interruption_gives_identical_outputs(chain, monkeypatch):
    from bot.master_v2 import w1_eval
    tmp_path, out, calls, ctl, step = chain
    for name in ('selfcheck', 'gate', 'export', 'series'):
        step(name)
    with pytest.raises(D.DayJError, match='resume_without_trials_started'):
        step('trials', extra=['--workers', '2', '--resume'])
    with monkeypatch.context() as m:                                 # interruption in the middle of run_trials
        m.setattr(w1_eval, 'run_l1_sensitivity', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('killed')))
        with pytest.raises(RuntimeError, match='killed'):
            step('trials')
    state = json.loads((out / D.STATE).read_text())
    assert 'trials' not in state['steps'] and state['trials_started']['workers'] == 2
    partial = (out / 'registry_w1.jsonl').read_bytes()
    with pytest.raises(D.DayJError, match='output_exists'):
        step('trials')
    step('trials', extra=['--workers', '3', '--resume'])
    state = json.loads((out / D.STATE).read_text())
    details = state['steps']['trials']['details']
    assert details['resumed'] and details['registered_at'] == state['trials_started']['registered_at']
    assert details['stats']['reused'] > 0 and details['quarantined']
    quarantine = out / details['quarantined'][0]['to']
    assert (quarantine / 'registry_w1.jsonl').read_bytes() == partial                               # kept, not deleted
    assert (out / 'registry_w1.jsonl').read_bytes().startswith(partial)
    plain = tmp_path / 'plain'
    plain.mkdir()
    run.run_trials(PACK, out / 'sol_usd_series.json.gz', registry_path=plain / 'r.jsonl',
                   sensitivity_registry_path=plain / 's.jsonl', registered_at=details['registered_at'], out=plain)
    assert (plain / 'bundles' / 'SHA256SUMS.json').read_bytes() == (out / 'run' / 'bundles' / 'SHA256SUMS.json').read_bytes()
    assert (plain / 'r.jsonl').read_bytes() == (out / 'registry_w1.jsonl').read_bytes()
    assert (plain / 's.jsonl').read_bytes() == (out / 'registry_sensitivity.jsonl').read_bytes()


def test_memory_guard_per_step_evaluate_is_the_binding_one(tmp_path, monkeypatch):
    """R02 M-2a: each heavy step projects its own memory (KB per exported signature) before running."""
    (tmp_path / 'MANIFEST.json').write_text(json.dumps(dict(pools=[dict(signatures=200_000)])))
    monkeypatch.setattr(D, '_memory_available_mb', lambda: 10_000)
    assert D.memory_guard('trials', tmp_path, None)['fits'] and D.memory_guard('ledger', tmp_path, None)['fits']
    with pytest.raises(D.DayJError, match='memory_projection_exceeds_available_owner_decision_needed'):
        D.memory_guard('evaluate', tmp_path, None)
    assert D.memory_guard('evaluate', tmp_path, 'R02-anchor-x')['fits'] is False            # override: recorded
    assert D.memory_projection(tmp_path, 'evaluate')['projected_mb'] == round(150 + 200_000 * 56 / 1024)


def test_memory_available_is_capped_by_the_cgroup_headroom(monkeypatch):
    """R02 G-1: the guard uses min(MemAvailable, cgroup limit - usage)."""
    monkeypatch.setattr(D, '_cgroup_headroom_mb', lambda: 100)
    assert D._memory_available_mb() == 100
    monkeypatch.setattr(D, '_cgroup_headroom_mb', lambda: None)
    assert D._memory_available_mb() > 100
