"""Atomic inventory transitions under cancellation, restart and exact uint64 lots."""
import asyncio
from contextlib import closing
import sqlite3

import pytest

from bot.analyser import token_inventory as inventory
from bot.analyser.paper_trader import record_quote, setup, MarketQuote, paper_capital
from bot.analyser.paper_engine import _realized_metrics
from bot.p3.accounting import SolFeeBreakdown
from bot.p3.collect import _record_quote
from test_p3_quotes import RaydiumQuoteClient, Session, Response, quote_payload, SOL_MINT, USDC


MODEL = dict(decision_approved=True, decision_score=75, tp_pct=10, sl_pct=8,
             hold_seconds=3600, cost_bps=200)
TABLES = ('paper_token_inventory','paper_token_legs','paper_token_exit_attempts',
          'paper_trades','paper_portfolio','paper_prices')


class InterruptedConnection(sqlite3.Connection):
    interrupt_after_capital = False

    def execute(self, statement, parameters=()):
        cursor = super().execute(statement, parameters)
        if self.interrupt_after_capital and statement.startswith('UPDATE paper_portfolio SET realized_capital_sol='):
            raise asyncio.CancelledError('synthetic cancellation after bankroll update')
        return cursor


def connect(path=':memory:'):
    con = sqlite3.connect(path, isolation_level=None, factory=InterruptedConnection)
    setup(con)
    return con


def observation(side, requested, *, quantity='1000', proceeds='1100000000', source=True):
    body = (quote_payload(output=quantity,minimum=quantity) if side == 'buy' else
            quote_payload(USDC,SOL_MINT,quantity,proceeds,proceeds))
    if source:
        body['data'].update(sourceTimeMs=requested-10,contextSlot=100 if side == 'buy' else 101)
    clocks, ticks = iter((requested,requested+20)), iter((0,1_000_000))
    quote = asyncio.run(RaydiumQuoteClient(Session(Response(body)),clock_ms=lambda:next(clocks),
        monotonic_ns=lambda:next(ticks)).quote(body['data']['inputMint'],body['data']['outputMint'],
                                             body['data']['inputAmount'],100))
    events=[]
    def append(kind,**event):
        events.append(dict(kind=kind,provenance='synthetic',available_at_ms=requested+21,**event))
    assert _record_quote(append,quote,side,'synthetic-'+str(requested))
    return events[0]


def enter(con, *, quantity='1000', source=True):
    context=dict(buy_observation=observation('buy',159970,quantity=quantity,source=source),
        token_decimals=6,fees=SolFeeBreakdown(5000,0,(),provenance='synthetic'),decision_at_ms=160000)
    result=record_quote(con,USDC,'creator',100,160,MarketQuote(12000,1,'pair'),MODEL,
        strategy_mode='shadow_final',inventory_context=context,require_inventory=True)
    assert result.startswith('ENTRY ')


def exit_context(con, quantity, proceeds, *, at=200, requested=None, fee=10000, version=None):
    state=inventory.inventory_state(con,USDC)
    return dict(sell_observation=observation('sell',at*1000-30 if requested is None else requested,
        quantity=str(quantity),proceeds=str(proceeds)),requested_quantity_atomic=str(quantity),
        inventory_version=state['version'] if version is None else version,
        fees=SolFeeBreakdown(5000,fee,(),provenance='synthetic'),decision_at_ms=at*1000)


def sell(con, context, at=200):
    return record_quote(con,USDC,'creator',100,at,MarketQuote(12000,1.2,'pair'),MODEL,
        strategy_mode='shadow_final',inventory_context=context,force_exit_reason='TEST')


def snapshot(con):
    return {table:con.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in TABLES}


@pytest.mark.parametrize('quantity',[400,1000])
def test_baseexception_after_capital_rolls_back_all_inventory_and_quote_state(quantity):
    with closing(connect()) as con:
        enter(con)
        before=snapshot(con)
        context=exit_context(con,quantity,500000000 if quantity==400 else 1100000000)
        con.interrupt_after_capital=True
        with pytest.raises(asyncio.CancelledError,match='bankroll'):
            sell(con,context)
        assert snapshot(con)==before
        assert con.in_transaction is False
        con.interrupt_after_capital=False
        assert sell(con,context).startswith('PARTIAL_EXIT ' if quantity==400 else 'EXIT ')
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(1,)
        assert con.execute('SELECT COUNT(*) FROM paper_token_exit_attempts').fetchone()==(1,)


def test_nested_cancellation_preserves_caller_transaction_and_rolls_back_only_leg():
    with closing(connect()) as con:
        enter(con)
        con.execute('BEGIN')
        con.execute("UPDATE paper_trades SET creator='caller-work' WHERE mint=?",(USDC,))
        before=snapshot(con)
        con.interrupt_after_capital=True
        with pytest.raises(asyncio.CancelledError):
            sell(con,exit_context(con,400,500000000))
        assert con.in_transaction is True and snapshot(con)==before
        con.interrupt_after_capital=False
        con.commit()
        assert con.execute('SELECT creator,status FROM paper_trades').fetchone()==('caller-work','open')


