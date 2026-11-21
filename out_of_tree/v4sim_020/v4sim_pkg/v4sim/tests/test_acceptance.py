"""Acceptance tests A-1 to A-10 of the V4 simulator (protocol v2, section 6).

Data: the frozen test pack and SYNTHETIC packs only, generated apart and read as files:
  V4SIM_PACKS   directory holding ``random500`` and ``stress100`` (v4synth/gen_pack.py)
  V4SIM_A3_DIR  directory prepared apart for A-3 (synthetic x40 archive pack + series), optional here
"""
import dataclasses
import functools
import gzip
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import pytest

from bot.market import replay as frozen_replay
from bot.market.collector import PoolArchive, summarize
from bot.market.launchlab_curve import CurveState, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import ExecutionModel
from bot.p4.historical_research_replay import usable_timeline

from v4sim import batch, engine, ledger, valuation
from v4sim.batch import FixedOrder
from v4sim.engine import Execution, identity_replay, replay
from v4sim.io import actors_from_archive, load_timeline_pack
from v4sim.ledger import MODES, InvariantError

PACKS = Path(os.environ.get('V4SIM_PACKS', 'packs'))
FROZEN_PACK = Path('tests/fixtures/launchlab_sol_pools')
MODEL = ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')
SIZES = (50_000_000, 100_000_000, 500_000_000, 1_000_000_000)
NEW = ('M-P', 'M-C', 'M-A')


@functools.lru_cache(maxsize=None)
def pack(name):
    return load_timeline_pack(PACKS / name)[1]


@functools.lru_cache(maxsize=None)
def frozen_pools():
    out = []
    for entry in json.loads((FROZEN_PACK / 'MANIFEST.json').read_text())['pools']:
        archive = PoolArchive.from_json(json.loads(gzip.decompress((FROZEN_PACK / entry['file']).read_bytes())))
        summary, timeline = summarize(archive)
        timeline, _ = usable_timeline(archive, summary, timeline)
        out.append((timeline, actors_from_archive(archive, timeline.events)[0]))
    return out


class ClockOrder(FixedOrder):
    """A fixed order that also carries a clock deadline (exercises the clock-exit path)."""

    def exit_deadline(self, position):
        return position.entry_time + 10


def run(timeline, decision, amount, hold, mode, **kwargs):
    return replay(timeline, FixedOrder(decision, amount, hold), kwargs.pop('model', MODEL), quote_mint=WSOL_MINT,
                  mode=mode, **kwargs)


# ---- A-1 identity replay ------------------------------------------------------------------------
def test_a1_identity_replay_field_by_field():
    events = 0
    for mode in MODES:
        for timeline, actors in frozen_pools():
            events += identity_replay(timeline, mode, actors)
            identity_replay(timeline, mode)                       # fee payer as the actor
        for name in ('random500', 'stress100'):
            events += sum(identity_replay(timeline, mode) for _entry, timeline in pack(name))
    assert events > 4 * 15_000


# ---- A-2 invariants on 10 000 seeded order flows ------------------------------------------------
def test_a2_invariants_hold_on_10000_order_flows():
    rng, flows, entered = random.Random(20261110), 0, {mode: 0 for mode in MODES}
    for _entry, timeline in pack('random500'):
        for _ in range(20):
            decision = rng.randrange(len(timeline.events))
            amount, hold = rng.choice(SIZES), rng.choice((1, 2, 5, 20, 10 ** 6))
            flows += 1
            for mode in MODES:
                result = run(timeline, decision, amount, hold, mode)     # InvariantError would fail the test
                if result.entry_index is None:
                    continue
                entered[mode] += 1
                if mode != 'M-L':
                    assert result.outcome in ('closed', 'open_at_end', 'migrated_unpriced'), result.notes
                    if result.outcome != 'migrated_unpriced':
                        assert result.received >= 0 and result.net_return >= -1
                    else:
                        assert result.v4['last_curve_value'] is not None
    assert flows == 10_000 and min(entered.values()) > 5_000


