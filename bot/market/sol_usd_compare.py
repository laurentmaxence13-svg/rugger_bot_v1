"""Offline consistency check between two SOL/USD series (``rugger-sol-usd-series-v1``).

Stop rule of the L2 plan: before any P1 collection, the reference series is compared
with a second, independent one (another pool, or Hermes if the owner approves) on a
sample of seconds. Thresholds are fixed BEFORE the comparison:
median deviation <= 0.3 % and 99th percentile <= 1 % by default, on at least
``min_compared`` seconds. Otherwise the verdict is FAIL or INSUFFICIENT and the
command exits non-zero: P1 stops.

At each second B, each series is read with the timing rule of the L1 spec
(T-0031 @ 1c28f76): decision instant ``D = B*1000 + 400`` ms; a point is available
at the END of its latest second clock (``t*1000 + 999``) or at ``received_at_ms``;
its age is measured from the START of its oldest clock; the latest available point
with age <= 5000 ms is used, never a later one, never an interpolation. Points are
taken in availability order, which lets a chain series (slot order) and a Hermes
series (publish_time order) be compared on the same clock.

Deviation at B = |p_a - p_b| / p_b, with exact fractions. Nothing here touches the
network.
"""
from fractions import Fraction
import gzip
import json
from pathlib import Path

from bot.market.backfill import BackfillError

MAX_AGE_MS = 5000
DECISION_OFFSET_MS = 400
SCHEMA = 'rugger-backfill-series-comparison-v1'


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
        return (available_ms(self.points[0]) // 1000, available_ms(self.points[-1]) // 1000 + 5)


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


def compare(document_a, document_b, *, start_second=None, end_second=None, step_seconds=1,
            max_median=Fraction(3, 1000), max_p99=Fraction(1, 100), min_compared=1000):
    """Verdict PASS / FAIL / INSUFFICIENT with the deviation statistics."""
    if type(step_seconds) is not int or step_seconds < 1:
        raise BackfillError('step_seconds_must_be_a_positive_integer')
    reader_a, reader_b = _Reader(document_a), _Reader(document_b)
    if not reader_a.points or not reader_b.points:
        raise BackfillError('series_without_timed_points')
    lo = max(reader_a.span_seconds()[0], reader_b.span_seconds()[0])
    hi = min(reader_a.span_seconds()[1], reader_b.span_seconds()[1])
    start = lo if start_second is None else start_second
    end = hi if end_second is None else end_second
    deviations, missing = [], {'a': 0, 'b': 0, 'both': 0}
    worst = None
    for second in range(start, end + 1, step_seconds):
        decision = second * 1000 + DECISION_OFFSET_MS
        pa, pb = reader_a.at(decision), reader_b.at(decision)
        if pa is None or pb is None:
            missing['both' if pa is None and pb is None else ('a' if pa is None else 'b')] += 1
            continue
        a, b = price(pa), price(pb)
        deviation = abs(a - b) / b
        deviations.append(deviation)
        if worst is None or deviation > worst[0]:
            worst = (deviation, second, a, b)
    ordered = sorted(deviations)
    median, p99 = _nearest_rank(ordered, Fraction(1, 2)), _nearest_rank(ordered, Fraction(99, 100))
    if len(ordered) < min_compared:
        verdict = 'INSUFFICIENT'
    elif median <= max_median and p99 <= max_p99:
        verdict = 'PASS'
    else:
        verdict = 'FAIL'
    return {'schema': SCHEMA, 'verdict': verdict,
            'thresholds': {'max_median': _decimal(max_median), 'max_p99': _decimal(max_p99),
                           'min_compared': min_compared},
            'seconds': {'start': start, 'end': end, 'step': step_seconds,
                        'compared': len(ordered), 'missing': missing},
            'deviation': {'median': _decimal(median), 'p99': _decimal(p99),
                          'max': _decimal(ordered[-1]) if ordered else None},
            'worst': None if worst is None else {'second': worst[1], 'price_a': _decimal(worst[2]),
                                                 'price_b': _decimal(worst[3])},
            'labels': {'a': document_a['label'], 'b': document_b['label']},
            'timing_rule': 'decision B*1000+400 ms; available at end of second clock; '
                           'age from start of clock <= 5000 ms (spec T-0031)'}
