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
                evidence_sha256=hashlib.sha256(f'synthetic:{slot}:{tx}:{publish}'.encode()).hexdigest(),
                signature=signature)


def hermes(publish, *, received=None, price=150_00000000):
    return point(None, tx=None, publish=publish, received=received, price=price, kind=sus.HERMES)


def series(points, label='SYNTHETIC_TEST_FIXTURE'):
    return sus.series_from_document(dict(schema=sus.SERIES_SCHEMA, label=label, points=points))


def fixture_transactions():
    for path in sorted(FIXTURES.glob('*.json.gz')):
        archive = json.loads(gzip.decompress(path.read_bytes()))
        for tx in archive['transactions'].values():
            yield archive['pool'], tx['slot'], tx.get('transactionIndex') or 0, tx['blockTime']


def fixture_series(skip=lambda pool, slot: False, *, publish_offset=-1, block=False):
    """One synthetic point per stored fixture transaction key.

    ``publish_offset=-1`` stamps it in the second BEFORE the transaction, so it is
    provably available at that transaction's decision (D = block_time*1000 + 400).
    """
    rows = {}
    for pool, slot, index, block_time in fixture_transactions():
        if not skip(pool, slot):
            rows[(slot, index)] = point(slot, tx=index, publish=block_time + publish_offset,
                                        block=block_time if block else None)
    return series([rows[key] for key in sorted(rows)])


def journal(bundle):
    return [row for pool in bundle['pools'] for row in pool['journal']]


def test_availability_and_observation_clocks():
    p = point(10, publish=1_000, received=1_000_500)
    assert sus.price_usd(p) == 150
    # No-future check: END of the second (or a later receipt); staleness: START of the oldest clock.
    assert sus.available_ms(p) == 1_000_999 and sus.observed_ms(p) == 1_000_000
    assert sus.available_ms(point(10, publish=1_000, received=1_002_000)) == 1_002_000
    trade = point(11, block=2_000, kind='sol_usdc_pool_last_trade', signature='SYNTHETIC-SIG')
    assert (sus.available_ms(trade), sus.observed_ms(trade)) == (2_000_999, 2_000_000)
    onchain = point(12, publish=1_998, block=2_000)
    assert (sus.available_ms(onchain), sus.observed_ms(onchain)) == (2_000_999, 1_998_000)


