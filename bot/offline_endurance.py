"""Bounded virtual-time endurance of the existing native PAPER ledger.

Synthetic quotes/fees exercise persistence and supervision, never market edge.
No sleeps, scanner, HTTP, wallet, or transaction construction are involved.
"""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sqlite3
import sys


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_offline_endurance(output, *, cycles=100):
    """Create one new synthetic book, restart its backups, and settle N legs.

    One projected lot is split into N exact portions. Every settled quote is
    replayed at a later decision time; committed-WAL backups become the next
    active local book. Admission failures do not suppress existing-position
    management. Monetary expectations are fixture assertions, not predictions.
    """
    output = Path(output)
    if type(cycles) is not int or not 2 <= cycles <= 1000:
        raise ValueError('Virtual endurance cycles must be an integer in 2..1000')
    if output.exists() or output.is_symlink() or output.name.startswith('.env'):
        raise ValueError('A new dedicated synthetic endurance directory is required')
    output.mkdir(parents=True)
    from bot.economic_demo import _load_api, _public_address, _quote_observation
    from bot.operations import OperationalEntryGuard, backup_paper_database
    from bot.scanner.supervision import ScannerHealth
    from types import SimpleNamespace
    api = _load_api()
    from bot.analyser.paper_trader import record_quote, _paper_free_capital
    from bot.analyser.token_inventory import inventory_state
    from bot.analyser.artifacts import atomic_write_json

    mint, creator, pool = (_public_address(n) for n in (51, 52, 53))
    model = dict(decision_approved=True, decision_score=75, tp_pct=10,
                 sl_pct=8, hold_seconds=3600, cost_bps=200)
    epoch_ms = 1_700_000_000_000
    clock = [epoch_ms]
    emergency = [False]
    virtual_step_ms=300000
    def new_health():
        value=ScannerHealth(require_observations=True,clock_ms=lambda:clock[0],
            monotonic_ms=lambda:clock[0]-epoch_ms)
        value.tasks.append(SimpleNamespace(done=lambda:False,cancelling=lambda:0,
            get_name=lambda:'synthetic_monitored_transport'))
        return value
    health=new_health()
    health.observe_rpc(True);health.observe_websocket('subscribed')
    rpc_receipts=websocket_callbacks=1
    restart_preflight_refusals=0

    database = output/'initial.sqlite'
    con = sqlite3.connect(database, isolation_level=None)
    fees = api['SolFeeBreakdown'](5000, 10000, (), provenance='synthetic')
    total_quantity, total_proceeds = cycles*1000, 1_050_000_000
    restarts = backups = duplicates = unhealthy = checks = 0
    reason_counts = {'healthy': 0, 'stale': 0, 'emergency': 0, 'disconnected': 0}
    snapshots = []
    try:
        api['setup'](con)
        api['ensure_paper_portfolio'](con, 10.0, epoch_ms//1000)
        con.execute('PRAGMA journal_mode=WAL')
        buy = _quote_observation(api, side='buy', mint=mint, pool=pool,
            amount=1_000_000_000, output=total_quantity,
            requested=epoch_ms-30, index=1, case='endurance')
        buy['id'] = 'synthetic-endurance-buy'
        context = dict(buy_observation=buy, token_decimals=6, fees=fees,
                       decision_at_ms=epoch_ms)
        message = record_quote(con,mint,creator,epoch_ms//1000,epoch_ms//1000,
            api['MarketQuote'](20000,1,pool),model,strategy_mode='shadow_final',
            inventory_context=context,require_inventory=True)
        _require(message.startswith('ENTRY '), 'Fixture entry did not attach native inventory')

        for index in range(1, cycles+1):
            clock[0] = epoch_ms+index*virtual_step_ms
            phase = ('healthy','stale','emergency','disconnected')[index % 4]
            if phase=='stale':
                health.observe_websocket('notification')
            else:
                health.observe_rpc(True);rpc_receipts+=1
                health.observe_websocket('disconnected' if phase=='disconnected' else 'subscribed')
            websocket_callbacks+=1
            emergency[0] = phase == 'emergency'
            guard = OperationalEntryGuard(con,health.operational_observations,
                emergency_stop_provider=lambda: emergency[0],clock_ms=lambda:clock[0],
                max_age_ms=120000,scanner_guard=health.permits_entries)
            allowed = guard()
            _require(allowed is (phase == 'healthy'), 'Health/emergency permission mismatch')
            reason_counts[phase] += 1
            unhealthy += int(not allowed)
            state = inventory_state(con,mint)
            _require(int(state['remaining_atomic']) == (cycles-index+1)*1000,
                     'Inventory drift before settlement')
            # Cumulative allocation preserves the exact total even if N does
            # not divide the fixture's total proceeds.
            received = total_proceeds*index//cycles-total_proceeds*(index-1)//cycles
            sell = _quote_observation(api,side='sell',mint=mint,pool=pool,
                amount=1000,output=received,requested=clock[0]-30,
                index=index+1,case='endurance')
            sell['id'] = 'synthetic-endurance-sell-'+str(index)
            context = dict(sell_observation=sell,requested_quantity_atomic='1000',
                inventory_version=state['version'],fees=fees,decision_at_ms=clock[0])
            message = record_quote(con,mint,creator,epoch_ms//1000,clock[0]//1000,
                api['MarketQuote'](20000,1.2,pool),model,allow_entry=allowed,
                strategy_mode='shadow_final',force_exit_reason='ENDURANCE_FIXTURE',
                inventory_context=context,require_inventory=True)
            _require(message.startswith('PARTIAL_EXIT ' if index<cycles else 'EXIT '),
                     'Admission refusal prevented existing-position management')
            after = inventory_state(con,mint)
            _require(int(after['remaining_atomic']) == (cycles-index)*1000,
                     'Exact quantity conservation failed')
            capital, free = _paper_free_capital(con)
            basis_allocated = 1_000_005_000*index//cycles
            pnl = total_proceeds*index//cycles-index*10000-basis_allocated
            _require(int(after['realized_pnl_lamports']) == pnl
                     and math.isclose(capital,10+pnl/1e9,rel_tol=0,abs_tol=1e-12),
                     'Native PnL and shared bankroll disagree')
            _require(con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()[0] == index,
                     'Settlement leg count drifted')
            checks += 3

            # The final closed trade also must not re-open or credit again.
            retained = deepcopy(after)
            old_capital = capital
            duplicate = deepcopy(context);duplicate['decision_at_ms'] = clock[0]+1000
            record_quote(con,mint,creator,epoch_ms//1000,(clock[0]+1000)//1000,
                api['MarketQuote'](20000,1.2,pool),model,allow_entry=False,
                strategy_mode='shadow_final',force_exit_reason='ENDURANCE_DUPLICATE',
                inventory_context=duplicate,require_inventory=True)
            _require(inventory_state(con,mint) == retained
                     and _paper_free_capital(con)[0] == old_capital
                     and con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()[0] == index,
                     'Replayed quote changed inventory or credited capital twice')
            duplicates += 1;checks += 1

            if index % max(1,cycles//10) == 0 or index == cycles:
                target=output/('backup-'+str(index)+'.sqlite')
                receipt=backup_paper_database(database,target)
                backups += 1
                con.close()
                database=target
                con=sqlite3.connect(database,isolation_level=None)
                con.execute('PRAGMA journal_mode=WAL')
                _require(inventory_state(con,mint) == retained
                         and _paper_free_capital(con)[0] == old_capital,
                         'Restored committed backup changed the book')
                restarts += 1;checks += 1
                health=new_health()
                restart_guard=OperationalEntryGuard(con,health.operational_observations,
                    clock_ms=lambda:clock[0],max_age_ms=120000,scanner_guard=health.permits_entries)
                _require(not restart_guard(),'Restart manufactured fresh source observations')
                restart_preflight_refusals+=1;checks+=1
                snapshots.append(dict(after_cycle=index,remaining_atomic=after['remaining_atomic'],
                    native_version=after['version'],legs=index,backup_quick_check=receipt['quick_check']))

        final = inventory_state(con,mint)
        capital,free = _paper_free_capital(con)
        net = total_proceeds-1_000_000_000-5000-cycles*10000
        _require(final['remaining_atomic']=='0'
                 and con.execute('SELECT status FROM paper_trades').fetchone()==('closed',)
                 and int(final['realized_pnl_lamports'])==net
                 and capital==free,'Final position did not reconcile after restart')
        report = dict(schema='rugger-offline-endurance-v2',data_kind='synthetic',
            virtual_cycles=cycles,virtual_step_ms=virtual_step_ms,
            virtual_elapsed_ms=cycles*virtual_step_ms+1000,
            internal_scanner_health_exercised=True,source_max_age_ms=120000,
            simulated_rpc_receipts=rpc_receipts,simulated_websocket_callbacks=websocket_callbacks,
            restart_preflight_refusals=restart_preflight_refusals,
            settled_legs=cycles,replayed_quotes_ignored=duplicates,
            health_phase_counts=reason_counts,admission_refusals=unhealthy,
            backups_verified=backups,restarts_verified=restarts,
            invariant_checks=checks+1,inventory_acquired_atomic=str(total_quantity),
            inventory_remaining_atomic=final['remaining_atomic'],
            fixture_entry_lamports='1000000000',fixture_total_proceeds_lamports=str(total_proceeds),
            fixture_total_extra_fees_lamports=str(5000+cycles*10000),
            fixture_net_pnl_lamports=str(net),final_capital_sol=capital,
            final_available_cash_sol=free,restart_snapshots=snapshots,
            final_database=database.name,network_requests=0,real_orders_enabled=False,
            economic_profitability_verified=False,execution_verified=False,
            scope='virtual-time software endurance; not wall-clock or production availability validation')
        atomic_write_json(output/'report.json',report,indent=2,sort_keys=True,allow_nan=False)
        return report
    finally:
        con.close()


def main(argv=None):
    os.environ['RUGGER_NO_DOTENV']='1'
    from bot.__main__ import _offline_policy
    sys.addaudithook(_offline_policy)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=100)
    args=parser.parse_args(argv)
    print(json.dumps(run_offline_endurance(args.output,cycles=args.cycles),sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
