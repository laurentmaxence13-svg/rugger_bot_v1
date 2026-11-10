"""w1aux.metrics: descriptive metrics equal to the frozen ones where they overlap, never a new decision."""
import io
import json
from pathlib import Path

import pytest

from bot.market import w1_collection
from bot.master_v2 import w1_run as run
from w1aux import dayj as D
from w1aux import ledger as L
from w1aux import metrics as M

PACK = Path('tests/fixtures/launchlab_sol_pools')
S0 = 464661843 - w1_collection.WARMUP_SLOTS


@pytest.fixture(scope='module')
def w1_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp('w1')
    mp = pytest.MonkeyPatch()
    mp.setenv('RUGGER_NO_DOTENV', '1')
    D._selfcheck_series(root / 'series.json')
    run.run_trials(PACK, root / 'series.json', registry_path=root / 'r.jsonl', sensitivity_registry_path=root / 's.jsonl',
                   registered_at='2026-11-09T00:00:00+00:00', out=root / 'run')
    run.evaluate(PACK, root / 'run', S0, registry_paths=[root / 'r.jsonl'], registry_path=root / 'r.jsonl',
                 sensitivity_registry_path=root / 's.jsonl', n_boot=200)
    assert L.main(['--pools', str(PACK), '--bundles', str(root / 'run' / 'bundles'), '--report',
                   str(root / 'run' / 'w1_report.json'), '--series', str(root / 'series.json'),
                   '--out', str(root / 'ledger')], out=io.StringIO()) == 0
    yield root
    mp.undo()


def test_metrics_match_the_frozen_report_and_keep_its_decision(w1_dir):
    buffer = io.StringIO()
    assert M.main(['--w1-dir', str(w1_dir), '--s0', str(S0)], out=buffer) == 0
    doc = json.loads((w1_dir / 'metrics' / 'metrics.json').read_text())
    report = json.loads((w1_dir / 'run' / 'w1_report.json').read_text())
    assert doc['w1_decision'] == report['decision'] == 'WAIT_INSUFFICIENT_DATA'
    assert doc['economic_verdict'] == 'NOT_CONCLUSIVE' and doc['flags']['decision_changed'] is False
    assert doc['population']['all'] == report['split']['all']
    for arm in ('M1', 'P1b', 'S1', 'S2', 'S3', 'P1', 'P2'):
        frozen, ours = report['trials'][arm]['all'], doc['arms'][arm]['all']
        assert (ours['entered'], ours['closed'], ours['independent_creators']) == (
            frozen['entries'], frozen['closed'], frozen['independent_creators']), arm
        for key in ('mean_return', 'pessimistic_mean'):
            assert ours[key] == pytest.approx(frozen[key]) if frozen[key] is not None else ours[key] is None, (arm, key)
    assert set(doc['sensitivities']) == {'M1_latency10', 'M1_failed_fee_105000', 'M1_event_horizon', 'P1b_event_horizon'}
    assert 'returns_by_pool' not in json.dumps(doc)
    assert json.loads(buffer.getvalue())['metrics_sha256']
    with pytest.raises(M.MetricsError, match='output_exists'):
        M.main(['--w1-dir', str(w1_dir), '--s0', str(S0)], out=io.StringIO())


def test_arm_metrics_definitions_on_a_hand_made_sample():
    trade = lambda pnl, outcome='closed', slot=1: dict(entry_index=1, outcome=outcome, pnl_lamports=pnl,      # noqa: E731
                                                     spent=100_000_000, tx_costs=0, failed_attempt_costs=0,
                                                     exit_slot=slot)
    rows = [('a', 1, 'c1', True, trade(50_000_000, slot=1)), ('b', 1, 'c2', True, trade(-90_000_000, slot=2)),
            ('c', 1, 'c3', True, trade(20_000_000, slot=3)), ('d', 1, 'c4', True, trade(0, 'migrated_unpriced')),
            ('e', 1, 'c5', True, dict(trade(0), entry_index=None))]
    m = M.arm_metrics(rows, ['a', 'b', 'c', 'd', 'e'], {'a': 1_000_000, 'b': 1_000_000, 'c': 1_000_000}, n_boot=200)
    assert (m['entered'], m['closed'], m['non_valued']) == (4, 3, {'migrated_unpriced': 1})
    assert m['mean_return'] == pytest.approx((0.5 - 0.9 + 0.2) / 3)
    assert m['pessimistic_mean'] == pytest.approx((0.5 - 0.9 + 0.2 - 1) / 4)
    assert m['win_rate'] == pytest.approx(2 / 3) and m['mean_loss'] == pytest.approx(-0.9)
    assert m['pnl_net_sol'] == pytest.approx(-0.02) and m['pnl_gross_sol'] == pytest.approx(-0.017)
    assert m['max_drawdown_sol'] == pytest.approx(0.09) and m['losses_le_minus_90pct'] == 1
    assert m['cvar_5pct'] == pytest.approx(-0.9) and m['concentration']['positive_pnl_share_top1'] == pytest.approx(5 / 7)
    assert m['quantiles']['q50'] == pytest.approx(0.2)


def test_tampered_bundle_or_failed_ledger_is_refused(w1_dir, tmp_path):
    import shutil
    copy = tmp_path / 'w1'
    shutil.copytree(w1_dir, copy, ignore=shutil.ignore_patterns('metrics'))
    ledger = json.loads((copy / 'ledger' / 'ledger.json').read_text())
    (copy / 'ledger' / 'ledger.json').write_text(json.dumps(dict(ledger, verdict='FAIL')))
    with pytest.raises(M.MetricsError, match='ledger_verdict_not_pass'):
        M.compute(copy, S0, n_boot=200)
    (copy / 'ledger' / 'ledger.json').write_text(json.dumps(ledger))
    victim = copy / 'run' / 'bundles' / 'S2.json.gz'
    victim.write_bytes(victim.read_bytes() + b'\0')
    with pytest.raises(M.MetricsError, match='bundle_file_changed:S2'):
        M.compute(copy, S0, n_boot=200)
