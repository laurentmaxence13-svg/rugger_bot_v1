"""Fail-closed admission of declared P3 PAPER data, without collecting anything.

This gate checks manifest attestations; it does not authenticate their source or
prove profitability. A technical prospective GO always retains the economic
verdict INSUFFICIENT DATA. The initial 5-second freshness cap is an explicitly
declared instrumentation bound, not a calibrated strategy parameter.
"""
import re


MAX_SNAPSHOT_AGE_MS = 5_000
MIN_FOLLOWUP_DELAY_MS = 15_000
_MAX_INTEGER = 2**63 - 1
_SHA256 = re.compile(r'[0-9a-fA-F]{64}\Z')
_MISSING = object()


def _mapping(value):
    return value if type(value) is dict else {}


def _observation(value, predicate, description, *, expected_type):
    if type(value) is not expected_type:
        return 'UNKNOWN', description + ': missing or invalid type'
    if not predicate(value):
        return 'FAIL', description + ': requirement not met'
    return 'PASS', None


def _integer(value, predicate, description):
    return _observation(value, lambda item: 0 <= item <= _MAX_INTEGER and predicate(item),
                        description, expected_type=int)


def _boolean(value, description):
    return _observation(value, lambda item: item is True, description, expected_type=bool)


def _combined(observations):
    statuses = [status for status, _ in observations]
    return 'FAIL' if 'FAIL' in statuses else ('UNKNOWN' if 'UNKNOWN' in statuses else 'PASS')


