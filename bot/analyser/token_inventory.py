"""Projected atomic inventory attached to the existing PAPER positions.

Only strictly qualified quote scenarios produce simulated realization legs.
There is one bankroll, paper_portfolio. Nothing here acquires real tokens.
Call the writers under paper_trader._paper_close_transaction; initialize schema
only at startup, never inside an accounting transaction.
"""
from dataclasses import asdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math

from bot.p3.accounting import (SolFeeBreakdown, _fees, native_sol_inventory_totals,
                               InsufficientAccountingData)
from bot.p3.exit_qualification import inventory_from_buy, qualify_inventory_exit


def setup_inventory_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS paper_token_inventory (
      mint TEXT PRIMARY KEY, acquired_atomic TEXT NOT NULL, remaining_atomic TEXT NOT NULL,
      token_decimals INTEGER, entry_budget_lamports TEXT NOT NULL, entry_extra_lamports TEXT,
      cost_basis_total_lamports TEXT, cost_basis_remaining_lamports TEXT,
      entry_decision_ms INTEGER NOT NULL, entry_observation_json TEXT NOT NULL,
      entry_fee_provenance TEXT, source_provenance TEXT NOT NULL, inventory_basis TEXT NOT NULL,
      entry_available_cash_lamports TEXT NOT NULL, realized_pnl_lamports TEXT NOT NULL DEFAULT '0',
      version INTEGER NOT NULL DEFAULT 0, last_settlement_ms INTEGER);
    CREATE TABLE IF NOT EXISTS paper_token_legs (
      id TEXT PRIMARY KEY, mint TEXT NOT NULL, decision_ms INTEGER NOT NULL,
      quantity_atomic TEXT NOT NULL, proceeds_lamports TEXT NOT NULL,
      extra_fee_lamports TEXT NOT NULL, allocated_basis_lamports TEXT NOT NULL,
      pnl_lamports TEXT NOT NULL, observation_json TEXT NOT NULL, fee_provenance TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS paper_token_exit_attempts (
      id TEXT PRIMARY KEY, mint TEXT NOT NULL, decision_ms INTEGER NOT NULL,
      observation_json TEXT, qualification_json TEXT NOT NULL);
    ''')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _lamports(sol):
    if type(sol) not in (int, float) or not math.isfinite(sol) or sol < 0:
        raise ValueError('A finite nonnegative SOL amount is required')
    return int((Decimal(str(sol))*1_000_000_000).to_integral_value(rounding=ROUND_FLOOR))


def _fee_object(value):
    if isinstance(value, SolFeeBreakdown):
        return value
    if type(value) is dict:
        value = dict(value)
        if type(value.get('failed_attempt_lamports')) is list:
            value['failed_attempt_lamports'] = tuple(value['failed_attempt_lamports'])
        try:
            return SolFeeBreakdown(**value)
        except TypeError:
            pass
    raise InsufficientAccountingData('Explicit fee evidence required')


def _one(cursor, operation):
    if cursor.rowcount != 1:
        raise ValueError('Atomic inventory '+operation+' did not persist exactly once')
    return cursor


def _row(con, mint):
    cursor = con.execute('SELECT * FROM paper_token_inventory WHERE mint=?', (mint,))
    row = cursor.fetchone()
    return dict(zip((c[0] for c in cursor.description), row)) if row else None


def inventory_state(con, mint):
    """Read a version for a provider before awaiting, without creating a schema."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='paper_token_inventory'").fetchone():
        return None
    return _row(con, mint)


def prepare_entry(con, mint, context, entry_ms, position_sol, available_cash_sol):
    """Validate and freeze an inventory hypothesis before inserting its trade."""
    if type(context) is not dict or type(context.get('buy_observation')) is not dict:
        return {'accepted': False, 'reason': 'buy_inventory_evidence_missing'}
    try:
        inventory = inventory_from_buy(context['buy_observation'],
            basis=context.get('basis', 'expected_buy_output'),
            token_decimals=context.get('token_decimals'),
            entry_decision_at_ms=entry_ms, max_source_age_ms=context.get('max_source_age_ms', 5000))
        if not inventory['accepted']:
            return {'accepted': False, 'reason': ';'.join(inventory['reasons'])}
        budget, cash = _lamports(position_sol), _lamports(available_cash_sol)
        if inventory['mint'] != mint or int(inventory['budget_lamports']) != budget or budget <= 0:
            return {'accepted': False, 'reason': 'inventory_budget_or_mint_does_not_match_position'}
        entry_fee, fee_source = None, None
        try:
            fees = _fee_object(context.get('fees'))
            if (fees.quote_amounts_net_of_pool_fees is True and fees.extra_fees_exclude_pool_fees is True
                    and fees.provenance in ('observed', 'estimate', 'synthetic')
                    and type(fees.entry_extra_lamports) is int and fees.entry_extra_lamports >= 0):
                entry_fee, fee_source = fees.entry_extra_lamports, fees.provenance
        except InsufficientAccountingData:
            pass  # Quantity can be projected; missing cost remains unknown.
        basis = budget+entry_fee if entry_fee is not None else None
        if (basis if basis is not None else budget) > cash:
            return {'accepted': False, 'reason': 'inventory_entry_and_known_fees_exceed_cash'}
        return {'accepted': True, 'inventory': inventory, 'budget': budget, 'cash': cash,
                'entry_fee': entry_fee, 'fee_source': fee_source, 'cost_basis': basis,
                'entry_ms': entry_ms}
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        return {'accepted': False, 'reason': 'invalid_inventory_entry_'+type(error).__name__}


def persist_entry(con, mint, prepared):
    if not prepared.get('accepted'):
        raise ValueError('Cannot persist a refused atomic inventory')
    p, i = prepared, prepared['inventory']
    text = lambda value: str(value) if value is not None else None
    written = con.execute('''INSERT INTO paper_token_inventory
      (mint,acquired_atomic,remaining_atomic,token_decimals,entry_budget_lamports,
       entry_extra_lamports,cost_basis_total_lamports,cost_basis_remaining_lamports,
       entry_decision_ms,entry_observation_json,entry_fee_provenance,source_provenance,
       inventory_basis,entry_available_cash_lamports)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (mint,i['acquired_atomic'],i['acquired_atomic'],i['token_decimals'],str(p['budget']),
       text(p['entry_fee']),text(p['cost_basis']),text(p['cost_basis']),p['entry_ms'],
       _json(i['buy_observation']),p['fee_source'],i['provenance'],i['basis'],str(p['cash'])))
    _one(written, 'entry')
    # Align the legacy float display to the exact native budget, never vice versa.
    _one(con.execute('UPDATE paper_trades SET position_sol=? WHERE mint=?',
                     (p['budget']/1e9,mint)), 'entry link')