def test_a2_invariant_guards_raise_on_a_corrupted_ledger():
    timeline = pack('random500')[0][1]
    others = ledger.Others('M-P', timeline.events)
    for event in timeline.events[:3]:
        others.observe(event)
    others.enter(0)
    others.check(timeline.events[2].state_after())
    others.sum_cf += 1
    with pytest.raises(InvariantError, match='I-1'):
        others.check(timeline.events[2].state_after())


# ---- A-3 non-regression of the legacy mode ------------------------------------------------------
def test_a3_legacy_mode_equals_the_frozen_replay_on_every_pack():
    rng, compared = random.Random(3), 0
    pools = [t for t, _a in frozen_pools()] + [t for _e, t in pack('random500')[:120]] + [t for _e, t in pack('stress100')]
    for timeline in pools:
        for _ in range(8):
            order = rng.choice((FixedOrder, ClockOrder))(rng.randrange(len(timeline.events)), rng.choice(SIZES),
                                                         rng.choice((1, 3, 10, 10 ** 6)))
            for model in (ExecutionModel(), MODEL, dataclasses.replace(MODEL, clock_exit_latency_s=2)):
                want = frozen_replay.replay(timeline, order, model, quote_mint=WSOL_MINT)
                got = replay(timeline, order, model, quote_mint=WSOL_MINT, mode='M-L')
                assert dataclasses.asdict(got) == dataclasses.asdict(want)
                compared += 1
    assert compared > 5_000


@pytest.mark.skipif(not os.environ.get('V4SIM_A3_DIR'), reason='A-3 run_trials check needs the pack prepared apart')
@pytest.mark.parametrize('name, expected', [
    ('frozen', '4aee76a3573344b37646202441c8b57c9fad0492d0674145691252dafbe85149'),
    ('x40', 'ba14a5db7a66b277f59b9ddf2222bb9364b33e75496483300707aadef5044b72')])
def test_a3_run_trials_bundles_are_byte_identical(name, expected, tmp_path, monkeypatch):
    from bot.master_v2 import harness
    from bot.master_v2 import w1_run
    from bot.p4 import historical_research_replay as hrr
    legacy = functools.partial(replay, mode='M-L')
    monkeypatch.setattr(harness, 'replay', legacy)
    monkeypatch.setattr(hrr, 'replay', legacy)
    base = Path(os.environ['V4SIM_A3_DIR'])
    pools = FROZEN_PACK if name == 'frozen' else base / 'x40'
    w1_run.run_trials(pools, base / 'series.json', registry_path=tmp_path / 'r.jsonl',
                      sensitivity_registry_path=tmp_path / 's.jsonl', registered_at='2026-11-09T00:00:00+00:00',
                      out=tmp_path / 'run')
    bundles = tmp_path / 'run' / 'bundles'
    if name == 'frozen':
        got = hashlib.sha256((bundles / 'SHA256SUMS.json').read_bytes()).hexdigest()
    else:
        sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in sorted(bundles.iterdir()))
        got = hashlib.sha256(sums.encode()).hexdigest()
    assert got == expected


# ---- A-4' continuity (protocol v2.1): fixed stake of 1 000 lamports -----------------------------
A4_STAKE = 1_000


def continuity(stake):
    """(positions, pools giving 0 token, positions priced by M-L, largest gap, gaps over the tolerance)."""
    rng, positions, no_token, priced, largest, over = random.Random(4), 0, 0, 0, 0, 0
    for entry, timeline in pack('random500'):
        decision = rng.randrange(len(timeline.events))
        model = ExecutionModel(latency_slots=0, fee_rate_ppm=entry['fee_rate_ppm'])
        results = {mode: run(timeline, decision, stake, 10 ** 6, mode, model=model) for mode in ('M-L', 'M-P', 'M-C')}
        if results['M-P'].entry_index is None or results['M-P'].tokens < 1:
            no_token += 1                                   # excluded and counted
            continue
        positions += 1
        if not results['M-L'].priced:
            continue
        priced += 1
        replayed = len(timeline.events) - 1 - results['M-L'].entry_index
        for mode in ('M-P', 'M-C'):
            assert results[mode].priced
            gap = abs(results[mode].received - results['M-L'].received)
            largest, over = max(largest, gap), over + (gap > max(1, replayed))
    return positions, no_token, priced, largest, over


