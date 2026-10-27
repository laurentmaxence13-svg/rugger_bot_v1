"""Integrated dashboard uses the active PAPER schema and reads it without writes."""
import json
import sqlite3

import pytest

from bot.analyser.functional_report import build_functional_report
from bot.analyser.paper_trader import setup, ensure_paper_portfolio


def ledger():
    con = sqlite3.connect(':memory:')
    setup(con)
    ensure_paper_portfolio(con, 10, 0)
    return con


def closed(con, mint, exit_at, size, pnl, cost=200):
    con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,"
        "exit_time,position_sol,net_return,pnl_sol,cost_bps,status) "
        "VALUES(?,'synthetic',1,1,1,?,?,?,?,?,'closed')",
        (mint, exit_at, size, pnl/size if pnl is not None else None, pnl, cost))
    if pnl is not None:
        con.execute('UPDATE paper_portfolio SET realized_capital_sol=realized_capital_sol+?', (pnl,))


def value(report, name):
    return report['metrics'][name]['value']


def test_weighted_gross_net_and_capital_reuse_reconciled_ledger_without_double_fees():
    with ledger() as con:
        closed(con, 'win', 20, 1, .08)
        closed(con, 'loss', 30, 2, -.20)
        changes = con.total_changes
        # The reporting API must work even when writes are prohibited.
        con.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in (
            sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) else sqlite3.SQLITE_OK)
        report = build_functional_report(con, data_kind='synthetic')
        assert con.total_changes == changes
        assert value(report, 'pnl_net_sol') == pytest.approx(-.12)
        assert value(report, 'modeled_cost_sol') == pytest.approx(.06)
        assert value(report, 'pnl_gross_sol') == pytest.approx(-.06)
        assert value(report, 'capital_initial_sol') == 10
        assert value(report, 'capital_final_sol') == pytest.approx(9.88)
        assert value(report, 'capital_available_sol') == pytest.approx(9.88)
        assert value(report, 'portfolio_return') == pytest.approx(-.012)
        assert value(report, 'average_gain_sol') == pytest.approx(.08)
        assert value(report, 'average_loss_sol') == pytest.approx(-.20)
        assert value(report, 'net_expectancy_sol') == pytest.approx(-.06)
        assert value(report, 'profit_factor') == pytest.approx(.4)
        assert value(report, 'win_rate') == .5
        assert value(report, 'max_drawdown') == pytest.approx(-.2/10.08)
        assert report['metrics']['pnl_net_sol']['reliability'] == 'model_only'
        assert report['economic_pnl_verified'] is False
        assert value(report, 'positions_without_qualified_exit') == 0
        assert value(report, 'observed_execution_fees_sol') is None
        assert value(report, 'realized_slippage_sol') is None
        json.dumps(report, allow_nan=False)


def test_distinct_tokens_and_accepted_decisions_do_not_hide_financial_permission_rejection():
    with sqlite3.connect(':memory:') as con:
        con.executescript('CREATE TABLE launch_candidates(mint,detection_latency_ms);'
                         'CREATE TABLE research_launches(mint);'
                         'CREATE TABLE paper_decisions(mint,enter,entry_allowed);')
        con.executemany('INSERT INTO launch_candidates VALUES(?,?)', [('a',10),('a',20),('b',None)])
        con.executemany('INSERT INTO research_launches VALUES(?)', [('a',),('c',)])
        con.executemany('INSERT INTO paper_decisions VALUES(?,?,?)', [('a',1,1),('a',1,0),('b',0,0)])
        report = build_functional_report(con, data_kind='synthetic')
        assert value(report, 'tokens_unique_detected') == 3
        assert value(report, 'analysis_decisions') == 3
        assert value(report, 'opportunities_analysed') == 2
        assert value(report, 'decisions_accepted') == 1
        assert value(report, 'decisions_rejected') == 2
        assert value(report, 'opportunities_accepted') == 1
        assert value(report, 'opportunities_rejected') == 2
        assert value(report, 'positions_open') is None  # Absent table is not zero.
        assert value(report, 'scanner_detection_latency_p50_ms') == 10
        assert value(report, 'scanner_detection_latency_p95_ms') == 20
        assert report['latency_sample_counts']['scanner_detection'] == {
            'valid_samples': 2, 'missing_or_invalid_samples': 1}