def settle_exit(con, mint, context, exit_ms, reason, price, peak):
    """Record a refusal or settle one exact partial/full quote scenario atomically."""
    row = _row(con, mint)
    if row is None:
        raise ValueError('Missing atomic inventory for settlement')
    context = context if type(context) is dict else {}
    sell = context.get('sell_observation')
    leg_id = _digest({'mint':mint, 'sell_observation':sell})
    if sell is not None and con.execute('SELECT 1 FROM paper_token_legs WHERE id=?', (leg_id,)).fetchone():
        return 'INVENTORY_DUPLICATE '+mint
    inv = dict(row, buy_observation=json.loads(row['entry_observation_json']),
               entry_decision_at_ms=row['entry_decision_ms'], basis=row['inventory_basis'])
    requested = context.get('requested_quantity_atomic', row['remaining_atomic'])
    try:
        verdict = qualify_inventory_exit(inv, sell, requested_quantity_atomic=requested,
            exit_decision_at_ms=exit_ms, max_source_age_ms=context.get('max_source_age_ms',5000))
    except (ValueError, TypeError, KeyError):
        verdict = {'accepted':False,'reasons':['invalid_exit_evidence']}
    if context.get('inventory_version') != row['version']:
        verdict = dict(verdict, accepted=False, reasons=['inventory_version_changed_or_unknown'])
    if row['last_settlement_ms'] is not None and exit_ms < row['last_settlement_ms']:
        verdict = dict(verdict, accepted=False, reasons=['exit_precedes_previous_settlement'])
    if row['last_settlement_ms'] is not None and verdict.get('accepted'):
        requested_at = sell.get('payload',{}).get('requested_at_ms')
        if type(requested_at) is not int or requested_at < row['last_settlement_ms']:
            verdict = dict(verdict,accepted=False,reasons=['sell_requested_before_remaining_inventory_known'])
    fee_object, extra = None, None
    if verdict.get('accepted'):
        try:
            fee_object = _fee_object(context.get('fees'))
            entry_extra, exit_extra, failed = _fees(fee_object)
            if row['entry_extra_lamports'] is None or entry_extra != int(row['entry_extra_lamports']):
                raise InsufficientAccountingData('Unknown or changed entry cost evidence')
            if row['source_provenance'] == 'synthetic' and fee_object.provenance != 'synthetic':
                raise InsufficientAccountingData('Synthetic fees must remain explicit')
            if row['source_provenance'] != 'synthetic' and fee_object.provenance == 'synthetic':
                raise InsufficientAccountingData('Market quotes cannot use invented synthetic fees')
            extra = exit_extra+sum(failed)
        except InsufficientAccountingData:
            verdict = dict(verdict,accepted=False,reasons=['additional_fees_unknown_or_inconsistent'])
    if verdict.get('accepted'):
        from bot.analyser.paper_trader import _paper_free_capital, _paper_realization_events
        capital, free = _paper_free_capital(con)
        prior_pnls = [event['pnl_sol'] for event in _paper_realization_events(con)]
        initial_capital = con.execute('SELECT initial_capital_sol FROM paper_portfolio WHERE id=1').fetchone()[0]
        if extra > _lamports(free):
            verdict = dict(verdict,accepted=False,reasons=['exit_fees_exceed_available_cash'])
    attempt_id = _digest({'leg':leg_id,'decision':exit_ms,'version':row['version'],
                          'verdict':verdict,'fees':asdict(fee_object) if fee_object else None})
    con.execute('INSERT OR IGNORE INTO paper_token_exit_attempts VALUES(?,?,?,?,?)',
                (attempt_id,mint,exit_ms,_json(sell) if sell is not None else None,_json(verdict)))
    if not verdict.get('accepted'):
        con.execute('UPDATE paper_trades SET peak_price=?,last_price=?,last_quote_time=? WHERE mint=?',
                    (peak,price,exit_ms//1000,mint))
        return 'INVENTORY_EXIT_UNQUALIFIED '+mint+' '+','.join(verdict.get('reasons',[]))
    acquired, remaining = int(row['acquired_atomic']), int(row['remaining_atomic'])
    q, proceeds = int(verdict['quantity_atomic']), int(verdict['proceeds_lamports'])
    total_basis, old_basis = int(row['cost_basis_total_lamports']), int(row['cost_basis_remaining_lamports'])
    cumulative_sold = acquired-remaining+q
    new_basis = total_basis-total_basis*cumulative_sold//acquired
    allocated = old_basis-new_basis
    pnl = proceeds-extra-allocated
    written = con.execute('INSERT INTO paper_token_legs VALUES(?,?,?,?,?,?,?,?,?,?)',
                (leg_id,mint,exit_ms,str(q),str(proceeds),str(extra),str(allocated),str(pnl),
                 _json(sell),fee_object.provenance))
    _one(written, 'leg')
    new_remaining, cumulative_pnl = remaining-q, int(row['realized_pnl_lamports'])+pnl
    changed = con.execute('''UPDATE paper_token_inventory SET remaining_atomic=?,
        cost_basis_remaining_lamports=?,realized_pnl_lamports=?,version=version+1,last_settlement_ms=?
        WHERE mint=? AND version=?''',
        (str(new_remaining),str(new_basis),str(cumulative_pnl),exit_ms,mint,row['version']))
    if changed.rowcount != 1:
        raise ValueError('Inventory changed during settlement')
    capital_after = initial_capital+math.fsum(prior_pnls+[pnl/1e9])
    _one(con.execute('UPDATE paper_portfolio SET realized_capital_sol=?,updated_at=? WHERE id=1',
                     (capital_after,exit_ms//1000)), 'portfolio')
    if new_remaining == 0:
        legs = con.execute('SELECT proceeds_lamports,extra_fee_lamports FROM paper_token_legs WHERE mint=?',(mint,)).fetchall()
        total_proceeds, extras = sum(int(x[0]) for x in legs),sum(int(x[1]) for x in legs)
        projection = native_sol_inventory_totals(
            entry_spent_lamports=int(row['entry_budget_lamports']), acquired_token_atomic=acquired,
            token_mint=mint, entry_extra_lamports=int(row['entry_extra_lamports']),
            legs=[{'quantity_atomic':int(qty),'proceeds_lamports':int(received),
                   'extra_fee_lamports':int(fee)} for qty,received,fee in con.execute(
                       'SELECT quantity_atomic,proceeds_lamports,extra_fee_lamports '
                       'FROM paper_token_legs WHERE mint=? ORDER BY decision_ms,id',(mint,))])
        if projection['net_pnl_lamports'] != cumulative_pnl:
            raise ValueError('Full native round-trip does not reconcile with partial legs')
        budget = int(row['entry_budget_lamports'])
        written = con.execute('''UPDATE paper_trades SET status='closed',exit_time=?,exit_price=?,
            exit_reason=?,pnl_sol=?,net_return=?,capital_after_sol=?,cost_bps=?,
            peak_price=?,last_price=?,last_quote_time=? WHERE mint=? AND status='open' ''',
            (exit_ms//1000,price,reason,cumulative_pnl/1e9,cumulative_pnl/budget,capital_after,
             (int(row['entry_extra_lamports'])+extras)*10000/budget,peak,price,exit_ms//1000,mint))
        _one(written, 'closure')
        return f'EXIT {mint} reason={reason} inventory=projected remaining=0 PnL={cumulative_pnl/1e9:+.9f} SOL'
    con.execute('UPDATE paper_trades SET peak_price=?,last_price=?,last_quote_time=? WHERE mint=?',
                (peak,price,exit_ms//1000,mint))
    return f'PARTIAL_EXIT {mint} sold={q} remaining={new_remaining} simulated_PnL={pnl/1e9:+.9f} SOL'
