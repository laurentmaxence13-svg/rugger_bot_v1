"""SOL/USD series input of the historical research replay (offline, synthetic samples only).

Every series built here is labelled SYNTHETIC_TEST_FIXTURE: it tests the input
contract and the as-of rule, it is not market data.
"""
import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'launchlab_sol_pools'


def point(slot, *, tx=0, publish=None, received=None, block=None, price=150_00000000, exponent=-8,
          kind='pyth_onchain_account', signature=None):
    return dict(schema=sus.POINT_SCHEMA, slot=slot, transaction_index=tx, block_time=block,
                received_at_ms=received, publish_time=publish, price=price, exponent=exponent,
                confidence=None, source_kind=kind, source_ref='SYNTHETIC-SOL-USD-REF',
                evidence_sha256=hashlib.sha256(f'synthetic:{slot}:{tx}'.encode()).hexdigest(),
                signature=signature)


def series(points, label='SYNTHETIC_TEST_FIXTURE'):
    return sus.series_from_document(dict(schema=sus.SERIES_SCHEMA, label=label, points=points))


def fixture_series(skip=lambda pool, slot: False):
    """One synthetic point per stored fixture transaction, published at its block time."""
    rows = {}
    for path in sorted(FIXTURES.glob('*.json.gz')):
        archive = json.loads(gzip.decompress(path.read_bytes()))
        for tx in archive['transactions'].values():
            if not skip(archive['pool'], tx['slot']):
                key = (tx['slot'], tx.get('transactionIndex') or 0)
                rows[key] = point(key[0], tx=key[1], publish=tx['blockTime'], block=tx['blockTime'])
    return series([rows[key] for key in sorted(rows)])


def test_price_and_reference_clock():
    p = point(10, publish=1_000, received=999_999)
    assert sus.price_usd(p) == 150 and sus.reference_ms(p) == 1_000_000
    trade = point(11, block=2_000, kind='sol_usdc_pool_last_trade', signature='SYNTHETIC-SIG')
    assert sus.reference_ms(trade) == 2_000_000


@pytest.mark.parametrize('mutate, error', [
    (lambda p: p.update(price=0), 'sol_usd_point_values'),
    (lambda p: p.update(source_kind='dexscreener_http'), 'sol_usd_point_source_kind'),
    (lambda p: p.update(evidence_sha256='abc'), 'sol_usd_point_evidence_sha256'),
    (lambda p: p.update(publish_time=None), 'sol_usd_point_publish_time_required'),
    (lambda p: p.update(extra=1), 'sol_usd_point_schema'),
    (lambda p: p.update(signature='X'), 'sol_usd_point_signature'),
])
def test_malformed_point_refuses_the_whole_series(mutate, error):
    bad = point(20, publish=5)
    mutate(bad)
    with pytest.raises(ValueError, match=error):
        series([point(10, publish=4), bad])


def test_pool_trade_needs_signature_and_series_must_be_strictly_sorted():
    with pytest.raises(ValueError, match='sol_usd_point_signature'):
        series([point(10, block=4, kind='sol_usdc_pool_last_trade')])
    with pytest.raises(ValueError, match='not_strictly_sorted'):
        series([point(10, publish=4), point(10, publish=5)])
    with pytest.raises(ValueError, match='sol_usd_series_schema'):
        sus.series_from_document(dict(schema=sus.SERIES_SCHEMA, label='MARKET', points=[point(1, publish=1)]))


def test_as_of_rule_and_refusals():
    s = series([point(100, tx=0, publish=1_000), point(100, tx=5, publish=1_002), point(105, publish=1_010)])
    # Latest point at or before (slot, tx); never a later one.
    chosen, age, refusal = s.as_of(slot=100, transaction_index=3, decision_ms=1_000_400)
    assert (chosen['transaction_index'], age, refusal) == (0, 400, None)
    chosen, _age, _refusal = s.as_of(slot=104, transaction_index=0, decision_ms=1_003_000)
    assert chosen['transaction_index'] == 5
    assert s.as_of(slot=99, transaction_index=0, decision_ms=1_000_000)[2] == 'sol_usd_rate_unavailable'
    assert s.as_of(slot=104, transaction_index=0, decision_ms=1_002_000 + sus.MAX_AGE_MS + 1)[2] == 'sol_usd_stale'
    assert s.as_of(slot=104, transaction_index=0, decision_ms=1_002_000 + sus.MAX_AGE_MS)[2] is None
    assert s.as_of(slot=105, transaction_index=0, decision_ms=1_009_000)[2] == 'sol_usd_point_from_future'


def test_constant_series_reproduces_the_declared_rate_decisions():
    """A synthetic series fixed at 150 USD must give exactly the decisions of --sol-usd 150."""
    declared = hrr.run_replay(FIXTURES, hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED'))
    synthetic = hrr.run_replay(FIXTURES, hrr.ReplayParams(), fixture_series())
    assert synthetic['sol_usd_series']['label'] == 'SYNTHETIC_TEST_FIXTURE'
    assert synthetic['sol_usd_series']['verification'] == 'NOT_VERIFIED_IN_REPLAY'
    assert synthetic['flags']['sol_usd_verified'] is False
    assert synthetic['flags']['counted_in_master_gate'] is False
    assert synthetic['totals'] == declared['totals']
    rows = [row for pool in synthetic['pools'] for row in pool['journal']]
    assert rows and all(row['sol_usd_point']['age_ms'] == 400 for row in rows if 'sol_usd_point' in row)
    assert not any('sol_usd_rate_unavailable' in row['blocking_reasons'] for row in rows)


def test_gap_in_the_series_blocks_with_stale_or_unavailable():
    pool = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
    first_slot = min(json.loads(gzip.decompress((FIXTURES / f'{pool}.json.gz').read_bytes()))['transactions'][s]['slot']
                     for s in json.loads(gzip.decompress((FIXTURES / f'{pool}.json.gz').read_bytes()))['transactions'])
    gappy = fixture_series(skip=lambda p, slot: p == pool and slot > first_slot + 10)
    bundle = hrr.run_replay(FIXTURES, hrr.ReplayParams(), gappy)
    reasons = bundle['totals']['master']['blocking_reasons']
    assert reasons.get('sol_usd_stale', 0) > 0
    # Determinism, and the series digest is part of the bundle.
    again = hrr.run_replay(FIXTURES, hrr.ReplayParams(), copy.deepcopy(gappy))
    assert again['bundle_sha256'] == bundle['bundle_sha256']
    assert bundle['sol_usd_series']['sha256'] == gappy.sha256


def test_constant_and_series_are_exclusive_and_default_bundle_unchanged():
    with pytest.raises(ValueError, match='exclusive'):
        hrr.run_replay(FIXTURES, hrr.ReplayParams(sol_usd=150, sol_usd_provenance='X'), fixture_series())
    default = hrr.run_replay(FIXTURES)
    assert 'sol_usd_series' not in default and 'sol_usd_source' not in default['flags']
