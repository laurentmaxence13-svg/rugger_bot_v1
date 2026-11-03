"""Offline, deterministic analysis of an archived LaunchLab census.

Reads only run.json, anchors/ and bundles/ (never SQLite, never the network),
verifies every segment against its separate anchor and the segment links, and
computes the outputs frozen in the protocol. Every enrolled creation stays in
the denominator: missing, refused and interrupted observations are counted as
categories, never imputed. Returns are gross quote/curve ratios, not P&L, not
fills, and not an economic verdict.
"""
import argparse
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct

from bot.analyser.artifacts import atomic_write_json
from bot.p3 import launchlab as ll
from bot.p3.census import (PROTOCOL_V1, CensusPolicyError, load_segments, preregistration_sha256,
                           read_run, replay, sha256_of, validate_authorization, validate_protocol)

REPORT_SCHEMA = 'p3-launchlab-census-report-v1'
# Flags raised by analyze_snapshot's structural/permission block. Projection
# arithmetic refusals are NOT structural and must not disqualify a later state.
STRUCTURAL_FLAGS = frozenset((
    'pool_not_in_active_launch_curve', 'unsupported_curve_type', 'unsupported_mint_program_flag',
    'base_mint_authority_present', 'freeze_authority_present', 'vault_uninitialized_or_frozen',
    'vault_delegate_or_close_authority_present', 'vault_native_currency_state_mismatch',
    'observed_reserves_or_vault_inventory_inconsistent', 'share_fee_exceeds_configured_maximum'))
_PROFILE = PROTOCOL_V1['analysis']['secondary_evidence_profile']


def dec(value):
    if value is None:
        return None
    places = PROTOCOL_V1['analysis']['decimal_places']
    with localcontext() as context:
        context.prec = 120
        number = Decimal(value.numerator) / Decimal(value.denominator)
        return str(number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN))


def quantiles(values):
    ordered = sorted(values)
    result = {}
    for text in PROTOCOL_V1['analysis']['quantiles']:
        q = Fraction(text)
        if not ordered:
            result[text] = None
            continue
        rank = max(1, math.ceil(q * len(ordered)))
        item = ordered[rank - 1]
        result[text] = dec(item) if isinstance(item, Fraction) else item
    return result


def histogram(values):
    edges = [Fraction(edge) for edge in PROTOCOL_V1['analysis']['histogram_edges']]
    labels = ['[%s,%s)' % (a, b) for a, b in zip(PROTOCOL_V1['analysis']['histogram_edges'],
                                                 PROTOCOL_V1['analysis']['histogram_edges'][1:])]
    labels.append('[%s,inf)' % PROTOCOL_V1['analysis']['histogram_edges'][-1])
    counts = {label: 0 for label in labels}
    counts['below_-1'] = 0
    for value in values:
        if value < edges[0]:
            counts['below_-1'] += 1
            continue
        for index, edge in enumerate(edges[1:]):
            if value < edge:
                counts[labels[index]] += 1
                break
        else:
            counts[labels[-1]] += 1
    return counts


def _distribution(categories, values):
    counts = {}
    for category in categories:
        counts[category] = counts.get(category, 0) + 1
    return {'population': len(categories), 'category_counts': dict(sorted(counts.items())),
            'observed_count': len(values),
            'observed_conditional_quantiles': quantiles(values),
            'observed_conditional_histogram': histogram(values),
            'note': 'quantiles/histogram are conditional on category observed; '
                    'other categories are counted, never imputed'}


def _task_category(terminal):
    if terminal is None:
        return 'not_terminal'
    if terminal['status'] != 'completed':
        return '%s:%s' % (terminal['status'], terminal['reason'])
    return None


def _quote_category(terminal):
    category = _task_category(terminal)
    if category is not None:
        return category
    result = terminal['result']
    if not result['recorded']:
        return 'evidence_refused:unsafe_or_invalid_quote_payload'
    if result['outcome'] == 'quoted':
        return 'quoted'
    return 'provider_%s:%s' % (result['outcome'], result['reason'])


def _accounts(event):
    payload = event['payload']
    result = payload['raw_rpc_result']
    return dict(zip(payload['requested_addresses'], result['value'])), result['context']['slot']


