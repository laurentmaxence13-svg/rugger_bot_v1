"""Offline integration of projected atomic inventory with the active PAPER loop.

``await run_economic_demo(new_directory)`` creates four independent synthetic
ledgers. Quotes are deterministic fixture observations, never HTTP responses or
blockchain fills. The explicit no-scanner lane does not attest supervision.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3


class _Clock:
    def __init__(self, milliseconds):
        self.milliseconds = milliseconds

    def __call__(self):
        return self.milliseconds/1000

    def advance(self, milliseconds=1000):
        self.milliseconds += milliseconds


def _load_api():
    previous = os.environ.get('RUGGER_NO_DOTENV')
    os.environ['RUGGER_NO_DOTENV'] = '1'
    try:
        from bot.analyser import paper_engine as engine
        from bot.analyser.behavior_pipeline import load_cached_transactions
        from bot.analyser.multi_creator_research_engine import ensure_schema
        from bot.analyser.paper_trader import (
            MarketQuote, setup, ensure_paper_portfolio, _paper_free_capital,
        )
        from bot.database.db import Database
        from bot.p3.accounting import SolFeeBreakdown
        from bot.p3.collect import _record_quote
        from bot.p3.quotes import RaydiumQuoteClient, SOL_MINT
        from bot.scanner.launch_detector import parse_launch_candidate
        from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID
        from bot.scanner.tx_recovery import TransactionRecovery
        return locals()
    finally:
        if previous is None:
            os.environ.pop('RUGGER_NO_DOTENV', None)
        else:
            os.environ['RUGGER_NO_DOTENV'] = previous


def _public_address(value):
    """Repeated public fixture bytes, not generated wallet/signing material."""
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number, encoded = int.from_bytes(bytes([value])*32, 'big'), ''
    while number:
        number, digit = divmod(number, 58)
        encoded = alphabet[digit]+encoded
    return encoded


def _fixture_launch(api, database, epoch, clock, mint, creator, pool):
    accounts = [_public_address(n) for n in (4, 2, 5, 6, 7, 3, 1)]
    signature = '3'*88
    transaction = {
        'slot':100, 'blockTime':epoch, 'meta':{'err':None},
        'transaction':{'signatures':[signature], 'message':{
            'accountKeys':[{'pubkey':key, 'signer':i in (0, 1), 'writable':True}
                           for i, key in enumerate(accounts)],
            'instructions':[{'programId':api['RAYDIUM_LAUNCHPAD_PROGRAM_ID'],
                             'accounts':accounts, 'parsed':{'type':'initialize_v2'}}]}}}
    event = {'signature':signature, 'slot':100,
             'received_at':datetime.fromtimestamp(epoch+1, timezone.utc)}
    recovery = api['TransactionRecovery'](database)
    if not recovery.enqueue(event, clock()):
        raise RuntimeError('Synthetic launch unexpectedly already exists')
    job = recovery.claim_due(clock())
    parsed = api['parse_launch_candidate'](transaction, event['received_at'])
    if recovery.complete(job, transaction, parsed, clock()) != 1:
        raise RuntimeError('Recovery/parser did not preserve the synthetic launch')
    return api['load_cached_transactions'](database)


def _quote_observation(api, *, side, mint, pool, amount, output, requested, index, case):
    """Use the production pure parser and retention envelope; never a transport."""
    sol = api['SOL_MINT']
    input_mint, output_mint = (sol, mint) if side == 'buy' else (mint, sol)
    minimum = int(output)*99//100 if output is not None else None
    body = ({'success':False, 'msg':'INSUFFICIENT_LIQUIDITY'} if output is None else {
        'success':True, 'data':{
            'swapType':'BaseIn', 'inputMint':input_mint, 'outputMint':output_mint,
            'inputAmount':str(amount), 'actualInputAmount':str(amount),
            'outputAmount':str(output), 'otherAmountThreshold':str(minimum),
            'slippageBps':100, 'priceImpactPct':'0',
            'sourceTimeMs':requested-5, 'contextSlot':100+index,
            'routePlan':[{'poolId':pool, 'inputMint':input_mint,
                'outputMint':output_mint, 'feeMint':input_mint,
                'feeAmount':'0', 'feeRate':0}]}})
    quote = dict(provider='raydium_trade_api', outcome='error', reason=None,
        input_mint=input_mint, output_mint=output_mint, input_amount_atomic=str(amount),
        actual_input_amount_atomic=None, output_amount_atomic=None,
        min_output_amount_atomic=None, slippage_bps=100, route=[], price_impact_pct=None,
        fee_details={'route_fees':[], 'network_fee_lamports':None,
            'priority_fee_lamports':None, 'account_creation_lamports':None,
            'total_cost_known':False, 'additional_costs_must_not_duplicate_route_fees':True},
        source_slot=None, source_time_ms=None, quality_flags=[],
        execution_guaranteed=False, executable_confirmed=False,
        requested_at_ms=requested, received_at_ms=requested+10, latency_ms=0,
        http_status=200, raw_payload=body, response_body_status='synthetic_json_fixture',
        retry_after_seconds=None)
    api['RaydiumQuoteClient']._parse(body, quote)
    if quote['source_time_ms'] is None:
        quote['quality_flags'].append('provider_source_time_unknown')
    if quote['source_slot'] is None:
        quote['quality_flags'].append('provider_context_slot_unknown')
    quote['quality_flags'].append('additional_execution_costs_unknown')
    events = []
    def append(kind, **event):
        events.append(dict(kind=kind, provenance='synthetic',
                           available_at_ms=requested+11, **event))
    if not api['_record_quote'](append, quote, side, f'synthetic-{case}-{side}-{index}'):
        raise RuntimeError('Synthetic quote was rejected by retention policy')
    return events[0]


def _state(con, api, mint, stage, messages):
    cursor = con.execute('SELECT * FROM paper_token_inventory WHERE mint=?', (mint,))
    raw = cursor.fetchone()
    inventory = dict(zip((column[0] for column in cursor.description), raw)) if raw else None
    trade = con.execute('SELECT status,exit_reason,pnl_sol FROM paper_trades WHERE mint=?', (mint,)).fetchone()
    capital, free = api['_paper_free_capital'](con)
    return {'stage':stage, 'messages':messages, 'position_state':trade[0] if trade else None,
            'exit_reason':trade[1] if trade else None,
            'aggregate_position_pnl_sol':trade[2] if trade else None,
            'inventory':inventory, 'capital_sol':capital, 'free_capital_sol':free,
            'settled_legs':con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()[0],
            'exit_attempts':con.execute('SELECT COUNT(*) FROM paper_token_exit_attempts').fetchone()[0]}


async def _run_case(api, output, name, expected_pnl_lamports):
    output.mkdir()
    database = output/'paper.sqlite'
    api['Database'](database)
    api['ensure_schema'](database)
    con = sqlite3.connect(database, isolation_level=None)
    engine = api['engine']
    epoch = 1_700_000_000
    clock = _Clock((epoch+1)*1000)
    mint, creator, pool = (_public_address(n) for n in (1, 2, 3))
    try:
        api['setup'](con)
        engine.ensure_signal_status_schema(con)
        engine.ensure_audit_schema(con)
        api['ensure_paper_portfolio'](con, 10.0, int(clock()))
        cached = _fixture_launch(api, database, epoch, clock, mint, creator, pool)
        candidate = con.execute('SELECT mint,deployer_candidate,pool_state FROM launch_candidates').fetchone()
        if candidate != (mint, creator, pool):
            raise RuntimeError('Fixture parser identity does not match the economic scenario')
        marks = [.001, .0007] if name == 'adverse_sl' else [.001, .0012]
        if name == 'partial_restart':
            marks.extend([.0012, .0012])
        cycle, observations, provider_calls = 0, [], []
        first_partial_quote = None
        fees = api['SolFeeBreakdown'](5000, 10000, (), provenance='synthetic')
        latencies = {}
        async def quote_provider(_session, requested_mint, **_kwargs):
            if requested_mint != mint:
                raise ValueError('Unknown synthetic mint')
            return api['MarketQuote'](20000.0, marks[cycle], pool,
                quote_source='synthetic_atomic_demo'), 0
        async def onchain_provider(*_args, **_kwargs):
            return None
        async def inventory_provider(_session, requested_mint, *, side, amount_atomic,
                                     inventory, decision_at_ms):
            nonlocal first_partial_quote
            if requested_mint != mint:
                raise ValueError('Unknown synthetic inventory mint')
            provider_calls.append({'side':side, 'engine_requested_atomic':str(amount_atomic),
                                   'inventory_version':inventory.get('version') if inventory else None})
            if side == 'buy':
                if int(amount_atomic) != 1_000_000_000:
                    raise RuntimeError('Active risk sizing did not allocate exactly 1 SOL')
                quantity, proceeds = int(amount_atomic), 25_000_000
            elif name == 'partial_restart':
                if cycle == 2:
                    return {'sell_observation':deepcopy(first_partial_quote),
                        'requested_quantity_atomic':'10000000', 'fees':fees, 'max_source_age_ms':5000}
                quantity = 10_000_000 if cycle == 1 else 15_000_000
                proceeds = 500_000_000 if cycle == 1 else 550_000_000
            else:
                quantity = int(amount_atomic)
                proceeds = {'full_tp':1_200_000_000, 'refused_liquidity':None,
                            'adverse_sl':700_000_000}[name]
            event = _quote_observation(api, side=side, mint=mint, pool=pool,
                amount=quantity, output=proceeds, requested=decision_at_ms,
                index=len(observations)+1, case=name)
            observations.append(event)
            clock.advance(20)  # Receipt and availability precede the engine's post-await decision.
            if side == 'buy':
                return {'buy_observation':event, 'basis':'expected_buy_output',
                        'token_decimals':6, 'fees':fees, 'max_source_age_ms':5000}
            if name == 'partial_restart' and cycle == 1:
                first_partial_quote = deepcopy(event)
            return {'sell_observation':event, 'requested_quantity_atomic':str(quantity),
                    'fees':fees, 'max_source_age_ms':5000}
        trace = []
        restart_verified = duplicate_ignored = None
        for cycle in range(len(marks)):
            messages, cooldown, _ = await engine.collect_once(
                con, None, cached, int(clock()), strategy_mode='shadow_final',
                initial_capital_sol=10.0, position_pct=10.0, entry_guard=None,
                quote_provider=quote_provider, onchain_quote_provider=onchain_provider,
                inventory_provider=inventory_provider, clock=clock, latency_samples_ms=latencies)
            if cooldown:
                raise RuntimeError('An offline fixture unexpectedly requested network cooldown')
            trace.append(_state(con, api, mint,
                ('entry' if cycle == 0 else 'duplicate_previous_exit' if name == 'partial_restart' and cycle == 2
                 else 'exit_'+str(cycle)), messages))
            if trace[-1]['inventory'] is None:
                raise RuntimeError('The active engine did not attach projected inventory to its entry')
            if name == 'partial_restart' and cycle == 1:
                before = trace[-1]
                con.close()
                con = sqlite3.connect(database, isolation_level=None)
                after = _state(con, api, mint, 'restart', [])
                restart_verified = (before['inventory'] == after['inventory']
                    and before['capital_sol'] == after['capital_sol']
                    and before['settled_legs'] == after['settled_legs'])
                if not restart_verified:
                    raise RuntimeError('Partial inventory or realized capital changed after SQLite restart')
                trace.append(after)
            elif name == 'partial_restart' and cycle == 2:
                after = trace[-1]
                duplicate_ignored = (before['inventory'] == after['inventory']
                    and before['capital_sol'] == after['capital_sol']
                    and before['settled_legs'] == after['settled_legs'])
                if not duplicate_ignored:
                    raise RuntimeError('Replaying a retained sell quote sold inventory or credited capital twice')
            clock.advance()
        final = trace[-1]
        inventory = final['inventory']
        pnl = int(inventory['realized_pnl_lamports'])
        expected_remaining = '25000000' if name == 'refused_liquidity' else '0'
        expected_status = 'open' if name == 'refused_liquidity' else 'closed'
        if (pnl != expected_pnl_lamports or inventory['remaining_atomic'] != expected_remaining
                or final['position_state'] != expected_status
                or not math.isclose(final['capital_sol'],10+expected_pnl_lamports/1e9,rel_tol=0,abs_tol=1e-12)):
            raise RuntimeError('Native inventory, fees and the single PAPER bankroll do not reconcile')
        legs = [dict(zip(('quantity_atomic','proceeds_lamports','extra_fee_lamports',
                         'allocated_basis_lamports','pnl_lamports'), row))
                for row in con.execute('SELECT quantity_atomic,proceeds_lamports,extra_fee_lamports,'
                                       'allocated_basis_lamports,pnl_lamports FROM paper_token_legs ORDER BY rowid')]
        if sum(int(leg['quantity_atomic']) for leg in legs)+int(expected_remaining) != 25_000_000:
            raise RuntimeError('Projected acquired/sold/remaining atomic quantities do not conserve')
        engine.paper_report(con, int(clock()), len(cached), output/'paper_report.json',
            strategy_mode='shadow_final', validation_status='synthetic_atomic_integration_only',
            data_kind='synthetic', latency_samples_ms=latencies)
        return {'case':name, 'data_kind':'synthetic', 'inventory_basis':'expected_buy_output',
            'acquisition_verified':False, 'execution_verified':False,
            'initial_capital_sol':10.0, 'final_capital_sol':final['capital_sol'],
            'simulated_realized_pnl_lamports':str(pnl), 'expected_pnl_lamports':str(expected_pnl_lamports),
            'entry_budget_lamports':'1000000000', 'entry_extra_fee_lamports':'5000',
            'exit_extra_fee_lamports_per_leg':'10000', 'acquired_atomic':'25000000',
            'remaining_atomic':inventory['remaining_atomic'], 'position_state':final['position_state'],
            'exit_reason':final['exit_reason'], 'ledger_reconciled':True,
            'quantity_conservation_verified':True, 'restart_verified':restart_verified,
            'duplicate_exit_ignored':duplicate_ignored, 'legs':legs, 'trace':trace,
            'provider_calls':provider_calls, 'quote_observations':observations,
            'database_file':name+'/paper.sqlite', 'report_file':name+'/paper_report.json'}
    finally:
        con.close()


async def run_economic_demo(output_dir):
    """Run four real collect_once/ledger scenarios in a NEW synthetic directory.

    Fee amounts are explicit synthetic assumptions. Native SOL quote amounts
    settle projected quantities; USD marks only trigger unchanged TP/SL rules.
    No scanner-supervision, bank-state, execution or market-return claim is made.
    """
    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise FileExistsError('The economic demo requires a new output directory')
    output.mkdir(parents=True, exist_ok=False)
    api = _load_api()
    cases = []
    for name, expected in (('full_tp',199_985_000), ('partial_restart',49_975_000),
                           ('refused_liquidity',0), ('adverse_sl',-300_015_000)):
        cases.append(await _run_case(api, output/name, name, expected))
    result = {'schema':'rugger-economic-inventory-demo-v1', 'data_kind':'synthetic',
        'paper_only':True, 'network_requests':0, 'real_orders_enabled':False,
        'acquisition_verified':False, 'execution_verified':False,
        'economic_profitability_verified':False, 'strategy_thresholds_modified':False,
        'scanner_scope':'explicit_offline_no_scanner_lane; no supervised scanner coverage claimed',
        'valuation_scope':'native_SOL_quote_scenarios; USD_marks_only_trigger_strategy',
        'fee_scope':'explicit_synthetic_extra_fees; route_fees_already_in_provider_amounts',
        'positions':len(cases), 'fully_settled_positions':sum(c['position_state']=='closed' for c in cases),
        'positions_with_remaining_inventory':sum(c['remaining_atomic']!='0' for c in cases),
        'market_cycles_qualified':0, 'cases':cases}
    (output/'demo_result.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return result
