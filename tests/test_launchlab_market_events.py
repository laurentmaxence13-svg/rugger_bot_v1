"""LaunchLab TradeEvent decoding, exact curve arithmetic and pool timelines.

Fixtures in tests/fixtures/launchlab_trades are unmodified public mainnet
``getTransaction`` results (signed, finalized) for pool 5BFfimP4...; no
network access happens in these tests.
"""
import copy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import random

import pytest

from bot.market.launchlab_curve import (
    CurveError, CurveState, buy_exact_in, fee_for, sell_exact_in,
)
from bot.market.launchlab_events import (
    EVENT_IX_TAG, LAUNCHLAB_PROGRAM, TRADE_EVENT_DISCRIMINATOR, EventDecodeError,
    TradeEvent, b58decode, b58encode, check_trade, decode_trade_payload,
    extract_trade_events,
)
from bot.market.pool_timeline import build_timeline

FIXTURES = Path(__file__).parent / 'fixtures' / 'launchlab_trades'
POOL = '5BFfimP4k3rZwTDFwP5koAM8UUW8iXKJUydFSLWbc4qU'
OBSERVED_TOTAL_FEE_PPM = 12_500   # 0.25 % protocol + 1 % platform


def _load(name_prefix):
    (path,) = FIXTURES.glob(f'{name_prefix}_*.json')
    return json.loads(path.read_text())


def _all_events():
    events = []
    for path in sorted(FIXTURES.glob('*.json')):
        events.extend(extract_trade_events(json.loads(path.read_text())))
    return events


# --- real signed mainnet data ------------------------------------------------

def test_discriminator_is_anchor_trade_event():
    assert TRADE_EVENT_DISCRIMINATOR.hex() == 'bddb7fd34ee661ee'


def test_every_real_fixture_decodes_one_exact_event():
    events = _all_events()
    assert len(events) == 7
    assert {e.pool for e in events} == {POOL}
    assert all(e.violations == () for e in events)
    assert sorted(e.side for e in events) == ['buy'] + ['sell'] * 6
    assert all(e.exact_in for e in events)


