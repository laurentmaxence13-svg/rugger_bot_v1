"""Offline adapter/validator: observer24h output -> pilot24h protocol, plus comparative ledger.

No network, no signing, no import of the observer (separate schema, read-only SQLite).
Unknown stays None; nothing is inferred, defaulted to 0 or forced to BUY.
"""
from datetime import datetime, timezone
import sqlite3

from bot.p3 import pilot24h as p

OBSERVER_EVENT_COLUMNS = ('signature', 'slot', 'event_index', 'pool', 'kind', 'program', 'recv_utc',
                          'chain_time', 'causality', 'decoded', 'slippage_bps', 'slippage_status',
                          'payload_json')
_KIND_EVENT = {'launchlab_trade_buy': ('buy', 'buy'), 'launchlab_trade_sell': ('sell', 'sell'),
               'launchlab_create': ('create', None), 'launchlab_migrate': ('migrate', None)}
# protocol fields the observer does not emit: they can never be filled from its output
OBSERVER_MISSING = ('mint', 'creator', 'creator_authenticated', 'sol_lamports', 'token_atomic',
                    'supply_atomic') + p.COST_FIELDS


def read_observer_events(db_path):
    """Read-only (SQLite uri mode=ro) dump of the observer events table."""
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute('SELECT * FROM events ORDER BY slot, signature, event_index')]
    finally:
        con.close()


def _utc(text):
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


def validate_observer_row(row):
    """Return the list of violations (empty = acceptable). Never repairs a row."""
    bad = []
    miss = [c for c in OBSERVER_EVENT_COLUMNS if c not in row]
    if miss:
        return ['missing_columns:' + ','.join(miss)]
    for c in ('slot', 'event_index', 'decoded'):
        if type(row[c]) is not int or row[c] < 0:
            bad.append(c + '_not_nonneg_int')
    if row['chain_time'] is not None and type(row['chain_time']) is not int:
        bad.append('chain_time_not_int')
    try:
        recv = _utc(row['recv_utc'])
        if type(row['chain_time']) is int and recv.timestamp() + 1 < row['chain_time']:
            bad.append('lookahead_recv_before_chain_time')  # received before it existed on chain
    except (TypeError, ValueError):
        bad.append('recv_utc_unparseable')
    if row['causality'] != 'ok':
        bad.append('causality_' + str(row['causality']))
    if row['slippage_status'] == 'unknown' and row['slippage_bps'] is not None:
        bad.append('slippage_known_value_with_unknown_status')
    if row['slippage_bps'] == 0 and row['slippage_status'] == 'unknown':
        bad.append('slippage_defaulted_to_zero')
    if row['kind'] not in _KIND_EVENT and not str(row['kind']).startswith('cpmm'):
        bad.append('unknown_kind')
    return bad


def adapt_observer_row(row):
    """Map one observer row to protocol vocabulary. Missing fields stay None, listed in `unmapped`."""
    ev, side = _KIND_EVENT.get(row['kind'], (None, None))
    venue = 'CPMM' if str(row['kind']).startswith('cpmm') else 'LAUNCHLAB'
    out = {f: None for f in p.OBSERVABLE_FIELDS}
    out.update(signature=row['signature'], slot=row['slot'], received_utc=row['recv_utc'],
               block_time_utc=(None if row['chain_time'] is None else
                               datetime.fromtimestamp(row['chain_time'], timezone.utc)
                               .strftime('%Y-%m-%dT%H:%M:%SZ')),
               venue=venue, event=ev, side=side, failed=False, pool=row['pool'])
    out['unmapped'] = list(OBSERVER_MISSING)
    return out


def qualification_report(rows):
    """What the observer output can and cannot support. Cycles are never reconstructed here."""
    viol = {}
    for r in rows:
        for v in validate_observer_row(r):
            viol[v] = viol.get(v, 0) + 1
    return {'rows': len(rows), 'violations': viol,
            'fields_never_provided': list(OBSERVER_MISSING),
            'qualified_cycles': 0, 'independent_creators': 0,
            'reason': 'observer rows carry no creator, mint, SOL leg or cost fields'}


def check_decisions_causal(decisions, observations):
    """Each decision names an observation key and the max slot of the data it used.
    Violation if it used data later than the observation it acts on, or is unknown."""
    slots = {(o['signature'], o['event'], o['mint']): o['slot'] for o in observations}
    bad = []
    for i, d in enumerate(decisions):
        k = tuple(d.get('obs', ()))
        if k not in slots:
            bad.append((i, 'unknown_observation'))
        elif type(d.get('data_max_slot')) is not int or d['data_max_slot'] > slots[k]:
            bad.append((i, 'lookahead_or_missing_data_max_slot'))
    return bad


def build_ledger(decisions, digest, cycles_by_engine, provenance):
    """Comparative ledger; refuses if decisions were not frozen before results (digest mismatch)."""
    if not p.verify_frozen(decisions, digest):
        raise p.ProtocolError('decisions do not match pre-registered digest')
    rows = []
    for engine, cycles in cycles_by_engine.items():
        for c in cycles:
            b, s = c.get('buy') or {}, c.get('sell') or {}
            known = bool(b) and bool(s) and all(x.get(f) is not None for x in (b, s) for f in p.COST_FIELDS)
            net = p.net_pnl_lamports(c) if known and None not in (b.get('sol_lamports'), s.get('sol_lamports')) else None
            rows.append({'engine': engine, 'creator': c.get('creator'), 'buy_slot': b.get('slot'),
                         'sell_slot': s.get('slot'), 'buy_signature': b.get('signature'),
                         'sell_signature': s.get('signature'), 'buy_utc': b.get('received_utc'),
                         'sell_utc': s.get('received_utc'), 'costs_all_known': known,
                         'net_lamports': net, 'provenance': provenance,
                         'qualified': c in p.qualified_cycles([c])})
    return {'decisions_digest': digest, 'rows': rows}


def recompute_ledger(ledger, cycles_by_engine):
    """Independent recalculation from the source legs; returns indexes of inconsistent rows."""
    flat = [(e, c) for e, cs in cycles_by_engine.items() for c in cs]
    bad = []
    if len(flat) != len(ledger['rows']):
        return ['row_count_mismatch']
    for i, ((e, c), r) in enumerate(zip(flat, ledger['rows'])):
        b, s = c.get('buy') or {}, c.get('sell') or {}
        legs = b and s and None not in (b.get('sol_lamports'), s.get('sol_lamports'))
        known = legs and all(x.get(f) is not None for x in (b, s) for f in p.COST_FIELDS)
        expect = p.net_pnl_lamports(c) if known else None
        if r['engine'] != e or r['net_lamports'] != expect:
            bad.append(i)
        if r['qualified'] and not r['sell_slot'] > r['buy_slot']:
            bad.append(i)
    return bad