def test_uint64_lot_partial_basis_and_remainder_survive_sqlite_restart(tmp_path):
    path=tmp_path/'huge-lot.sqlite'
    total=2**64-1
    first=total//3
    with closing(connect(path)) as con:
        enter(con,quantity=str(total))
        assert con.execute('SELECT typeof(acquired_atomic),typeof(remaining_atomic) FROM paper_token_inventory').fetchone()==('text','text')
        assert sell(con,exit_context(con,first,500000000)).startswith('PARTIAL_EXIT ')
        state=inventory.inventory_state(con,USDC)
        assert int(state['remaining_atomic'])==total-first > 2**63-1
        assert int(state['cost_basis_remaining_lamports'])==1000005000-1000005000*first//total
    with closing(connect(path)) as con:
        remaining=int(inventory.inventory_state(con,USDC)['remaining_atomic'])
        assert sell(con,exit_context(con,remaining,600000000,at=201),at=201).startswith('EXIT ')
        quantities=con.execute('SELECT quantity_atomic,allocated_basis_lamports FROM paper_token_legs').fetchall()
        assert sum(int(row[0]) for row in quantities)==total
        assert sum(int(row[1]) for row in quantities)==1000005000
        assert inventory.inventory_state(con,USDC)['remaining_atomic']=='0'
        assert inventory.inventory_state(con,USDC)['cost_basis_remaining_lamports']=='0'
        assert paper_capital(con)[1]==pytest.approx(10.099975)
        metrics=_realized_metrics(con)
        assert metrics['capital_reconciled'] is True and metrics['realization_events']==2


def test_old_distinct_sell_quote_cannot_be_reused_after_partial_settlement():
    with closing(connect()) as con:
        enter(con)
        old_quote=exit_context(con,600,550000000,at=201,requested=199980)
        assert sell(con,exit_context(con,400,500000000)).startswith('PARTIAL_EXIT ')
        old_quote['inventory_version']=inventory.inventory_state(con,USDC)['version']
        before=inventory.inventory_state(con,USDC)
        capital=paper_capital(con)
        result=sell(con,old_quote,at=201)
        assert result.startswith('INVENTORY_EXIT_UNQUALIFIED ')
        assert inventory.inventory_state(con,USDC)==before and paper_capital(con)==capital
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(1,)


def test_stale_version_oversell_and_duplicate_never_credit_the_portfolio_twice():
    with closing(connect()) as con:
        enter(con)
        first=exit_context(con,400,500000000)
        assert sell(con,first).startswith('PARTIAL_EXIT ')
        capital=paper_capital(con)
        state=inventory.inventory_state(con,USDC)
        # Exact provider observation repeated at a later engine iteration.
        repeated=dict(first,decision_at_ms=201000,inventory_version=state['version'])
        assert sell(con,repeated,at=201).startswith('INVENTORY_DUPLICATE ')
        assert paper_capital(con)==capital
        # Independent fresh quote based on a stale inventory version.
        assert sell(con,exit_context(con,600,550000000,at=202,version=0),at=202).startswith('INVENTORY_EXIT_UNQUALIFIED ')
        assert sell(con,exit_context(con,601,550000000,at=203),at=203).startswith('INVENTORY_EXIT_UNQUALIFIED ')
        assert inventory.inventory_state(con,USDC)==state
        assert paper_capital(con)==capital
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(1,)


def test_unknown_buy_source_keeps_lot_but_never_settles_economic_proceeds():
    with closing(connect()) as con:
        enter(con,source=False)
        state=inventory.inventory_state(con,USDC)
        assert state['remaining_atomic']=='1000'
        result=sell(con,exit_context(con,1000,1100000000))
        assert result.startswith('INVENTORY_EXIT_UNQUALIFIED ')
        assert inventory.inventory_state(con,USDC)==state
        assert paper_capital(con)==(10,10)
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(0,)


def test_later_exit_fees_can_use_cash_already_realized_without_future_borrowing():
    with closing(connect()) as con:
        enter(con)
        assert sell(con,exit_context(con,500,100000000000)).startswith('PARTIAL_EXIT ')
        # The second 20 SOL fee was not known/reserved at entry, but is now fully
        # affordable from the first settled leg BEFORE second hypothetical proceeds.
        assert sell(con,exit_context(con,500,100000000000,at=201,fee=20000000000),at=201).startswith('EXIT ')
        assert inventory.inventory_state(con,USDC)['realized_pnl_lamports']=='178999985000'
        assert paper_capital(con)[1]==pytest.approx(188.999985)
        assert _realized_metrics(con)['pnl_sol']==pytest.approx(178.999985)


def test_current_exit_fee_cannot_borrow_from_its_own_assumed_future_proceeds():
    with closing(connect()) as con:
        enter(con)
        before=snapshot(con)
        context=exit_context(con,1000,100000000000,fee=20000000000)
        result=sell(con,context)
        assert result.startswith('INVENTORY_EXIT_UNQUALIFIED ')
        assert 'exit_fees_exceed_available_cash' in result
        after=snapshot(con)
        for table in ('paper_token_inventory','paper_token_legs','paper_portfolio'):
            assert after[table]==before[table]
        assert con.execute('SELECT status,pnl_sol FROM paper_trades').fetchone()==('open',None)
        assert con.execute('SELECT COUNT(*) FROM paper_token_exit_attempts').fetchone()==(1,)
        assert paper_capital(con)==(10,10)
