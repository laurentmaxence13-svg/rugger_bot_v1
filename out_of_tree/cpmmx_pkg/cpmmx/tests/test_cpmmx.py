"""cpmmx: exact arithmetic, event decoding, pool timeline. Synthetic data only (no mainnet swap yet)."""
import base64
import random
import struct

import pytest

from cpmmx import curve, events, timeline

POOL = bytes(range(1, 33))
BASE = bytes(range(33, 65))
QUOTE_B58 = timeline.WSOL
OTHER = '11111111111111111111111111111111'
D = curve.FEE_DENOMINATOR


def b58decode(text):
    number = 0
    for char in text:
        number = number * 58 + events._ALPHABET.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, 'big')
    return b'\0' * (len(text) - len(text.lstrip('1'))) + raw


QUOTE = b58decode(QUOTE_B58).rjust(32, b'\0')
POOL_B58, BASE_B58 = events.b58encode(POOL), events.b58encode(BASE)


def swap_payload(in_before, out_before, amount_in, amount_out, base_input, mint_in, mint_out, trade_fee, creator_fee,
                 on_input, *, pool=POOL, legacy=False):
    head = events.SWAP_DISCRIMINATOR + struct.pack('<32s6Q?', pool, in_before, out_before, amount_in, amount_out,
                                                   0, 0, base_input)
    if legacy:
        return head
    return head + struct.pack('<32s32s2Q?', mint_in, mint_out, trade_fee, creator_fee, on_input)


def logs(*payloads, program=events.CPMM_PROGRAM, outer=None):
    lines = []
    if outer:
        lines.append(f'Program {outer} invoke [1]')
    depth = 2 if outer else 1
    lines.append(f'Program {program} invoke [{depth}]')
    lines.append('Program log: Instruction: SwapBaseInput')
    for payload in payloads:
        lines.append('Program data: ' + base64.b64encode(payload).decode())
    lines.append(f'Program {program} consumed 1 of 2 compute units')
    lines.append(f'Program {program} success')
    if outer:
        lines.append(f'Program {outer} success')
    return lines


def tx(slot, index, lines, *, err=None, when=None):
    return dict(slot=slot, transactionIndex=index, blockTime=1_700_000_000 + slot if when is None else when,
                meta=dict(err=err, logMessages=lines))


class Sim:
    """An independent pool: applies the program's rules and logs what the program would log."""

    def __init__(self, base, quote, fees, on_input):
        self.base, self.quote, self.fees, self.on_input = base, quote, fees, on_input

    def swap(self, side, amount, *, exact_in=True):
        x, y = (self.quote, self.base) if side == 'buy' else (self.base, self.quote)
        got = (curve.swap_base_input if exact_in else curve.swap_base_output)(amount, x, y, self.fees, self.on_input)
        mints = (QUOTE, BASE) if side == 'buy' else (BASE, QUOTE)
        payload = swap_payload(x, y, got.input_amount, got.output_amount, exact_in, *mints, got.trade_fee,
                               got.creator_fee, self.on_input)
        new_x, new_y = curve.reserves_after(x, y, got)
        self.quote, self.base = (new_x, new_y) if side == 'buy' else (new_y, new_x)
        return payload, got


# ---------------------------------------------------------------- arithmetic

def test_base_input_matches_a_hand_computed_swap():
    fees = curve.Fees(2500, 0, 120_000, 40_000)
    got = curve.swap_base_input(1_000_000, 50_000_000, 80_000_000, fees, True)
    assert got.trade_fee == 2500 and got.creator_fee == 0
    assert got.output_amount == 997_500 * 80_000_000 // (50_000_000 + 997_500) == 1_564_782
    assert (got.protocol_fee, got.fund_fee) == (300, 100)
    assert curve.reserves_after(50_000_000, 80_000_000, got) == (50_000_000 + 1_000_000 - 400, 80_000_000 - 1_564_782)


def test_fees_round_up_against_the_trader():
    got = curve.swap_base_input(1001, 10**9, 10**9, curve.Fees(2500), True)
    assert got.trade_fee == 3                      # ceil(1001 * 2500 / 1e6) = ceil(2.5025)


