"""Exact inventory reporting over the one PAPER ledger; no provider/database access."""
import json
import sqlite3

import pytest

from bot.analyser.functional_report import build_functional_report
from bot.analyser.paper_trader import setup, ensure_paper_portfolio
from bot.analyser.token_inventory import setup_inventory_schema


def ledger():
    con = sqlite3.connect(':memory:')
    setup(con)
    ensure_paper_portfolio(con, 10, 0)
    return con


def native_position(con, *, partial=False, entry_extra=1000):
    setup_inventory_schema(con)
    acquired, remaining = 100, 60 if partial else 0
    total_basis = 1_000_000_000+entry_extra
    allocated = total_basis*40//100 if partial else total_basis
    proceeds, exit_fee = (500_000_000 if partial else 1_200_000_000), 2000
    pnl = proceeds-exit_fee-allocated
    status = 'open' if partial else 'closed'
    con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,"
        "exit_time,position_sol,pnl_sol,net_return,cost_bps,status) VALUES('native','c',1,1,1,?,1,?,?,9999,?)",
        (None if partial else 2,None if partial else pnl/1e9,None if partial else pnl/1e9,status))
    con.execute("INSERT INTO paper_token_inventory(mint,acquired_atomic,remaining_atomic,token_decimals,"
        "entry_budget_lamports,entry_extra_lamports,cost_basis_total_lamports,cost_basis_remaining_lamports,"
        "entry_decision_ms,entry_observation_json,source_provenance,inventory_basis,entry_available_cash_lamports,"
        "realized_pnl_lamports,version) VALUES('native','100',?,6,'1000000000',?,?,?,1000,'{}','synthetic',"
        "'expected_buy_output','10000000000',?,1)",
        (str(remaining),str(entry_extra),str(total_basis),str(total_basis-allocated),str(pnl)))
    con.execute("INSERT INTO paper_token_legs VALUES('leg','native',2000,?,?,?,?,?,'{}','synthetic')",
        (str(acquired-remaining),str(proceeds),str(exit_fee),str(allocated),str(pnl)))
    con.execute('UPDATE paper_portfolio SET realized_capital_sol=?', (10+pnl/1e9,))
    return pnl


def test_legacy_history_does_not_get_invented_atomic_inventory():
    with ledger() as con:
        con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,position_sol,status) "
                    "VALUES('legacy','c',1,1,1,1,'open')")
        report = build_functional_report(con, data_kind='synthetic')
        inventory = report['atomic_inventory']
        assert inventory['positions'] == []
        assert inventory['positions_with_atomic_inventory'] == 0
        assert inventory['legacy_positions_inventory_unknown'] == 1
        assert report['metrics']['positions_open']['value'] == 1
        assert report['metrics']['positions_without_qualified_exit']['value'] is None


def test_native_full_costs_use_exact_extra_fees_not_derived_basis_points_twice():
    with ledger() as con:
        pnl = native_position(con)
        before = con.total_changes
        report = build_functional_report(con, data_kind='synthetic')
        assert con.total_changes == before
        inv = report['atomic_inventory']
        assert inv['positions_fully_settled'] == 1
        assert inv['positions_open_partial'] == 0
        assert inv['positions'][0]['acquired_atomic'] == '100'
        assert inv['positions'][0]['remaining_atomic'] == '0'
        assert inv['realized_pnl_lamports'] == str(pnl)
        assert inv['recognized_extra_fee_lamports'] == '3000'
        assert inv['positions'][0]['entry_decision_ms'] == 1000
        assert inv['positions'][0]['settled_exit_legs'][0]['decision_ms'] == 2000
        assert inv['positions'][0]['settled_exit_legs'][0]['extra_fee_lamports'] == '2000'
        assert report['metrics']['pnl_net_sol']['value'] == pytest.approx(.199997)
        assert report['metrics']['modeled_cost_sol']['value'] == pytest.approx(.000003)
        assert report['metrics']['pnl_gross_sol']['value'] == pytest.approx(.2)
        assert report['metrics']['pnl_net_sol']['reliability'] == 'model_only'
        json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('entry_extra', [0, 1000])
