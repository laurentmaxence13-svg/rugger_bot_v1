"""Native quantities share the active PAPER bankroll, including partial legs."""
from contextlib import closing
import sqlite3

import pytest

from bot.analyser.paper_trader import (setup, record_quote, MarketQuote, paper_capital,
    _paper_free_capital, entry_allowed)
from bot.analyser.paper_engine import _realized_metrics
from bot.analyser.token_inventory import inventory_state
from bot.p3.accounting import SolFeeBreakdown
from test_p3_exit_qualification import event
from test_p3_quotes import quote_payload, SOL_MINT, USDC


MODEL = dict(decision_approved=True, decision_score=75, tp_pct=10, sl_pct=8,
             hold_seconds=3600, cost_bps=200)


def connect(path=':memory:', factory=sqlite3.Connection):
    con = sqlite3.connect(path,isolation_level=None,factory=factory)
    setup(con)
    return con


def enter(con, *, unknown_fee=False, decision_ms=160000):
    buy = event('buy',quote_payload(output='1000',minimum='900'),159970)
    context = dict(buy_observation=buy,token_decimals=6,
                   fees=SolFeeBreakdown(None if unknown_fee else 5000,0,(),provenance='synthetic'),
                   decision_at_ms=decision_ms)
    return record_quote(con,USDC,'creator',100,160,MarketQuote(12000,1,'pair'),MODEL,
        strategy_mode='shadow_final',inventory_context=context,require_inventory=True)


def sell(con, quantity, proceeds, *, at=200, price=1.2, fee=10000, force='TEST'):
    state = inventory_state(con,USDC)
    body = quote_payload(USDC,SOL_MINT,str(quantity),str(proceeds),str(proceeds))
    observation = event('sell',body,at*1000-30)
    context = dict(sell_observation=observation,requested_quantity_atomic=str(quantity),
        inventory_version=state['version'],fees=SolFeeBreakdown(5000,fee,(),provenance='synthetic'))
    return record_quote(con,USDC,'creator',100,at,MarketQuote(12000,price,'pair'),MODEL,
        strategy_mode='shadow_final',inventory_context=context,force_exit_reason=force)


def test_partial_then_full_after_restart_reconciles_basis_cash_and_one_credit(tmp_path):
    path=tmp_path/'synthetic.sqlite'
    with closing(connect(path)) as con:
        assert enter(con).startswith('ENTRY ')
        assert _paper_free_capital(con)==pytest.approx((10,8.999995))
        assert sell(con,400,500000000).startswith('PARTIAL_EXIT ')
        assert con.execute('SELECT status,pnl_sol FROM paper_trades').fetchone()==('open',None)
        assert _paper_free_capital(con)==pytest.approx((10.099988,9.499985))
        metrics=_realized_metrics(con)
        assert metrics['pnl_sol']==pytest.approx(.099988)
        assert metrics['closed_trades']==0 and metrics['realization_events']==1
        assert metrics['capital_reconciled'] is True
    with closing(connect(path)) as con:
        assert inventory_state(con,USDC)['remaining_atomic']=='600'
        assert sell(con,600,550000000,at=201).startswith('EXIT ')
        assert _paper_free_capital(con)==pytest.approx((10.049975,10.049975))
        metrics=_realized_metrics(con)
        assert metrics['pnl_sol']==pytest.approx(.049975)
        assert metrics['closed_trades']==1 and metrics['realization_events']==2
        assert metrics['capital_end_sol']==pytest.approx(10.049975)
        # A legacy closure is added exactly once beside the already settled legs.
        legacy=dict(creator_scores={'creator':.1},fallback_score=0,cost_bps=0)
        record_quote(con,'legacy','creator',100,202,(12000,1,'pair'),legacy)
        record_quote(con,'legacy','creator',100,203,(12000,1.1,'pair'),legacy,force_exit_reason='TEST')
        metrics=_realized_metrics(con)
        assert metrics['pnl_sol']==pytest.approx(.15047475)
        assert metrics['capital_end_sol']==pytest.approx(10.15047475)
        assert metrics['closed_trades']==2 and metrics['realization_events']==3


def test_partial_loss_is_counted_on_its_day_before_position_closes():
    with closing(connect()) as con:
        enter(con)
        sell(con,500,100000000,price=.8)
        assert con.execute('SELECT status FROM paper_trades').fetchone()==('open',)
        assert paper_capital(con)[1]==pytest.approx(9.5999875)
        assert entry_allowed(con,201,max_daily_loss_pct=3) is False
        assert entry_allowed(con,86401,max_daily_loss_pct=3) is True
        partial_session=_realized_metrics(con,200,200)
        assert partial_session['pnl_sol']==pytest.approx(-.4000125)
        next_session=_realized_metrics(con,201,201)
        assert next_session['pnl_sol']==0
        assert next_session['capital_start_sol']==pytest.approx(9.5999875)


def test_unknown_entry_fee_keeps_projected_quantity_but_cannot_invent_available_cash():
    with closing(connect()) as con:
        assert enter(con,unknown_fee=True).startswith('ENTRY ')
        state=inventory_state(con,USDC)
        assert state['acquired_atomic']=='1000' and state['cost_basis_remaining_lamports'] is None
        with pytest.raises(ValueError):
            _paper_free_capital(con)
        assert paper_capital(con)==(10,10)
        assert entry_allowed(con,201) is False


def test_inventory_position_cannot_close_from_price_without_exact_sell_evidence():
    with closing(connect()) as con:
        enter(con)
        message=record_quote(con,USDC,'creator',100,200,MarketQuote(12000,2,'pair'),MODEL,
                             strategy_mode='shadow_final')
        assert message.startswith('INVENTORY_EXIT_UNQUALIFIED ')
        assert inventory_state(con,USDC)['remaining_atomic']=='1000'
        assert paper_capital(con)==(10,10)
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(0,)


def test_millisecond_decision_must_belong_to_recorded_quote_second():
    with closing(connect()) as con:
        with pytest.raises(ValueError,match='decision time'):
            enter(con,decision_ms=161000)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()==(0,)


@pytest.mark.parametrize('stage', ['leg_insert','portfolio_credit','position_close'])
def test_every_native_financial_write_must_succeed_or_rollback_all_state(stage):
    with closing(connect()) as con:
        enter(con)
        definition = {
            'leg_insert': 'BEFORE INSERT ON paper_token_legs',
            'portfolio_credit': 'BEFORE UPDATE ON paper_portfolio',
            'position_close': 'BEFORE UPDATE OF status ON paper_trades',
        }[stage]
        con.execute('CREATE TRIGGER reject_financial_write '+definition+' BEGIN SELECT RAISE(IGNORE); END')
        with pytest.raises((ValueError,RuntimeError)):
            sell(con,400,500000000) if stage == 'leg_insert' else sell(con,1000,1200000000)
        assert paper_capital(con)==(10,10)
        assert inventory_state(con,USDC)['remaining_atomic']=='1000'
        assert inventory_state(con,USDC)['version']==0
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(0,)
        assert con.execute('SELECT status,pnl_sol FROM paper_trades').fetchone()==('open',None)


def test_inventory_insert_failure_cannot_leave_an_untracked_legacy_position():
    with closing(connect()) as con:
        con.execute('CREATE TRIGGER reject_inventory BEFORE INSERT ON paper_token_inventory '
                    'BEGIN SELECT RAISE(IGNORE); END')
        with pytest.raises((ValueError,RuntimeError)):
            enter(con)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()==(0,)
        assert con.execute('SELECT COUNT(*) FROM paper_token_inventory').fetchone()==(0,)
        assert paper_capital(con)==(None,None)