def test_real_buy_is_reproduced_by_independent_arithmetic():
    (event,) = extract_trade_events(_load('464541196'))
    assert event.side == 'buy' and event.amount_in == 23_903
    x = event.virtual_base - event.real_base_before
    y = event.virtual_quote + event.real_quote_before
    fee = -(-23_903 * OBSERVED_TOTAL_FEE_PPM // 1_000_000)
    net = 23_903 - fee
    assert fee == event.total_fee == 299
    assert net * x // (y + net) == event.amount_out == 2_522_387_521_678
    assert event.real_quote_after - event.real_quote_before == net


def test_real_sell_is_reproduced_by_independent_arithmetic():
    (event,) = extract_trade_events(_load('457008408'))   # jsonParsed encoding
    x = event.virtual_base - event.real_base_before
    y = event.virtual_quote + event.real_quote_before
    gross = event.amount_in * y // (x + event.amount_in)
    assert gross == 204_903
    assert -(-gross * OBSERVED_TOTAL_FEE_PPM // 1_000_000) == event.total_fee == 2_562
    assert gross - event.total_fee == event.amount_out == 202_341


def test_observed_fee_schedule_is_consistent_for_every_real_trade():
    for event in _all_events():
        assert fee_for(event.quote_volume, OBSERVED_TOTAL_FEE_PPM) == event.total_fee
        fill = (buy_exact_in if event.side == 'buy' else sell_exact_in)(
            event.state_before(), event.amount_in, OBSERVED_TOTAL_FEE_PPM)
        assert (fill.amount_out, fill.fee, fill.after) == (
            event.amount_out, event.total_fee, event.state_after())


def test_fee_payer_and_timestamps_come_from_the_signed_transaction():
    tx = _load('464541196')
    (event,) = extract_trade_events(tx)
    keys = tx['result']['transaction']['message']['accountKeys']
    assert event.fee_payer == keys[0]
    assert event.block_time == tx['result']['blockTime']
    assert event.signature == tx['result']['transaction']['signatures'][0]


# --- fail-closed behaviour ---------------------------------------------------

def test_failed_transaction_yields_no_event():
    tx = copy.deepcopy(_load('464541196'))
    tx['result']['meta']['err'] = {'InstructionError': [3, {'Custom': 6001}]}
    assert extract_trade_events(tx) == []


def test_missing_inner_instructions_is_refused_not_treated_as_empty():
    tx = copy.deepcopy(_load('464541196'))
    tx['result']['meta']['innerInstructions'] = None
    with pytest.raises(EventDecodeError):
        extract_trade_events(tx)


def _event_ix(tx):
    for group in tx['result']['meta']['innerInstructions']:
        for ix in group['instructions']:
            if b58decode(ix['data']).startswith(EVENT_IX_TAG + TRADE_EVENT_DISCRIMINATOR):
                return ix
    raise AssertionError('no event instruction')


def test_event_emitted_by_another_program_is_ignored():
    tx = copy.deepcopy(_load('464541196'))
    keys = tx['result']['transaction']['message']['accountKeys']
    other = next(i for i, k in enumerate(keys) if k != LAUNCHLAB_PROGRAM and i > 0)
    _event_ix(tx)['programIdIndex'] = other
    assert extract_trade_events(tx) == []


def test_tampered_amount_is_flagged_and_rejected_by_timeline():
    tx = copy.deepcopy(_load('464541196'))
    ix = _event_ix(tx)
    raw = bytearray(b58decode(ix['data']))
    offset = len(EVENT_IX_TAG) + 40 + 8 * 8          # amount_out
    value = int.from_bytes(raw[offset:offset + 8], 'little') + 1
    raw[offset:offset + 8] = value.to_bytes(8, 'little')
    ix['data'] = b58encode(bytes(raw))
    (event,) = extract_trade_events(tx)
    assert 'buy_base_delta_mismatch' in event.violations
    timeline = build_timeline(POOL, [event])
    assert timeline.events == () and timeline.rejected and not timeline.complete


def test_wrong_size_or_discriminator_is_not_a_trade_event():
    payload = TRADE_EVENT_DISCRIMINATOR + bytes(139)
    assert decode_trade_payload(payload)['side'] == 'buy'
    with pytest.raises(EventDecodeError):
        decode_trade_payload(payload[:-1])
    with pytest.raises(EventDecodeError):
        decode_trade_payload(bytes(8) + payload[8:])
    with pytest.raises(EventDecodeError):
        decode_trade_payload(payload[:144] + b'\x02\x00\x01')


def test_constant_product_decrease_is_a_violation():
    (event,) = extract_trade_events(_load('464541196'))
    values = {k: getattr(event, k) for k in (
        'total_base_sell', 'virtual_base', 'virtual_quote', 'real_base_before',
        'real_quote_before', 'real_base_after', 'real_quote_after', 'amount_in',
        'amount_out', 'protocol_fee', 'platform_fee', 'creator_fee', 'share_fee',
        'side', 'exact_in')}
    values.update(amount_in=values['amount_in'] - 10, platform_fee=values['platform_fee'] - 10)
    values.update(real_quote_after=values['real_quote_before'] + values['amount_in']
                  - values['protocol_fee'] - values['platform_fee'])
    values.update(real_quote_after=values['real_quote_after'] - 5_000)
    assert check_trade(values)


# --- curve arithmetic --------------------------------------------------------

FRESH = CurveState(virtual_base=1_073_025_605_596_382, virtual_quote=30_000_852_951,
                   real_base=0, real_quote=0, total_base_sell=793_100_000_000_000)


def test_buy_matches_rational_model_floor():
    fill = buy_exact_in(FRESH, 1_000_000_000, OBSERVED_TOTAL_FEE_PPM)
    net = 1_000_000_000 - fill.fee
    exact = Fraction(net * FRESH.base_reserve, FRESH.quote_reserve + net)
    assert fill.amount_out == int(exact)
    assert fill.after.base_reserve * fill.after.quote_reserve >= (
        FRESH.base_reserve * FRESH.quote_reserve)


def test_immediate_round_trip_loses_at_least_both_fees():
    spend = 500_000_000
    buy = buy_exact_in(FRESH, spend, OBSERVED_TOTAL_FEE_PPM)
    sell = sell_exact_in(buy.after, buy.amount_out, OBSERVED_TOTAL_FEE_PPM)
    assert sell.amount_out < spend
    assert spend - sell.amount_out >= buy.fee + sell.fee
    assert sell.after.real_base == 0


def test_curve_refuses_unmodelled_or_impossible_trades():
    with pytest.raises(CurveError):
        buy_exact_in(FRESH, 10**15, OBSERVED_TOTAL_FEE_PPM)       # crosses migration
    with pytest.raises(CurveError):
        sell_exact_in(FRESH, 1, OBSERVED_TOTAL_FEE_PPM)           # nothing sold yet
    with pytest.raises(CurveError):
        buy_exact_in(FRESH, 1, OBSERVED_TOTAL_FEE_PPM)            # consumed by fee
    with pytest.raises(CurveError):
        fee_for(10, 1_000_000)


# --- timelines ---------------------------------------------------------------

def _synthetic_chain(n=12, seed=7):
    rng = random.Random(seed)
    state, events = FRESH, []
    for i in range(n):
        if state.real_base and rng.random() < 0.4:
            fill = sell_exact_in(state, max(1, state.real_base // rng.randint(2, 6)),
                                 OBSERVED_TOTAL_FEE_PPM)
        else:
            fill = buy_exact_in(state, rng.randint(10**7, 2 * 10**9), OBSERVED_TOTAL_FEE_PPM)
        events.append(_event_from_fill(fill, slot=100 + i // 4, sig=f'sig{i:02d}'))
        state = fill.after
    return events


def _event_from_fill(fill, *, slot, sig, pool=POOL):
    values = dict(
        signature=sig, slot=slot, block_time=None, event_index=0, fee_payer='payer',
        pool=pool, side=fill.side, exact_in=True, pool_status=0,
        total_base_sell=fill.before.total_base_sell, virtual_base=fill.before.virtual_base,
        virtual_quote=fill.before.virtual_quote,
        real_base_before=fill.before.real_base, real_quote_before=fill.before.real_quote,
        real_base_after=fill.after.real_base, real_quote_after=fill.after.real_quote,
        amount_in=fill.amount_in, amount_out=fill.amount_out,
        protocol_fee=fill.fee, platform_fee=0, creator_fee=0, share_fee=0)
    return TradeEvent(violations=check_trade(values), **values)


def test_synthetic_events_pass_the_same_exactness_checks():
    assert all(e.violations == () for e in _synthetic_chain())


def test_timeline_recovers_intra_slot_order_from_reserve_chain():
    chain = _synthetic_chain()
    shuffled = list(chain)
    random.Random(3).shuffle(shuffled)
    # Signatures carry no ordering information inside a slot.
    shuffled = [replace(e, signature=f'z{hash(e.signature) % 10**6:06d}{e.signature}')
                for e in shuffled]
    timeline = build_timeline(POOL, shuffled + shuffled[:3])          # with duplicates
    assert timeline.complete
    assert [e.real_base_before for e in timeline.events] == [e.real_base_before for e in chain]
    assert timeline.complete_from(0)


def test_missing_trade_is_reported_as_gap():
    chain = _synthetic_chain()
    timeline = build_timeline(POOL, chain[:5] + chain[6:])
    assert len(timeline.gaps) == 1
    gap = timeline.gaps[0]
    assert gap.reason == 'reserve_chain_break' and gap.before_key == chain[6].key
    assert timeline.complete_from(len(chain) - 2) and not timeline.complete_from(0)


def test_history_not_starting_at_launch_is_reported():
    chain = _synthetic_chain()
    timeline = build_timeline(POOL, chain[3:])
    assert [g.reason for g in timeline.gaps] == ['history_starts_mid_curve']
    assert timeline.complete_from(0)


def test_other_pool_events_are_rejected():
    chain = _synthetic_chain(4)
    foreign = replace(chain[0], pool='11111111111111111111111111111111', signature='f')
    timeline = build_timeline(POOL, chain + [foreign])
    assert ('f', 0) in dict(timeline.rejected)
    assert len(timeline.events) == 4


def test_real_fixture_timeline_marks_unobserved_intervals():
    timeline = build_timeline(POOL, _all_events())
    assert len(timeline.events) == 7 and not timeline.rejected
    assert [e.slot for e in timeline.events] == sorted(e.slot for e in timeline.events)
    # The seven fixtures are a sample, not the full history: gaps must show it.
    assert timeline.gaps and timeline.gaps[0].reason == 'history_starts_mid_curve'


def test_inconsistent_curve_state_is_a_violation_not_a_crash():
    (event,) = extract_trade_events(_load('464541196'))
    values = {k: getattr(event, k) for k in (
        'total_base_sell', 'virtual_base', 'virtual_quote', 'real_base_before',
        'real_quote_before', 'real_base_after', 'real_quote_after', 'amount_in',
        'amount_out', 'protocol_fee', 'platform_fee', 'creator_fee', 'share_fee',
        'side', 'exact_in')}
    assert check_trade(values) == ()
    values['total_base_sell'] = values['real_base_before'] - 1
    assert check_trade(values) == ('curve_refused:invalid_curve_state',)
