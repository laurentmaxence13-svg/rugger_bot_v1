"""Deterministic integration of the active PAPER pipeline, with no market access.

``await run_demo(new_directory)`` owns a new synthetic SQLite database. It feeds
fixture notifications through the real recovery/parser and backfill, uses the
real scanner entry guard, decision engine and PAPER ledger, then reopens the
ledger before following and closing its position. No inventory or fill on a
blockchain is claimed. The CLI installs its offline guard before importing us.
"""
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3


class _Clock:
    def __init__(self, value):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds=1):
        self.value += seconds


def _public_address(value):
    """Deterministic public fixture bytes; no wallet or signing key is made."""
    raw = bytes([value])*32
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number, text = int.from_bytes(raw, 'big'), ''
    while number:
        number, digit = divmod(number, 58)
        text = alphabet[digit]+text
    return text


def _load_pipeline():
    # Library callers get the same no-dotenv import boundary as the demo CLI.
    previous = os.environ.get('RUGGER_NO_DOTENV')
    os.environ['RUGGER_NO_DOTENV'] = '1'
    try:
        from bot.analyser import paper_engine as engine
        from bot.analyser.multi_creator_research_engine import ensure_schema
        from bot.analyser.behavior_pipeline import load_cached_transactions
        from bot.analyser.paper_trader import MarketQuote, setup, ensure_paper_portfolio
        from bot.database.db import Database
        from bot.scanner.tx_recovery import TransactionRecovery, recover_transactions
        from bot.scanner.backfill import ProgramBackfill
        from bot.scanner.supervision import ScannerHealth, _await_paper_cleanup, _raise_paper_failures
        from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID
        return locals()
    finally:
        if previous is None:
            os.environ.pop('RUGGER_NO_DOTENV', None)
        else:
            os.environ['RUGGER_NO_DOTENV'] = previous


