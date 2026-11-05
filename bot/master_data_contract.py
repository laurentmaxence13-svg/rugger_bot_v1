"""RUGGER 03 offline data contract that would lift each MASTER WAIT cause (issue #177).

Pure validation of fixture-shaped dicts. No network, no collection, no strategy
or threshold change, no BUY forcing. It mirrors, but does not import or alter,
the frozen gates of ``bot.master_decision``. A passing contract proves only that
a record is *shaped* well enough to be considered; it never proves profitability.
"""
import math

SCHEMA = 'rugger03-master-data-contract-v1'
MIN_CYCLES, MIN_CREATOR_GROUPS = 50, 20  # copied from frozen policy; read-only mirror
PROVENANCE = ('observed', 'estimate', 'synthetic')

# field -> (WAIT cause lifted, source, validation rule)
MATRIX = (
    ('fees.entry_extra_lamports', 'additional_costs_unknown', 'BUY tx meta.fee + priority/tip', 'int>=0'),
    ('fees.exit_extra_lamports', 'additional_costs_unknown', 'SELL tx meta.fee + priority/tip (needs executed or simulated SELL)', 'int>=0'),
    ('fees.failed_attempt_lamports', 'additional_costs_unknown', 'chain_failed tx meta.fee attributed to owner wallet', 'list[int>=0]'),
    ('fees.quote_amounts_net_of_pool_fees', 'additional_costs_unknown', 'quote semantics from pool math', 'is True'),
    ('fees.extra_fees_exclude_pool_fees', 'additional_costs_unknown', 'fee decomposition', 'is True'),
    ('fees.provenance', 'additional_costs_unknown', 'collector tag', 'in observed|estimate|synthetic'),
    ('research_evidence.qualified_economic_cycles', 'qualified_past_edge_evidence_unavailable', 'complete BUY/SELL cycles', f'int>={MIN_CYCLES}'),
    ('research_evidence.independent_creator_groups', 'qualified_past_edge_evidence_unavailable', 'creator clustering', f'int>={MIN_CREATOR_GROUPS}'),
    ('research_evidence.training_end_ms<=available_at_ms<=decision_at_ms', 'qualified_past_edge_evidence_unavailable', 'report publication time', 'causal order'),
    ('research_evidence.policy_sha256/report_sha256', 'qualified_past_edge_evidence_unavailable', 'frozen policy + report digest', '64 lowercase hex'),
    ('bank_state.identity_qualified', 'source_identity_supply_creation_unqualified', 'creator identity check', 'is True'),
    ('bank_state.supply_verified', 'source_identity_supply_creation_unqualified', 'mint supply / authorities from chain', 'is True'),
    ('bank_state.creation_verified', 'source_identity_supply_creation_unqualified', 'creation tx matched to launch', 'is True'),
    ('event.source_time_ms<=received_at_ms<=available_at_ms', 'causal timestamps', 'source clock, receiver clock, availability', 'ints, ordered'),
    ('event.source_slot', 'causal timestamps', 'RPC slot', 'int>0'),
    ('trade.side/signature/mint/amounts/status', 'buys, sells, migrations', 'swap tx on LaunchLab/CPMM', 'side in BUY|SELL, status in ok|chain_failed'),
    ('migration.launchlab_pool -> cpmm_pool', 'buys, sells, migrations', 'migrate event', 'same mint, cpmm after launchlab'),
    ('coverage.venues', 'LaunchLab/CPMM coverage', 'per-venue event counts', 'both venues present'),
)


def _int(v):
    return v if type(v) is int and v >= 0 else None


def _hex64(v):
    return type(v) is str and len(v) == 64 and all(c in '0123456789abcdef' for c in v)


def validate_fees(fees):
    """Return list of defects (empty = contract met) for the cost block."""
    if type(fees) is not dict:
        return ['fees_missing']
    d = []
    for k in ('quote_amounts_net_of_pool_fees', 'extra_fees_exclude_pool_fees'):
        if fees.get(k) is not True:
            d.append(f'{k}_not_true')
    if fees.get('provenance') not in PROVENANCE:
        d.append('provenance_invalid')
    for k in ('entry_extra_lamports', 'exit_extra_lamports'):
        if _int(fees.get(k)) is None:
            d.append(f'{k}_invalid')
    f = fees.get('failed_attempt_lamports')
    if type(f) is not list or any(_int(n) is None for n in f):
        d.append('failed_attempt_lamports_invalid')
    return d