def test_creator_fee_on_input_splits_one_combined_fee():
    fees = curve.Fees(2500, 1000)
    got = curve.swap_base_input(10_000_001, 10**10, 10**10, fees, True)
    total = -(-10_000_001 * 3500 // D)
    assert got.creator_fee == total * 1000 // 3500 and got.trade_fee == total - got.creator_fee
    less = 10_000_001 - total
    assert got.output_amount == less * 10**10 // (10**10 + less)


def test_creator_fee_on_output_is_taken_from_what_the_curve_gives():
    fees = curve.Fees(2500, 1000)
    got = curve.swap_base_input(10_000_001, 10**10, 10**10, fees, False)
    trade = -(-10_000_001 * 2500 // D)
    swapped = (10_000_001 - trade) * 10**10 // (10**10 + 10_000_001 - trade)
    creator = -(-swapped * 1000 // D)
    assert (got.trade_fee, got.creator_fee, got.output_amount) == (trade, creator, swapped - creator)
    new_in, new_out = curve.reserves_after(10**10, 10**10, got)
    assert new_out == 10**10 - swapped             # the creator fee leaves the reserve too


@pytest.mark.parametrize('on_input', [True, False])
def test_the_invariant_never_decreases(on_input):
    rng = random.Random(7)
    for _ in range(2000):
        x, y = rng.randrange(10**6, 10**13), rng.randrange(10**6, 10**15)
        fees = curve.Fees(rng.choice([0, 100, 2500, 10_000, 40_000]), rng.choice([0, 500, 1000]),
                          rng.choice([0, 120_000]), rng.choice([0, 40_000]))
        amount = rng.randrange(1, x // 2)
        try:
            got = curve.swap_base_input(amount, x, y, fees, on_input)
        except curve.CurveError:
            continue
        new_x, new_y = curve.reserves_after(x, y, got)
        assert new_x * new_y >= x * y
        assert got.output_amount < y


@pytest.mark.parametrize('on_input', [True, False])
def test_exact_output_costs_at_least_what_exact_input_would_return(on_input):
    rng = random.Random(11)
    for _ in range(2000):
        x, y = rng.randrange(10**7, 10**13), rng.randrange(10**7, 10**13)
        fees = curve.Fees(rng.choice([0, 2500, 10_000]), rng.choice([0, 1000]))
        wanted = rng.randrange(1, y // 3)
        out = curve.swap_base_output(wanted, x, y, fees, on_input)
        assert out.output_amount == wanted
        back = curve.swap_base_input(out.input_amount, x, y, fees, on_input)
        assert back.output_amount >= wanted            # paying that input as exact-in gives at least the output
        new_x, new_y = curve.reserves_after(x, y, out)
        assert new_x * new_y >= x * y


def test_refusals():
    fees = curve.Fees(2500)
    for call in (lambda: curve.swap_base_input(0, 10, 10, fees, True),
                 lambda: curve.swap_base_input(1, 10**9, 10**9, fees, True),       # consumed by the fee
                 lambda: curve.swap_base_input(5, 10**12, 10, fees, True),         # output rounds to zero
                 lambda: curve.swap_base_output(10, 10, 10, fees, True),
                 lambda: curve.swap_base_input(-1, 10, 10, fees, True),
                 lambda: curve.swap_base_input(1.0, 10, 10, fees, True),
                 lambda: curve.Fees(D),
                 lambda: curve.Fees(600_000, 400_000)):
        with pytest.raises(curve.CurveError):
            call()


# ---------------------------------------------------------------- events

def test_discriminators_are_the_anchor_event_hashes():
    import hashlib
    assert events.SWAP_DISCRIMINATOR == hashlib.sha256(b'event:SwapEvent').digest()[:8]
    assert len(swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True)) == 8 + 162


def test_swap_event_round_trip_both_layouts():
    event = events.decode(swap_payload(11, 22, 33, 44, True, QUOTE, BASE, 5, 6, False))
    assert (event.pool, event.input_vault_before, event.output_vault_before) == (POOL_B58, 11, 22)
    assert (event.input_amount, event.output_amount, event.base_input) == (33, 44, True)
    assert (event.input_mint, event.output_mint) == (QUOTE_B58, BASE_B58)
    assert (event.trade_fee, event.creator_fee, event.creator_fee_on_input, event.layout) == (5, 6, False, 'current')
    old = events.decode(swap_payload(11, 22, 33, 44, False, QUOTE, BASE, 0, 0, False, legacy=True))
    assert old.layout == 'legacy' and old.input_mint is None and old.base_input is False


def test_unknown_sizes_and_bad_booleans_are_errors_not_guesses():
    good = swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True)
    for bad in (good[:-1], good + b'\0', good[:8 + 80]):
        with pytest.raises(events.EventDecodeError):
            events.decode(bad)
    broken = bytearray(good)
    broken[8 + 80] = 2
    with pytest.raises(events.EventDecodeError):
        events.decode(bytes(broken))
    assert events.decode(b'\x01' * 60) is None      # another program's event


def test_b58_matches_known_addresses():
    assert events.b58encode(bytes(32)) == OTHER
    assert events.b58encode(QUOTE) == QUOTE_B58
    assert events.b58encode(b58decode(events.CPMM_PROGRAM)) == events.CPMM_PROGRAM


def test_only_the_cpmm_frame_is_believed():
    payload = swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True)
    assert len(events.transaction_events(tx(1, 0, logs(payload)), POOL_B58)) == 1
    assert len(events.transaction_events(tx(1, 0, logs(payload, outer='Router111')), POOL_B58)) == 1
    forged = logs(payload, program='Evi1111111111111111111111111111111111111111')
    assert events.transaction_events(tx(1, 0, forged), POOL_B58) == []
    # an outer program logging the bytes after the CPMM frame returned is not believed either
    lines = logs(outer='Router111')
    lines.insert(-1, 'Program data: ' + base64.b64encode(payload).decode())
    assert events.transaction_events(tx(1, 0, lines), POOL_B58) == []


def test_failed_truncated_and_malformed_logs():
    payload = swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True)
    assert events.transaction_events(tx(1, 0, logs(payload), err={'InstructionError': [0, 'Custom']}), POOL_B58) == []
    with pytest.raises(events.LogsTruncated):
        events.transaction_events(tx(1, 0, logs(payload)[:2] + ['Log truncated']), POOL_B58)
    with pytest.raises(events.EventDecodeError):
        events.transaction_events(tx(1, 0, None), POOL_B58)
    with pytest.raises(events.EventDecodeError):
        events.transaction_events(tx(1, 0, logs(payload)[:-1]), POOL_B58)            # frame never closed
    with pytest.raises(events.EventDecodeError):
        events.transaction_events(tx(1, 0, ['Program data: AAAA']), POOL_B58)        # outside any frame
    bad = logs()
    bad.insert(2, 'Program data: ***')
    with pytest.raises(events.EventDecodeError):
        events.transaction_events(tx(1, 0, bad), POOL_B58)


def test_failed_inner_frame_is_popped():
    lines = ['Program Router111 invoke [1]', f'Program {events.CPMM_PROGRAM} invoke [2]',
             f'Program {events.CPMM_PROGRAM} failed: custom program error: 0x1771', 'Program Router111 failed: x']
    assert events.program_data(lines) == []


def test_free_text_logs_cannot_open_or_close_a_frame():
    payload = swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True)
    lines = logs(payload)
    for text in ('Program log: success', 'Program log: failed to do x', 'Program log: invoke [1]',
                 f'Program log: Program {events.CPMM_PROGRAM} success', 'Program return: abc AAAA'):
        noisy = lines[:1] + [text] + lines[1:]
        assert len(events.transaction_events(tx(1, 0, noisy), POOL_B58)) == 1
    # a foreign program printing a fake CPMM frame in its own log text gains nothing
    fake = ['Program Evil111 invoke [1]', f'Program log: Program {events.CPMM_PROGRAM} invoke [2]',
            'Program data: ' + base64.b64encode(payload).decode(), 'Program Evil111 success']
    assert events.transaction_events(tx(1, 0, fake), POOL_B58) == []


