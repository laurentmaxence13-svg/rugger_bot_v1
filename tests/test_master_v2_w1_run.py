"""W1 run script (protocol v2.5), end to end on the 3-pool fixture pack. Offline, no secret."""
import hashlib
import json
from pathlib import Path

import pytest

from bot.market import w1_collection
from bot.master_v2 import registry, w1_eval
from bot.master_v2 import w1_run as run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
AT = '2026-11-08T00:00:00+00:00'
FIRST_SLOT, FIRST_TIME = 464661843, 1793658217          # creation of the earliest fixture pool


def _series(tmp_path, acceptance=dict(max_age_ms=120_000, max_confidence_ppm=1_000), label='COLLECTED'):
    point = dict(schema=sus.POINT_SCHEMA, slot=FIRST_SLOT - 50, transaction_index=0, block_time=FIRST_TIME - 12,
                 received_at_ms=None, publish_time=FIRST_TIME - 13, price=15_000_000_000, exponent=-8,
                 confidence=7_500_000, source_kind='pyth_onchain_account', source_ref='synthetic-test-account',
                 evidence_sha256='0' * 64, signature=None)
    doc = dict(schema=sus.SERIES_SCHEMA, label=label, points=[point], acceptance=acceptance)
    path = tmp_path / 'sol_usd.json'
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def no_dotenv(monkeypatch):
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')


def test_every_step_refuses_to_run_without_no_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv('RUGGER_NO_DOTENV', raising=False)
    with pytest.raises(run.W1RunError, match='RUGGER_NO_DOTENV'):
        run.run_trials(PACK, _series(tmp_path), registry_path=tmp_path / 'r', sensitivity_registry_path=tmp_path / 's',
                       registered_at=AT, out=tmp_path / 'o')
    with pytest.raises(run.W1RunError, match='RUGGER_NO_DOTENV'):
        run.evaluate(PACK, tmp_path / 'o', 1, registry_paths=[], registry_path=tmp_path / 'r',
                     sensitivity_registry_path=tmp_path / 's')
    with pytest.raises(run.W1RunError, match='RUGGER_NO_DOTENV'):
        run.sol_usd_series([], tmp_path / 'study.json', '0' * 64, tmp_path / 'x.json')


def test_parameters_are_the_protocol_ones():
    l1, v2 = run.l1_params(), run.v2_params()
    for params in (l1, v2):
        assert (params.latency_slots, params.base_fee_lamports, params.priority_fee_lamports,
                params.failed_attempt_fee_lamports) == (4, 5_000, 100_000, 0)
    assert (l1.exit_horizon_ms, v2.exit_horizon_ms) == (30_000, 25_000)
    assert run.L1_EXIT == hrr.ExitOptions(clock_horizon=True)
    assert set(run.V2_ARMS) == {'P1', 'P2', 'S1', 'S2', 'S3'} and set(run.V2_ARMS) | set(w1_eval.L1_ARMS) == set(w1_eval.REQUIRED)
    names = {k: make().name for k, (make, _rule) in run.V2_ARMS.items()}
    assert names == dict(P1='placebo-random-entry', P2='placebo-no-trade', S1='immediate-snipe',
                         S2='diagnostic-fixed-delay', S3='challenger-insider-veto-5s')
    assert run.V2_ARMS['S2'][0]().delay_s == 5 and not run.V2_ARMS['P2'][1].clock_exit
    assert all(rule.max_hold_s == 25 for _make, rule in run.V2_ARMS.values())


