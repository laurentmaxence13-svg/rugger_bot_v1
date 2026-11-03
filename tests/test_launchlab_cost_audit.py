"""Offline tests of the LaunchLab cost audit (committed SOL fixtures only)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
POOLS = {
    'closed_loss': '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2',
    'closed_gain': 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC',
    'no_entry': 'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r',
}


def _audit():
    spec = importlib.util.spec_from_file_location('launchlab_cost_audit', ROOT / 'tools' / 'launchlab_cost_audit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_two_entries_are_audited_and_third_pool_has_none():
    audit = _audit()
    rows = {k: audit.audit_pool(FIXTURES, p) for k, p in POOLS.items()}
    assert rows['closed_loss']['outcome'] == rows['closed_gain']['outcome'] == 'closed'
    assert rows['no_entry']['outcome'] == 'no_entry'
    assert 'entry_leg' not in rows['no_entry']


def test_legs_reproduce_replay_totals_exactly():
    audit = _audit()
    for key, expected_pnl in (('closed_loss', -5_040_190), ('closed_gain', 2_926_591)):
        row = audit.audit_pool(FIXTURES, POOLS[key])
        entry, leg, acc = row['entry_leg'], row['exit_leg'], row['accounting']
        assert entry['curve_input_lamports'] == 50_000_000
        assert entry['net_into_curve_lamports'] + entry['entry_fee_lamports'] == 50_000_000
        assert leg['curve_output_gross_lamports'] - leg['exit_fee_lamports'] == leg['net_received_lamports']
        assert acc['pnl_lamports'] == expected_pnl
        assert acc['pnl_lamports'] == leg['net_received_lamports'] - 50_000_000 - acc['tx_costs_lamports']
        assert acc['curve_fees_total_lamports'] == entry['entry_fee_lamports'] + leg['exit_fee_lamports']
        assert acc['identity_ok'] and row['entry_matches_replay']
        assert row['baseline_report_differences'] == []


def test_assumptions_and_unexposed_values_are_stated_not_invented():
    audit = _audit()
    row = audit.audit_pool(FIXTURES, POOLS['closed_gain'])
    assert row['latency_slots_assumed'] == 2 and row['entry_size_SOL'] == 0.05
    assert row['fee_rate_ppm_used'] == 12_500
    assert row['tx_fee_lamports']['kind'].startswith('assumed')
    assert any(item.startswith('priority_fee_lamports') for item in row['not_exposed'])
    assert row['flags'] == {'migrated': False, 'final_liquidation_marked_not_executed': False,
                            'counterfactual_divergence': False}


def test_sensitivity_to_observed_max_fee_is_worse_than_assumed():
    audit = _audit()
    acc = audit.audit_pool(FIXTURES, POOLS['closed_gain'])['accounting']
    assert acc['sensitivity_pnl_SOL_if_both_txs_pay_observed_max_fee'] < acc['pnl_SOL']


def test_gross_inversion_and_unknown_pool_not_replayable(tmp_path):
    audit = _audit()
    for gross in (1_000_000, 45_495_095, 53_659_503):
        received = gross - audit.fee_for(gross, 12_500)
        assert audit._exit_gross(received, 12_500) == gross
    assert audit.audit_pool(tmp_path, 'missing')['outcome'] == 'not_replayable'