def test_events_of_another_pool_are_dropped():
    payload = swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True, pool=bytes(32))
    assert events.transaction_events(tx(1, 0, logs(payload)), POOL_B58) == []


def test_lp_change_event():
    payload = events.LP_DISCRIMINATOR + struct.pack('<32s7QB', POOL, 1, 2, 3, 4, 5, 6, 7, 1)
    event = events.decode(payload)
    assert (event.lp_amount_before, event.token_1_transfer_fee, event.change_type) == (1, 7, 1)
    with pytest.raises(events.EventDecodeError):
        events.decode(payload + b'\0')


# ---------------------------------------------------------------- timeline

def market(fees, on_input, *, seed=3, n=60, exact_out_share=0.2):
    rng = random.Random(seed)
    sim = Sim(206_900_000 * 10**6, 85 * 10**9, fees, on_input)
    txs, slot = {}, 1000
    for i in range(n):
        slot += rng.choice([0, 0, 1, 3])
        side = rng.choice(['buy', 'sell'])
        exact_in = rng.random() >= exact_out_share
        if side == 'buy':
            amount = rng.randrange(10**7, 2 * 10**9) if exact_in else rng.randrange(10**9, 10**12)
        else:
            amount = rng.randrange(10**9, 10**12) if exact_in else rng.randrange(10**7, 10**9)
        payload, _ = sim.swap(side, amount, exact_in=exact_in)
        txs[f'sig{i:03d}'] = tx(slot, i, logs(payload, outer='Router111' if i % 3 == 0 else None))
    return txs, sim


