"""w1aux.ledger: independent re-verification of every BUY/SELL cycle of the W1 bundles.

Rehearsal on the frozen 3-pool fixture pack (real LaunchLab pools, slots before S0): trials run by
the frozen w1_run, then the ledger re-derives each cycle and must find every tampering.
"""
import gzip
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

from bot.market import w1_collection
from bot.master_v2 import w1_run as run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from w1aux import ledger as L

PACK = Path('tests/fixtures/launchlab_sol_pools')          # relative to the frozen checkout (cwd)
AT = '2026-11-08T00:00:00+00:00'
FIRST_SLOT, FIRST_TIME = 464661843, 1793658217


@pytest.fixture(scope='module')
def rehearsal(tmp_path_factory):
    root = tmp_path_factory.mktemp('rehearsal')
    point = dict(schema=sus.POINT_SCHEMA, slot=FIRST_SLOT - 50, transaction_index=0, block_time=FIRST_TIME - 12,
                 received_at_ms=None, publish_time=FIRST_TIME - 13, price=15_000_000_000, exponent=-8,
                 confidence=7_500_000, source_kind='pyth_onchain_account', source_ref='synthetic-test-account',
                 evidence_sha256='0' * 64, signature=None)
    (root / 'sol_usd.json').write_text(json.dumps(dict(schema=sus.SERIES_SCHEMA, label='COLLECTED', points=[point],
                                                       acceptance=dict(max_age_ms=120_000, max_confidence_ppm=1_000))))
    mp = pytest.MonkeyPatch()
    mp.setenv('RUGGER_NO_DOTENV', '1')
    try:
        run.run_trials(PACK, root / 'sol_usd.json', registry_path=root / 'trials.jsonl',
                       sensitivity_registry_path=root / 'sens.jsonl', registered_at=AT, out=root / 'out')
        run.evaluate(PACK, root / 'out', FIRST_SLOT - w1_collection.WARMUP_SLOTS, registry_paths=[root / 'trials.jsonl'],
                     registry_path=root / 'trials.jsonl', sensitivity_registry_path=root / 'sens.jsonl', n_boot=200)
    finally:
        mp.undo()
    return root


def _copy(rehearsal, tmp_path):
    shutil.copytree(rehearsal / 'out' / 'bundles', tmp_path / 'bundles')
    return tmp_path / 'bundles'


def _rewrite(bundles, trial_id, mutate, *, rehash_l1=True):
    """Tamper a bundle CONSISTENTLY (file, internal hash, SHA256SUMS), as a wrong replay would."""
    path = bundles / f'{trial_id}.json.gz'
    bundle = json.loads(gzip.decompress(path.read_bytes()))
    mutate(bundle)
    if rehash_l1 and bundle['schema'] == L.L1_SCHEMA:
        bundle['bundle_sha256'] = hrr._sha({k: v for k, v in bundle.items() if k != 'bundle_sha256'})
    data = gzip.compress(json.dumps(bundle, sort_keys=True).encode(), mtime=0)
    path.write_bytes(data)
    sums = json.loads((bundles / 'SHA256SUMS.json').read_text())
    sums[trial_id] = hashlib.sha256(data).hexdigest()
    (bundles / 'SHA256SUMS.json').write_text(json.dumps(sums))


def _closed(bundle):
    rows = [pool['trade'] for pool in bundle['pools']] if 'policy' in bundle else \
        [row for pool in bundle['pools'] for row in pool['arms'].values()]
    return [row for row in rows if row['outcome'] == 'closed']