def test_collect_command_checks_the_cap_and_sends_nothing(tmp_path):
    from tests_helpers_w1 import pilot_dir
    pilot = pilot_dir(tmp_path, 11)
    argv = run.collect_command(1_000_000, pilot_dir=pilot, max_credits=w1_collection.CREDIT_CAP - 11, out=tmp_path / 'w',
                               other_runs=[])
    b = w1_collection.bounds(1_000_000)
    assert argv[:2] == ['run', '--network'] and argv[argv.index('--slot-max') + 1] == str(b['slot_max'])
    assert argv[argv.index('--costs') + 1] == w1_collection.COSTS and '--max-credits' in argv
    from bot.market import backfill as bf
    with pytest.raises(bf.BackfillError, match='run_cap_above_credits_left_after_the_pilot'):
        run.collect_command(1_000_000, pilot_dir=pilot, max_credits=w1_collection.CREDIT_CAP, out=tmp_path / 'w',
                            other_runs=[])
    with pytest.raises(TypeError):
        run.collect_command(1_000_000, pilot_dir=pilot, max_credits=1, out=tmp_path / 'w')    # other_runs required


def test_trials_registered_then_evaluated_from_the_saved_bundles(tmp_path, no_dotenv):
    reg, sens = tmp_path / 'trials.jsonl', tmp_path / 'sensitivity.jsonl'
    series = _series(tmp_path)
    sums = run.run_trials(PACK, series, registry_path=reg, sensitivity_registry_path=sens, registered_at=AT,
                          out=tmp_path / 'out')
    assert set(sums) == {'L1', 'P1', 'P2', 'S1', 'S2', 'S3', w1_eval.SENSITIVITY_ID, 'L1_failed_fee_105000', 'L1_event_horizon'}
    assert len(registry.load(reg)) == 7 and len(registry.load(sens)) == 4      # latency 10 + 3 descriptive (R02 D-5)
    s0 = FIRST_SLOT - w1_collection.WARMUP_SLOTS
    report = run.evaluate(PACK, tmp_path / 'out', s0, registry_paths=[reg], registry_path=reg,
                          sensitivity_registry_path=sens, n_boot=200)
    assert report['n_trials'] == 7 and report['decision'] == 'WAIT_INSUFFICIENT_DATA'
    assert report['embargo_slots'] == 4_513                                   # the protocol constant (R02 D-8)
    assert report['split']['all'] == 3 and report['bundles_sha256'] == sums
    assert set(report['descriptive_sensitivities']) == set(w1_eval.DESCRIPTIVE)
    near = report['m1_near_usd_threshold']
    # The L1 NativeQuote carries no volume: the scorer's volume threshold never acts on M1 (R02 N-1).
    assert near['decisions_with_volume'] == 0
    assert near['error'] == 0.005 and near['decisions'] > 0 and set(near['by_threshold']) == {
        'funding_5', 'funding_25', 'funding_250', 'liquidity_tpsl_3000', 'liquidity_tpsl_25000', 'volume_5000'}
    assert report['flags']['master_operational_trade'] is False and report['flags']['counted_in_master_gate'] is False
    assert json.loads((tmp_path / 'out' / 'w1_report.json').read_text())['decision'] == 'WAIT_INSUFFICIENT_DATA'
    # A bundle edited after the run is refused (documents are rebuilt from the files).
    path = tmp_path / 'out' / 'bundles' / 'S1.json.gz'
    path.write_bytes(path.read_bytes() + b'\0')
    with pytest.raises(run.W1RunError, match='bundle_file_changed:S1'):
        run.evaluate(PACK, tmp_path / 'out', s0, registry_paths=[reg], registry_path=reg,
                     sensitivity_registry_path=sens, n_boot=200)


def test_series_must_be_collected_with_its_measured_acceptance(tmp_path, no_dotenv):
    for kwargs in (dict(label='SYNTHETIC_TEST_FIXTURE'), dict(acceptance=dict(max_age_ms=5_000, max_confidence_ppm=None))):
        with pytest.raises(run.W1RunError, match='measured_acceptance'):
            run.run_trials(PACK, _series(tmp_path, **kwargs), registry_path=tmp_path / 'r',
                           sensitivity_registry_path=tmp_path / 's', registered_at=AT, out=tmp_path / 'o')
    assert not (tmp_path / 'r').exists()                              # nothing registered