@pytest.mark.parametrize('fees,on_input', [
    (curve.Fees(2500, 0, 120_000, 40_000), True),
    (curve.Fees(10_000, 1000, 120_000, 40_000), True),
    (curve.Fees(2500, 1000, 120_000, 40_000), False),
])
def test_every_swap_is_reproduced_and_reserves_chain(fees, on_input):
    txs, sim = market(fees, on_input)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    assert len(line.swaps) == 60 and not line.skipped
    assert [s.key for s in line.swaps] == sorted(s.key for s in line.swaps)
    by_side = {}
    for side in ('buy', 'sell'):
        got, flag, _ = timeline.infer_fees(line.swaps, side)
        assert flag is on_input
        by_side[side] = (got, flag)
    report = timeline.reproduce(line, by_side)
    assert report['exact'] == report['swaps'] == 60 and report['share_exact'] == 1.0
    assert timeline.continuity(line, 120_000, 40_000) == []
    last = line.swaps[-1]
    base, quote, evidence = timeline.reserves_at(line, slot_limit=last.slot, protocol_fee_rate=120_000,
                                                 fund_fee_rate=40_000)
    assert (base, quote) == (sim.base, sim.quote)
    assert evidence['source'] == 'logged_amounts_of_last_swap' and evidence['input_side_overstated_by_at_most'] == 0


def test_inferred_rates_are_the_true_ones():
    true = curve.Fees(2500, 1000, 120_000, 40_000)
    txs, _ = market(true, True, n=200)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    got, flag, evidence = timeline.infer_fees(line.swaps, 'buy')
    assert flag is True and (got.trade_fee_rate, got.creator_fee_rate) == (2500, 1000)
    assert evidence['combined_rate_interval'][1] == 3500
    txs, _ = market(true, False, n=200)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    got, flag, evidence = timeline.infer_fees(line.swaps, 'sell')
    assert flag is False and (got.trade_fee_rate, got.creator_fee_rate) == (2500, 1000)


def test_unknown_protocol_share_shows_as_a_skim_bounded_by_the_trade_fee():
    true = curve.Fees(2500, 0, 120_000, 40_000)
    txs, _ = market(true, True)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    by_side = {side: (curve.Fees(2500), True) for side in ('buy', 'sell')}
    assert timeline.reproduce(line, by_side)['share_exact'] == 1.0             # outputs do not depend on the shares
    breaks = timeline.continuity(line)
    assert breaks and all(b['reason'] == 'reserves_discontinuity' for b in breaks)
    for b in breaks:                                    # the skim is exactly the protocol + fund fee of that swap
        assert b['skim'] == b['trade_fee'] * 120_000 // D + b['trade_fee'] * 40_000 // D
        assert 0 < b['skim'] <= b['trade_fee']


def test_a_wrong_fee_rate_is_reported_swap_by_swap():
    txs, _ = market(curve.Fees(2500), True, n=20, exact_out_share=0)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    report = timeline.reproduce(line, {side: (curve.Fees(3000), True) for side in ('buy', 'sell')})
    assert report['exact'] == 0 and len(report['differences']) == 20
    assert set(report['differences'][0]['fields']) == {'output_amount', 'trade_fee'}


def test_a_fee_change_inside_the_swaps_is_refused():
    a, sim = market(curve.Fees(2500), True, n=20, exact_out_share=0)
    sim.fees = curve.Fees(10_000)
    payload, _ = sim.swap('buy', 10**9)
    a['late'] = tx(5000, 0, logs(payload))
    line = timeline.build(POOL_B58, a, base_mint=BASE_B58)
    with pytest.raises(timeline.TimelineError):
        timeline.infer_fees(line.swaps, 'buy')
    prefix = [s for s in line.swaps if s.slot < 5000]
    assert timeline.infer_fees(prefix, 'buy')[0].trade_fee_rate == 2500         # causal prefix: unaffected