def test_every_cycle_of_the_rehearsal_is_re_derived_identically(rehearsal):
    led = L.build_ledger(PACK, rehearsal / 'out' / 'bundles', report_path=rehearsal / 'out' / 'w1_report.json',
                         series=sus.load_series(rehearsal / 'sol_usd.json'))
    assert led['verdict'] == 'PASS' and led['mismatches'] == []
    assert led['cycles_with_entry'] == 9 and led['cycles_verified'] == 9
    closed = [e for e in led['entries'] if e['outcome'] == 'closed']
    assert len(closed) == 8 and all(e['checks']['decomposition_identity_exact'] for e in closed)
    for e in closed:
        d = e['decomposition']
        assert d['pnl'] == e['pnl_lamports']
        assert d['launchlab_buy_fee'] > 0 and d['launchlab_sell_fee'] > 0 and d['tx_costs'] == 210_000
        assert d['slippage'] >= 0                                      # a round trip never gains on own impact
        assert abs(d['market_move'] - d['slippage'] - d['launchlab_buy_fee'] - d['launchlab_sell_fee']
                   - d['tx_costs'] - d['failed_attempt_costs'] - d['pnl']) < 0.01
        assert e['pnl_usd'] == pytest.approx(e['pnl_lamports'] / 1e9 * 150.0) and e['usd_refusal'] is None
    # the MASTER arm abstains on this pack: no entry, nothing invented
    assert led['comparison']['L1:master']['entries'] == 0 and led['comparison']['L1:master']['mean_pnl_lamports'] is None
    s1 = led['comparison']['S1:immediate-snipe']
    assert s1['closed'] == 2 and s1['pnl_lamports'] == sum(e['pnl_lamports'] for e in closed if e['trial'] == 'S1')
    assert led['w1_report']['decision'] == 'WAIT_INSUFFICIENT_DATA' and led['w1_report']['quoted_not_recomputed']
    assert led['flags']['profitability_demonstrated'] is False and led['flags']['master_operational_trade'] is False
    md = L.markdown(led)
    assert '**PASS**: 9 / 9' in md and 'WAIT_INSUFFICIENT_DATA' in md and 'not evidence of profitability' in md
    failed_fee = [e for e in closed if e['trial'] == 'L1_failed_fee_105000']
    assert failed_fee and all(e['decomposition']['failed_attempt_costs'] == 210_000 for e in failed_fee)
    timed = [e for e in closed if e['decomposition']['sale'] == 'timed']
    assert timed and all(e['checks']['exit_block_time'] and e['checks']['exit_slot'] for e in timed)
    assert all(e['checks']['fee_rate_ppm'] and e['checks']['fee_rate_evidence'] for e in closed)
    assert led['cycles_not_re_derived'] == 0 and led['independence'].startswith('partial')
    l1 = [e for e in led['entries'] if e['trial'] in ('L1', 'L1_failed_fee_105000', 'L1_event_horizon', 'M1_latency10')]
    assert l1 and all(e['checks']['l1_exit_plan_re_derived'] for e in l1)            # R02 R-1
    assert led['cycles_l1_plan_re_derived'] == len(l1) and 're-derived by the FROZEN observer' in led['independence']


@pytest.mark.parametrize('field, delta, expected', [
    ('received', 1, 'received'), ('tokens', -1, 'tokens'), ('spent', 1_000_000, 'tokens'),
    ('spent', 1, 'pnl_lamports'),                       # one lamport rounds to the same tokens: the P&L catches it
    ('pnl_lamports', 1, 'pnl_lamports'), ('tx_costs', 1, 'tx_costs'), ('entry_index', 1, 'entry_index'),
    ('entry_slot', 1, 'entry_slot'), ('decision_slot', -1, 'decision_slot'), ('fee_rate_ppm', 100, 'fee_rate_ppm'),
    ('exit_index', 1, 'exit_index'), ('exit_index', -1, 'exit_index'), ('failed_attempt_costs', 1, 'failed_attempt_costs'),
    ('entry_block_time', 1, 'entry_block_time'), ('decision_block_time', -1, 'decision_block_time'),
    ('exit_block_time', 5, 'exit_block_time'), ('exit_slot', 1, 'exit_slot'), ('hold_slots', 1, 'hold_slots'),
    ('net_return', 0.001, 'net_return')])