@pytest.mark.parametrize('mutate, error', [
    (lambda p: p.update(price=0), 'sol_usd_point_values'),
    (lambda p: p.update(slot=None), 'sol_usd_point_values'),
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


@pytest.mark.parametrize('field, value', [('slot', 300_000_000), ('transaction_index', 0), ('block_time', 1_000)])
def test_hermes_point_carries_no_solana_position(field, value):
    """B2: a Hermes update has a Pythnet slot, not a Solana one; it is ordered by publish_time only."""
    bad = hermes(1_000)
    bad[field] = value
    with pytest.raises(ValueError, match='sol_usd_point_hermes_has_no_solana_position'):
        series([bad])


def test_sorting_and_ordering_domains():
    with pytest.raises(ValueError, match='sol_usd_point_signature'):
        series([point(10, block=4, kind='sol_usdc_pool_last_trade')])
    with pytest.raises(ValueError, match='not_strictly_sorted'):
        series([point(10, publish=4), point(10, publish=5)])
    with pytest.raises(ValueError, match='not_strictly_sorted'):
        series([point(10, tx=None, publish=4), point(10, tx=0, publish=5)])
    with pytest.raises(ValueError, match='sol_usd_series_schema'):
        sus.series_from_document(dict(schema=sus.SERIES_SCHEMA, label='MARKET', points=[point(1, publish=1)]))
    with pytest.raises(ValueError, match='mixes_chain_and_hermes'):
        series([point(10, publish=4), hermes(5)])
    with pytest.raises(ValueError, match='not_strictly_sorted'):
        series([hermes(5), hermes(5)])
    assert series([point(10, publish=4)]).ordering == 'chain_position'
    assert series([hermes(4), hermes(5)]).ordering == 'publish_time'


def test_as_of_rule_and_refusals():
    s = series([point(100, tx=0, publish=999), point(100, tx=5, publish=1_000), point(105, publish=1_010)])
    # Latest positioned point that is provably available; never a later one.
    chosen, age, refusal = s.as_of(slot=100, transaction_index=3, decision_ms=1_000_400)
    assert (chosen['transaction_index'], age, refusal) == (0, 1_400, None)
    chosen, age, _refusal = s.as_of(slot=104, transaction_index=0, decision_ms=1_001_000)
    assert (chosen['transaction_index'], age) == (5, 1_000)
    # Same point, but D falls inside its publish second: fall back to the earlier point.
    chosen, age, _refusal = s.as_of(slot=104, transaction_index=0, decision_ms=1_000_500)
    assert (chosen['transaction_index'], age) == (0, 1_500)
    assert s.as_of(slot=99, transaction_index=0, decision_ms=1_000_000)[2] == 'sol_usd_rate_unavailable'
    assert s.as_of(slot=104, transaction_index=0, decision_ms=1_000_000 + sus.MAX_AGE_MS + 1)[2] == 'sol_usd_stale'
    assert s.as_of(slot=104, transaction_index=0, decision_ms=1_000_000 + sus.MAX_AGE_MS)[2] is None
    assert series([point(100, publish=1_000)]).as_of(
        slot=100, transaction_index=0, decision_ms=1_000_400)[2] == 'sol_usd_point_from_future'
    with pytest.raises(ValueError, match='sol_usd_as_of_arguments'):
        s.as_of(slot=104, transaction_index=None, decision_ms=1_001_000)


def test_b1_null_transaction_index_is_never_placed_inside_the_decision_slot():
    """R02 B1 case A: decision slot 100 index 5; a same-slot point with index null is refused."""
    assert series([point(100, tx=None, publish=999)]).as_of(
        slot=100, transaction_index=5, decision_ms=1_000_400)[2] == 'sol_usd_rate_unavailable'
    s = series([point(99, tx=None, publish=998), point(100, tx=None, publish=999, price=1)])
    chosen, age, refusal = s.as_of(slot=100, transaction_index=5, decision_ms=1_000_400)
    assert (chosen['slot'], age, refusal) == (99, 2_400, None)
    chosen, _age, _refusal = s.as_of(slot=101, transaction_index=0, decision_ms=1_000_400)
    assert chosen['slot'] == 100           # a strictly earlier slot is safe


def test_b1_second_resolution_clock_counts_from_the_end_of_its_second():
    """R02 B1 case B: a point stamped in the decision second may be up to 599 ms after D."""
    decision = dict(slot=101, transaction_index=0, decision_ms=1_000_400)
    assert series([hermes(1_000)]).as_of(**decision)[2] == 'sol_usd_point_from_future'
    chosen, age, _refusal = series([hermes(999)]).as_of(**decision)
    assert (chosen['publish_time'], age) == (999, 1_400)
    # On chain: an older publish_time does not help if the block (or the receipt) is in the decision second.
    assert series([point(100, publish=998, block=1_000)]).as_of(**decision)[2] == 'sol_usd_point_from_future'
    assert series([point(100, publish=998, received=1_000_500)]).as_of(**decision)[2] == 'sol_usd_point_from_future'
    chosen, age, _refusal = series([point(100, publish=998, received=1_000_300)]).as_of(**decision)
    assert age == 2_400                     # staleness from the START of the oldest clock


def test_b2_hermes_series_is_ordered_by_publish_time_only():
    s = series([hermes(990), hermes(995), hermes(999), hermes(1_000), hermes(1_001)])
    for slot in (1, 300_000_000, 10 ** 12):  # the decision slot plays no part
        chosen, age, refusal = s.as_of(slot=slot, transaction_index=0, decision_ms=1_000_400)
        assert (chosen['publish_time'], age, refusal) == (999, 1_400, None)
    assert s.as_of(slot=1, transaction_index=0, decision_ms=989_999)[2] == 'sol_usd_rate_unavailable'
    assert s.as_of(slot=1, transaction_index=0, decision_ms=990_500)[2] == 'sol_usd_point_from_future'


def test_points_published_after_the_decision_never_change_the_answer():
    """Poisoning every point whose clock may lie after D (or whose position is later) changes nothing."""
    base = [point(100, tx=0, publish=999), point(101, tx=None, publish=1_000),
            point(101, tx=2, publish=1_000, block=1_001),
            point(102, tx=1, publish=1_001), point(103, tx=0, publish=1_002, received=1_003_100)]
    poison = 10 ** 15
    for slot in range(99, 105):
        for index in (0, 1, 3):
            for decision_ms in range(999_000, 1_006_000, 100):
                expected = series(base).as_of(slot=slot, transaction_index=index, decision_ms=decision_ms)
                poisoned = [dict(p, price=poison) if (
                    sus.available_ms(p) > decision_ms or (p['slot'], p['transaction_index'] or 0) > (slot, index)
                    or (p['transaction_index'] is None and p['slot'] >= slot)) else p for p in base]
                got = series(poisoned).as_of(slot=slot, transaction_index=index, decision_ms=decision_ms)
                assert got[1:] == expected[1:]
                assert got[0] is None or got[0]['price'] != poison


def test_constant_series_reproduces_the_declared_rate_decisions():
    """A synthetic series fixed at 150 USD must give exactly the decisions of --sol-usd 150."""
    declared = hrr.run_replay(FIXTURES, hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED'))
    synthetic = hrr.run_replay(FIXTURES, hrr.ReplayParams(), fixture_series())
    assert synthetic['sol_usd_series']['label'] == 'SYNTHETIC_TEST_FIXTURE'
    assert synthetic['sol_usd_series']['ordering'] == 'chain_position'
    assert synthetic['sol_usd_series']['verification'] == 'NOT_VERIFIED_IN_REPLAY'
    assert synthetic['flags']['sol_usd_verified'] is False
    assert synthetic['flags']['counted_in_master_gate'] is False
    assert synthetic['totals'] == declared['totals']
    rows = journal(synthetic)
    used = [row for row in rows if 'sol_usd_point' in row]
    assert used and all(row['sol_usd_point']['age_ms'] == 1_400 for row in used)
    assert all(row['sol_usd_point']['available_ms'] <= row['modelled_receipt_ms'] for row in used)
    assert not any('sol_usd_rate_unavailable' in row['blocking_reasons'] for row in rows)


def test_hermes_series_in_the_replay_matches_the_declared_rate():
    seconds = sorted({block_time - 1 for _pool, _slot, _index, block_time in fixture_transactions()})
    declared = hrr.run_replay(FIXTURES, hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED'))
    bundle = hrr.run_replay(FIXTURES, hrr.ReplayParams(), series([hermes(t) for t in seconds]))
    assert bundle['sol_usd_series']['ordering'] == 'publish_time'
    assert bundle['totals'] == declared['totals']


def test_replay_never_uses_a_point_from_the_decision_second():
    """Old fixture series (stamped in each transaction's own second): every such point is refused."""
    bundle = hrr.run_replay(FIXTURES, hrr.ReplayParams(), fixture_series(publish_offset=0, block=True))
    rows = journal(bundle)
    used = [row for row in rows if 'sol_usd_point' in row]
    assert used
    for row in used:
        p = row['sol_usd_point']
        assert p['available_ms'] <= row['modelled_receipt_ms']
        assert p['age_ms'] >= 1_400
        assert (p['slot'], p['transaction_index']) < (row['slot'], row['transaction_index'])
    reasons = bundle['totals']['master']['blocking_reasons']
    assert reasons.get('sol_usd_point_from_future', 0) + reasons.get('sol_usd_stale', 0) > 0


def test_replay_null_index_points_only_from_earlier_slots():
    rows = {}
    for _pool, slot, _index, block_time in fixture_transactions():
        rows[slot] = point(slot, tx=None, publish=block_time - 1)
    bundle = hrr.run_replay(FIXTURES, hrr.ReplayParams(), series([rows[slot] for slot in sorted(rows)]))
    used = [row for row in journal(bundle) if 'sol_usd_point' in row]
    assert used and all(row['sol_usd_point']['slot'] < row['slot'] for row in used)


def test_gap_in_the_series_blocks_with_stale_or_unavailable():
    pool = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
    first_slot = min(slot for p, slot, _index, _time in fixture_transactions() if p == pool)
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