def test_reserves_at_prefers_what_the_next_swap_logged():
    fees = curve.Fees(2500, 0, 120_000, 40_000)
    txs, _ = market(fees, True)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    middle = line.swaps[30]
    following = next(s for s in line.swaps if s.slot > middle.slot)
    base, quote, evidence = timeline.reserves_at(line, slot_limit=middle.slot)
    assert evidence['source'] == 'next_swap_logged_reserves'
    assert (base, quote) == (following.base_before, following.quote_before)     # exact despite unknown shares
    assert timeline.reserves_at(line, time_limit=middle.block_time)[:2] == (base, quote)
    for bad in (dict(slot_limit=line.swaps[0].slot - 1), dict(), dict(slot_limit=1, time_limit=1),
                dict(slot_limit=middle.slot, protocol_fee_rate=1)):
        with pytest.raises(timeline.TimelineError):
            timeline.reserves_at(line, **bad)


def test_state_between_the_pool_creation_and_its_first_swap():
    fees = curve.Fees(2500)
    sim = Sim(206_900_000 * 10**6, 85 * 10**9, fees, True)
    start = (sim.base, sim.quote)
    payload, _ = sim.swap('buy', 10**9)
    txs = dict(a=tx(2000, 0, logs(payload)))
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58, opened=(1990, 1_700_001_990))
    base, quote, evidence = timeline.reserves_at(line, slot_limit=1994)
    assert (base, quote) == start and evidence['source'] == 'first_swap_logged_reserves'
    assert timeline.reserves_at(line, time_limit=1_700_001_995)[:2] == start
    with pytest.raises(timeline.TimelineError):
        timeline.reserves_at(line, slot_limit=1989)                              # the pool does not exist yet
    with pytest.raises(timeline.TimelineError):
        timeline.reserves_at(timeline.build(POOL_B58, txs, base_mint=BASE_B58), slot_limit=1994)   # creation unknown
    with pytest.raises(timeline.TimelineError):
        timeline.build(POOL_B58, txs, base_mint=BASE_B58, opened=(2001, 1))      # a swap before the creation
    with pytest.raises(timeline.TimelineError):
        timeline.reserves_at(timeline.build(POOL_B58, {}, base_mint=BASE_B58, opened=(1990, 5)), slot_limit=1994)


def test_sell_value_is_the_program_output_on_the_landing_state():
    fees = curve.Fees(2500, 1000, 120_000, 40_000)
    txs, sim = market(fees, False)
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    tokens = 3 * 10**11
    value, evidence = timeline.sell_value(line, tokens, fees, False, slot_limit=line.swaps[-1].slot,
                                          protocol_fee_rate=120_000, fund_fee_rate=40_000)
    payload, got = sim.swap('sell', tokens)
    assert value == got.output_amount and evidence['creator_fee'] == got.creator_fee
    assert evidence['base_reserve'] + tokens - got.protocol_fee - got.fund_fee == sim.base


def test_unknown_shares_give_the_bound_that_is_worse_for_the_seller():
    fees = curve.Fees(2500, 0, 120_000, 40_000)
    for last_side in ('buy', 'sell'):
        sim = Sim(206_900_000 * 10**6, 85 * 10**9, fees, True)
        first, _ = sim.swap('sell', 10**11)
        second, got = sim.swap(last_side, 10**9 if last_side == 'buy' else 10**11)
        line = timeline.build(POOL_B58, dict(a=tx(10, 0, logs(first)), b=tx(11, 0, logs(second))), base_mint=BASE_B58)
        tokens = 5 * 10**11
        exact, _ = timeline.sell_value(line, tokens, fees, True, slot_limit=11, protocol_fee_rate=120_000,
                                       fund_fee_rate=40_000)
        bound, evidence = timeline.sell_value(line, tokens, fees, True, slot_limit=11)
        assert evidence['input_side_overstated_by_at_most'] == got.trade_fee
        assert bound <= exact and exact - bound <= 2 * got.trade_fee + 1
        assert exact == curve.swap_base_input(tokens, sim.base, sim.quote, fees, True).output_amount


