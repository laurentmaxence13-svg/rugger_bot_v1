"""Unit fixtures for the registered synthetic protocol; no market inference."""
from dataclasses import asdict, replace
import json

import pytest

from bot.analyser import synthetic_benchmark as synthetic


def row(i, *, when=None, gross=.2, **kwargs):
    return synthetic.Observation(i * 1000 if when is None else when,
        f's{i}', f'm{i}', .1, 100, gross, **kwargs)


def test_sol_ledger_accounts_for_position_size_and_cost_once():
    result = synthetic.simulate([row(0), row(1, when=1, gross=-.2)], 'all_eligible', 200)
    assert result['trades'] == 2
    assert result['closed_trades'][0]['pnl_sol'] == pytest.approx(.18)
    assert result['closed_trades'][1]['pnl_sol'] == pytest.approx(-.22)
    assert result['final_capital_sol'] == pytest.approx(9.96)
    assert result['net_pnl_sol'] == pytest.approx(-.04)
    assert result['capital_return'] == pytest.approx(-.004)
    assert result['profit_factor'] == pytest.approx(.18 / .22)
    assert result['max_drawdown_realized'] == pytest.approx(.22 / 10.18)
    assert result['max_reserved_sol'] == 2


def test_simultaneous_exits_have_no_invented_intrasecond_equity_peak():
    result = synthetic.simulate([row(0, gross=.2), row(1, when=0, gross=-.2)],
                                'all_eligible', 0)
    assert result['final_capital_sol'] == pytest.approx(10)
    assert result['max_drawdown_realized'] == 0


def test_exposure_limit_and_rejected_entry_do_not_consume_capital():
    rows = [row(i, when=i) for i in range(4)]
    result = synthetic.simulate(rows, 'all_eligible', 0)
    assert result['trades'] == 3
    assert result['rejections']['exposure'] == 1
    assert result['max_open_positions'] == 3
    assert result['minimum_available_cash_sol'] == 7
    assert result['final_capital_sol'] == pytest.approx(10.6)


def test_bankruptcy_cannot_borrow_or_lose_more_than_all_in_budget():
    result = synthetic.simulate([row(i, gross=-1) for i in range(12)],
                                'all_eligible', 1000, 300)
    assert result['trades'] == 10
    assert result['rejections']['balance'] == 2
    assert result['final_capital_sol'] == 0
    assert result['minimum_available_cash_sol'] == 0
    assert result['worst_trade_pnl_sol'] == -1


@pytest.mark.parametrize('gross,status,pf', [(.2, 'no_losses', None),
                                           (0, 'no_nonzero_trades', None),
                                           (-.2, 'finite', 0)])
def test_profit_factor_degenerate_cases_are_json_safe(gross, status, pf):
    result = synthetic.simulate([row(0, gross=gross)], 'all_eligible', 0)
    assert result['profit_factor_status'] == status
    assert result['profit_factor'] == pf
    json.dumps(result, allow_nan=False)


def test_execution_checks_use_only_observable_entry_fields():
    rows = [replace(row(0), entry_available=False),
            replace(row(1), quote_delay=180), replace(row(2), liquidity_sol=19)]
    result = synthetic.simulate(rows, 'all_eligible')
    assert result['trades'] == 0
    assert result['rejections']['missing_entry_quote'] == 1
    assert result['rejections']['stale_quote'] == 1
    assert result['rejections']['liquidity'] == 1
    assert result['mean_trade_pnl_sol'] is None
    assert result['execution_fraction'] == 0


def test_cost_and_slippage_sensitivity_has_identical_executed_cohort():
    rows = [row(i, gross=.2 if i % 2 else -.1) for i in range(8)]
    results = [synthetic.simulate(rows, 'all_eligible', cost, slip)
               for cost, slip in ((200, 0), (500, 100), (1000, 300))]
    assert [result['trades'] for result in results] == [8, 8, 8]
    assert all({trade['mint'] for trade in result['closed_trades']} ==
               {f'm{i}' for i in range(8)} for result in results)
    assert results[0]['net_pnl_sol'] > results[1]['net_pnl_sol'] > results[2]['net_pnl_sol']


def test_three_periods_preserve_signatures_times_and_actual_label_availability():
    rows = synthetic.generate(17, 180)
    train, validation, final_test, info = synthetic.split_periods(rows)
    for left, right in ((train, validation), (train, final_test), (validation, final_test)):
        assert not ({r.signature for r in left} & {r.signature for r in right})
        assert not ({r.signal_time for r in left} & {r.signal_time for r in right})
    assert max(r.exit_time for r in train) < info['validation_started_at']
    assert max(r.exit_time for r in validation) < info['final_test_started_at']
    assert info['train']['purged_train_observations'] > 0
    assert info['purged_validation_observations'] > 0
    assert all(len(part) >= minimum for part, minimum in
               zip((train, validation, final_test), synthetic.MIN_SIZES))