def test_a_consistently_rewritten_wrong_cycle_is_found(rehearsal, tmp_path, field, delta, expected):
    bundles = _copy(rehearsal, tmp_path)

    def mutate(bundle):
        row = _closed(bundle)[0]
        row[field] += delta
    _rewrite(bundles, 'S1', mutate)
    led = L.build_ledger(PACK, bundles, series=sus.load_series(rehearsal / 'sol_usd.json'))
    assert led['verdict'] == 'FAIL'
    assert any(m['trial'] == 'S1' and any(x.startswith(expected) for x in m['mismatches']) for m in led['mismatches'])


def _s1_cycle(rehearsal):
    _manifest, events_by_pool = L.timelines(PACK)
    bundle = json.loads(gzip.decompress((rehearsal / 'out' / 'bundles' / 'S1.json.gz').read_bytes()))
    pool = next(p for p in bundle['pools'] if p['trade']['outcome'] == 'closed'
                and p['trade']['exit_index'] > p['trade']['entry_index'] + 20)
    return dict(pool['trade']), events_by_pool[pool['pool']], bundle['params'], dict(kind='V2', rule=bundle['exit_rule'])


def _event_driven_row(row, events, params, rule, *, delay=0):
    """A cycle made CONSISTENT with an event-driven exit (optionally delayed by ``delay`` events)."""
    from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
    hold = L.derive_hold(events, row['entry_index'], row['spent'], row['tokens'], row['fee_rate_ppm'],
                         L._V2Rule(rule, events), params['latency_slots'])
    assert hold['sale'] == 'event_driven'
    trigger_index = hold['trigger']['index'] + delay
    pending = events[trigger_index].slot + params['latency_slots']
    last = max(j for j in range(len(events)) if events[j].slot <= pending)
    state = buy_exact_in(events[row['entry_index']].state_after(), row['spent'], row['fee_rate_ppm']).after
    for j in range(row['entry_index'] + 1, last + 1):
        state = L._replay_real(state, events[j])
    received = sell_exact_in(state, row['tokens'], row['fee_rate_ppm']).amount_out
    mark_state = buy_exact_in(events[row['entry_index']].state_after(), row['spent'], row['fee_rate_ppm']).after
    for j in range(row['entry_index'] + 1, trigger_index + 1):
        mark_state = L._replay_real(mark_state, events[j])
    mark = sell_exact_in(mark_state, row['tokens'], row['fee_rate_ppm']).amount_out
    pnl = received - row['spent'] - row['tx_costs'] - row['failed_attempt_costs']
    return dict(row, notes=[], exit_index=last, exit_slot=pending, exit_block_time=events[last].block_time,
                exit_trigger=dict(reason=hold['trigger']['reason'], index=trigger_index, mark=mark),
                hold_slots=events[last].slot - events[row['entry_index']].slot, received=received,
                pnl_lamports=pnl, net_return=pnl / (row['spent'] + row['tx_costs'] + row['failed_attempt_costs']))


def test_the_exit_is_re_derived_timed_and_event_driven(rehearsal):
    row, events, params, spec = _s1_cycle(rehearsal)
    assert 'clock_exit' in row['notes'] and L.verify_cycle(events, row, params, spec)[2] == []
    # timed sale: landing = entry block_time + max_hold_s + ceil(4 x 215 ms) = + 25 + 1 s
    assert row['exit_block_time'] == row['entry_block_time'] + 26
    assert any(m.startswith('exit_index') for m in L.verify_cycle(events, dict(row, exit_index=row['exit_index'] - 1),
                                                                     params, spec)[2])
    assert L.verify_cycle(events, row, params, None)[2] == ['exit_rule_unknown']
    # the same cycle under a rule with a take profit: the sale becomes event-driven at the first trigger
    rule = dict(spec['rule'], take_profit=0.01)
    driven = _event_driven_row(row, events, params, rule)
    checks, decomposition, bad = L.verify_cycle(events, driven, params, dict(kind='V2', rule=rule))
    assert bad == [] and checks['exit_trigger'] and decomposition['sale'] == 'event_driven'
    # C-L3: a consistently DELAYED trigger (exit recomputed later) is found
    late = _event_driven_row(row, events, params, rule, delay=3)
    bad = L.verify_cycle(events, late, params, dict(kind='V2', rule=rule))[2]
    assert any(m.startswith('exit_index') or m.startswith('exit_trigger') for m in bad)
    # and a timed sale that a trigger should have pre-empted is found too (C-L3)
    bad = L.verify_cycle(events, row, params, dict(kind='V2', rule=rule))[2]
    assert any(m.startswith('exit_index') for m in bad)


