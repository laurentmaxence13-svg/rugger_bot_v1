"""Persist the cost assumption actually charged by an active PAPER closure."""
from contextlib import closing
from dataclasses import replace
import math
import sqlite3

import pytest

from bot.analyser.final_decision_engine import Decision
from bot.analyser.paper_engine import _performance_metrics
from bot.analyser.paper_trader import MarketQuote, paper_capital, record_quote, setup


def test_changed_closure_cost_is_recoverable_and_matches_net_pnl_after_restart(tmp_path):
    path = tmp_path/'synthetic.db'
    entry = Decision(enter=True, score=75, reasons=(), risk_flags=(),
                     tp_pct=10, sl_pct=8, hold_seconds=300,
                     trailing_stop_pct=None, cost_bps=200)
    closing_decision = replace(entry, cost_bps=1000)
    with closing_connection(path) as con:
        setup(con)
        assert record_quote(con, 'synthetic-mint', 'synthetic-creator', 100, 160,
                            MarketQuote(12000, 1, 'synthetic-pair'), entry.to_paper_model(),
                            strategy_mode='shadow_final').startswith('ENTRY ')
        assert record_quote(con, 'synthetic-mint', 'synthetic-creator', 100, 200,
                            MarketQuote(12000, 1.2, 'synthetic-pair'), closing_decision.to_paper_model(),
                            strategy_mode='shadow_final').startswith('EXIT ')
    # A restarted reporter only has the persisted ledger, not the latest model.
    with closing_connection(path) as con:
        paid_cost_bps, net, pnl, position = con.execute(
            'SELECT cost_bps,net_return,pnl_sol,position_sol FROM paper_trades').fetchone()
        gross = 1.2/1-1
        assert paid_cost_bps == 1000
        assert math.isclose(gross-net, paid_cost_bps/10000, abs_tol=1e-12)
        assert math.isclose(pnl, position*net, abs_tol=1e-12)
        assert math.isclose(paper_capital(con)[1], 10.1, abs_tol=1e-12)
        assert _performance_metrics(con)['assumed_cost_bps_total'] == 1000


def closing_connection(path):
    return closing(sqlite3.connect(path, isolation_level=None))


def test_failed_closure_rolls_back_changed_cost_assumption_with_capital():
    class FailingCapital(sqlite3.Connection):
        fail = False
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if self.fail and sql.startswith('UPDATE paper_portfolio SET realized_capital_sol='):
                raise RuntimeError('synthetic failure after capital update')
            return cursor
    with closing(sqlite3.connect(':memory:', isolation_level=None, factory=FailingCapital)) as con:
        setup(con)
        model = dict(creator_scores={'creator': .1}, fallback_score=0, cost_bps=200)
        record_quote(con, 'mint', 'creator', 100, 160, (12000, 1, 'pair'), model)
        con.fail = True
        with pytest.raises(RuntimeError, match='synthetic failure'):
            record_quote(con, 'mint', 'creator', 100, 200, (12000, 1.2, 'pair'),
                         dict(model, cost_bps=1000), force_exit_reason='TEST')
        assert con.execute('SELECT status,cost_bps,pnl_sol FROM paper_trades').fetchone() == ('open', 200, None)
        assert paper_capital(con) == (10, 10)
