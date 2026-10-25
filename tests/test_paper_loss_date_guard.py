"""Fail-closed daily loss checks on synthetic ledgers only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from bot.analyser import paper_trader as pt
from bot.analyser import paper_engine as pe

MODEL=pe.shadow_baseline_model()
QUOTE=pt.MarketQuote(20000,1,'pair',quote_source='dex_market')

class ObservedConnection(sqlite3.Connection):
    attempting=None
    def execute(self,sql,parameters=()):
        if sql=='BEGIN IMMEDIATE' and self.attempting is not None:
            self.attempting.set()
        return super().execute(sql,parameters)

class DailyLossDateGuardTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(self.con.close)
        pt.setup(self.con); pt.ensure_paper_portfolio(self.con,10,100)
    def enter(self,mint='new',now=201,**kwargs):
        return pt.record_quote(self.con,mint,'creator',now-65,now,QUOTE,MODEL,**kwargs)
    def close(self,mint,price=.02,now=200,**kwargs):
        quote=pt.MarketQuote(20000,price,'pair',quote_source='dex_market')
        return pt.record_quote(self.con,mint,'creator',now-100,now,quote,MODEL,**kwargs)
    def loss(self,price=.02,mint='loss',entry=165,exit=200):
        self.assertTrue(self.enter(mint,entry).startswith('ENTRY '))
        self.assertTrue(self.close(mint,price,exit).startswith('EXIT '))
    def finances(self):
        return (self.con.execute('SELECT * FROM paper_trades ORDER BY mint').fetchall(),
                self.con.execute('SELECT * FROM paper_portfolio').fetchall())

    def test_null_exit_time_cannot_bypass_realized_loss(self):
        self.loss()
        self.assertFalse(pt.entry_allowed(self.con,201))
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='loss'")
        before=self.finances()
        self.assertFalse(pt.entry_allowed(self.con,201))
        self.assertIsNone(self.enter())
        self.assertEqual(self.finances(),before)
        self.assertEqual(pt.paper_capital(self.con),(10,9))

    def test_no_losses_and_valid_zero_pnl_history(self):
        self.assertTrue(pt.entry_allowed(self.con,201))
        self.loss(price=1.02,exit=3765)  # Timeout: gross +2%, costs 2%.
        self.assertTrue(pt.entry_allowed(self.con,3766))
        self.assertTrue(self.enter(now=3766).startswith('ENTRY '))

    def test_loss_below_boundary(self):
        self.loss(price=.8)
        self.assertAlmostEqual(pt.paper_capital(self.con)[1],9.78)
        self.assertTrue(pt.entry_allowed(self.con,201))
        self.assertTrue(self.enter().startswith('ENTRY '))

    def test_loss_equal_boundary(self):
        self.loss(price=.02)
        self.assertEqual(pt.paper_capital(self.con),(10,9))
        self.assertFalse(pt.entry_allowed(self.con,201))
        self.assertIsNone(self.enter())

    def test_loss_above_boundary(self):
        self.loss(price=0)
        self.assertAlmostEqual(pt.paper_capital(self.con)[1],8.98)
        self.assertFalse(pt.entry_allowed(self.con,201))

    def test_multiple_losses_accumulate_in_sol(self):
        self.loss(price=.5,mint='first')  # -0.52 SOL, bankroll 9.48.
        self.loss(price=.5,mint='second',entry=201,exit=202)  # .948 * -.52 = -.49296.
        self.assertAlmostEqual(pt.paper_capital(self.con)[1],8.98704)
        self.assertFalse(pt.entry_allowed(self.con,203))
        self.assertIsNone(self.enter(now=203))

    def test_null_pnl_in_today_or_previous_day_refuses(self):
        self.loss()
        for exit_time in (200,86420):
            with self.subTest(exit_time=exit_time):
                self.con.execute("UPDATE paper_trades SET exit_time=?,pnl_sol=NULL WHERE mint='loss'",(exit_time,))
                self.assertFalse(pt.entry_allowed(self.con,86500))

    def test_mixed_valid_and_undated_history_refuses_even_gain(self):
        self.loss(price=1.2,mint='gain')
        self.loss(price=.8,mint='loss',entry=201,exit=202)
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='gain'")
        before=self.finances()
        self.assertFalse(pt.entry_allowed(self.con,203))
        self.assertIsNone(self.enter(now=203))
        self.assertEqual(self.finances(),before)

    def test_prior_day_losses_are_not_todays_losses(self):
        self.loss(price=.02)
        self.assertTrue(pt.entry_allowed(self.con,86500))
        self.assertTrue(self.enter(now=86500).startswith('ENTRY '))

    def test_overnight_closure_counts_on_exit_day(self):
        self.loss(price=.02,entry=86300,exit=86410)
        self.assertFalse(pt.entry_allowed(self.con,86411))
        self.assertTrue(pt.entry_allowed(self.con,172900))

    def test_future_negative_text_infinite_and_reversed_exit_dates_refuse(self):
        self.loss(price=1.2)
        for date in (None,202,-1,'not-a-date',float('inf'),float('-inf'),float('nan'),164):
            with self.subTest(exit_time=date):
                self.con.execute("UPDATE paper_trades SET exit_time=? WHERE mint='loss'",(date,))
                before=self.finances()
                self.assertFalse(pt.entry_allowed(self.con,201))
                self.assertIsNone(self.enter('blocked'))
                self.assertEqual(self.finances(),before)

    def test_invalid_entry_dates_in_closed_history_refuse(self):
        self.loss(price=1.2)
        for date in ('unknown',-1,201,float('inf')):
            with self.subTest(entry_time=date):
                self.con.execute("UPDATE paper_trades SET entry_time=? WHERE mint='loss'",(date,))
                self.assertFalse(pt.entry_allowed(self.con,202))

    def test_nonfinite_or_text_pnl_refuses(self):
        self.loss(price=.8)
        for pnl in (None,'unknown',float('inf'),float('-inf'),float('nan')):
            with self.subTest(pnl=pnl):
                self.con.execute("UPDATE paper_trades SET pnl_sol=? WHERE mint='loss'",(pnl,))
                self.assertFalse(pt.entry_allowed(self.con,201))

    def test_explicitly_disabled_guard_keeps_existing_policy(self):
        self.loss()
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='loss'")
        for index,disabled in enumerate((None,0,-1)):
            with self.subTest(limit=disabled):
                self.assertTrue(pt.entry_allowed(self.con,201,max_daily_loss_pct=disabled))
                self.assertTrue(self.enter('disabled'+str(index),max_daily_loss_pct=disabled).startswith('ENTRY '))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'").fetchone()[0],3)
        self.assertFalse(pt.entry_allowed(self.con,201,max_daily_loss_pct=None)) # Other limits still apply.

    def test_disabled_policy_does_not_bypass_existing_capital_integrity(self):
        self.loss(price=.8)
        self.con.execute("UPDATE paper_trades SET pnl_sol=NULL WHERE mint='loss'")
        self.assertTrue(pt.entry_allowed(self.con,201,max_daily_loss_pct=None))
        with self.assertRaises(ValueError): self.enter(max_daily_loss_pct=None)

    def test_open_positions_still_close_and_pnl_not_applied_twice(self):
        self.assertTrue(self.enter('active',165).startswith('ENTRY '))
        self.loss(price=.8,mint='historical',entry=166,exit=200)
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='historical'")
        self.assertFalse(pt.entry_allowed(self.con,201))
        message=self.close('active',1.2,201,allow_entry=False)
        self.assertTrue(message.startswith('EXIT '))
        self.assertAlmostEqual(pt.paper_capital(self.con)[1],9.96)
        self.assertIsNone(self.close('active',1.2,202))
        self.assertAlmostEqual(pt.paper_capital(self.con)[1],9.96)
        self.assertIsNone(self.enter('blocked',203))

    def test_under_lock_recheck_ignores_stale_advisory_permission(self):
        self.loss(price=.8)
        self.assertTrue(pt.entry_allowed(self.con,201))
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='loss'")
        seen=[]; original=pt.entry_allowed
        def checked(con,now,**kwargs):
            seen.append(con.in_transaction)
            return original(con,now,**kwargs)
        before=self.finances()
        with patch.object(pt,'entry_allowed',side_effect=checked):
            self.assertIsNone(self.enter(allow_entry=True))
        self.assertEqual(seen,[True]); self.assertEqual(self.finances(),before)

    def test_caller_rollback_retains_original_history(self):
        self.loss(price=.8)
        self.con.execute('BEGIN')
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='loss'")
        self.assertIsNone(self.enter())
        self.assertTrue(self.con.in_transaction)
        self.con.rollback()
        self.assertTrue(pt.entry_allowed(self.con,201))
        self.assertEqual(self.con.execute("SELECT exit_time FROM paper_trades WHERE mint='loss'").fetchone()[0],200)

    def test_restart_and_replay_keep_refusal_and_capital(self):
        self.loss()
        self.con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='loss'")
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.db'
            with closing(sqlite3.connect(path)) as destination: self.con.backup(destination)
            for index in range(2):
                with closing(sqlite3.connect(path,isolation_level=None)) as con:
                    self.assertFalse(pt.entry_allowed(con,201+index))
                    self.assertIsNone(pt.record_quote(con,'new','creator',136,201+index,QUOTE,MODEL))
                    self.assertIsNone(pt.record_quote(con,'loss','creator',100,201+index,QUOTE,MODEL))
                    self.assertEqual(pt.paper_capital(con),(10,9))
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],1)

    def test_entry_waits_for_committed_date_invalidation_then_refuses(self):
        self.loss(price=.8)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.db'
            with closing(sqlite3.connect(path)) as destination: self.con.backup(destination)
            writer_ready=threading.Event(); entry_attempting=threading.Event()
            def invalidate():
                with closing(sqlite3.connect(path,isolation_level=None,timeout=5)) as con:
                    con.execute('BEGIN IMMEDIATE')
                    con.execute("UPDATE paper_trades SET exit_time=NULL WHERE mint='loss'")
                    writer_ready.set()
                    if not entry_attempting.wait(5): raise AssertionError('entry did not request its lock')
                    con.commit()
            def enter():
                if not writer_ready.wait(5): raise AssertionError('writer not ready')
                with closing(sqlite3.connect(path,isolation_level=None,timeout=5,factory=ObservedConnection)) as con:
                    con.attempting=entry_attempting
                    return pt.record_quote(con,'new','creator',136,201,QUOTE,MODEL,allow_entry=True)
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer=pool.submit(invalidate); entrant=pool.submit(enter)
                writer.result(timeout=10); self.assertIsNone(entrant.result(timeout=10))
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],1)
                self.assertAlmostEqual(pt.paper_capital(con)[1],9.78)

    def test_valid_fractional_unix_dates_preserved(self):
        self.loss(price=.8)
        self.con.execute("UPDATE paper_trades SET exit_time=200.5 WHERE mint='loss'")
        self.assertTrue(pt.entry_allowed(self.con,201))

if __name__=='__main__': unittest.main()
