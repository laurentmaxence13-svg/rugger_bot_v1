"""W1 protocol R7 (option B'): offline decoder of Pyth push-oracle updates, on two real P0 transactions."""
import hashlib
import json
from pathlib import Path

import pytest

from bot.market import pyth_push as pp
from bot.p4 import sol_usd_series as sus

FIX = Path(__file__).parent / 'fixtures' / 'pyth_push'
A = FIX / 'pyth_push_466226774_5KohzTfi.json'
B = FIX / 'pyth_push_466227015_3niXUBPi.json'


def _entry(path):
    return json.loads(path.read_text())


def test_fixtures_are_the_archived_p0_entries():
    assert hashlib.sha256(A.read_bytes()).hexdigest() == 'b133ecc1e9029503ff0f95243fd8c82a18bf77864ae14865a43062216f0ad84a'
    assert hashlib.sha256(B.read_bytes()).hexdigest() == 'ebdede5af90d7696c6a55487901b3e57a6d5267cfc867154f575b9db0a367e75'


def test_sol_usd_updates_decode_as_read_by_rugger_03():
    (a,) = pp.updates(_entry(A))
    (b,) = pp.updates(_entry(B))
    assert (a['price'], a['conf'], a['exponent'], a['publish_time'], a['prev_publish_time']) == (
        9004008179, 5278626, -8, 1793993267, 1793993266)
    assert (b['price'], b['conf'], b['exponent'], b['publish_time'], b['prev_publish_time']) == (
        8994092915, 5246920, -8, 1793993318, 1793993317)
    assert a['feed_id'] == b['feed_id'] == pp.SOL_USD_FEED_ID and a['shard_id'] == 0 and a['proof_nodes'] == 12
    assert _entry(A)['blockTime'] - a['publish_time'] == 1 and _entry(B)['blockTime'] - b['publish_time'] == 1


def test_seven_feeds_per_push_and_every_one_parses():
    for path in (A, B):
        entry = _entry(path)
        keys = pp.account_keys(entry)
        pushes = [ix for ix in pp._instructions(entry) if keys[ix['programIdIndex']] == pp.PUSH_ORACLE_PROGRAM]
        decoded = [pp.decode_update(pp.b58decode(ix['data'])) for ix in pushes]
        assert len(decoded) == 7 and len({d['feed_id'] for d in decoded}) == 7


def test_points_feed_the_replay_series_and_its_causal_lookup():
    points = pp.sol_usd_points([_entry(B), _entry(A)])
    assert [p['slot'] for p in points] == [466226774, 466227015]
    assert points[0]['evidence_sha256'] == pp.evidence_sha256(_entry(A))
    series = sus.series_from_document(dict(schema=sus.SERIES_SCHEMA, label='SYNTHETIC_TEST_FIXTURE', points=points))
    assert series.ordering == 'chain_position'
    # One slot after A, 1 s after its block: the point is available, age = 2 s from publish_time.
    point, age, refusal = series.as_of(slot=466226775, transaction_index=0, decision_ms=1793993269_000)
    assert refusal is None and point['slot'] == 466226774 and age == 2_000
    # 50 s later, before B: the current 5 s rule refuses the stale point (why R7 needs a measured threshold).
    assert series.as_of(slot=466227000, transaction_index=0, decision_ms=1793993317_000)[2] == 'sol_usd_stale'
    # Same slot as A, earlier transaction: not positioned yet (no look-ahead).
    assert series.as_of(slot=466226774, transaction_index=264, decision_ms=1793993269_000)[2] == 'sol_usd_rate_unavailable'


def test_failed_transactions_and_other_feeds_give_nothing():
    failed = _entry(A)
    failed['meta']['err'] = {'InstructionError': [3, 'Custom']}
    assert pp.updates(failed) == []
    assert pp.updates(_entry(A), feed_id='00' * 32) == []