def test_a4_continuity_at_1000_lamports():
    positions, no_token, priced, largest, over = continuity(A4_STAKE)
    assert priced >= 100 and over == 0, (positions, no_token, priced, largest, over)


def test_a4_descriptive_measure_at_100000_lamports(record_property):
    positions, no_token, priced, largest, over = continuity(100_000)        # published, not a criterion
    record_property('a4_descriptive_100000', dict(positions=positions, no_token=no_token, priced=priced,
                                                  largest_gap=largest, over_tolerance=over))
    assert positions > 0


# ---- A-5 artefact L1 removed; value computed by hand ---------------------------------------------
def by_hand(events, order, rate, mode, latency_slots=4):
    """Independent integer arithmetic (no v4sim, no frozen curve function): value of our position."""
    def fee(amount, r):
        return -(-amount * r // 1_000_000)

    def implied(e):
        fees = e.protocol_fee + e.platform_fee + e.creator_fee + e.share_fee
        basis = e.amount_in if e.side == 'buy' else e.amount_out + fees
        return 0 if basis <= 0 or fees == 0 else min((fees - 1) * 1_000_000 // basis + 1, 999_999)
    k = order['decision_index']
    land = k
    while land + 1 < len(events) and events[land + 1].slot <= events[k].slot + latency_slots:
        land += 1
    last = events[land]
    vb, vq, rb, rq = last.virtual_base, last.virtual_quote, last.real_base_after, last.real_quote_after
    real = {}
    for e in events[:land + 1]:
        real[e.fee_payer] = real.get(e.fee_payer, 0) + (e.amount_out if e.side == 'buy' else -e.amount_in)
    cf, sellers = dict(real), set()
    net = order['amount_lamports'] - fee(order['amount_lamports'], rate)
    ours = net * (vb - rb) // (vq + rq + net)
    rb, rq = rb + ours, rq + net
    for e in events[land + 1:land + 1 + order['exit_after_events']]:
        r = implied(e)
        if e.side == 'buy':
            n = e.amount_in - fee(e.amount_in, r)
            out = n * (vb - rb) // (vq + rq + n)
            rb, rq = rb + out, rq + n
            real[e.fee_payer] = real.get(e.fee_payer, 0) + e.amount_out
            cf[e.fee_payer] = cf.get(e.fee_payer, 0) + out
        else:
            held_real, held = real[e.fee_payer], cf[e.fee_payer]
            if mode == 'M-C':
                sold = min(e.amount_in, held)
            elif mode == 'M-A' and e.fee_payer not in sellers:
                sold = held
            else:
                sold = held if e.amount_in == held_real else e.amount_in * held // held_real
            sellers.add(e.fee_payer)
            if sold:
                gross = sold * (vq + rq) // (vb - rb + sold)
                rb, rq = rb - sold, rq - gross
            real[e.fee_payer], cf[e.fee_payer] = held_real - e.amount_in, held - sold
    gross = ours * (vq + rq) // (vb - rb + ours)
    return ours, gross - fee(gross, rate), sum(cf.values())


def test_a5_stress_pack_no_inventory_artefact_and_hand_computed_value():
    legacy_divergences = 0
    for entry, timeline in pack('stress100'):
        order = entry['our_order']
        model = dataclasses.replace(MODEL, fee_rate_ppm=entry['fee_rate_ppm'])
        legacy = run(timeline, order['decision_index'], order['amount_lamports'], order['exit_after_events'], 'M-L', model=model)
        legacy_divergences += legacy.outcome == 'counterfactual_divergence'
        for mode in NEW:
            got = run(timeline, order['decision_index'], order['amount_lamports'], order['exit_after_events'], mode, model=model)
            assert got.outcome == 'closed' and not got.v4['flags'], (mode, got.notes, got.v4)
            assert not any('sell_exceeds_curve_inventory' in note for note in got.notes)
            tokens, value, others_left = by_hand(timeline.events, order, entry['fee_rate_ppm'], mode)
            assert (got.tokens, got.received) == (tokens, value), (mode, timeline.pool)
            assert others_left == 0                         # every other holder is out: we sell last
    assert legacy_divergences == 100                        # the frozen engine breaks on every pool of this pack


# ---- A-6 valuation rules ------------------------------------------------------------------------
BASE = CurveState(1_073_025_605_596_382, 30_000_852_951, 400_000_000_000_000, 20_000_000_000, 793_100_000_000_000)


def test_a6_rule1_full_sale_is_the_exact_frozen_output():
    assert valuation.liquidation(BASE, 10 ** 12, 10_000)[:3] == (sell_exact_in(BASE, 10 ** 12, 10_000).amount_out, 10 ** 12, ())


def test_a6_rule2_sale_limited_by_the_quote_reserve_is_maximal():
    state = dataclasses.replace(BASE, real_quote=1_000_000)
    value, sold, flags, after = valuation.liquidation(state, 3 * 10 ** 14, 10_000)
    assert flags == (valuation.PARTIAL,) and 0 < sold < 3 * 10 ** 14 and value > 0
    assert valuation._gross(state, sold) <= state.real_quote < valuation._gross(state, sold + 1)
    assert after.real_quote >= 0 and value == sell_exact_in(state, sold, 10_000).amount_out


def test_a6_rule3_sale_limited_by_the_inventory_is_flagged_external():
    state = dataclasses.replace(BASE, real_base=10 ** 9, real_quote=10 ** 9)
    value, sold, flags, _after = valuation.liquidation(state, 5 * 10 ** 9, 10_000)
    assert valuation.EXTERNAL in flags and valuation.PARTIAL in flags and sold == 10 ** 9 and value > 0


def test_a6_rule4_dust_is_zero_and_never_minus_one_by_convention():
    assert valuation.liquidation(BASE, 1, 10_000)[:3] == (0, 0, (valuation.DUST,))
    assert valuation.liquidation(dataclasses.replace(BASE, real_base=0, real_quote=0), 10 ** 9, 10_000)[0] == 0


# ---- A-7 determinism ----------------------------------------------------------------------------
def test_a7_same_bytes_twice_and_with_1_2_4_processes():
    digests = {hashlib.sha256(batch.dumps(batch.run_pack(PACKS / 'stress100', workers=w))).hexdigest() for w in (1, 1, 2, 4)}
    assert len(digests) == 1
    assert len(batch.run_pack(PACKS / 'stress100')['code_fingerprint']) == 64


# ---- A-8 monotonicity ---------------------------------------------------------------------------
def test_a8_tokens_per_lamport_never_increase_with_the_size():
    for _entry, timeline in pack('random500')[:200]:
        state = timeline.events[len(timeline.events) // 2].state_after()
        rates = []
        for size in SIZES:
            try:
                rates.append((buy_exact_in(state, size, 10_000).amount_out, size))
            except Exception:
                break
        assert all(a * s2 >= b * s1 for (a, s1), (b, s2) in zip(rates, rates[1:]))


def test_a8_failures_are_nested_in_p_fail_and_always_traced():
    keys = [(f'pool{i}', side, i % 7, i % 3) for i in range(2_000) for side in ('buy', 'sell')]
    low = {k for k in keys if engine.not_included(Execution(p_fail=0.10), *k)}
    high = {k for k in keys if engine.not_included(Execution(p_fail=0.25), *k)}
    assert low < high and 0.07 < len(low) / len(keys) < 0.13 and 0.21 < len(high) / len(keys) < 0.29
    assert not any(engine.not_included(Execution(), *k) for k in keys)
    timeline = pack('random500')[0][1]
    for p in (0.0, 0.25):
        result = run(timeline, 2, SIZES[1], 3, 'M-P', execution=Execution(p_fail=p, max_retries=2))
        costs = sum(f['cost'] for f in result.v4['failed_attempts'])
        done = (result.entry_index is not None) + (result.outcome in ('closed', 'open_at_end'))
        assert result.tx_costs == costs + done * MODEL.tx_cost
        assert p or not result.v4['failed_attempts']


def test_a8_order_before_the_landing_slot_trades():
    """O-2: with slot_order='before' our order lands before every real trade of the landing slot."""
    found = 0
    for _entry, timeline in pack('random500'):
        events = timeline.events
        for k in range(len(events) - 1):
            limit = events[k].slot + MODEL.latency_slots
            if not any(e.slot == limit for e in events[k + 1:k + 12]):
                continue
            after = run(timeline, k, SIZES[0], 10 ** 6, 'M-P')
            before = run(timeline, k, SIZES[0], 10 ** 6, 'M-P', execution=Execution(slot_order='before'))
            if after.entry_index is None or before.entry_index is None:
                continue
            expected = max(i for i in range(k, len(events)) if i == k or events[i].slot < limit)
            assert before.entry_index == expected < after.entry_index
            assert events[after.entry_index].slot == limit and events[before.entry_index].slot < limit
            found += 1
            break
    assert found >= 50


# ---- A-9 failures and fees, to the lamport -------------------------------------------------------
def moving_pool():
    for _entry, timeline in pack('random500'):
        for k in range(len(timeline.events) - 2):
            nxt = timeline.events[k + 1]
            if nxt.side == 'buy' and nxt.slot == timeline.events[k].slot and nxt.amount_in > 10 ** 9:
                return timeline, k
    raise AssertionError('no pool with a large buy in the decision slot')


def test_a9_slippage_failure_pays_base_and_priority():
    timeline, k = moving_pool()
    result = run(timeline, k, SIZES[1], 3, 'M-P', execution=Execution(slippage_bps=1))
    assert result.entry_index is None and result.notes == ['entry_failed']
    assert result.v4['failed_attempts'] == [dict(side='buy', decision_index=k, attempt=0, kind='slippage', cost=MODEL.tx_cost)]
    assert result.tx_costs == MODEL.tx_cost == 105_000
    assert run(timeline, k, SIZES[1], 3, 'M-P', execution=Execution(slippage_bps=None)).entry_index is not None


def test_a9_non_inclusion_fee_rule_and_retries():
    timeline = pack('random500')[0][1]
    never = Execution(p_fail=0.999999, max_retries=2)
    result = run(timeline, 2, SIZES[1], 3, 'M-P', execution=never)
    assert [f['kind'] for f in result.v4['failed_attempts']] == ['not_included'] * 3
    assert result.tx_costs == 3 * MODEL.base_fee_lamports and result.v4['non_inclusion_fee'] == 'base_fee'
    with pytest.raises(ValueError, match='archived_official_reference'):
        Execution(non_inclusion_fee='zero')
    free = Execution(p_fail=0.999999, max_retries=2, non_inclusion_fee='zero', fee_reference=dict(url='u', read_at='d', sha256='0' * 64))
    assert run(timeline, 2, SIZES[1], 3, 'M-P', execution=free).tx_costs == 0
    second = engine.landing_index(timeline.events, 2, timeline.events[2].slot + MODEL.latency_slots)
    salt = next(s for s in map(str, range(10_000))
                if engine.not_included(Execution(p_fail=0.5, salt=s), timeline.pool, 'buy', 2, 0)
                and not engine.not_included(Execution(p_fail=0.5, salt=s), timeline.pool, 'buy', second, 1))
    retried = run(timeline, 2, SIZES[1], 10 ** 6, 'M-P', execution=Execution(p_fail=0.5, salt=salt, max_retries=1))
    assert retried.entry_index is not None and retried.v4['failed_attempts'][0]['attempt'] == 0
    assert retried.tx_costs == MODEL.base_fee_lamports + 2 * MODEL.tx_cost      # failed try + entry + final mark


# ---- A-10 mutations: every injected defect is caught by a core check ------------------------------
def core_checks():
    checks = dict(invariant_guard=test_a2_invariant_guards_raise_on_a_corrupted_ledger,
                  fees=test_a9_slippage_failure_pays_base_and_priority,
                  landing=check_landing_latency, valuation=test_a6_rule2_sale_limited_by_the_quote_reserve_is_maximal,
                  by_hand=test_a5_stress_pack_no_inventory_artefact_and_hand_computed_value, causality=check_causality)
    failed = []
    for name, check in checks.items():
        try:
            check()
        except (Exception, pytest.fail.Exception):          # any failure counts as a detection
            failed.append(name)
    return failed


def check_landing_latency():
    timeline, k = moving_pool()
    result = run(timeline, k, SIZES[1], 10 ** 6, 'M-P')
    expected = k
    while expected + 1 < len(timeline.events) and timeline.events[expected + 1].slot <= timeline.events[k].slot + 4:
        expected += 1
    assert expected > k and result.entry_index == expected


def check_causality():
    """Nothing decided up to the exit may depend on events that come after it."""
    for entry, timeline in pack('random500')[:60]:
        if len(timeline.events) < 12:
            continue
        cut = type(timeline)(timeline.pool, timeline.events[:9], ())
        for mode in NEW:
            full, short = run(timeline, 1, SIZES[0], 2, mode), run(cut, 1, SIZES[0], 2, mode)
            if full.outcome == 'closed' and full.exit_index < 8:
                assert (full.received, full.exit_index, full.tokens) == (short.received, short.exit_index, short.tokens)


def test_a10_the_unmutated_simulator_passes_every_core_check():
    assert core_checks() == []


def test_a10_mutation_conservation_check_disabled(monkeypatch):
    monkeypatch.setattr(ledger.Others, 'check', lambda self, state: None)
    assert 'invariant_guard' in core_checks()


def test_a10_mutation_fees_times_zero(monkeypatch):
    monkeypatch.setattr(ExecutionModel, 'tx_cost', property(lambda self: 0))
    assert 'fees' in core_checks()


def test_a10_mutation_latency_zero(monkeypatch):
    monkeypatch.setattr(engine, 'landing_index', lambda events, start, limit, order='after': start)
    assert 'landing' in core_checks()


def test_a10_mutation_fallback_to_zero_reintroduced(monkeypatch):
    def fallback(state, tokens, rate):
        try:
            fill = sell_exact_in(state, tokens, rate)
            return fill.amount_out, tokens, (), fill.after
        except Exception:
            return 0, 0, (), state
    monkeypatch.setattr(valuation, 'liquidation', fallback)
    assert 'valuation' in core_checks()


def test_a10_mutation_ledger_ignores_our_impact(monkeypatch):
    original = ledger.Others.replay

    def legacy_amounts(self, state, event):                 # the L1 defect: real token amounts replayed as they are
        mode, self.mode = self.mode, 'M-L'
        try:
            return original(self, state, event)
        finally:
            self.mode = mode
    monkeypatch.setattr(ledger.Others, 'replay', legacy_amounts)
    assert 'by_hand' in core_checks()


def test_a10_mutation_reading_a_future_event(monkeypatch):
    original = engine.replay

    def peeking(timeline, strategy, model=MODEL, **kwargs):
        result = original(timeline, strategy, model, **kwargs)
        if result.outcome == 'closed':
            result.received += len(timeline.events)          # a value that depends on what happens later
        return result
    monkeypatch.setattr(sys.modules[__name__], 'replay', peeking)
    assert 'causality' in core_checks()
