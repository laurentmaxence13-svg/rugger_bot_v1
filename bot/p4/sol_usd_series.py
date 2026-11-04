"""Causal SOL/USD price series consumed by the historical research replay (no network).

The collection of these points belongs to RUGGER 03 (L2 collection plan). This module
only defines and checks the input the replay accepts, and the as-of lookup rule:

* Point (``rugger-sol-usd-point-v1``): ``slot`` (int > 0), ``transaction_index``
  (int >= 0 or None), ``block_time`` (int s or None), ``received_at_ms`` (int or
  None; prospective receipt clock), ``publish_time`` (int s or None; required for the
  Pyth kinds), ``price`` (int mantissa > 0), ``exponent`` (int, price_usd = price *
  10**exponent), ``confidence`` (int >= 0 or None, same exponent), ``source_kind``,
  ``source_ref`` (price account / Hermes feed id / pool address), ``evidence_sha256``
  (64 lowercase hex: raw account data, signed update bytes or raw transaction) and
  ``signature`` (trade signature, required for the pool kind, else None).
* Accepted ``source_kind``: ``pyth_onchain_account``, ``pyth_hermes_signed_update``,
  ``sol_usdc_pool_last_trade``. Nothing here verifies the raw evidence: every point is
  ``NOT_VERIFIED_IN_REPLAY``. Only a later, audited verifier may certify a Pyth point;
  a pool trade is a market observation and is never certified.
* Series (``rugger-sol-usd-series-v1``): ``label`` = ``SYNTHETIC_TEST_FIXTURE`` or
  ``COLLECTED``, ``points`` strictly sorted by ``(slot, transaction_index or 0)``.
  Any malformed point refuses the whole series (fail closed).

As-of rule at a decision (slot S, transaction index T, decision time D in ms): take
the LAST point with ``(slot, transaction_index or 0) <= (S, T)``. Its reference time
is ``publish_time*1000`` if present, else ``received_at_ms``, else ``block_time*1000``.
Refusals: no such point -> ``sol_usd_rate_unavailable``; reference time after D ->
``sol_usd_point_from_future``; ``D - reference > MAX_AGE_MS`` (5000) ->
``sol_usd_stale``. No interpolation, no average, no later point.
"""
from dataclasses import dataclass
from fractions import Fraction
import gzip
import hashlib
import json
import re

POINT_SCHEMA = 'rugger-sol-usd-point-v1'
SERIES_SCHEMA = 'rugger-sol-usd-series-v1'
SOURCE_KINDS = frozenset({'pyth_onchain_account', 'pyth_hermes_signed_update',
                          'sol_usdc_pool_last_trade'})
LABELS = frozenset({'SYNTHETIC_TEST_FIXTURE', 'COLLECTED'})
MAX_AGE_MS = 5000
VERIFICATION = 'NOT_VERIFIED_IN_REPLAY'
_FIELDS = frozenset({'schema', 'slot', 'transaction_index', 'block_time', 'received_at_ms',
                     'publish_time', 'price', 'exponent', 'confidence', 'source_kind',
                     'source_ref', 'evidence_sha256', 'signature'})
_HEX64 = re.compile(r'[0-9a-f]{64}')


def _int(value, *, minimum=None, optional=False):
    if value is None and optional:
        return True
    return type(value) is int and (minimum is None or value >= minimum)


def _check_point(point):
    if type(point) is not dict or set(point) != _FIELDS or point['schema'] != POINT_SCHEMA:
        raise ValueError('sol_usd_point_schema')
    if not (_int(point['slot'], minimum=1) and _int(point['transaction_index'], minimum=0, optional=True)
            and _int(point['block_time'], minimum=1, optional=True)
            and _int(point['received_at_ms'], minimum=1, optional=True)
            and _int(point['publish_time'], minimum=1, optional=True)
            and _int(point['price'], minimum=1) and _int(point['exponent'])
            and -18 <= point['exponent'] <= 18
            and _int(point['confidence'], minimum=0, optional=True)):
        raise ValueError('sol_usd_point_values')
    if point['source_kind'] not in SOURCE_KINDS:
        raise ValueError('sol_usd_point_source_kind')
    if type(point['source_ref']) is not str or not 1 <= len(point['source_ref']) <= 128:
        raise ValueError('sol_usd_point_source_ref')
    if type(point['evidence_sha256']) is not str or not _HEX64.fullmatch(point['evidence_sha256']):
        raise ValueError('sol_usd_point_evidence_sha256')
    is_trade = point['source_kind'] == 'sol_usdc_pool_last_trade'
    if is_trade != (type(point['signature']) is str and 1 <= len(point['signature']) <= 128):
        raise ValueError('sol_usd_point_signature')
    if not is_trade and point['signature'] is not None:
        raise ValueError('sol_usd_point_signature')
    if not is_trade and point['publish_time'] is None:
        raise ValueError('sol_usd_point_publish_time_required')
    if reference_ms(point) is None:
        raise ValueError('sol_usd_point_without_clock')


def reference_ms(point):
    """Clock of a point: oracle publish time, else receipt, else chain block time."""
    if point['publish_time'] is not None:
        return point['publish_time'] * 1000
    if point['received_at_ms'] is not None:
        return point['received_at_ms']
    if point['block_time'] is not None:
        return point['block_time'] * 1000
    return None


def _key(point):
    return point['slot'], point['transaction_index'] or 0


def price_usd(point):
    return Fraction(point['price']) * Fraction(10) ** point['exponent']


@dataclass(frozen=True)
class SolUsdSeries:
    label: str
    points: tuple
    sha256: str

    def as_of(self, *, slot, transaction_index, decision_ms):
        """Return ``(point, age_ms, None)`` or ``(None, None, refusal_reason)``."""
        limit = (slot, transaction_index or 0)
        chosen = None
        for point in self.points:            # sorted; stop at the first later point
            if _key(point) > limit:
                break
            chosen = point
        if chosen is None:
            return None, None, 'sol_usd_rate_unavailable'
        age = decision_ms - reference_ms(chosen)
        if age < 0:
            return None, None, 'sol_usd_point_from_future'
        if age > MAX_AGE_MS:
            return None, None, 'sol_usd_stale'
        return chosen, age, None


def series_from_document(document):
    """Validate a parsed series document; its sha256 is that of the canonical JSON."""
    if (type(document) is not dict or set(document) != {'schema', 'label', 'points'}
            or document['schema'] != SERIES_SCHEMA or document['label'] not in LABELS
            or type(document['points']) is not list or not document['points']):
        raise ValueError('sol_usd_series_schema')
    previous = None
    for point in document['points']:
        _check_point(point)
        if previous is not None and _key(point) <= _key(previous):
            raise ValueError('sol_usd_series_not_strictly_sorted')
        previous = point
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return SolUsdSeries(document['label'], tuple(document['points']),
                        hashlib.sha256(canonical.encode()).hexdigest())


def load_series(path):
    data = open(path, 'rb').read()
    if str(path).endswith('.gz'):
        data = gzip.decompress(data)
    return series_from_document(json.loads(data))
