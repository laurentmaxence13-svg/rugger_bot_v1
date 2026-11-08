"""Causal SOL/USD price series consumed by the historical research replay (no network).

The collection of these points belongs to RUGGER 03 (L2 collection plan). This module
only defines and checks the input the replay accepts, and the as-of lookup rule:

* Point (``rugger-sol-usd-point-v1``): ``slot`` (int > 0; Solana slot), ``transaction_index``
  (int >= 0 or None), ``block_time`` (int s or None), ``received_at_ms`` (int or
  None; prospective receipt clock), ``publish_time`` (int s or None; required for the
  Pyth kinds), ``price`` (int mantissa > 0), ``exponent`` (int, price_usd = price *
  10**exponent), ``confidence`` (int >= 0 or None, same exponent), ``source_kind``,
  ``source_ref`` (price account / Hermes feed id / pool address), ``evidence_sha256``
  (64 lowercase hex: raw account data, signed update bytes or raw transaction) and
  ``signature`` (trade signature, required for the pool kind, else None).
  A ``pyth_hermes_signed_update`` is off chain: its ``slot``, ``transaction_index``
  and ``block_time`` must be None (a Pythnet slot is not a Solana slot).
* Accepted ``source_kind``: ``pyth_onchain_account``, ``pyth_hermes_signed_update``,
  ``sol_usdc_pool_last_trade``. Nothing here verifies the raw evidence: every point is
  ``NOT_VERIFIED_IN_REPLAY``. Only a later, audited verifier may certify a Pyth point;
  a pool trade is a market observation and is never certified.
* Series (``rugger-sol-usd-series-v1``): ``label`` = ``SYNTHETIC_TEST_FIXTURE`` or
  ``COLLECTED``. Either only on-chain points, strictly sorted by ``(slot,
  transaction_index or 0)`` (ordering ``chain_position``), or only Hermes points,
  strictly sorted by ``publish_time`` (ordering ``publish_time``); never mixed.
  Any malformed point refuses the whole series (fail closed).

As-of rule at a decision (slot S, transaction index T, decision time D in ms):

1. Position. ``chain_position``: the point's ``(slot, transaction_index)`` is at or
   before ``(S, T)``; a point whose ``transaction_index`` is None is usable only if
   its slot is strictly before S (its place inside slot S is unknown).
   ``publish_time``: the point's ``publish_time * 1000 <= D``.
2. Availability (no future data). ``available_ms`` = the latest of
   ``received_at_ms`` and the END of every second-resolution clock
   (``publish_time*1000 + 999``, ``block_time*1000 + 999``); it must be ``<= D``.
3. Take the LAST positioned point that is available. Its age is ``D -
   observed_ms``, where ``observed_ms`` is the START of its oldest clock.

Refusals: no positioned point -> ``sol_usd_rate_unavailable``; positioned points but
none available at D -> ``sol_usd_point_from_future``; age above ``MAX_AGE_MS`` (5000)
-> ``sol_usd_stale``. No interpolation, no average, no later point.

Optional ``acceptance`` (W1 protocol R7, option B'): a series document may carry
``{"max_age_ms": int, "max_confidence_ppm": int or null}``, part of the canonical document
and so of its sha256 (which the pre-registration records). ``max_age_ms`` (1000 to 120000)
replaces MAX_AGE_MS; with ``max_confidence_ppm`` (1 to 10000), the chosen point is refused
when ``confidence / price`` exceeds it (``sol_usd_confidence_too_wide``) or its confidence is
unknown (``sol_usd_confidence_unknown``): never a fallback to an older point. A document
without ``acceptance`` behaves, and hashes, exactly as before.
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
HERMES = 'pyth_hermes_signed_update'
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
    off_chain = point['source_kind'] == HERMES
    if not (_int(point['slot'], minimum=1, optional=off_chain)
            and _int(point['transaction_index'], minimum=0, optional=True)
            and _int(point['block_time'], minimum=1, optional=True)
            and _int(point['received_at_ms'], minimum=1, optional=True)
            and _int(point['publish_time'], minimum=1, optional=True)
            and _int(point['price'], minimum=1) and _int(point['exponent'])
            and -18 <= point['exponent'] <= 18
            and _int(point['confidence'], minimum=0, optional=True)):
        raise ValueError('sol_usd_point_values')
    if point['source_kind'] not in SOURCE_KINDS:
        raise ValueError('sol_usd_point_source_kind')
    if off_chain and any(point[key] is not None for key in ('slot', 'transaction_index', 'block_time')):
        raise ValueError('sol_usd_point_hermes_has_no_solana_position')
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
    if available_ms(point) is None:
        raise ValueError('sol_usd_point_without_clock')


def available_ms(point):
    """Latest moment the point may have become known (no-future check).

    A second-resolution clock (``publish_time``, ``block_time``) only says the event
    happened within that second, so its END (``t*1000 + 999``) is used; a receipt
    clock can only make the point later, never earlier.
    """
    ends = [point[key] * 1000 + 999 for key in ('publish_time', 'block_time') if point[key] is not None]
    if point['received_at_ms'] is not None:
        ends.append(point['received_at_ms'])
    return max(ends) if ends else None


def observed_ms(point):
    """Earliest moment of the price (staleness): START of its oldest clock."""
    starts = [point[key] * 1000 for key in ('publish_time', 'block_time') if point[key] is not None]
    if point['received_at_ms'] is not None:
        starts.append(point['received_at_ms'])
    return min(starts) if starts else None


def _sort_key(point, ordering):
    if ordering == 'publish_time':
        return point['publish_time']
    return point['slot'], point['transaction_index'] or 0


def price_usd(point):
    return Fraction(point['price']) * Fraction(10) ** point['exponent']


@dataclass(frozen=True)
class SolUsdSeries:
    label: str
    ordering: str
    points: tuple
    sha256: str
    max_age_ms: int = MAX_AGE_MS
    max_confidence_ppm: int = None

    def _positioned(self, point, slot, transaction_index, decision_ms):
        """``None`` once past the decision position (the series is sorted), else a bool."""
        if self.ordering == 'publish_time':
            return None if point['publish_time'] * 1000 > decision_ms else True
        if _sort_key(point, self.ordering) > (slot, transaction_index):
            return None
        # Unknown place inside the slot: only a strictly earlier slot is safe.
        return point['transaction_index'] is not None or point['slot'] < slot

    def as_of(self, *, slot, transaction_index, decision_ms):
        """Return ``(point, age_ms, None)`` or ``(None, None, refusal_reason)``."""
        if not (type(slot) is int and type(transaction_index) is int and type(decision_ms) is int):
            raise ValueError('sol_usd_as_of_arguments')
        positioned, chosen = False, None
        for point in self.points:
            usable = self._positioned(point, slot, transaction_index, decision_ms)
            if usable is None:
                break
            if usable:
                positioned = True
                if available_ms(point) <= decision_ms:
                    chosen = point
        if not positioned:
            return None, None, 'sol_usd_rate_unavailable'
        if chosen is None:
            return None, None, 'sol_usd_point_from_future'
        age = decision_ms - observed_ms(chosen)
        if age > self.max_age_ms:
            return None, None, 'sol_usd_stale'
        if self.max_confidence_ppm is not None:
            if chosen['confidence'] is None:
                return None, None, 'sol_usd_confidence_unknown'
            if chosen['confidence'] * 1_000_000 > self.max_confidence_ppm * chosen['price']:
                return None, None, 'sol_usd_confidence_too_wide'
        return chosen, age, None


def series_from_document(document):
    """Validate a parsed series document; its sha256 is that of the canonical JSON."""
    if (type(document) is not dict or set(document) - {'acceptance'} != {'schema', 'label', 'points'}
            or document['schema'] != SERIES_SCHEMA or document['label'] not in LABELS
            or type(document['points']) is not list or not document['points']):
        raise ValueError('sol_usd_series_schema')
    acceptance = document.get('acceptance', dict(max_age_ms=MAX_AGE_MS, max_confidence_ppm=None))
    if (type(acceptance) is not dict or set(acceptance) != {'max_age_ms', 'max_confidence_ppm'}
            or type(acceptance['max_age_ms']) is not int or not 1000 <= acceptance['max_age_ms'] <= 120_000
            or not (acceptance['max_confidence_ppm'] is None
                    or (type(acceptance['max_confidence_ppm']) is int and 1 <= acceptance['max_confidence_ppm'] <= 10_000))):
        raise ValueError('sol_usd_series_acceptance')
    for point in document['points']:
        _check_point(point)
    kinds = {point['source_kind'] == HERMES for point in document['points']}
    if len(kinds) != 1:
        raise ValueError('sol_usd_series_mixes_chain_and_hermes_points')
    ordering = 'publish_time' if kinds.pop() else 'chain_position'
    keys = [_sort_key(point, ordering) for point in document['points']]
    if any(later <= earlier for earlier, later in zip(keys, keys[1:])):
        raise ValueError('sol_usd_series_not_strictly_sorted')
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return SolUsdSeries(document['label'], ordering, tuple(document['points']),
                        hashlib.sha256(canonical.encode()).hexdigest(), acceptance['max_age_ms'],
                        acceptance['max_confidence_ppm'])


def load_series(path):
    with open(path, 'rb') as handle:         # closed explicitly (ResourceWarning under -W error)
        data = handle.read()
    if str(path).endswith('.gz'):
        data = gzip.decompress(data)
    return series_from_document(json.loads(data))