def test_fee_rate_is_re_derived_from_its_source(rehearsal):
    row, events, params, spec = _s1_cycle(rehearsal)
    k = row['decision_index']
    assert L.derive_fee_rate(events, k, row, params)[0] == row['fee_rate_ppm']
    assert L.derive_fee_rate(events, k, dict(row, fee_rate_source='pool_event_at_decision'), params)[0] == L._rate(events[k])
    assert L.derive_fee_rate(events, k, dict(row, fee_rate_source='model'), params)[2] == \
        'fee_rate_source_model_without_a_rate_parameter'
    assert L.derive_fee_rate(events, k, dict(row, fee_rate_source='model'), dict(params, fee_rate_ppm=12500))[0] == 12500
    assert L.verify_cycle(events, dict(row, fee_rate_source='guess'), params, spec)[2] == ['unknown_fee_rate_source:guess']
    from bot.market.replay import causal_fee_rate
    for j in range(len(events)):                                          # the own copy equals the frozen rule
        assert L._causal_rate(events[:j + 1]) == causal_fee_rate(events[:j + 1])


def test_tampering_an_l1_master_cycle_is_found_even_with_a_recomputed_internal_hash(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, 'L1', lambda b: _closed(b)[0].__setitem__('received', _closed(b)[0]['received'] + 7))
    led = L.build_ledger(PACK, bundles, series=sus.load_series(rehearsal / 'sol_usd.json'))
    assert led['verdict'] == 'FAIL' and led['mismatches'][0]['trial'] == 'L1'


def test_file_and_hash_and_series_guards(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)
    path = bundles / 'S2.json.gz'
    path.write_bytes(path.read_bytes() + b'\0')
    with pytest.raises(L.LedgerError, match='bundle_file_changed:S2'):
        L.build_ledger(PACK, bundles)
    bundles = _copy(rehearsal, tmp_path / 'b')
    _rewrite(bundles, 'L1', lambda b: _closed(b)[0].__setitem__('spent', 1), rehash_l1=False)
    with pytest.raises(L.LedgerError, match='bundle_internal_hash_mismatch:L1'):
        L.build_ledger(PACK, bundles)
    other = dict(json.loads((rehearsal / 'sol_usd.json').read_text()))
    other['points'][0]['price'] += 1
    (tmp_path / 'other.json').write_text(json.dumps(other))
    with pytest.raises(L.LedgerError, match='series_is_not_the_one_replayed'):
        L.build_ledger(PACK, rehearsal / 'out' / 'bundles', series=sus.load_series(tmp_path / 'other.json'))


def test_a_pool_missing_from_the_export_is_not_verified(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, 'S1', lambda b: [p.__setitem__('pool', 'X' * 44) for p in b['pools'] if p['trade']['entry_index'] is not None][:1])
    led = L.build_ledger(PACK, bundles, series=sus.load_series(rehearsal / 'sol_usd.json'))
    assert led['verdict'] == 'FAIL' and ['pool_not_in_the_exported_pools'] in [m['mismatches'] for m in led['mismatches']]


def test_independent_landing_rule():
    class E:
        def __init__(self, slot):
            self.slot = slot
    events = [E(s) for s in (10, 10, 12, 14, 15, 20)]
    assert L._landing(events, 0, 4) == 3 and L._landing(events, 0, 5) == 4 and L._landing(events, 4, 4) == 4
    assert L._landing(events, 5, 4) == 5 and L._landing(events, 2, 0) == 2


