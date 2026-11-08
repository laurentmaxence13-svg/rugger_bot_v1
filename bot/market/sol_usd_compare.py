"""Offline consistency check between two SOL/USD series (``rugger-sol-usd-series-v1``).

Stop rule of the L2 plan: before any P1 collection, the reference series is compared
with a second, independent one (another pool, or Hermes if the owner approves). The
verdict is PASS only when ALL of these hold, with thresholds frozen BEFORE the run:

- coverage (R02 O1 on T-0034): the share of grid seconds of the window where either
  series has no usable point is at most ``max_missing_share``. The window is, by
  default, the UNION of the two series' usable spans, so a series that starts late,
  stops early or is present one second in two cannot pass on a dense subset;
- at least ``min_compared`` seconds were compared;
- median deviation <= ``max_median`` and 99th percentile <= ``max_p99``;
- the two series share no transaction evidence and no source reference (a series
  compared with itself, or with the same pool, trivially agrees: R02 O3).

Pre-registration (R02 O2 on T-0034): the thresholds are read ONLY from an OWNER
``create`` event of the T-REG registry (payload key ``compare_series_thresholds``,
schema ``rugger-compare-thresholds-v1``), found in a snapshot written by
``treg.py ingest``. The event digest is recomputed; a command-line value that
differs from the registered one is refused. Without a pre-registration the
statistics are still computed, but the verdict is ``NOT_PREREGISTERED``: never PASS.
The report names the event (id, digest, utc) and the SHA-256 of both inputs so the
auditor can check that the event is on GitHub and older than the run.

Timing rule of the L1 spec (T-0031 @ 1c28f76), at each second B: decision instant
``D = B*1000 + 400`` ms; a point is available at the END of its latest second clock
(``t*1000 + 999``) or at ``received_at_ms``; its age is measured from the START of its
oldest clock; the latest available point with age <= 5000 ms is used, never a later
one, never an interpolation. Deviation at B = |p_a - p_b| / p_b, exact fractions.
Nothing here touches the network.
"""
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import re

from bot.market.backfill import BackfillError

MAX_AGE_MS = 5000
DECISION_OFFSET_MS = 400
SCHEMA = 'rugger-backfill-series-comparison-v2'
THRESHOLDS_SCHEMA = 'rugger-compare-thresholds-v1'
THRESHOLDS_KEY = 'compare_series_thresholds'
TREG_EVENT_SCHEMA = 'rugger-treg-event-v1'
TREG_SNAPSHOT_SCHEMA = 'rugger-treg-snapshot-v1'
_DECIMAL = re.compile(r'(0|1)(\.[0-9]{1,12})?\Z')
_THRESHOLD_KEYS = {'schema', 'max_median', 'max_p99', 'min_compared', 'max_missing_share',
                   'step_seconds', 'window'}


def load_series_document(path):
    path = Path(path)
    data = path.read_bytes()
    if path.suffix == '.gz':
        data = gzip.decompress(data)
    document = json.loads(data)
    if (type(document) is not dict or set(document) != {'schema', 'label', 'points'}
            or document['schema'] != 'rugger-sol-usd-series-v1' or not document['points']):
        raise BackfillError(f'not_a_sol_usd_series:{path.name}')
    return document