def _pool_facts(accounts, creation):
    account = accounts.get(creation['pool'])
    if account is None:
        return {'state_category': 'pool_account_absent'}
    try:
        pool, _ = ll._pool(account)
    except (ValueError, TypeError, KeyError, struct.error):
        return {'state_category': 'pool_layout_unsupported'}
    x, y = pool['virtual_a'] - pool['real_a'], pool['virtual_b'] + pool['real_b']
    spot = None
    if x > 0 and y > 0 and pool['decimals_a'] <= 18 and pool['decimals_b'] <= 18:
        spot = Fraction(y * 10**pool['decimals_a'], x * 10**pool['decimals_b'])
    progress = (Fraction(pool['real_b'], pool['total_fundraising_b'])
                if pool['total_fundraising_b'] > 0 else None)
    return {'state_category': 'observed', 'pool_status_code': pool['status'],
            'migrate_type': pool['migrate_type'], 'decimals_a': pool['decimals_a'],
            'quote_mint': pool['mint_b'],
            **{key: str(pool[key]) for key in ('real_a', 'real_b', 'virtual_a', 'virtual_b',
                                               'total_sell_a', 'total_fundraising_b')},
            'spot_quote_per_whole_base_token': spot, 'fundraising_progress': progress}


def _local_entry(accounts, slot, creation, size):
    report = ll.analyze_snapshot(accounts, context_slot=slot, expected_mint=creation['mint'],
                                 pool_address=creation['pool'], input_lamports=size,
                                 evidence_profile=_PROFILE)
    projection = report['conditional_projection']
    if projection is None:
        reason = report['risk_flags'][0] if report['risk_flags'] else 'projection_unavailable'
        return None, 'local_entry_unavailable:' + reason
    return int(projection['buy_output_atomic']), None


def _local_exit(accounts, slot, creation, quantity, size):
    report = ll.analyze_snapshot(accounts, context_slot=slot, expected_mint=creation['mint'],
                                 pool_address=creation['pool'], input_lamports=size,
                                 evidence_profile=_PROFILE)
    structural = [flag for flag in report['risk_flags'] if flag in STRUCTURAL_FLAGS]
    if 'quote_vault' not in report['facts'] or structural:
        flags = structural or report['risk_flags'] or ['unqualified']
        return None, 'local_exit_state_unqualified:' + flags[0]
    try:
        addresses = ll.addresses_from_pool(accounts[creation['pool']], creation['mint'],
                                           creation['pool'])
        pool, _ = ll._pool(accounts[creation['pool']])
        config, _ = ll._config(accounts[addresses['config']])
        platform, _ = ll._platform(accounts[addresses['platform']])
        vault, _ = ll._vault(accounts[addresses['vault_b']], 'quote_vault', metadata_only=True)
        estimate = ll.observed_sell_projection(
            pool, input_token_atomic=quantity,
            fee_rates_ppm=(config['trade_fee_rate_ppm'], platform['platform_fee_rate_ppm'],
                           platform['creator_fee_rate_ppm']),
            quote_vault_lamports=vault['amount_atomic'], curve_type=config['curve_type'])
    except ll.SnapshotEvidenceError as error:
        return None, 'local_exit_refused:' + str(error)
    except (ValueError, TypeError, KeyError, struct.error):
        return None, 'local_exit_refused:malformed_state'
    return int(estimate['output_lamports']), None


def _task_events(terminal, by_id, kind):
    if terminal is None:
        return []
    return [by_id[(terminal['segment'], identity)] for identity in terminal['evidence_ids']
            if (terminal['segment'], identity) in by_id
            and by_id[(terminal['segment'], identity)]['kind'] == kind]


def _quote_times(terminal, by_id):
    """Provider quote clocks as journaled; Raydium supplies no source time/slot."""
    provider = [event for event in _task_events(terminal, by_id, 'quote_attempt')
                if event['payload'].get('provider') == 'raydium_trade_api'
                or event['payload'].get('quote_side') in ('buy', 'sell')]
    if not provider:
        return {}
    event = provider[-1]
    return {'source_time_ms': event['source_time_ms'], 'source_slot': event['source_slot'],
            'received_at_ms': event['received_at_ms'], 'available_at_ms': event['available_at_ms'],
            'analysis_at_ms': event['available_at_ms'],
            'requested_at_ms': event['payload'].get('requested_at_ms'),
            'latency_ms': event['payload'].get('latency_ms')}


def _verified_time(run_events, run, protocol, authorization):
    created = run['created_at_ms']
    protocol_hash = validate_protocol(protocol, now_ms=created)
    authorization_hash = validate_authorization(authorization, protocol, now_ms=created)
    if (protocol_hash != run['protocol_sha256'] or authorization_hash != run['authorization_sha256']
            or preregistration_sha256(protocol_hash, authorization_hash) != run['preregistration_sha256']):
        raise CensusPolicyError('Journaled pre-registration does not match the run identity')
    return protocol_hash, authorization_hash


