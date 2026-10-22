"""Synthetic, in-memory accounting scenarios; no market or user database."""
import contextlib
import io
import json
import sqlite3
import unittest

from bot.analyser.paper_engine import (
    _performance_metrics, _session_summary, _print_session_summary, paper_report,
)
from bot.analyser.paper_trader import setup, ensure_paper_portfolio


class RealizedPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.addCleanup(self.con.close)
        setup(self.con)
        ensure_paper_portfolio(self.con, 10, 0)

    def closed(self, mint, entry, exit_time, size, net, pnl):
        self.con.execute(
            "INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,"
            "exit_time,position_sol,net_return,pnl_sol,cost_bps,status) "
            "VALUES(?, 'synthetic', ?, ?, 1, ?, ?, ?, ?, 200, 'closed')",
            (mint, entry, entry, exit_time, size, net, pnl),
        )
        if pnl is not None:
            self.con.execute(
                'UPDATE paper_portfolio SET realized_capital_sol=realized_capital_sol+?',
                (pnl,),
            )

    def test_partial_allocation_and_net_costs(self):
        # 10% gross less 200 bps, on 1 SOL: +.08 SOL, +.8% portfolio.
        self.closed('a', 1, 2, 1, .08, .08)
        m = _performance_metrics(self.con)
        self.assertAlmostEqual(m['pnl_sol'], .08)
        self.assertAlmostEqual(m['net_return_after_costs'], .008)
        self.assertEqual(m['max_drawdown'], 0)

    def test_different_sizes_and_closure_order(self):
        # Insert backwards: SQL must order closures, not insertion or entry.
        self.closed('loss', 1, 30, 2, -.10, -.20)
        self.closed('win', 2, 20, 1, .10, .10)
        m = _performance_metrics(self.con)
        self.assertAlmostEqual(m['pnl_sol'], -.10)
        self.assertAlmostEqual(m['net_return_after_costs'], -.01)
        self.assertAlmostEqual(m['max_drawdown'], -.20 / 10.10)
        self.assertAlmostEqual(m['profit_factor'], .5)

    def test_sessions_use_closures_and_prior_capital(self):
        self.closed('prior', 1, 10, 1, .10, .10)
        self.closed('carried', 20, 110, 2, -.10, -.20)
        self.closed('later', 105, 300, 1, .50, .50)
        s = _session_summary(self.con, 100, 200)
        self.assertEqual(s['entries'], 1)
        self.assertEqual(s['closed_trades'], 1)
        self.assertEqual(s['open_positions'], 1)
        self.assertAlmostEqual(s['capital_start_sol'], 10.1)
        self.assertAlmostEqual(s['capital_end_sol'], 9.9)
        self.assertAlmostEqual(s['net_return_after_costs'], -.2 / 10.1)
        self.assertAlmostEqual(s['max_drawdown'], -.2 / 10.1)

    def test_session_bounds_and_carried_open_positions(self):
        self.closed('start', 1, 100, 1, -.1, -.1)
        self.closed('end', 2, 200, 1, .1, .1)
        self.con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,"
                         "entry_price,position_sol,status) VALUES('open','c',1,3,1,1,'open')")
        s = _session_summary(self.con, 100, 200)
        self.assertEqual(s['entries'], 0)
        self.assertEqual(s['closed_trades'], 2)
        self.assertEqual(s['open_positions'], 1)
        self.assertAlmostEqual(s['max_drawdown'], -.01)

    def test_unknown_history_is_not_zero(self):
        for exit_time, pnl in ((2, None), (None, .1)):
            with self.subTest(exit_time=exit_time, pnl=pnl):
                self.con.execute('DELETE FROM paper_trades')
                self.closed('unknown', 1, exit_time, 1, .1, pnl)
                for m in (_performance_metrics(self.con), _session_summary(self.con, 1, 5)):
                    self.assertFalse(m['performance_data_complete'])
                    self.assertIsNone(m['pnl_sol'])
                    self.assertIsNone(m['max_drawdown'])
                    self.assertIsNone(m['net_return_after_costs'])
                s = _session_summary(self.con, 1, 5)
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    _print_session_summary(s, 10, 10)
                self.assertIn('N/D', out.getvalue())
                json.dumps(s, allow_nan=False)

    def test_missing_prior_pnl_invalidates_session_reference(self):
        self.closed('old', 1, 2, 1, .1, None)
        self.closed('new', 100, 110, 1, .1, .1)
        self.assertIsNone(_session_summary(self.con, 100, 200)['net_return_after_costs'])

    def test_missing_portfolio_is_not_created(self):
        self.con.execute('DELETE FROM paper_portfolio')
        m = _performance_metrics(self.con)
        self.assertFalse(m['performance_data_complete'])
        self.assertIsNone(m['net_return_after_costs'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_portfolio').fetchone()[0], 0)

    def test_inconsistent_pnl_and_insolvent_curve_are_unknown(self):
        self.closed('bad', 1, 2, 1, -.1, -1)
        self.assertEqual(_performance_metrics(self.con)['inconsistent_closed_trades'], 1)
        self.con.execute('UPDATE paper_trades SET position_sol=20,net_return=-1,pnl_sol=-20')
        self.con.execute('UPDATE paper_portfolio SET realized_capital_sol=-10')
        self.assertIsNone(_performance_metrics(self.con)['max_drawdown'])

    def test_portfolio_must_reconcile_with_closed_pnl(self):
        self.closed('gain', 1, 2, 1, .1, .1)
        self.con.execute('UPDATE paper_portfolio SET realized_capital_sol=10')
        m = _performance_metrics(self.con)
        self.assertFalse(m['capital_reconciled'])
        self.assertIsNone(m['net_return_after_costs'])
        self.assertIsNone(m['pnl_sol'])

    def test_known_sol_pnl_is_not_dropped_when_trade_return_missing(self):
        self.closed('known', 1, 2, 1, None, .1)
        m = _performance_metrics(self.con)
        self.assertAlmostEqual(m['net_return_after_costs'], .01)
        self.assertIsNone(m['average_net_return'])
        self.assertTrue(m['capital_reconciled'])
        self.assertTrue(m['performance_data_complete'])
        self.assertEqual(m['invalid_position_closed_trades'], 0)

    def assert_invalid_position(self, size):
        for net in (.1, None):
            with self.subTest(size=size, net=net):
                self.con.execute('DELETE FROM paper_trades')
                self.con.execute('UPDATE paper_portfolio SET realized_capital_sol=10')
                self.closed('invalid-size', 1, 2, size, net, .1)
                for m in (_performance_metrics(self.con),
                          _session_summary(self.con, 1, 5),
                          paper_report(self.con, 5, 0)):
                    # Capital reconciliation alone cannot validate a position.
                    self.assertTrue(m['capital_reconciled'])
                    self.assertFalse(m['performance_data_complete'])
                    self.assertEqual(m['invalid_position_closed_trades'], 1)
                    for key in ('pnl_sol', 'net_return_after_costs', 'max_drawdown'):
                        self.assertIsNone(m[key])
                    json.dumps(m, allow_nan=False)

    def test_null_position_is_incomplete(self):
        self.assert_invalid_position(None)

    def test_zero_position_is_incomplete(self):
        self.assert_invalid_position(0)

    def test_negative_position_is_incomplete(self):
        self.assert_invalid_position(-1)

    def test_nonfinite_positions_are_incomplete(self):
        for size in (float('inf'), float('-inf'), float('nan')):
            # sqlite3 stores NaN as SQL NULL; infinities remain REAL values.
            self.assert_invalid_position(size)

    def test_nonnumeric_position_is_incomplete(self):
        self.assert_invalid_position('invalid')

    def test_invalid_position_outside_session_is_still_reported(self):
        self.closed('old', 1, 2, None, None, .1)
        self.closed('future', 100, 300, 0, None, .1)
        m = _session_summary(self.con, 100, 200)
        self.assertEqual(m['invalid_position_closed_trades'], 2)
        self.assertFalse(m['performance_data_complete'])

    def test_missing_return_requires_finite_implied_return(self):
        self.closed('tiny', 1, 2, 1e-320, None, .1)
        m = _performance_metrics(self.con)
        self.assertEqual(m['inconsistent_closed_trades'], 1)
        self.assertFalse(m['performance_data_complete'])
        self.assertIsNone(m['net_return_after_costs'])

    def test_zero_capital_and_no_trades(self):
        m = _performance_metrics(self.con)
        self.assertEqual(m['net_return_after_costs'], 0)
        self.assertEqual(m['max_drawdown'], 0)
        self.closed('wipeout', 1, 2, 10, -1, -10)
        m = _performance_metrics(self.con)
        self.assertEqual(m['net_return_after_costs'], -1)
        self.assertEqual(m['max_drawdown'], -1)

    def test_report_propagates_unknown_and_is_json_safe(self):
        self.closed('unknown', 1, 2, 1, .1, None)
        report = paper_report(self.con, 3, 0)
        self.assertIsNone(report['pnl_sol'])
        self.assertFalse(report['performance_data_complete'])
        self.assertEqual(report['equity_basis'], 'realized_sol')
        json.dumps(report, allow_nan=False)