def test_undecodable_transactions_are_listed_and_legacy_events_not_guessed():
    fees = curve.Fees(2500)
    txs, sim = market(fees, True, n=5, exact_out_share=0)
    payload, _ = sim.swap('buy', 10**9)
    txs['trunc'] = tx(9000, 0, logs(payload)[:2] + ['Log truncated'])
    txs['old'] = tx(9001, 0, logs(swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 0, 0, True, legacy=True)))
    txs['failed'] = tx(9002, 0, logs(payload), err={'x': 1})
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    assert len(line.swaps) == 5
    assert dict(line.skipped) == {'trunc': 'log_truncated', 'old': 'legacy_swap_event_without_mints'}
    # the truncated swap really happened: continuity shows the hole when a later swap is seen
    payload, _ = sim.swap('sell', 10**10)
    txs['after'] = tx(9003, 0, logs(payload))
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    breaks = timeline.continuity(line)
    assert [b['index'] for b in breaks] == [4] and breaks[0]['skim'] is None     # both sides moved: a missing swap


def test_lp_change_between_two_swaps_is_named_and_never_bridged():
    fees = curve.Fees(2500)
    sim = Sim(10**15, 10**11, fees, True)
    first, _ = sim.swap('buy', 10**9)
    lp = events.LP_DISCRIMINATOR + struct.pack('<32s7QB', POOL, 1, sim.quote, sim.base, 10**9, 10**13, 0, 0, 0)
    sim.quote, sim.base = sim.quote + 10**9, sim.base + 10**13
    second, _ = sim.swap('sell', 10**10)
    txs = dict(a=tx(10, 0, logs(first)), b=tx(11, 0, logs(lp)), c=tx(12, 0, logs(second)))
    line = timeline.build(POOL_B58, txs, base_mint=BASE_B58)
    assert len(line.lp_changes) == 1
    assert [b['reason'] for b in timeline.continuity(line)] == ['lp_change_between']
    base, quote, evidence = timeline.reserves_at(line, slot_limit=10)
    assert evidence['source'] == 'logged_amounts_of_last_swap' and evidence['lp_change_follows'] is True


def test_two_swaps_of_one_transaction_keep_their_order():
    fees = curve.Fees(2500)
    sim = Sim(10**15, 10**11, fees, True)
    a, _ = sim.swap('buy', 10**9)
    b, _ = sim.swap('sell', 10**12)
    line = timeline.build(POOL_B58, dict(x=tx(10, 4, logs(a, b))), base_mint=BASE_B58)
    assert [(s.order, s.side) for s in line.swaps] == [(0, 'buy'), (1, 'sell')]
    assert timeline.continuity(line) == []


def test_foreign_mints_and_missing_positions_are_errors():
    payload = swap_payload(1, 2, 3, 4, True, QUOTE, bytes(32), 5, 6, True)
    with pytest.raises(timeline.TimelineError):
        timeline.build(POOL_B58, dict(x=tx(1, 0, logs(payload))), base_mint=BASE_B58)
    bad = tx(1, 0, logs())
    del bad['transactionIndex']
    with pytest.raises(timeline.TimelineError):
        timeline.build(POOL_B58, dict(x=bad), base_mint=BASE_B58)


# ---------------------------------------------------------------- A-12 report

def test_a12_report_passes_on_a_complete_pool_and_names_every_defect(tmp_path, capsys):
    import gzip
    import json
    from cpmmx import a12
    true = curve.Fees(2500, 1000, 120_000, 40_000)
    txs, _ = market(true, True, n=80)
    document = dict(pool=POOL_B58, base_mint=BASE_B58, opened=None, transactions=txs)
    good = a12.report(document, 120_000, 40_000)
    assert good['passed'] and good['reproduction']['share_exact'] == 1.0 and good['continuity']['breaks'] == 0
    assert good['fees']['sell']['trade_fee_rate'] == 2500 and good['fees']['buy']['creator_fee_rate'] == 1000
    blind = a12.report(document)                               # shares unknown: the skim is measured, not a hole
    assert blind['passed'] and blind['continuity']['both_sides'] == 0 and blind['continuity']['input_side_only'] > 0
    assert all(150_000 <= v <= 160_000 for v in blind['continuity']['skim_share_of_trade_fee_ppm'])
    lost = dict(document, transactions={k: v for k, v in txs.items() if k != 'sig040'})
    hole = a12.report(lost, 120_000, 40_000)
    assert not hole['passed'] and hole['reasons'] == ['reserve_chain_has_holes']
    assert hole['continuity']['both_sides_indices'] == [39]
    path = tmp_path / 'pool.json.gz'
    path.write_bytes(gzip.compress(json.dumps(document).encode()))
    assert a12.main([str(path), '--protocol-fee-rate', '120000', '--fund-fee-rate', '40000']) == 0
    assert json.loads(capsys.readouterr().out)['passed'] is True