def _canonical(obj):
    """The T-REG canonical form (treg.py): sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha256_of(obj):
    return hashlib.sha256(_canonical(obj)).hexdigest()


# ----------------------------------------------------------------- pre-registration
def _share(value, name):
    if type(value) is not str or not _DECIMAL.match(value) or Fraction(value) > 1:
        raise BackfillError(f'threshold_{name}_must_be_a_decimal_string_in_0_1')
    return Fraction(value)


def parse_thresholds(document):
    """Validate a ``rugger-compare-thresholds-v1`` document -> exact values.

    Decimals are strings (no binary float); every key is mandatory, so nothing is left
    to a default chosen after the data is seen. ``window`` is null (union span of the
    two series) or ``{"start_second", "end_second"}`` fixed in advance.
    """
    if type(document) is not dict or set(document) != _THRESHOLD_KEYS \
            or document['schema'] != THRESHOLDS_SCHEMA:
        raise BackfillError('thresholds_fields')
    values = {name: _share(document[name], name)
              for name in ('max_median', 'max_p99', 'max_missing_share')}
    for name in ('min_compared', 'step_seconds'):
        if type(document[name]) is not int or document[name] < 1:
            raise BackfillError(f'threshold_{name}_must_be_a_positive_integer')
        values[name] = document[name]
    window = document['window']
    if window is not None:
        if (type(window) is not dict or set(window) != {'start_second', 'end_second'}
                or any(type(window[k]) is not int for k in window)
                or window['start_second'] > window['end_second']):
            raise BackfillError('threshold_window_invalid')
        window = (window['start_second'], window['end_second'])
    values['window'] = window
    return values


def load_preregistration(snapshot_path, event_id):
    """Find the OWNER event that froze the thresholds in a T-REG snapshot.

    Returns ``(thresholds_document, reference)``. Refused: missing or duplicated event,
    recomputed digest that differs, an author other than OWNER, an event type other than
    ``create``, or a thresholds document that does not validate.
    """
    try:
        snapshot = json.loads(Path(snapshot_path).read_bytes())
    except ValueError as exc:
        raise BackfillError('not_a_treg_snapshot') from exc
    if type(snapshot) is not dict or snapshot.get('schema') != TREG_SNAPSHOT_SCHEMA \
            or type(snapshot.get('events')) is not list:
        raise BackfillError('not_a_treg_snapshot')
    found = [e for e in snapshot['events'] if type(e) is dict and e.get('event_id') == event_id]
    if len(found) != 1:
        raise BackfillError(f'preregistration_event_not_found_once:{event_id}')
    event = found[0]
    if event.get('schema') != TREG_EVENT_SCHEMA or \
            sha256_of({k: v for k, v in event.items() if k != 'digest'}) != event.get('digest'):
        raise BackfillError('preregistration_event_digest_mismatch')
    if event.get('from_agent') != 'OWNER' or event.get('type') != 'create':
        raise BackfillError('preregistration_must_be_an_owner_create_event')
    document = (event.get('payload') or {}).get(THRESHOLDS_KEY)
    parse_thresholds(document)
    return document, {'event_id': event['event_id'], 'task_id': event.get('task_id'),
                      'digest': event['digest'], 'utc': event.get('utc'),
                      'thresholds_sha256': sha256_of(document)}


def reconcile_overrides(values, overrides):
    """Refuse any command-line value that differs from the registered one (equal is fine).

    ``overrides`` maps max_median / max_p99 / max_missing_share (decimal strings),
    min_compared / step_seconds / start_second / end_second (integers) to the value given
    on the command line, or None when it was not given.
    """
    window = values['window']
    registered = dict(values, start_second=window[0] if window else None,
                      end_second=window[1] if window else None)
    for name, given in overrides.items():
        if given is None:
            continue
        if name in ('max_median', 'max_p99', 'max_missing_share'):
            try:
                same = Fraction(given) == registered[name]
            except (TypeError, ValueError):
                same = False
        else:
            same = given == registered[name]
        if not same:
            raise BackfillError(f'cli_value_differs_from_preregistration:{name}')


# ----------------------------------------------------------------------- reading
def available_ms(point):
    ends = [point[k] * 1000 + 999 for k in ('publish_time', 'block_time') if point.get(k) is not None]
    if point.get('received_at_ms') is not None:
        ends.append(point['received_at_ms'])
    return max(ends) if ends else None


def observed_ms(point):
    starts = [point[k] * 1000 for k in ('publish_time', 'block_time') if point.get(k) is not None]
    if point.get('received_at_ms') is not None:
        starts.append(point['received_at_ms'])
    return min(starts) if starts else None


def price(point):
    return Fraction(point['price']) * Fraction(10) ** point['exponent']


class _Reader:
    """Monotone as-of reader over one series, in availability order."""

    def __init__(self, document):
        timed = [p for p in document['points'] if available_ms(p) is not None]
        # Stable sort: equal availability keeps the series' own order (latest wins).
        self.points = sorted(timed, key=available_ms)
        self.cursor, self.current = 0, None

    def at(self, decision_ms):
        while self.cursor < len(self.points) and available_ms(self.points[self.cursor]) <= decision_ms:
            self.current = self.points[self.cursor]
            self.cursor += 1
        if self.current is None or decision_ms - observed_ms(self.current) > MAX_AGE_MS:
            return None
        return self.current

    def span_seconds(self):
        """First and last decision seconds at which some point of the series is usable."""
        first = -(-(available_ms(self.points[0]) - DECISION_OFFSET_MS) // 1000)
        last = max((observed_ms(p) + MAX_AGE_MS - DECISION_OFFSET_MS) // 1000 for p in self.points)
        return first, last


# --------------------------------------------------------------------- statistics
def _nearest_rank(sorted_values, q):
    if not sorted_values:
        return None
    rank = max(1, -(-len(sorted_values) * q.numerator // q.denominator))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _decimal(value, digits=9):
    if value is None:
        return None
    scaled = value * 10 ** digits
    floor = scaled.numerator // scaled.denominator
    rest = scaled - floor
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and floor % 2):
        floor += 1
    sign = '-' if floor < 0 else ''
    floor = abs(floor)
    return f'{sign}{floor // 10 ** digits}.{floor % 10 ** digits:0{digits}d}'


def independence(document_a, document_b):
    """Shared transaction evidence or source references between the two series."""
    def keys(document, field):
        return {p.get(field) for p in document['points'] if p.get(field) is not None}
    shared_evidence = keys(document_a, 'evidence_sha256') & keys(document_b, 'evidence_sha256')
    shared_sources = keys(document_a, 'source_ref') & keys(document_b, 'source_ref')
    return {'identical_documents': sha256_of(document_a) == sha256_of(document_b),
            'shared_evidence': len(shared_evidence), 'shared_source_refs': sorted(shared_sources)}


def compare(document_a, document_b, *, thresholds=None, preregistration=None, window=None,
            step_seconds=1):
    """Statistics, coverage and verdict.

    ``thresholds`` is a ``rugger-compare-thresholds-v1`` document. The verdict is PASS,
    FAIL or INSUFFICIENT only with a ``preregistration`` reference (the T-REG event the
    thresholds come from); otherwise it is NOT_PREREGISTERED and ``checks`` only says
    what those thresholds would give. ``window`` (start, end) and ``step_seconds`` are
    only for a run without thresholds; with thresholds they come from the document.
    """
    values = parse_thresholds(thresholds) if thresholds is not None else None
    if values is not None and (window is not None or step_seconds != 1):
        raise BackfillError('window_and_step_come_from_the_thresholds_document')
    if type(step_seconds) is not int or step_seconds < 1:
        raise BackfillError('step_seconds_must_be_a_positive_integer')
    step = values['step_seconds'] if values else step_seconds
    if values is not None:
        window = values['window']
    reader_a, reader_b = _Reader(document_a), _Reader(document_b)
    if not reader_a.points or not reader_b.points:
        raise BackfillError('series_without_timed_points')
    spans = (reader_a.span_seconds(), reader_b.span_seconds())
    if window is not None:
        start, end = window
        if type(start) is not int or type(end) is not int or start > end:
            raise BackfillError('window_invalid')
    else:
        start, end = min(s[0] for s in spans), max(s[1] for s in spans)   # union, not overlap
    deviations, missing = [], {'a': 0, 'b': 0, 'both': 0}
    worst, run, longest, total = None, 0, 0, 0
    for second in range(start, end + 1, step):
        total += 1
        decision = second * 1000 + DECISION_OFFSET_MS
        pa, pb = reader_a.at(decision), reader_b.at(decision)
        if pa is None or pb is None:
            missing['both' if pa is None and pb is None else ('a' if pa is None else 'b')] += 1
            run += 1
            longest = max(longest, run)
            continue
        run = 0
        a, b = price(pa), price(pb)
        deviation = abs(a - b) / b
        deviations.append(deviation)
        if worst is None or deviation > worst[0]:
            worst = (deviation, second, a, b)
    ordered = sorted(deviations)
    median, p99 = _nearest_rank(ordered, Fraction(1, 2)), _nearest_rank(ordered, Fraction(99, 100))
    missing_share = Fraction(total - len(ordered), total)
    indep = independence(document_a, document_b)
    checks, failed = None, []
    if values:
        checks = {
            'coverage': missing_share <= values['max_missing_share'],
            'min_compared': len(ordered) >= values['min_compared'],
            'median': median is not None and median <= values['max_median'],
            'p99': p99 is not None and p99 <= values['max_p99'],
            'independent': not indep['identical_documents'] and not indep['shared_evidence']
            and not indep['shared_source_refs'],
        }
        failed = [name for name, ok in checks.items() if not ok]
    if preregistration is None or values is None:
        verdict = 'NOT_PREREGISTERED'
    elif not failed:
        verdict = 'PASS'
    elif failed == ['min_compared']:
        verdict = 'INSUFFICIENT'
    else:
        verdict = 'FAIL'
    return {'schema': SCHEMA, 'verdict': verdict, 'failed_checks': failed, 'checks': checks,
            'preregistration': preregistration,
            'thresholds': None if values is None else {
                'max_median': _decimal(values['max_median']), 'max_p99': _decimal(values['max_p99']),
                'max_missing_share': _decimal(values['max_missing_share']),
                'min_compared': values['min_compared'], 'step_seconds': step,
                'window': thresholds['window'], 'sha256': sha256_of(thresholds)},
            'window_rule': 'registered' if values and values['window'] else (
                'given' if window is not None else 'union_of_usable_spans'),
            'inputs': {'a_sha256': sha256_of(document_a), 'b_sha256': sha256_of(document_b)},
            'seconds': {'start': start, 'end': end, 'step': step, 'evaluated': total,
                        'compared': len(ordered), 'missing': missing,
                        'missing_share': _decimal(missing_share),
                        'longest_missing_run': longest,
                        'span_a': list(spans[0]), 'span_b': list(spans[1])},
            'deviation': {'median': _decimal(median), 'p99': _decimal(p99),
                          'max': _decimal(ordered[-1]) if ordered else None},
            'worst': None if worst is None else {'second': worst[1], 'price_a': _decimal(worst[2]),
                                                 'price_b': _decimal(worst[3])},
            'independence': indep,
            'labels': {'a': document_a['label'], 'b': document_b['label']},
            'timing_rule': 'decision B*1000+400 ms; available at end of second clock; '
                           'age from start of clock <= 5000 ms (spec T-0031)'}