def test_holdout_outcomes_never_change_policy_selection_or_selection_fingerprint():
    rows = synthetic.generate(23, 180)
    result = synthetic.run_experiment(rows, 23)
    boundary = result['partition']['final_test_started_at']
    shocked = [replace(r, gross_return_sol=-.95) if r.signal_time >= boundary else r for r in rows]
    changed = synthetic.run_experiment(shocked, 23)
    assert changed['final_policy'] == result['final_policy']
    assert changed['selection_input_sha256'] == result['selection_input_sha256']
    assert changed['development'] == result['development']
    assert changed['dataset_sha256'] != result['dataset_sha256']
    assert changed['final_test'][0]['net_pnl_sol'] < result['final_test'][0]['net_pnl_sol']


def test_report_is_deterministic_nonactivatable_and_explicit_about_sol_units():
    rows = synthetic.generate(99, 180, 'adverse')
    first = synthetic.run_experiment(rows, 99, 'adverse')
    assert first == synthetic.run_experiment(rows, 99, 'adverse')
    assert first['economic_verdict'] == 'INSUFFICIENT DATA'
    assert first['model_eligible'] is first['paper_eligible'] is False
    assert first['real_orders_enabled'] is False
    assert first['synthetic_return_field'] == 'gross_return_sol'
    assert first['unit'] == 'SOL'
    assert first['candidate_trials'] == 3
    assert first['no_trade_control']['net_pnl_sol'] == 0
    assert first['no_trade_control']['final_capital_sol'] == 10
    chosen = next(r for r in first['development'] if r['policy'] == first['final_policy'])
    assert first['validation_positive'] == (chosen['validation']['net_pnl_sol'] > 0)
    assert len(first['final_test']) == 9
    assert synthetic._digest({key: value for key, value in first.items()
                               if key != 'report_sha256'}) == first['report_sha256']
    json.dumps(first, allow_nan=False)


@pytest.mark.parametrize('replacement', [None, float('nan'), float('inf')])
def test_missing_or_nonfinite_outcomes_never_become_a_zero_return(replacement):
    rows = synthetic.generate(1, 180)
    rows[0] = replace(rows[0], gross_return_sol=replacement)
    with pytest.raises(ValueError, match='INSUFFICIENT DATA'):
        synthetic.run_experiment(rows)


def test_all_one_group_cannot_be_relabelled_as_independent_periods():
    rows = [replace(row(i, when=100), signature='one-transaction') for i in range(100)]
    with pytest.raises(ValueError, match='no grouped final-test boundary'):
        synthetic.split_periods(rows)


def test_duplicate_mints_and_insufficient_post_purge_samples_refuse():
    rows = synthetic.generate(1, 180)
    with pytest.raises(ValueError, match='Duplicate temporal mint'):
        synthetic.split_periods(rows + [rows[0]])
    with pytest.raises(ValueError, match='INSUFFICIENT DATA after grouping/purge'):
        synthetic.split_periods(synthetic.generate(1, 40))


def test_generated_null_world_does_not_encode_momentum_in_returns():
    null = synthetic.generate(7, 20, 'null')
    linked = synthetic.generate(7, 20, 'momentum_linked')
    assert [r.event for r in null] == [r.event for r in linked]
    assert [r.momentum for r in null] == [r.momentum for r in linked]
    for zero_edge, artificial_edge in zip(null, linked):
        assert artificial_edge.gross_return_sol - zero_edge.gross_return_sol == pytest.approx(
            zero_edge.momentum * .5)


def test_least_bad_negative_candidate_does_not_become_a_positive_result():
    report = synthetic.run_experiment([row(i, gross=-.2) for i in range(180)], 1)
    assert report['validation_positive'] is False
    assert report['selection_outcome'] == 'no_positive_validation_candidate'
    assert all(run['net_pnl_sol'] < report['no_trade_control']['net_pnl_sol']
               for run in report['final_test'])
    assert report['model_eligible'] is False
    assert report['economic_verdict'] == 'INSUFFICIENT DATA'


def test_cli_only_generates_synthetic_data_and_writes_atomic_diagnostic(tmp_path, monkeypatch):
    destination = tmp_path / 'synthetic.json'
    monkeypatch.setattr('sys.argv', ['synthetic_benchmark', '--count', '180',
                                    '--seed', '99', '--output', str(destination)])
    synthetic.main()
    report = json.loads(destination.read_text())
    assert report['data_kind'] == 'synthetic'
    assert report['economic_verdict'] == 'INSUFFICIENT DATA'
    assert report['model_eligible'] is False