def test_command_writes_the_ledger_and_its_summary(rehearsal, tmp_path):
    out = io.StringIO()
    with pytest.raises(L.LedgerError, match='output_directory_already_exists'):
        L.main(['--pools', str(PACK), '--bundles', str(rehearsal / 'out' / 'bundles'), '--out', str(tmp_path)],
               out=io.StringIO())
    code = L.main(['--pools', str(PACK), '--bundles', str(rehearsal / 'out' / 'bundles'),
                   '--report', str(rehearsal / 'out' / 'w1_report.json'), '--series', str(rehearsal / 'sol_usd.json'),
                   '--out', str(tmp_path / 'ledger')], out=out)
    summary = json.loads(out.getvalue())
    assert code == 0 and summary['verdict'] == 'PASS' and summary['cycles_verified'] == 9
    assert summary['ledger_sha256'] == hashlib.sha256((tmp_path / 'ledger' / 'ledger.json').read_bytes()).hexdigest()
    assert (tmp_path / 'ledger' / 'ledger.md').read_text().startswith('# W1 ledger')
    bundles = _copy(rehearsal, tmp_path / 'c')
    _rewrite(bundles, 'S1', lambda b: _closed(b)[0].__setitem__('received', _closed(b)[0]['received'] - 1))
    out = io.StringIO()
    assert L.main(['--pools', str(PACK), '--bundles', str(bundles), '--out', str(tmp_path / 'l2')], out=out) == 4


class _Fee:
    """A fee-bearing event reduced to what the fee-rate rules read."""

    def __init__(self, fee, basis=1000, side='buy'):
        self.side, self.amount_in, self.amount_out = side, basis, basis
        self.protocol_fee, self.platform_fee, self.creator_fee, self.share_fee = fee, 0, 0, 0


def test_causal_fee_rate_copy_equals_the_frozen_rule_on_wide_and_breaking_intervals():
    from bot.market.replay import causal_fee_rate
    # ceil(1000 r / 1e6) = 13 -> r in [12001, 13000]; 19 -> [18001, 19000]: disjoint, the run stops there
    run = [_Fee(19), _Fee(19), _Fee(13), _Fee(0), _Fee(13)]
    rate, evidence = L._causal_rate(run)
    assert (rate, evidence['interval_ppm'], evidence['events_used'], evidence['events_skipped']) == \
        (13000, [12001, 13000], 2, 1)
    assert (rate, evidence) == causal_fee_rate(run)
    narrower = [_Fee(19), _Fee(13), _Fee(126, basis=10_000)]          # [12501, 12600] inside [12001, 13000]
    assert L._causal_rate(narrower)[0] == 12600 == causal_fee_rate(narrower)[0]
    # an event before the disjoint one is NOT read, even if it would narrow the interval (the run stops)
    stopped = [_Fee(126, basis=10_000), _Fee(19), _Fee(13)]
    assert L._causal_rate(stopped)[0] == 13000 == causal_fee_rate(stopped)[0]
    later = [_Fee(13), _Fee(19), _Fee(19)]
    assert L._causal_rate(later) == causal_fee_rate(later) and L._causal_rate(later)[0] == 19000


def test_l1_exit_rule_take_profit_and_stop_loss(rehearsal):
    row, events, params, _spec = _s1_cycle(rehearsal)
    land, tokens, spent, rate = row['entry_index'], row['tokens'], row['spent'], row['fee_rate_ppm']
    l1_params = dict(params, exit_horizon_ms=30_000)
    rule = L._L1Rule(dict(tp_pct=1, sl_pct=50), dict(clock_horizon=True), l1_params, land, events)
    hold = L.derive_hold(events, land, spent, tokens, rate, rule, params['latency_slots'])
    assert hold['sale'] == 'event_driven' and hold['trigger']['reason'] == 'take_profit'
    first = hold['trigger']['index']
    assert hold['trigger']['mark'] >= spent * 1.01
    from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
    state = buy_exact_in(events[land].state_after(), spent, rate).after
    for j in range(land + 1, first):                       # no earlier event reached the take profit
        state = L._replay_real(state, events[j])
        assert sell_exact_in(state, tokens, rate).amount_out < spent * 1.01
    stop = L._L1Rule(dict(tp_pct=1, sl_pct=99.9), dict(clock_horizon=True), l1_params, land, events)
    assert stop.trigger(first, events[land].block_time, spent, 0) == 'stop_loss'      # stop loss has precedence
    assert stop.trigger(first, events[land].block_time, spent, spent * 2) == 'take_profit'
    event_horizon = L._L1Rule(dict(tp_pct=500, sl_pct=99.9), dict(clock_horizon=False), l1_params, land, events)
    late = next(j for j in range(land, len(events)) if (events[j].block_time - events[land].block_time) >= 30)
    assert event_horizon.trigger(late, events[land].block_time, spent, spent) == 'exit_horizon'
    assert event_horizon.trigger(land, events[land].block_time, spent, spent) is None