def analyze(directory):
    root = Path(directory)
    run = read_run(root)
    events, tail, segments = load_segments(root, run)
    state = replay(events)
    started = state['started']
    if started is None or started['run'] != run:
        raise CensusPolicyError('Census start record is missing or belongs to another run')
    protocol, authorization = started['protocol'], started['owner_quota_approval']
    _verified_time(events, run, protocol, authorization)
    by_id = {(event['segment'], event['id']): event for event in events}
    schedule = PROTOCOL_V1['schedule']
    offsets, sizes = schedule['state_offsets_ms'], schedule['buy_sizes_lamports']
    tolerance = dict(zip(offsets, schedule['tolerance_ms']))
    primary_offset = 900000

    creations = []
    for enrolled in state['creations']:
        terminal = {task['task_id']: state['terminal'].get(task['task_id']) for task in enrolled['tasks']}
        def find(kind, offset=None, size=None):
            for task in enrolled['tasks']:
                if task['kind'] == kind and task['offset_ms'] == offset and task['size_lamports'] == size:
                    return terminal[task['task_id']]
            return None
        verify = find('verify')
        verified = (verify is not None and verify['status'] == 'completed'
                    and verify['result'].get('creation_verified') is True)
        block_time = verify['result'].get('creation_block_time_ms') if verified else None
        creation_slot = verify['result'].get('creation_slot') if verified else None
        observed_tx = [event for event in _task_events(verify, by_id, 'transaction')
                       if verified and event['signature'] == verify['result'].get('signature')]
        row = state['universe'].get(enrolled['mint'], {})
        record = {'seq': enrolled['seq'], 'mint': enrolled['mint'], 'pool': enrolled['pool'],
                  'quote_mint_claim': row.get('quote_mint_claim'),
                  'anchor_ms': enrolled['anchor_ms'], 'anchor_basis': enrolled['anchor_basis'],
                  'enrolled_at_ms': enrolled['enrolled_at_ms'],
                  'verification': _task_category(verify) or ('creation_verified' if verified
                                                            else 'creation_not_verified'),
                  'creation_block_time_ms': block_time, 'creation_slot': creation_slot,
                  'creation_signature': verify['result'].get('signature') if verified else None,
                  'creation_received_at_ms': observed_tx[-1]['received_at_ms'] if observed_tx else None,
                  'creation_available_at_ms': observed_tx[-1]['available_at_ms'] if observed_tx else None,
                  'index_detection_latency_ms': (enrolled['enrolled_at_ms'] - block_time
                                                 if type(block_time) is int else None),
                  'states': {}, 'buys': {}, 'sells': {}, 'primary': {}, 'secondary': {}}
        states, accounts_by_offset, decimals, price_times = {}, {}, None, []
        raw_curve = {}
        for offset in offsets:
            task = find('state', offset)
            category = _task_category(task)
            entry = {'category': category}
            if category is None:
                result = task['result']
                entry.update({key: result.get(key) for key in (
                    'context_slot', 'received_at_ms', 'available_at_ms', 'analysis_at_ms',
                    'source_time_ms')})
                if result['state_status'] != 'observed':
                    entry['category'] = 'state_' + result['state_status']
                else:
                    event = by_id[(task['segment'], result['snapshot_observation_id'])]
                    accounts, slot = _accounts(event)
                    facts = _pool_facts(accounts, enrolled)
                    entry['category'] = facts.pop('state_category')
                    entry.update(facts)
                    if entry['category'] == 'observed':
                        accounts_by_offset[offset] = (accounts, slot)
                        raw_curve[offset] = (int(facts['real_b']), facts['spot_quote_per_whole_base_token'])
                        decimals = facts['decimals_a'] if decimals is None else decimals
                        if facts['spot_quote_per_whole_base_token'] is not None:
                            price_times.append((result['available_at_ms'], result['context_slot']))
                    if type(block_time) is int:
                        actual = result['received_at_ms'] - block_time
                        entry['actual_offset_ms_vs_verified_creation'] = actual
                        entry['within_tolerance_vs_verified_creation'] = (
                            offset <= actual <= offset + tolerance[offset])
                        if type(result.get('source_time_ms')) is int:
                            entry['source_offset_ms_vs_verified_creation'] = result['source_time_ms'] - block_time
            for key in ('spot_quote_per_whole_base_token', 'fundraising_progress'):
                if key in entry:
                    entry[key] = dec(entry[key])
            states[str(offset)] = entry
        record['states'] = states
        record['_raw_curve'] = raw_curve
        entries = {}
        for size in sizes:
            buy = find('buy', schedule['buy_offset_ms'], size)
            category = _quote_category(buy)
            entry = {'category': category}
            if buy is not None and buy['status'] == 'completed':
                entry['http_status'] = buy['result']['http_status']
                entry.update(_quote_times(buy, by_id))
            if category == 'quoted':
                result = buy['result']
                spent = int(result['actual_input_amount_atomic'] or result['input_amount_atomic'])
                received = int(result['output_amount_atomic'])
                entry.update(input_lamports=str(spent), output_atomic=str(received),
                             implied_lamports_per_atomic=dec(Fraction(spent, received)),
                             implied_sol_per_whole_token=(dec(Fraction(spent * 10**decimals, received * 10**9))
                                                          if decimals is not None else None))
                entries[size] = spent
                quoted = [by_id[(buy['segment'], identity)] for identity in buy['evidence_ids']
                          if (buy['segment'], identity) in by_id]
                quoted = [e for e in quoted if e['kind'] == 'quote_attempt' and e['outcome'] == 'quoted']
                if quoted:
                    price_times.append((quoted[0]['available_at_ms'], None))
            record['buys'][str(size)] = entry
        for offset in schedule['sell_offsets_ms']:
            for size in sizes:
                sell = find('sell', offset, size)
                category = _quote_category(sell)
                entry = {'category': category}
                if sell is not None and sell['status'] == 'completed':
                    entry['http_status'] = sell['result']['http_status']
                    entry.update(_quote_times(sell, by_id))
                    if category == 'quoted':
                        entry['output_lamports'] = sell['result']['output_amount_atomic']
                record['sells']['%d:%d' % (offset, size)] = entry
        for size in sizes:
            buy_category = record['buys'][str(size)]['category']
            sell_entry = record['sells']['%d:%d' % (primary_offset, size)]
            if buy_category != 'quoted':
                record['primary'][str(size)] = {'category': 'buy:' + buy_category}
            elif sell_entry['category'] != 'quoted':
                record['primary'][str(size)] = {'category': 'sell:' + sell_entry['category']}
            else:
                ratio = Fraction(int(sell_entry['output_lamports']), entries[size]) - 1
                record['primary'][str(size)] = {'category': 'observed', 'gross_return': ratio}
            # Secondary: local curve arithmetic only, explicitly conditional.
            if schedule['buy_offset_ms'] not in accounts_by_offset:
                secondary = {'category': 'local_entry_unavailable:no_observed_plus60_state'}
            else:
                accounts, slot = accounts_by_offset[schedule['buy_offset_ms']]
                quantity, reason = _local_entry(accounts, slot, enrolled, size)
                if quantity is None:
                    secondary = {'category': reason}
                elif primary_offset not in accounts_by_offset:
                    secondary = {'category': 'local_exit_unavailable:no_observed_plus900_state'}
                else:
                    later, later_slot = accounts_by_offset[primary_offset]
                    output, reason = _local_exit(later, later_slot, enrolled, quantity, size)
                    secondary = ({'category': reason} if output is None else
                                 {'category': 'observed', 'gross_return': Fraction(output, size) - 1,
                                  'entry_quantity_atomic': str(quantity), 'exit_lamports': str(output)})
            record['secondary'][str(size)] = secondary
        codes = [(int(o), s['pool_status_code']) for o, s in states.items() if s['category'] == 'observed']
        left = [o for o, code in codes if code != 0]
        record['migration'] = {
            'observed_state_count': len(codes),
            'status_codes_by_offset': {str(o): code for o, code in codes},
            'left_active_curve_within_window': bool(left) if codes else None,
            'first_offset_not_active_ms': min(left) if left else None,
            'pool_account_absent_observed': any(s['category'] == 'pool_account_absent'
                                                for s in states.values())}
        if type(block_time) is int and price_times:
            first, first_slot = min(price_times, key=lambda item: item[0])
            record['detection'] = {'category': 'observed',
                                   'latency_ms': first - block_time,
                                   'first_price_available_at_ms': first,
                                   'slot_lag': (first_slot - creation_slot
                                                if type(first_slot) is int and type(creation_slot) is int
                                                else None)}
        else:
            record['detection'] = {'category': 'creation_not_verified' if type(block_time) is not int
                                   else 'no_local_price_observed'}
        creations.append(record)

    population = len(creations)
    outputs = {'primary_buy60_sell900': {}, 'secondary_local_curve_buy60_sell900': {},
               'sellable_exit': {}, 'buy_quote_plus60': {}, 'state_availability': {}}
    for size in sizes:
        for label, key in (('primary_buy60_sell900', 'primary'),
                           ('secondary_local_curve_buy60_sell900', 'secondary')):
            items = [c[key][str(size)] for c in creations]
            outputs[label][str(size)] = _distribution(
                [item['category'] for item in items],
                [item['gross_return'] for item in items if item['category'] == 'observed'])
        buys = [c['buys'][str(size)]['category'] for c in creations]
        counts = {}
        for category in buys:
            counts[category] = counts.get(category, 0) + 1
        outputs['buy_quote_plus60'][str(size)] = {
            'population': population, 'quoted': buys.count('quoted'),
            'category_counts': dict(sorted(counts.items()))}
        for offset in schedule['sell_offsets_ms']:
            sells = [c['sells']['%d:%d' % (offset, size)] for c in creations]
            categories = {}
            for item in sells:
                categories[item['category']] = categories.get(item['category'], 0) + 1
            outputs['sellable_exit']['%d:%d' % (offset, size)] = {
                'sellable_quoted': sum(item['category'] == 'quoted' for item in sells),
                'denominator_all_enrolled': population,
                'denominator_plus60_buy_quoted': buys.count('quoted'),
                'denominator_sell_dispatched': sum('http_status' in item for item in sells),
                'category_counts': dict(sorted(categories.items()))}
    for offset in offsets:
        counts = {}
        for c in creations:
            category = c['states'][str(offset)]['category']
            counts[category] = counts.get(category, 0) + 1
        observed = [c['states'][str(offset)] for c in creations
                    if c['states'][str(offset)]['category'] == 'observed']
        outputs['state_availability'][str(offset)] = {
            'population': population, 'category_counts': dict(sorted(counts.items())),
            'within_tolerance_vs_verified_creation': sum(
                s.get('within_tolerance_vs_verified_creation') is True for s in observed),
            'actual_offset_ms_quantiles': quantiles([s['actual_offset_ms_vs_verified_creation']
                                                     for s in observed
                                                     if 'actual_offset_ms_vs_verified_creation' in s])}
    base = schedule['buy_offset_ms']
    outputs['state_change_vs_plus60'] = {}
    for offset in offsets[1:]:
        pairs = [(c['_raw_curve'][base], c['_raw_curve'][offset]) for c in creations
                 if base in c['_raw_curve'] and offset in c['_raw_curve']]
        reserve = [Fraction(later[0], first[0]) for first, later in pairs if first[0] > 0]
        spot = [later[1] / first[1] for first, later in pairs
                if first[1] is not None and later[1] is not None and first[1] > 0]
        outputs['state_change_vs_plus60'][str(offset)] = {
            'population': population, 'pairs_observed': len(pairs),
            'pairs_unavailable': population - len(pairs),
            'real_b_lower': sum(later[0] < first[0] for first, later in pairs),
            'real_b_equal': sum(later[0] == first[0] for first, later in pairs),
            'real_b_higher': sum(later[0] > first[0] for first, later in pairs),
            'real_b_ratio_quantiles': quantiles(reserve),
            'spot_ratio_quantiles': quantiles(spot),
            'note': 'descriptive curve observations; no death label is inferred'}
    for c in creations:
        del c['_raw_curve']
    detection = [c['detection'] for c in creations]
    detection_counts = {}
    for item in detection:
        detection_counts[item['category']] = detection_counts.get(item['category'], 0) + 1
    outputs['detection_latency'] = {
        'population': population, 'category_counts': dict(sorted(detection_counts.items())),
        'latency_ms_quantiles': quantiles([d['latency_ms'] for d in detection if d['category'] == 'observed']),
        'slot_lag_quantiles': quantiles([d['slot_lag'] for d in detection
                                         if d['category'] == 'observed' and d['slot_lag'] is not None]),
        'index_detection_latency_ms_quantiles': quantiles([c['index_detection_latency_ms'] for c in creations
                                                           if c['index_detection_latency_ms'] is not None]),
        'block_time_resolution_ms': 1000}
    migration = [c['migration'] for c in creations]
    outputs['migration_within_window'] = {
        'population': population,
        'left_active_curve': sum(m['left_active_curve_within_window'] is True for m in migration),
        'stayed_active_in_all_observed_states': sum(m['left_active_curve_within_window'] is False for m in migration),
        'no_state_observed': sum(m['left_active_curve_within_window'] is None for m in migration),
        'pool_account_absent_observed': sum(m['pool_account_absent_observed'] for m in migration),
        'status_code_meaning': 'raw LaunchLab pool status; 0 is the active launch curve, other codes are not interpreted further'}
    verification = {}
    for c in creations:
        verification[c['verification']] = verification.get(c['verification'], 0) + 1
    outputs['creation_verification'] = dict(sorted(verification.items()))

    dispositions = {}
    for row in state['universe'].values():
        dispositions[row['disposition']] = dispositions.get(row['disposition'], 0) + 1
    gaps, opened, reasons_open = {}, {}, {}
    for event in events:
        if event['kind'] != 'gap':
            continue
        gap = event['payload']['gap_id']
        if event['outcome'] == 'open':
            opened[gap] = event['reason']
        else:
            opened.pop(gap, None)
        key = '%s:%s' % (event['outcome'], event['reason'])
        gaps[key] = gaps.get(key, 0) + 1
    for reason in opened.values():
        reasons_open[reason] = reasons_open.get(reason, 0) + 1
    continuity = {}
    for poll in state['polls']:
        continuity[poll['continuity']] = continuity.get(poll['continuity'], 0) + 1
    refused = sum(1 for e in events if (e['reason'] or '').startswith('unsafe_or_invalid')
                  or (e['kind'] == 'gap' and 'rejected_by_evidence_policy' in (e['reason'] or '')))
    effective = started['effective_limits']
    protocol_limits = {key: PROTOCOL_V1['checkpoint'][key] for key in effective}
    tasks_total = sum(len(c['tasks']) for c in state['creations'])
    report = {
        'schema': REPORT_SCHEMA, 'run_id': run['run_id'],
        'data_kind': started['data_kind'],
        'preregistration': {key: run[key] for key in ('protocol_sha256', 'authorization_sha256',
                                                      'preregistration_sha256', 'source_revision')},
        'protocol_deviations': [] if effective == protocol_limits else [
            {'field': 'checkpoint_segment_limits', 'effective': effective, 'protocol': protocol_limits}],
        'run_complete': state['complete'] is not None,
        'enrollment_close_reason': (state['enrollment_closed'] or {}).get('reason'),
        'tasks_total': tasks_total, 'tasks_terminal': sum(t in state['terminal'] for c in state['creations']
                                                          for t in (task['task_id'] for task in c['tasks'])),
        'evidence': {'segments': segments, 'events': len(events), 'final_tail_hash': tail,
                     'refused_or_digest_only_bodies': refused,
                     'sqlite_retained_in_archive': False},
        'coverage': {
            'coverage_of_all_launchlab_creations': None,
            'statement': PROTOCOL_V1['universe']['coverage_of_all_launchlab_creations'],
            'polls': len(state['polls']),
            'polls_observed': sum(p['outcome'] == 'observed' for p in state['polls']),
            'polls_failed': sum(p['outcome'] != 'observed' for p in state['polls']),
            'poll_continuity_counts': dict(sorted(continuity.items())),
            'universe_disposition_counts': dict(sorted(dispositions.items())),
            'identity_conflicts': len(state['conflicts']),
            'gap_event_counts': dict(sorted(gaps.items())),
            'open_gaps_by_reason': dict(sorted(reasons_open.items()))},
        'budget': {'authorized': authorization['request_budgets'],
                   'used': (state['complete'] or {}).get('requests_used', state['cumulative_requests']),
                   'throttle_events': len(state['throttles']),
                   'resumes': len(state['resumes'])},
        'population_enrolled': population,
        'outputs': outputs,
        'creations': creations,
        'economic_verdict': 'not_part_of_census',
        'position_acquired': False, 'real_orders_enabled': False,
    }
    return _json_ready(report)


def _json_ready(value):
    if isinstance(value, Fraction):
        return dec(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True,
                        help='Directory with run.json, anchors/ and bundles/')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.suffix != '.json':
        parser.error('Use a new .json output path')
    report = analyze(args.evidence)
    atomic_write_json(args.output, report, indent=2, sort_keys=True, allow_nan=False)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(json.dumps({'report_sha256': digest, 'population_enrolled': report['population_enrolled'],
                      'run_complete': report['run_complete']}, sort_keys=True))
    return digest


if __name__ == '__main__':
    main()