def validate_evidence(ev, decision_at_ms, policy_sha256):
    if type(ev) is not dict:
        return ['evidence_missing']
    d = []
    a, e = _int(ev.get('available_at_ms')), _int(ev.get('training_end_ms'))
    if a is None or e is None or not (e <= a <= decision_at_ms):
        d.append('timestamps_not_causal')
    if ev.get('policy_sha256') != policy_sha256:
        d.append('policy_hash_mismatch')
    if not (_int(ev.get('qualified_economic_cycles')) is not None and ev['qualified_economic_cycles'] >= MIN_CYCLES):
        d.append('cycles_below_minimum')
    if not (_int(ev.get('independent_creator_groups')) is not None and ev['independent_creator_groups'] >= MIN_CREATOR_GROUPS):
        d.append('creator_groups_below_minimum')
    r = ev.get('gross_proceeds_return_lower_bound')
    if type(r) not in (int, float) or not math.isfinite(r) or not 0 < r <= 10:
        d.append('return_bound_invalid')
    if not _hex64(ev.get('report_sha256')):
        d.append('report_sha256_invalid')
    return d


def validate_bank_state(bank):
    if type(bank) is not dict:
        return ['bank_state_missing']
    return [f'{k}_not_true' for k in ('identity_qualified', 'supply_verified', 'creation_verified') if bank.get(k) is not True]


def validate_event_time(ev, decision_at_ms):
    if type(ev) is not dict:
        return ['event_missing']
    s, r, a, slot = (_int(ev.get(k)) for k in ('source_time_ms', 'received_at_ms', 'available_at_ms', 'source_slot'))
    if None in (s, r, a, slot) or slot <= 0:
        return ['timestamp_or_slot_missing']
    return [] if s <= r <= a <= decision_at_ms else ['timestamps_not_causal']


def validate_trades(trades):
    """Trades: dicts with signature, mint, side, status, available_at_ms, fee_lamports, owner."""
    d, seen = [], set()
    for t in trades:
        sig = t.get('signature') if type(t) is dict else None
        if type(sig) is not str or not sig:
            d.append('signature_missing'); continue
        if sig in seen:
            d.append(f'duplicate_signature:{sig}')
        seen.add(sig)
        if t.get('side') not in ('BUY', 'SELL'):
            d.append(f'side_invalid:{sig}')
        if t.get('status') not in ('ok', 'chain_failed'):
            d.append(f'status_invalid:{sig}')
        if t.get('status') == 'chain_failed' and (_int(t.get('fee_lamports')) is None or not t.get('owner')):
            d.append(f'failed_tx_fee_or_owner_missing:{sig}')
        if not t.get('mint') or _int(t.get('available_at_ms')) is None:
            d.append(f'mint_or_time_missing:{sig}')
    return d


def validate_migration(m):
    if type(m) is not dict or not m.get('mint') or not m.get('launchlab_pool') or not m.get('cpmm_pool'):
        return ['migration_incomplete']
    a, b = _int(m.get('launchlab_available_at_ms')), _int(m.get('cpmm_available_at_ms'))
    if a is None or b is None or b < a:
        return ['migration_order_invalid']
    return []


def validate_coverage(venue_counts):
    d = [f'venue_absent:{v}' for v in ('launchlab', 'cpmm') if not (type(venue_counts) is dict and _int(venue_counts.get(v)))]
    return d


def lifts(frame, decision_at_ms, policy_sha256):
    """Which WAIT causes the contract would lift for a frame (empty defects)."""
    ctx = frame.get('inventory_context') or frame.get('buy_context')
    fees = ctx.get('fees') if type(ctx) is dict else None
    return dict(
        additional_costs_unknown=not validate_fees(fees),
        qualified_past_edge_evidence_unavailable=not validate_evidence(frame.get('research_evidence'), decision_at_ms, policy_sha256),
        source_identity_supply_creation_unqualified=not validate_bank_state(frame.get('bank_state')),
    )