def test_malformed_updates_are_refused():
    entry = _entry(A)
    keys = pp.account_keys(entry)
    ix = next(ix for ix in pp._instructions(entry) if keys[ix['programIdIndex']] == pp.PUSH_ORACLE_PROGRAM
              and pp.decode_update(pp.b58decode(ix['data']))['feed_id'] == pp.SOL_USD_FEED_ID)
    data = pp.b58decode(ix['data'])
    with pytest.raises(pp.PythPushError, match='not_update_price_feed'):
        pp.decode_update(b'\0' * 8 + data[8:])
    with pytest.raises(pp.PythPushError, match='unexpected_instruction_length'):
        pp.decode_update(data + b'\0')
    with pytest.raises(pp.PythPushError, match='feed_id_mismatch'):
        pp.decode_update(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(pp.PythPushError, match='feed_written_to_another_account'):
        pp.updates(entry, price_account='So11111111111111111111111111111111111111112')
    moved = _entry(B)
    moved['slot'] = 466226000                                   # B placed before A: A is then older than B
    decoded = pp.decode_entries([_entry(A), moved])
    assert decoded['not_newer'] == 1 and decoded['updates'] == 2       # A ignored and counted (R02 D-4)
    assert [p['publish_time'] for p in decoded['points']] == [1793993318]
    same = pp.decode_entries([_entry(A), dict(_entry(A), slot=466226900, transactionIndex=1)])
    assert same['not_newer'] == 1 and len(same['points']) == 1          # equal publish_time: not newer
    with pytest.raises(pp.PythPushError, match='chain_position_required'):
        pp.sol_usd_points([dict(_entry(A), transactionIndex=None)])


def _series(acceptance=None, label='SYNTHETIC_TEST_FIXTURE'):
    doc = dict(schema=sus.SERIES_SCHEMA, label=label, points=pp.sol_usd_points([_entry(A), _entry(B)]))
    if acceptance is not None:
        doc['acceptance'] = acceptance
    return sus.series_from_document(doc), doc


def test_acceptance_rule_is_part_of_the_series_and_its_hash():
    plain, doc = _series()
    assert (plain.max_age_ms, plain.max_confidence_ppm) == (sus.MAX_AGE_MS, None)
    legacy = sus.series_from_document(json.loads(json.dumps(doc)))
    assert legacy.sha256 == plain.sha256                                  # no acceptance: unchanged
    wide, _ = _series(dict(max_age_ms=75_000, max_confidence_ppm=1_000))
    assert wide.sha256 != plain.sha256 and (wide.max_age_ms, wide.max_confidence_ppm) == (75_000, 1_000)
    point, age, refusal = wide.as_of(slot=466227000, transaction_index=0, decision_ms=1793993317_000)
    assert refusal is None and point['slot'] == 466226774 and age == 50_000          # 50 s old, accepted
    assert wide.as_of(slot=466227000, transaction_index=0, decision_ms=1793993342_001)[2] == 'sol_usd_stale'
    # conf/price of A = 5278626 / 9004008179 = 586 ppm: refused under 500 ppm, accepted at 586.
    tight, _ = _series(dict(max_age_ms=75_000, max_confidence_ppm=500))
    assert tight.as_of(slot=466227000, transaction_index=0, decision_ms=1793993317_000)[2] == 'sol_usd_confidence_too_wide'
    edge, _ = _series(dict(max_age_ms=75_000, max_confidence_ppm=587))
    assert edge.as_of(slot=466227000, transaction_index=0, decision_ms=1793993317_000)[2] is None
    for bad in (dict(max_age_ms=999, max_confidence_ppm=None), dict(max_age_ms=120_001, max_confidence_ppm=None),
                dict(max_age_ms=60_000, max_confidence_ppm=0), dict(max_age_ms=60_000), dict(max_age_ms=60_000.0, max_confidence_ppm=None),
                dict(max_age_ms=60_000, max_confidence_ppm=None, extra=1)):
        with pytest.raises(ValueError, match='sol_usd_series_acceptance'):
            _series(bad)


def test_confidence_unknown_is_refused_under_a_confidence_rule():
    doc = dict(schema=sus.SERIES_SCHEMA, label='SYNTHETIC_TEST_FIXTURE',
               points=[dict(p, confidence=None) for p in pp.sol_usd_points([_entry(A)])],
               acceptance=dict(max_age_ms=75_000, max_confidence_ppm=1_000))
    series = sus.series_from_document(doc)
    assert series.as_of(slot=466227000, transaction_index=0, decision_ms=1793993300_000)[2] == 'sol_usd_confidence_unknown'


def test_confidence_at_exactly_the_limit_is_accepted():
    point = dict(pp.sol_usd_points([_entry(A)])[0], price=1_000_000, confidence=586, exponent=-4)
    doc = dict(schema=sus.SERIES_SCHEMA, label='SYNTHETIC_TEST_FIXTURE', points=[point],
               acceptance=dict(max_age_ms=75_000, max_confidence_ppm=586))
    at = dict(slot=466227000, transaction_index=0, decision_ms=1793993300_000)
    assert sus.series_from_document(doc).as_of(**at)[2] is None                      # 586 ppm == limit
    doc['acceptance']['max_confidence_ppm'] = 585
    assert sus.series_from_document(doc).as_of(**at)[2] == 'sol_usd_confidence_too_wide'


def _push_ix(entry):
    keys = pp.account_keys(entry)
    return next(ix for ix in pp._instructions(entry) if keys[ix['programIdIndex']] == pp.PUSH_ORACLE_PROGRAM
                and pp.decode_update(pp.b58decode(ix['data']))['feed_id'] == pp.SOL_USD_FEED_ID)


def _with_data(entry, transform):
    """Copy of ``entry`` whose SOL/USD UpdatePriceFeed data goes through ``transform``."""
    import copy
    entry = copy.deepcopy(entry)
    ix = _push_ix(entry)
    from bot.market.launchlab_events import b58encode
    ix['data'] = b58encode(transform(pp.b58decode(ix['data'])))
    return entry


def test_r02_survivors_shard_price_several_updates_inner_and_duplicates():
    import struct
    # shard id (u16 LE just before the 32-byte feed id at the end of the data) must be 0.
    shard = _with_data(_entry(A), lambda d: d[:-34] + struct.pack('<H', 1) + d[-32:])
    with pytest.raises(pp.PythPushError, match='unexpected_shard'):
        pp.updates(shard)
    # price <= 0: message starts after 8 + 4 bytes; price is i64 BE at message offset 33.
    def zero_price(d):
        at = 12 + 33
        return d[:at] + struct.pack('>q', 0) + d[at + 8:]
    with pytest.raises(pp.PythPushError, match='non_positive_price'):
        pp.sol_usd_points([_with_data(_entry(A), zero_price)])
    # two SOL/USD updates in one transaction are refused.
    import copy
    double = copy.deepcopy(_entry(A))
    double['transaction']['message']['instructions'].append(copy.deepcopy(_push_ix(double)))
    with pytest.raises(pp.PythPushError, match='several_updates_of_one_feed_in_one_transaction'):
        pp.updates(double)
    # an update made through a CPI (inner instruction) counts like a top-level one.
    inner = copy.deepcopy(_entry(A))
    ix = _push_ix(inner)
    inner['transaction']['message']['instructions'].remove(ix)
    inner['meta']['innerInstructions'] = [{'index': 0, 'instructions': [ix]}]
    assert [u['price'] for u in pp.updates(inner)] == [9004008179]
    # the same chain position twice is refused.
    with pytest.raises(pp.PythPushError, match='duplicate_chain_position'):
        pp.sol_usd_points([_entry(A), _entry(A)])