def test_incomplete_pnl_unknown_exit_and_missing_timing_never_become_zero_or_profit():
    with ledger() as con:
        closed(con, 'unknown', 20, 1, None)
        con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,position_sol,status) "
                    "VALUES('open','synthetic',1,1,1,1,'open')")
        report = build_functional_report(con, data_kind='market_observation')
        assert report['performance_data_complete'] is False
        for name in ('pnl_net_sol','pnl_gross_sol','modeled_cost_sol','profit_factor',
                     'max_drawdown','scanner_detection_latency_p50_ms'):
            assert value(report, name) is None
            assert report['metrics'][name]['reliability'] == 'unknown'
        assert value(report, 'positions_open') == 1
        assert value(report, 'positions_without_qualified_exit') is None
        assert value(report, 'positions_with_unknown_exit_qualification') == 1
        assert report['missing_data_counts']['closed_ledger_records_incomplete'] == 1
        known = build_functional_report(con, exit_qualification_by_mint={'open': False})
        assert value(known, 'positions_without_qualified_exit') == 1
        assert value(known, 'positions_with_unknown_exit_qualification') == 0
        json.dumps(report, allow_nan=False)


def test_caller_latency_samples_are_measured_separately_and_invalid_values_are_disclosed():
    with ledger() as con:
        report = build_functional_report(con, data_kind='synthetic',
            latency_samples_ms={'quote_response': [10,20,30,40,100,None,-1,float('nan')]})
        assert value(report, 'quote_response_latency_p50_ms') == 30
        assert value(report, 'quote_response_latency_p95_ms') == 100
        assert value(report, 'quote_response_latency_p99_ms') == 100
        assert report['latency_sample_counts']['quote_response'] == {
            'valid_samples': 5, 'missing_or_invalid_samples': 3}
        assert value(report, 'scanner_detection_latency_p50_ms') is None
        json.dumps(report, allow_nan=False)


def admission_fixture():
    return {'schema': 'p3-archived-quote-pair-admission-v1', 'pairs_checked': 2,
            'pairs': [dict(run_id=run, mint='reference' if index == 0 else 'candidate',
                          buy_id=1, sell_id=2, qualification='UNQUALIFIED',
                          reasons=['buy_quote_body_missing'], net_pnl_lamports=None)
                      for index, run in enumerate(('pr19_access_smoke','launchlab_001'))],
            'full_position_closures_verified': 0, 'ledger_mutated': False,
            'new_network_requests': 0, 'economic_verdict': 'INSUFFICIENT DATA',
            'additional_fee_evidence': 'unknown_not_zero', 'max_source_age_ms': 5000}


def test_market_release_summary_separates_reference_quotes_and_keeps_unobserved_pnl_unknown():
    from bot.analyser.functional_report import summarize_market_quote_admission
    report = summarize_market_quote_admission(admission_fixture())
    assert report['quote_pairs_checked'] == 2
    assert report['launchlab_quote_pairs'] == 1
    assert report['reference_access_smoke_pairs'] == 1
    assert report['economically_qualified_cycles'] == 0
    assert report['pnl_net_sol'] is report['pnl_gross_sol'] is None
    assert report['observed_execution_costs_sol'] is None
    assert report['positions_acquired'] is report['execution_verified'] is False
    assert report['blocker_counts'] == {'buy_quote_body_missing': 2}
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('defect', ['duplicate_pair', 'invented_zero_pnl', 'inconsistent_pair_count'])
def test_market_summary_rejects_inflated_counts_or_invented_qualified_cashflows(defect):
    from bot.analyser.functional_report import summarize_market_quote_admission
    admission = admission_fixture()
    if defect == 'duplicate_pair':
        admission['pairs'][1] = admission['pairs'][0].copy()
    elif defect == 'invented_zero_pnl':
        admission['pairs'][0]['net_pnl_lamports'] = 0
    else:
        admission['pairs_checked'] = 3
    with pytest.raises(ValueError):
        summarize_market_quote_admission(admission)