async def run_demo(output_dir):
    """Return a verified synthetic cycle and write reports into a NEW directory.

    Monetary results are the legacy PAPER USD-mark model with constant SOL/USD,
    a 1 SOL position, and its existing 200 bps assumed round-trip cost. This is
    an integration proof, not executable market P&L or a profitability study.
    """
    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise FileExistsError('The demo requires a new output directory; existing work is preserved')
    output.mkdir(parents=True, exist_ok=False)
    api = _load_pipeline()
    pe, MarketQuote = api['engine'], api['MarketQuote']
    database = output/'paper.sqlite'
    epoch = 1_700_000_000
    clock = _Clock(epoch+1)
    mint, creator, pool = (_public_address(n) for n in (1, 2, 3))
    signature = '2'*88
    program = api['RAYDIUM_LAUNCHPAD_PROGRAM_ID']
    accounts = [_public_address(n) for n in (4, 2, 5, 6, 7, 3, 1)]
    transaction = {
        'slot':100, 'blockTime':epoch, 'meta':{'err':None},
        'transaction':{'signatures':[signature], 'message':{
            'accountKeys':[{'pubkey':key, 'signer':i in (0, 1), 'writable':True}
                           for i, key in enumerate(accounts)],
            'instructions':[{'programId':program, 'accounts':accounts,
                             'parsed':{'type':'initialize_v2'}}]}}}
    event = {'signature':signature, 'slot':100,
             'received_at':datetime.fromtimestamp(epoch+1, timezone.utc)}
    trace, fetches, failures = [], [], []
    con = scanner_task = None
    stop = asyncio.Event()
    notifications_delivered = asyncio.Event()
    result = None
    try:
        api['Database'](database)
        api['ensure_schema'](database)
        con = sqlite3.connect(database, isolation_level=None)
        api['setup'](con)
        pe.ensure_signal_status_schema(con)
        pe.ensure_audit_schema(con)
        api['ensure_paper_portfolio'](con, 10.0, int(clock()))
        recovery = api['TransactionRecovery'](database, retry_base=0)
        async def notifications():
            yield event
            yield event  # The scanner must durably deduplicate the notification.
            notifications_delivered.set()
            await stop.wait()
        async def fetch_transaction(value):
            if value != signature:
                raise ValueError('Fixture requested an unknown transaction')
            fetches.append(value)
            return transaction
        health = api['ScannerHealth']()
        scanner_task = health.start_task(api['recover_transactions'](
            notifications(), recovery, fetch_transaction, clock=clock,
            idle_seconds=.001, health=health), 'synthetic-scanner-recovery')
        async def fetch_page(_program, options):
            if _program != program or options != {'limit':100, 'commitment':'confirmed'}:
                raise ValueError('Unexpected fixture backfill request')
            return [{'signature':signature, 'slot':100, 'err':None}]
        backfill = api['ProgramBackfill'](recovery, program, fetch_page, clock=clock)
        guard = pe._ScannerEntryGuard(database, scanner_task, health=health, clock=clock)
        await notifications_delivered.wait()
        async def await_receipt():
            while con.execute('SELECT state FROM scanner_tx_recovery WHERE signature=?', (signature,)).fetchone() != ('done',):
                if scanner_task.done():
                    await scanner_task
                    raise RuntimeError('Scanner stopped before completing the fixture')
                await asyncio.sleep(0)
        await asyncio.wait_for(await_receipt(), timeout=2)
        candidate = con.execute('SELECT mint,deployer_candidate,pool_state,block_time,detection_latency_ms '
                                'FROM launch_candidates').fetchone()
        if candidate != (mint, creator, pool, epoch, 1000):
            raise RuntimeError('Recovery/parser fixture did not persist its exact launch identity')
        trace.append({'stage':'detection_and_parser', 'time':int(clock()), 'mint':mint,
                      'detection_latency_ms':candidate[4], 'recovery_fetches':len(fetches)})
        await backfill.on_state({'state':'subscribed'})
        clock.advance()
        await backfill.once()
        baseline_refused = not guard.allows(con)
        if not baseline_refused:
            raise RuntimeError('A recent baseline must not grant scanner entry permission')
        clock.advance()
        await backfill.once()
        caught_up_allowed = guard.allows(con)
        if not caught_up_allowed:
            raise RuntimeError('The fixture did not establish a fresh covered scanner prefix')
        trace.append({'stage':'scanner_gate', 'time':int(clock()),
                      'baseline_entry_refused':baseline_refused, 'caught_up_entry_allowed':caught_up_allowed})
        cached = api['load_cached_transactions'](database)
        prices = iter((.001, .00105, .0012))
        latencies = {}
        async def quote_provider(_session, requested_mint, **kwargs):
            if requested_mint != mint:
                raise ValueError('Fixture requested an unknown mint')
            return MarketQuote(20000.0, next(prices), pool, quote_source='synthetic_demo'), 0
        async def onchain_provider(*args, **kwargs):
            return None  # Explicit fixture boundary, never an RPC fallback.
        for cycle in range(3):
            messages, cooldown, _ = await pe.collect_once(
                con, None, cached, int(clock()), strategy_mode='shadow_final',
                initial_capital_sol=10.0, position_pct=10.0, entry_guard=guard,
                quote_provider=quote_provider, onchain_quote_provider=onchain_provider,
                clock=clock, latency_samples_ms=latencies)
            state = con.execute('SELECT status,last_price FROM paper_trades WHERE mint=?', (mint,)).fetchone()
            if state is None:
                raise RuntimeError('The real decision engine did not open the synthetic position')
            trace.append({'stage':('entry','follow','exit')[cycle], 'time':int(clock()),
                          'position_state':state[0], 'last_price_usd':state[1],
                          'cooldown_seconds':cooldown, 'messages':messages})
            if cycle == 0:
                if state[0] != 'open':
                    raise RuntimeError('The fixture must first open its position')
                owned, con = con, None
                owned.close()
                con = sqlite3.connect(database, isolation_level=None)
                reopened_recovery = api['TransactionRecovery'](database, retry_base=0)
                duplicate_was_ignored = not reopened_recovery.enqueue(event, clock())
                if not duplicate_was_ignored or reopened_recovery.claim_due(clock()) is not None:
                    raise RuntimeError('Recovery restart incorrectly repeated a completed transaction')
                trace.append({'stage':'restart', 'time':int(clock()), 'ledger_connection_reopened':True,
                              'completed_notification_ignored_after_restart':duplicate_was_ignored})
            elif cycle == 1 and state[0] != 'open':
                raise RuntimeError('The middle quote must follow rather than close the position')
            clock.advance()
        row = con.execute('SELECT status,exit_reason,position_sol,entry_price,exit_price,cost_bps,pnl_sol '
                          'FROM paper_trades WHERE mint=?', (mint,)).fetchone()
        initial, final = pe.paper_capital(con)
        if (row[:2] != ('closed','TP') or not math.isclose(row[2],1.0)
                or not math.isclose(row[6],.18,abs_tol=1e-12)
                or not math.isclose(initial,10.0) or not math.isclose(final,10.18,abs_tol=1e-12)
                or len(fetches) != 1):
            raise RuntimeError('The deterministic PAPER ledger does not reconcile')
        report = pe.paper_report(con, int(clock()), len(cached), output/'paper_report.json',
            strategy_mode='shadow_final', validation_status='synthetic_integration_only',
            data_kind='synthetic', latency_samples_ms=latencies)
        result = {'schema':'rugger-functional-demo-v1', 'data_kind':'synthetic',
            'paper_only':True, 'network_requests':0, 'real_orders_enabled':False,
            'private_keys_used':False, 'atomic_token_inventory_observed':False,
            'blockchain_execution_verified':False, 'economic_profitability_verified':False,
            'strategy_mode':'shadow_final', 'strategy_thresholds_modified':False,
            'trace':trace, 'recovery_fetch_count':len(fetches),
            'initial_capital_sol':initial, 'final_capital_sol':final,
            'position_sol':row[2], 'entry_price_usd':row[3], 'exit_price_usd':row[4],
            'gross_paper_pnl_sol':row[2]*(row[4]/row[3]-1),
            'assumed_round_trip_cost_bps':row[5], 'assumed_cost_sol':row[2]*row[5]/10000,
            'net_paper_pnl_sol':row[6], 'exit_reason':row[1],
            'valuation_scope':report['valuation_scope'],
            'restart_scope':'PAPER SQLite connection reopened; recovery receipt reloaded; no process-restart claim',
            'scanner_scope':'synthetic subscribed stream and two real backfill passes; coverage relative to fixture anchor',
            'latency_scope':'scanner delay is a fixed synthetic 1000ms sample; quote acquisition measures local fixture code only, never HTTP',
            'report_file':'paper_report.json', 'database_file':'paper.sqlite'}
    except BaseException as error:
        failures.append(('functional demo',error))
    finally:
        async def cleanup():
            nonlocal con
            stop.set()
            if scanner_task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(scanner_task), timeout=2)
                except asyncio.TimeoutError:
                    scanner_task.cancel()
                    await asyncio.gather(scanner_task, return_exceptions=True)
                except asyncio.CancelledError:
                    if not scanner_task.done():
                        scanner_task.cancel()
                    await asyncio.gather(scanner_task, return_exceptions=True)
                except Exception as error:
                    failures.append(('demo scanner cleanup',error))
            if con is not None:
                owned, con = con, None
                try:
                    owned.close()
                except BaseException as error:
                    failures.append(('demo SQLite close',error))
        await api['_await_paper_cleanup'](cleanup(),failures)
    api['_raise_paper_failures'](failures)
    (output/'demo_result.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return result
