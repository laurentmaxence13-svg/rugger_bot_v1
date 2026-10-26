"""A reconciled simulated ledger must not claim observed FX or executable SOL PnL."""
import json

import pytest

from test_paper_report_cleanup import synthetic_session


@pytest.mark.parametrize('mode,capital', [('tp', 10.18), ('sl', 9.78)])
def test_completed_paper_session_keeps_economic_limit_in_both_reports(tmp_path, mode, capital):
    result = synthetic_session(tmp_path / mode, mode)
    periodic = json.loads(result['periodic'])
    session = json.loads(result['session'])
    assert session['capital_end_sol'] == pytest.approx(capital)
    assert periodic['realized_capital_sol'] == pytest.approx(capital)
    assert session['closed_trades'] == 1
    assert periodic['capital_reconciled'] is True
    for report in (periodic, session):
        scope = report['valuation_scope']
        assert scope['account_currency'] == 'SOL'
        assert scope['observed_price_currency'] == 'USD'
        assert scope['return_conversion_assumption'] == 'constant_SOL_USD'
        assert scope['fx_observed_at_entry_and_exit'] is False
        assert scope['economic_pnl_verified'] is False
        assert scope['execution_prices_verified'] is False