def evaluate_readiness(manifest: dict) -> dict:
    """Evaluate every selected row; absent or ill-typed evidence never passes.

    plan.sample_size is the preregistered maximum selection size. It is not a
    minimum statistical sample. A complete independent reference and zero gaps
    are separate economic gates. Candidate booleans must attest checks on all
    required snapshots. The supplied snapshot periods are checked for strictly
    increasing slots, preregistered spacing, and receipt/ingestion/analysis order.
    This checks retained timestamp attestations, not an external trusted clock.
    snapshot_source_age_ms is the maximum source age at receipt; source age at
    analysis is checked separately. The caller remains responsible for retaining
    the registered plan and underlying observations behind these attestations
    and its plan_sha256. Request provenance and public-address authentication
    belong to that collector, not to this manifest-only gate.
    """
    root = _mapping(manifest)
    plan, run, policy = (_mapping(root.get(name)) for name in ('plan', 'run', 'policy'))
    criteria = []

    def add(name, scope, observations):
        if not observations:
            observations = [('UNKNOWN', name + ': no selected candidate evidence')]
        criteria.append({
            'name': name, 'scope': scope, 'status': _combined(observations),
            'evidence_count': sum(status == 'PASS' for status, _ in observations),
            'known_count': sum(status != 'UNKNOWN' for status, _ in observations),
            'required_count': len(observations),
            'reasons': [reason for _, reason in observations if reason is not None],
        })

    def get(section, name):
        return section.get(name, _MISSING)

    add('live_data', 'collection', [_observation(get(root, 'data_kind'),
        lambda value: value == 'live', 'data_kind must be live', expected_type=str)])
    add('registered_plan_identity', 'collection', [
        _observation(get(plan, 'plan_id'), lambda value: bool(value.strip()),
                     'plan_id must identify the registered plan', expected_type=str),
        _observation(get(plan, 'plan_sha256'), lambda value: _SHA256.fullmatch(value) is not None,
                     'plan_sha256 must identify retained plan evidence', expected_type=str),
    ])
    registered, started = get(plan, 'registered_at_ms'), get(plan, 'started_at_ms')
    preregistration = [
        _integer(registered, lambda value: True, 'registered_at_ms'),
        _integer(started, lambda value: True, 'started_at_ms'),
    ]
    if _combined(preregistration) == 'PASS':
        preregistration.append(('PASS', None) if registered < started else
                               ('FAIL', 'plan must be registered before the first read'))
    add('preregistration', 'collection', preregistration)

    for name, maximum, used in (
            ('request_budget', 'max_requests', 'requests_used'),
            ('duration_budget', 'max_elapsed_ms', 'elapsed_ms')):
        limit, actual = get(plan, maximum), get(run, used)
        observations = [_integer(limit, lambda value: value > 0, maximum),
                        _integer(actual, lambda value: True, used)]
        if _combined(observations) == 'PASS':
            observations.append(('PASS', None) if actual <= limit else
                                ('FAIL', used + ' exceeds the registered limit'))
        add(name, 'collection', observations)

    for name in ('anonymous_transport', 'wire_retry_disabled', 'integrity_verified',
                 'tail_anchor_verified'):
        add(name, 'collection', [_boolean(get(run, name), name)])
    add('no_financial_methods', 'collection', [_observation(get(run, 'financial_methods_used'),
        lambda value: len(value) == 0, 'financial_methods_used must be explicitly empty',
        expected_type=list)])

    rows = get(root, 'candidates')
    valid_rows = type(rows) is list
    candidates = rows if valid_rows else []
    selected, sample_size = get(run, 'selected_count'), get(plan, 'sample_size')
    accounting = [_integer(sample_size, lambda value: value > 0, 'sample_size'),
                  _integer(selected, lambda value: value > 0, 'selected_count')]
    accounting.append(('PASS', None) if valid_rows else
                      ('UNKNOWN', 'candidates must be an explicit list'))
    if valid_rows and type(selected) is int:
        accounting.append(('PASS', None) if selected == len(candidates) else
                          ('FAIL', 'every selected candidate must have exactly one row'))
    if type(selected) is int and type(sample_size) is int:
        accounting.append(('PASS', None) if selected <= sample_size else
                          ('FAIL', 'selected_count exceeds the registered sample size'))
    add('selected_rows_accounted', 'collection', accounting)

    mint_observations, mints = [], set()
    for index, row in enumerate(candidates):
        mint = get(_mapping(row), 'mint')
        observation = _observation(mint, lambda value: bool(value.strip()),
            'candidate[' + str(index) + '].mint', expected_type=str)
        if observation[0] == 'PASS':
            if mint in mints:
                observation = ('FAIL', 'candidate[' + str(index) + '].mint is duplicated')
            mints.add(mint)
        mint_observations.append(observation)
    add('selected_mint_identity', 'collection', mint_observations)

    add('independent_reference_complete', 'economic', [_boolean(
        get(run, 'independent_reference_complete'), 'independent_reference_complete')])
    add('no_open_gaps', 'economic', [_integer(get(run, 'open_gaps'),
        lambda value: value == 0, 'open_gaps must be zero')])

    age_limit = get(policy, 'max_snapshot_age_ms')
    add('declared_snapshot_age_bound', 'economic', [_integer(age_limit,
        lambda value: 0 < value <= MAX_SNAPSHOT_AGE_MS,
        'max_snapshot_age_ms must declare an instrumentation bound at most 5000 ms')])
    followup = get(plan, 'followup_delay_ms')
    followup_observations = [_integer(followup,
        lambda value: value >= MIN_FOLLOWUP_DELAY_MS,
        'followup_delay_ms must declare at least 15000 ms between observed periods')]
    duration_limit = get(plan, 'max_elapsed_ms')
    if (type(followup) is int and type(duration_limit) is int
            and 0 <= followup <= _MAX_INTEGER and 0 < duration_limit <= _MAX_INTEGER):
        followup_observations.append(('PASS', None) if followup <= duration_limit else
            ('FAIL', 'followup_delay_ms exceeds the entire collection duration'))
    add('declared_followup_delay', 'economic', followup_observations)
    for field in ('creation_verified', 'all_account_links_verified',
                  'account_discriminators_certified', 'native_sol',
                  'token_transfer_restrictions_known', 'exit_liquidity_checked',
                  'fees_complete', 'network_fee_bound_known',
                  'source_clock_bound_known', 'pit_decision_order_verified',
                  'exit_observation_available'):
        add(field, 'economic', [_boolean(get(_mapping(row), field),
            'candidate[' + str(index) + '].' + field)
            for index, row in enumerate(candidates)])
    periods, temporal, source_times = [], [], []
    elapsed = get(run, 'elapsed_ms')
    for index, raw_row in enumerate(candidates):
        row = _mapping(raw_row)
        prefix = 'candidate[' + str(index) + ']'
        count = get(row, 'coherent_snapshot_count')
        periods.append(_integer(count, lambda value: value >= 2,
            prefix + ' needs two distinct ordered coherent snapshot periods'))
        snapshots = get(row, 'snapshots')
        if type(snapshots) is not list:
            observation = ('UNKNOWN', prefix + '.snapshots must be an explicit evidence list')
            periods.append(observation)
            temporal.append(observation)
            source_times.append(observation)
            continue
        if len(snapshots) < 2:
            observation = ('FAIL', prefix + '.snapshots must contain at least two periods')
            periods.append(observation)
            temporal.append(observation)
            source_times.append(observation)
        if type(count) is int:
            periods.append(('PASS', None) if count == len(snapshots) else
                ('FAIL', prefix + '.coherent_snapshot_count disagrees with retained periods'))

        previous = None
        for period, raw_snapshot in enumerate(snapshots):
            snapshot = _mapping(raw_snapshot)
            label = prefix + '.snapshots[' + str(period) + ']'
            slot, receipt, available, analysis = (get(snapshot, field) for field in
                ('context_slot', 'received_at_ms', 'available_at_ms', 'analysis_at_ms'))
            observations = [_integer(value, lambda item: True, label + '.' + field)
                for field, value in (('context_slot', slot), ('received_at_ms', receipt),
                                     ('available_at_ms', available), ('analysis_at_ms', analysis))]
            numeric_valid = _combined(observations) == 'PASS'
            observations.append(_boolean(get(snapshot, 'coherent'), label + '.coherent'))
            if numeric_valid:
                observations.append(('PASS', None) if receipt <= available <= analysis else
                    ('FAIL', label + ': receipt must precede availability and analysis'))
                if type(started) is int and 0 <= started <= _MAX_INTEGER:
                    observations.append(('PASS', None) if started <= receipt else
                        ('FAIL', label + ': observation predates the campaign start'))
                else:
                    observations.append(('UNKNOWN', label + ': campaign start is unavailable'))
                if (type(started) is int and type(elapsed) is int
                        and 0 <= started <= _MAX_INTEGER and 0 <= elapsed <= _MAX_INTEGER):
                    observations.append(('PASS', None) if analysis <= started + elapsed else
                        ('FAIL', label + ': analysis exceeds the completed collection window'))
                else:
                    observations.append(('UNKNOWN', label + ': completed collection duration unavailable'))
                if previous is not None:
                    prev_slot, prev_receipt, prev_analysis = previous
                    observations.append(('PASS', None) if prev_slot < slot else
                        ('FAIL', label + ': context slots must strictly increase'))
                    observations.append(('PASS', None) if prev_analysis <= receipt else
                        ('FAIL', label + ': prior analysis must finish before the next period'))
                    if type(followup) is int and MIN_FOLLOWUP_DELAY_MS <= followup <= _MAX_INTEGER:
                        observations.append(('PASS', None) if receipt - prev_receipt >= followup else
                            ('FAIL', label + ': observed periods are too close'))
                    else:
                        observations.append(('UNKNOWN', label + ': declared followup delay unavailable'))
                previous = (slot, receipt, analysis)
            else:
                # Do not silently connect valid periods around malformed evidence.
                previous = None
            temporal.extend(observations)
            source = get(snapshot, 'source_time_ms')
            source_observations = [_integer(source, lambda value: True, label + '.source_time_ms')]
            if _combined(source_observations) == 'PASS':
                if type(receipt) is int and 0 <= receipt <= _MAX_INTEGER:
                    source_observations.append(('PASS', None) if source <= receipt else
                        ('FAIL', label + ': source time exceeds receipt time'))
                else:
                    source_observations.append(('UNKNOWN', label + ': receipt time unavailable'))
            source_times.extend(source_observations)
    add('coherent_snapshot_periods', 'economic', periods)
    add('snapshot_temporal_evidence', 'economic', temporal)
    add('snapshot_source_time_evidence', 'economic', source_times)

    freshness, decision_freshness = [], []
    for index, row in enumerate(candidates):
        mapped_row = _mapping(row)
        age = get(mapped_row, 'snapshot_source_age_ms')
        description = 'candidate[' + str(index) + '].snapshot_source_age_ms'
        observation = _integer(age, lambda value: True, description)
        if observation[0] == 'PASS':
            if type(age_limit) is not int or not 0 < age_limit <= MAX_SNAPSHOT_AGE_MS:
                observation = ('UNKNOWN', description + ': declared age bound is unavailable')
            elif age > age_limit:
                observation = ('FAIL', description + ': exceeds the declared source-age bound')
        freshness.append(observation)
        snapshots = get(mapped_row, 'snapshots')
        observed_ages = []
        if type(snapshots) is list:
            for snapshot in snapshots:
                source = get(_mapping(snapshot), 'source_time_ms')
                receipt = get(_mapping(snapshot), 'received_at_ms')
                analysis = get(_mapping(snapshot), 'analysis_at_ms')
                if (type(source) is int and type(receipt) is int
                        and 0 <= source <= receipt <= _MAX_INTEGER):
                    actual_age = receipt - source
                    observed_ages.append(actual_age)
                    if type(age_limit) is int and 0 < age_limit <= MAX_SNAPSHOT_AGE_MS:
                        freshness.append(('PASS', None) if actual_age <= age_limit else
                            ('FAIL', description + ': a retained period exceeds the source-age bound'))
                if (type(source) is int and type(analysis) is int
                        and 0 <= source <= _MAX_INTEGER and 0 <= analysis <= _MAX_INTEGER):
                    if type(age_limit) is int and 0 < age_limit <= MAX_SNAPSHOT_AGE_MS:
                        decision_freshness.append(('PASS', None)
                            if 0 <= analysis - source <= age_limit else
                            ('FAIL', description + ': source age at analysis exceeds the declared bound'))
                    else:
                        decision_freshness.append(('UNKNOWN', description + ': declared age bound unavailable'))
                else:
                    decision_freshness.append(('UNKNOWN', description + ': analysis/source time unavailable'))
            if (snapshots and len(observed_ages) == len(snapshots)
                    and type(age) is int and 0 <= age <= _MAX_INTEGER):
                freshness.append(('PASS', None) if age == max(observed_ages) else
                    ('FAIL', description + ': does not match the maximum retained period age'))
    add('snapshot_source_freshness', 'economic', freshness)
    add('snapshot_decision_freshness', 'economic', decision_freshness)

    collection_go = all(item['status'] == 'PASS' for item in criteria
                        if item['scope'] == 'collection')
    economic_go = collection_go and all(item['status'] == 'PASS' for item in criteria)
    return {
        'schema': 'p3-readiness-v1',
        'collection_readiness': 'GO' if collection_go else 'NO-GO',
        'economic_readiness': 'GO' if economic_go else 'NO-GO',
        'p3_go': economic_go,
        'economic_verdict': 'INSUFFICIENT DATA',
        'scope': 'prospective PAPER data admission; no profitability validation',
        'evidence_basis': 'manifest attestations requiring retained underlying evidence',
        'max_snapshot_age_cap_ms': MAX_SNAPSHOT_AGE_MS,
        'criteria': criteria,
        'reasons': [reason for item in criteria for reason in item['reasons']],
    }