def test_w1_run_module_opens_no_socket():
    import ast
    tree = ast.parse(Path(run.__file__).read_bytes())
    names = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
             for alias in (node.names if isinstance(node, ast.Import) else [type('A', (), dict(name=node.module or ''))])}
    assert not names & {'socket', 'urllib', 'http', 'requests', 'aiohttp', 'websockets', 'subprocess'}


class _PythChain:
    """Fake RPC serving the two archived P0 push transactions at the SOL/USD account (no network)."""

    def __init__(self):
        fix = Path(__file__).parent / 'fixtures' / 'pyth_push'
        self.entries = [json.loads(p.read_text()) for p in sorted(fix.glob('*.json'))]
        self.calls = []

    def __call__(self, request, timeout):
        import io
        body = json.loads(request.data)
        self.calls.append(body['method'])
        address, options = body['params']
        from bot.market import pyth_push
        assert address == pyth_push.SOL_USD_ACCOUNT
        if body['method'] == 'getTransactionsForAddress':
            slot = options['filters']['slot']
            data = [e for e in self.entries if slot['gte'] <= e['slot'] <= slot['lte']]
            result = {'data': data, 'paginationToken': None}
        else:
            result = [{'signature': e['transaction']['signatures'][0], 'slot': e['slot'], 'err': None,
                       'blockTime': e['blockTime'], 'memo': None, 'confirmationStatus': 'finalized'}
                      for e in sorted(self.entries, key=lambda e: e['slot'], reverse=True)]
            if 'before' in options:
                result = []
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())


def test_sol_usd_window_to_series_v2_4(tmp_path, no_dotenv):
    from bot.market import backfill as bf, pyth_push
    s0 = 466226774 - w1_collection.WARMUP_SLOTS - 10
    b = w1_collection.bounds(s0)
    budget = bf.CreditBudget(1_000, 60_000, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / 'pyth' / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=_PythChain())
    manifest = bf.Backfill(rpc, bf.Window(pyth_push.SOL_USD_ACCOUNT, b['slot_min'], b['slot_max']), tmp_path / 'pyth').run()
    assert manifest['complete']
    entries = run.pyth_entries(tmp_path / 'pyth', s0)
    study = tmp_path / 'study.json'
    study.write_text(json.dumps(dict(verdict='ACCEPTED', acceptance=dict(max_age_ms=65_000, max_confidence_ppm=1_000))))
    anchored = hashlib.sha256(study.read_bytes()).hexdigest()
    series = run.sol_usd_series(entries, study, anchored, tmp_path / 'sol.json.gz')
    assert series.label == 'COLLECTED' and len(series.points) == 2 and series.max_age_ms == 65_000
    assert sus.load_series(tmp_path / 'sol.json.gz').sha256 == series.sha256
    decoding = json.loads((tmp_path / 'sol.json.gz.decoding.json').read_text())
    assert decoding == dict(updates=2, not_newer=0, points=2, study_report_sha256=anchored, series_sha256=series.sha256)
    with pytest.raises(run.W1RunError, match='age_study_report_is_not_the_anchored_one'):       # R02 D-7
        run.sol_usd_series(entries, study, '0' * 64, tmp_path / 'other.json')
    rejected = tmp_path / 'rejected.json'
    rejected.write_text(json.dumps(dict(verdict='REJECTED', acceptance=None)))
    with pytest.raises(run.W1RunError, match='age_study_not_accepted'):
        run.sol_usd_series(entries, rejected, hashlib.sha256(rejected.read_bytes()).hexdigest(), tmp_path / 'other.json')
    with pytest.raises(run.W1RunError, match='not_the_w1_sol_usd_window'):
        run.pyth_entries(tmp_path / 'pyth', s0 + 1)
    argv = run.collect_command(s0, pilot_dir=__import__('tests_helpers_w1').pilot_dir(tmp_path, 11),
                               max_credits=50_000, out=tmp_path / 'p', address=pyth_push.SOL_USD_ACCOUNT,
                               other_runs=[tmp_path / 'pyth'])
    assert argv[argv.index('--address') + 1] == pyth_push.SOL_USD_ACCOUNT
    with pytest.raises(run.W1RunError, match='launchlab_program_or_the_sol_usd_account'):
        run.collect_command(s0, pilot_dir=tmp_path / 'pilot', max_credits=1, out=tmp_path / 'p', address='other',
                            other_runs=[])