class _At:
    def __init__(self, block_time):
        self.block_time = block_time


def test_exact_equality_bounds_of_take_profit_and_stop_loss():
    """R02 O-V3-1: the frozen rules use >= for take profit and <= for stop loss (L1 exact, V2 float ratio)."""
    events = [_At(100), _At(101)]
    rule = dict(stop_loss=0.25, take_profit=0.25, trailing=None, exit_progress_ppm=None, max_hold_s=None, clock_exit=False)
    assert L._V2Rule(rule, events).trigger(1, 100, 1000, 1250) == 'take_profit'        # ratio == 1 + tp
    assert L._V2Rule(rule, events).trigger(1, 100, 1000, 1249) is None
    assert L._V2Rule(rule, events).trigger(1, 100, 1000, 750) == 'stop_loss'           # ratio == 1 - sl
    assert L._V2Rule(rule, events).trigger(1, 100, 1000, 751) is None
    l1 = L._L1Rule(dict(tp_pct=25, sl_pct=25), dict(clock_horizon=True), dict(exit_horizon_ms=30_000), 0, events)
    assert l1.trigger(1, 100, 1000, 1250) == 'take_profit'                               # mark == spent x (1 + tp)
    assert l1.trigger(1, 100, 1000, 1249) is None
    assert l1.trigger(1, 100, 1000, 750) == 'stop_loss'                                  # mark == spent x (1 - sl)
    assert l1.trigger(1, 100, 1000, 751) is None


def test_r1_a_consistently_rewritten_l1_exit_plan_is_found(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)

    def mutate(bundle):
        row = _closed(bundle)[0]
        row['exit_conditions'] = dict(row['exit_conditions'], tp_pct=row['exit_conditions']['tp_pct'] + 1)
    _rewrite(bundles, 'L1', mutate)
    series = sus.load_series(rehearsal / 'sol_usd.json')
    led = L.build_ledger(PACK, bundles, series=series)
    assert led['verdict'] == 'FAIL'
    assert any(m['trial'] == 'L1' and any(x.startswith('l1_exit_plan') for x in m['mismatches']) for m in led['mismatches'])
    # without the replayed series the plan cannot be re-derived: never a silent pass
    led = L.build_ledger(PACK, rehearsal / 'out' / 'bundles')
    assert led['verdict'] == 'FAIL' and all(
        m['mismatches'] == ['l1_plan_not_re_derived'] for m in led['mismatches'] if m['trial'].startswith(('L1', 'M1')))


def test_ledger_reads_one_pool_at_a_time_under_lazy(rehearsal):
    from w1aux import lazy
    series = sus.load_series(rehearsal / 'sol_usd.json')
    eager = L.build_ledger(PACK, rehearsal / 'out' / 'bundles', series=series)
    lazy.PARSES.clear()
    with lazy.lazy_archives():
        lazy_led = L.build_ledger(PACK, rehearsal / 'out' / 'bundles', series=series)
    assert json.dumps(eager, sort_keys=True) == json.dumps(lazy_led, sort_keys=True)
    assert lazy.PARSES and all(n <= 2 for n in lazy.PARSES.values())        # creator history pass + verification pass
