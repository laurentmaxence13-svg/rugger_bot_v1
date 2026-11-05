"""Offline pilot-24h protocol: observable schema, frozen decisions, verdict gate.

Pure functions; no network, no database, no signing. Nothing here executes or
simulates a fill: it only validates observed records, counts WAIT causes and
refuses to call profitability proven without enough qualified evidence.
"""
from collections import Counter
import hashlib
import json

PROTOCOL_VERSION = 'pilot24h-v1'
MIN_CREATORS = 50
MIN_CYCLES = 20
COST_FIELDS = ('network_fee_lamports', 'priority_fee_lamports', 'pool_fee_lamports',
               'protocol_fee_lamports', 'ata_rent_lamports', 'wsol_rent_lamports')
OBSERVABLE_FIELDS = (
    'signature', 'slot', 'block_time_utc', 'received_utc', 'venue',  # LAUNCHLAB|CPMM
    'event', 'mint', 'creator', 'creator_authenticated', 'supply_atomic',
    'creation_signature', 'migration_signature', 'side', 'sol_lamports',
    'token_atomic', 'failed') + COST_FIELDS
EVENTS = frozenset(('create', 'buy', 'sell', 'migrate', 'missed'))
VENUES = frozenset(('LAUNCHLAB', 'CPMM'))


class ProtocolError(ValueError):
    pass


def validate_observation(rec):
    """Return (record, unknown_costs). Unknown costs are flagged, never zeroed."""
    if not isinstance(rec, dict):
        raise ProtocolError('record must be an object')
    missing = [f for f in ('signature', 'slot', 'received_utc', 'venue', 'event', 'mint') if rec.get(f) in (None, '')]
    if missing:
        raise ProtocolError('missing: ' + ','.join(missing))
    if rec['venue'] not in VENUES or rec['event'] not in EVENTS:
        raise ProtocolError('unknown venue/event')
    for f in ('slot', 'sol_lamports', 'token_atomic') + COST_FIELDS:
        v = rec.get(f)
        if v is not None and (type(v) is not int or v < 0):
            raise ProtocolError(f + ' must be a nonnegative integer (never float)')
    if rec['event'] in ('buy', 'sell') and rec.get('side') != rec['event']:
        raise ProtocolError('side mismatch')
    unknown = [f for f in COST_FIELDS if rec.get(f) is None]
    return rec, unknown


def dedup(records):
    """Keep first record per (signature, event, mint); report duplicates."""
    seen, out, dup = set(), [], 0
    for r in records:
        k = (r['signature'], r['event'], r['mint'])
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        out.append(r)
    return out, dup


def freeze(decisions):
    """Hash decisions (list of dicts: observation key -> engine -> action) before results."""
    blob = json.dumps({'v': PROTOCOL_VERSION, 'decisions': decisions}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode()).hexdigest()


def verify_frozen(decisions, digest):
    return freeze(decisions) == digest


def wait_by_cause(decisions, engine='MASTER'):
    c = Counter()
    for d in decisions:
        if d.get('engine') == engine and d.get('action') == 'WAIT':
            c[d.get('cause') or 'cause_missing'] += 1
    return dict(c)


def qualified_cycles(cycles):
    """A cycle counts only if BUY+SELL executable, all costs known, creator authenticated."""
    ok = []
    for c in cycles:
        b, s = c.get('buy'), c.get('sell')
        if not b or not s or b.get('failed') or s.get('failed'):
            continue
        if not (c.get('creator_authenticated') and c.get('creator')):
            continue
        if any(x.get(f) is None for x in (b, s) for f in COST_FIELDS):
            continue
        if s['slot'] <= b['slot']:  # causal: exit strictly after entry
            continue
        ok.append(c)
    return ok


def net_pnl_lamports(cycle):
    b, s = cycle['buy'], cycle['sell']
    cost = sum(b[f] + s[f] for f in COST_FIELDS)
    return s['sol_lamports'] - b['sol_lamports'] - cost


def verdict(cycles_master, cycles_ref, provenance='live'):
    """Gate: INSUFFICIENT DATA unless real data meets creator/cycle minimums."""
    qm, qr = qualified_cycles(cycles_master), qualified_cycles(cycles_ref)
    creators = {c['creator'] for c in qm}
    out = {'qualified_cycles_master': len(qm), 'qualified_cycles_reference': len(qr),
           'independent_creators': len(creators)}
    if provenance != 'live':
        out['status'] = 'INSUFFICIENT DATA'
        out['reason'] = 'non-live provenance cannot demonstrate profitability'
    elif len(qm) < MIN_CYCLES or len(creators) < MIN_CREATORS:
        out['status'] = 'INSUFFICIENT DATA'
        out['reason'] = 'below %d cycles or %d creators' % (MIN_CYCLES, MIN_CREATORS)
    else:
        out['status'] = 'EVALUABLE'
        out['master_net_lamports'] = sum(map(net_pnl_lamports, qm))
        out['reference_net_lamports'] = sum(map(net_pnl_lamports, qr))
        out['note'] = 'point estimate only; no inference test applied'
    return out