def _run_and_paths(tmp_path):
    reg, sens = tmp_path / 'trials.jsonl', tmp_path / 'sensitivity.jsonl'
    run.run_trials(PACK, _series(tmp_path), registry_path=reg, sensitivity_registry_path=sens, registered_at=AT,
                   out=tmp_path / 'out')
    return reg, sens, FIRST_SLOT - w1_collection.WARMUP_SLOTS


def _rewrite_bundle(tmp_path, trial_id, change):
    """Edit a saved bundle AND its SHA256SUMS entry, so only the deeper checks can catch it."""
    path = tmp_path / 'out' / 'bundles' / f'{trial_id}.json.gz'
    bundle = run._read_json(path)
    change(bundle)
    sha = run._write_json(path, bundle)
    sums_path = tmp_path / 'out' / 'bundles' / 'SHA256SUMS.json'
    sums = run._read_json(sums_path)
    sums[trial_id] = sha
    run._write_json(sums_path, sums)


def test_r02_survivors_l1_hash_v2_entry_and_w1_registry(tmp_path, no_dotenv):
    reg, sens, s0 = _run_and_paths(tmp_path)
    kwargs = dict(registry_paths=[reg], registry_path=reg, sensitivity_registry_path=sens, n_boot=200)
    with pytest.raises(run.W1RunError, match='w1_registry_not_among_the_registries_given'):
        run.evaluate(PACK, tmp_path / 'out', s0, **dict(kwargs, registry_paths=[]))
    _rewrite_bundle(tmp_path, 'S1', lambda b: b.update(preregistration_sha256='f' * 64))
    with pytest.raises(run.W1RunError, match='no_registry_entry_for_bundle'):
        run.evaluate(PACK, tmp_path / 'out', s0, **kwargs)
    _rewrite_bundle(tmp_path, 'L1', lambda b: b['pools'][0].update(creator='someone-else'))
    with pytest.raises(run.W1RunError, match='l1_bundle_hash_mismatch'):
        run.evaluate(PACK, tmp_path / 'out', s0, **kwargs)


def test_embargo_is_the_protocol_constant():
    import inspect
    assert run.EMBARGO_SLOTS == w1_collection.GAP_SLOTS == 4_513
    assert 'embargo_slots' not in inspect.signature(run.evaluate).parameters


def test_incomplete_sol_usd_window_is_refused(tmp_path, no_dotenv):
    from bot.market import backfill as bf, pyth_push

    class Partial(_PythChain):
        def __call__(self, request, timeout):
            body = json.loads(request.data)
            if body['method'] == 'getSignaturesForAddress':      # second listing misses one signature
                self.entries = self.entries[:1]
            return super().__call__(request, timeout)
    s0 = 466226774 - w1_collection.WARMUP_SLOTS - 10
    b = w1_collection.bounds(s0)
    budget = bf.CreditBudget(1_000, 60_000, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / 'pyth' / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=Partial())
    manifest = bf.Backfill(rpc, bf.Window(pyth_push.SOL_USD_ACCOUNT, b['slot_min'], b['slot_max']), tmp_path / 'pyth').run()
    assert not manifest['complete']
    with pytest.raises(run.W1RunError, match='sol_usd_window_not_verified_or_incomplete'):
        run.pyth_entries(tmp_path / 'pyth', s0)