def test_partial_native_legs_are_realized_without_full_trade_or_invented_entry_fee_split(entry_extra):
    with ledger() as con:
        pnl = native_position(con,partial=True,entry_extra=entry_extra)
        for n, accepted in enumerate((True,False,None)):
            con.execute('INSERT INTO paper_token_exit_attempts VALUES(?,?,?,?,?)',
                (str(n),'native',2000+n,None,json.dumps({'accepted':accepted})))
        report = build_functional_report(con,data_kind='synthetic')
        inv = report['atomic_inventory']
        assert report['metrics']['positions_closed']['value'] == 0
        assert report['metrics']['positions_open']['value'] == 1
        assert report['metrics']['pnl_net_sol']['value'] == pytest.approx(pnl/1e9)
        assert inv['positions_open_partial'] == 1
        assert inv['positions'][0]['remaining_atomic'] == '60'
        assert inv['positions'][0]['settled_fraction'] == '2/5'
        assert inv['settled_exit_extra_fee_lamports'] == '2000'
        assert inv['attempts'] == {'accepted':1,'rejected':1,'unknown':1}
        assert report['metrics']['positions_without_qualified_exit']['value'] is None
        if entry_extra:
            assert inv['entry_extra_fee_capitalized_lamports'] == '1000'
            assert inv['recognized_extra_fee_lamports'] is None
            assert report['metrics']['modeled_cost_sol']['value'] is None
            assert report['metrics']['pnl_gross_sol']['value'] is None
        else:
            assert inv['recognized_extra_fee_lamports'] == '2000'
            assert report['metrics']['modeled_cost_sol']['value'] == pytest.approx(.000002)
        json.dumps(report, allow_nan=False)


def market_events(sell_quantity='10'):
    import asyncio
    from bot.p3.collect import _record_quote
    from test_p3_quotes import RaydiumQuoteClient, Session, Response, quote_payload, SOL_MINT, USDC
    events = []
    for n, (phase, side) in enumerate((('initial','buy'),('initial','sell'),('followup','buy'),('followup','sell')),1):
        body = (quote_payload(output='1000', minimum='990') if side == 'buy' else
                quote_payload(USDC,SOL_MINT,sell_quantity,'100','99'))
        clock = iter((1000+n*100,1020+n*100)); mono = iter((0,1000000))
        quote = asyncio.run(RaydiumQuoteClient(Session(Response(body)),clock_ms=lambda:next(clock),
            monotonic_ns=lambda:next(mono)).quote(body['data']['inputMint'],body['data']['outputMint'],
            body['data']['inputAmount'],100))
        def append(kind, **record):
            record['payload']['probe_phase'] = phase
            events.append(dict(kind=kind,id=n,available_at_ms=quote['received_at_ms']+1,
                               provenance='live',**record))
            return n
        assert _record_quote(append,quote,side,'phase-'+str(n))
    control = dict(schema='p3-active-exit-result-v1',position_acquired=False,execution_verified=False,
                   net_pnl_lamports=None,records=len(events),selected_mint=USDC,
                   fixed_sell_quantity_atomic=sell_quantity)
    return events,control


def test_market_partial_projection_preserves_inventory_without_settlement_or_unknown_fee_profit():
    from bot.analyser.functional_report import summarize_atomic_market_events
    events,control = market_events()
    report = summarize_atomic_market_events(events,control,token_decimals=6)
    assert report['projected_entry_inventory_atomic'] == '1000'
    assert report['projected_remaining_after_one_indicative_sale_atomic'] == '990'
    assert report['indicative_sell_quotes_available'] == report['indicative_sell_quotes_attempted'] == 2
    assert report['freshness_status'] == 'UNKNOWN'
    assert report['full_projected_quantity_sell_requests'] == 0
    assert report['full_projected_quantity_quote_availability_rate'] is None
    assert report['settled_legs'] == report['qualified_economic_cycles'] == 0
    assert report['pnl_net_sol'] is report['additional_execution_costs_lamports'] is None
    assert all(not attempt['strict_exit_accepted'] for attempt in report['attempts'])
    json.dumps(report,allow_nan=False)


def test_quote_availability_does_not_become_economic_admission_when_full_size_is_quoted():
    from bot.analyser.functional_report import summarize_atomic_market_events
    events,control = market_events('1000')
    report = summarize_atomic_market_events(events,control,token_decimals=6)
    assert report['full_projected_quantity_sell_requests'] == 2
    assert report['full_projected_quantity_quote_availability_rate'] == 1
    assert report['strict_qualified_partial_exit_observations'] == 0
    assert report['settled_legs'] == 0
    assert report['pnl_net_sol'] is None
