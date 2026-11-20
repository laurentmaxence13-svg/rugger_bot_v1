"""W1 BUY/SELL ledger: independent re-verification of every simulated cycle, and comparison report.

Outside the frozen tree, offline, read-only. It never changes a rule, never re-runs a policy and
never recomputes the W1 decision: it reads the saved bundles (their file sha256 checked against
SHA256SUMS.json and their internal bundle_sha256) and the exported pools (MANIFEST sha256
checked by the frozen loader), and for each cycle with an entry it RE-DERIVES, with its own loop
and only the frozen curve arithmetic (launchlab_curve.buy_exact_in / sell_exact_in) and event
decoding:

* causality: decision <= entry <= exit; decision and entry slot, signature and block_time read
  from the events; the entry lands after every real event of slot <= decision slot + latency_slots;
* the fee rate of our fills, re-derived from its declared source (causal interval of the fee-bearing
  events up to the decision, or the decision event's implied rate) (R02 C-L1);
* the exit, re-derived by an own holding loop in the frozen replay order: after each real event the
  exit rule of the trial (L1: scorer plan tp/sl at entry, ExitOptions; V2: ExitRule) is applied to
  the exact net sell quote; a trigger sells at trigger slot + latency (event-driven: exit_index,
  exit_slot and trigger reason/index/mark must match); without a trigger the timed sale lands at
  entry block_time + horizon (L1 ceil(exit_horizon_ms/1000), V2 max_hold_s) + ceil(latency x 215 ms)
  seconds, applying exactly the real events with block_time <= landing (exit_block_time, exit_slot
  estimate and exit_index must match) (R02 C-L2, C-L3);
* the buy: tokens = buy_exact_in(state after the landing event, spent, fee rate);
* the holding: every later real trade replayed with its own exact-in amount on the shifted curve;
* the sale: received = sell_exact_in(shifted state, tokens, fee rate);
* the P&L: pnl = received - spent - tx_costs - failed_attempt_costs, tx_costs = 2 x (base +
  priority) for a sale, net_return = pnl / (spent + tx_costs + failed);
* an exact decomposition (rational arithmetic, mid = curve spot quote/base):
      pnl = market_move - slippage - launchlab_fees - tx_costs - failed_attempt_costs
  market_move = tokens x (mid before our sale - mid after our buy)   (other traders, during the hold)
  slippage    = (buy_net - tokens x mid_before_buy) + (tokens x mid_before_sale - sell_gross)
                - tokens x (mid_after_buy - mid_before_buy)            (round trip of our own orders)
  launchlab_fees = buy fee + sell fee (quote units, at the fee rate used for our fills).

Independence is partial (INDEPENDENCE below). Any difference with the bundle is a MISMATCH and the
ledger verdict is FAIL. Research only
(HISTORICAL_REPLAY): not an operational Master trade, not counted toward the 50-cycle /
20-creator thresholds, and a verified cycle is not evidence of profitability.
"""
import gzip
import hashlib
import json
from fractions import Fraction
from pathlib import Path

from bot.market.collector import summarize
from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import implied_fee_rate_ppm
from bot.p4 import historical_research_replay as hrr

SCHEMA = 'rugger-w1-ledger-v1'
L1_SCHEMA = 'rugger-historical-research-replay-v1'
V2_SCHEMA = 'rugger-master-v2-research-v1'
LAMPORTS_PER_SOL = 1_000_000_000


class LedgerError(RuntimeError):
    pass


INDEPENDENCE = ('partial: own loops for landing, fee rate (causal interval), holding, exit triggers, timed '
                'landing and P&L; the frozen curve arithmetic (launchlab_curve), event decoding (implied fee '
                'rate) and pool timeline (summarize, usable_timeline) are reused; the L1 exit plan (tp/sl) is '
                're-derived by the FROZEN observer at the decision (R-1); policy entry decisions are not re-derived')


# ----------------------------------------------------------------- inputs
def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value):
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def _load_bundle(bundles_dir, trial_id, sha):
    data = (Path(bundles_dir) / f'{trial_id}.json.gz').read_bytes()
    if _sha_bytes(data) != sha:
        raise LedgerError(f'bundle_file_changed:{trial_id}')
    bundle = json.loads(gzip.decompress(data))
    if bundle.get('schema') not in (L1_SCHEMA, V2_SCHEMA):
        raise LedgerError(f'unknown_bundle_schema:{trial_id}')
    return bundle


def _sums(bundles_dir):
    return json.loads((Path(bundles_dir) / 'SHA256SUMS.json').read_text(encoding='utf-8'))


def load_bundles(bundles_dir):
    """{trial id: bundle}, every file checked against SHA256SUMS.json."""
    sums = _sums(bundles_dir)
    return {trial_id: _load_bundle(bundles_dir, trial_id, sha) for trial_id, sha in sorted(sums.items())}, sums


def timelines(pools_dir):
    """{pool: events} with the frozen loader (MANIFEST sha256 checked) and the frozen usable timeline."""
    manifest_sha, _digests, pools, _manifest = hrr.load_fixtures(pools_dir)
    out = {}
    for _entry, archive in pools:
        summary, timeline = summarize(archive)
        try:
            timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
        except hrr.PoolExcluded:
            continue
        out[archive.pool] = timeline.events
    return manifest_sha, out


def cycles(trial_id, bundle):
    """(arm, pool, row, params, exit spec) for every pool row of a bundle."""
    params = bundle['params']
    if bundle['schema'] == L1_SCHEMA:
        # The bundle records exit_options only when one is enabled (frozen run_replay); absent = all off.
        spec = dict(kind='L1', options=bundle.get('exit_options') or dict(clock_horizon=False, max_hold=False,
                                                                           trailing_stop=False))
        for pool in bundle['pools']:
            for arm, row in sorted(pool['arms'].items()):
                yield arm, pool['pool'], row, params, spec
    else:
        spec = dict(kind='V2', rule=bundle['exit_rule'])
        for pool in bundle['pools']:
            yield bundle['policy'], pool['pool'], pool['trade'], params, spec


# ----------------------------------------------------------------- independent re-derivation
CLOCK_SLOT_MS = 215                  # protocol: latency slots -> whole seconds of a timed sale (W1 v2.2 D3)
FEE_DENOMINATOR = 1_000_000


def _rate(event):
    return implied_fee_rate_ppm({
        'side': event.side, 'amount_in': event.amount_in, 'amount_out': event.amount_out,
        'protocol_fee': event.protocol_fee, 'platform_fee': event.platform_fee,
        'creator_fee': event.creator_fee, 'share_fee': event.share_fee})


def _fee_interval(event):
    """Integer rates r with ceil(basis * r / D) == the event's fee, as (low, high); None if uninformative."""
    fees = event.protocol_fee + event.platform_fee + event.creator_fee + event.share_fee
    basis = event.amount_in if event.side == 'buy' else event.amount_out + fees
    if basis <= 0 or fees <= 0:
        return None
    low, high = ((fees - 1) * FEE_DENOMINATOR) // basis + 1, min((fees * FEE_DENOMINATOR) // basis, FEE_DENOMINATOR - 1)
    return (low, high) if low <= high else None


def _causal_rate(events):
    """Largest rate compatible with the longest consistent run of fee-bearing events ending at the decision."""
    low = high = None
    used = skipped = 0
    for event in reversed(events):
        interval = _fee_interval(event)
        if interval is None:
            skipped += 1
            continue
        new_low = interval[0] if low is None else max(low, interval[0])
        new_high = interval[1] if high is None else min(high, interval[1])
        if new_low > new_high:
            break
        low, high, used = new_low, new_high, used + 1
    if high is None:
        return _rate(events[-1]), dict(rule='no_fee_bearing_event_decision_event_rate', interval_ppm=None,
                                       events_used=0, events_skipped=skipped)
    return high, dict(rule='largest_rate_compatible_with_the_longest_consistent_run_up_to_the_decision',
                      interval_ppm=[low, high], events_used=used, events_skipped=skipped)


def derive_fee_rate(events, k, row, params):
    """(rate, evidence or None, mismatch or None), re-derived from the row's declared source (C-L1)."""
    source = row.get('fee_rate_source')
    if source == 'pool_events_causal_interval':
        rate, evidence = _causal_rate(events[:k + 1])
        return rate, evidence, None
    if source == 'pool_event_at_decision':
        return _rate(events[k]), None, None
    if source == 'model':
        rate = params.get('fee_rate_ppm')
        return rate, None, None if type(rate) is int else 'fee_rate_source_model_without_a_rate_parameter'
    return None, None, f'unknown_fee_rate_source:{source}'


def _replay_real(state, event):
    if event.side == 'buy':
        return buy_exact_in(state, event.amount_in, _rate(event)).after
    if event.side == 'sell':
        return sell_exact_in(state, event.amount_in, _rate(event)).after
    raise LedgerError(f'unknown_event_side:{event.side}')


def _mid(state):
    return Fraction(state.quote_reserve, state.base_reserve)


def _spot_real(event):
    state = event.state_after()
    return Fraction(state.quote_reserve, state.base_reserve)


def _landing(events, decision_index, latency_slots):
    limit, index = events[decision_index].slot + latency_slots, decision_index
    while index + 1 < len(events) and events[index + 1].slot <= limit:
        index += 1
    return index


def _clock_latency_s(latency_slots):
    return max(1, -(-(latency_slots * CLOCK_SLOT_MS) // 1000))


def _slots_for_ms(duration_ms):
    floor = 190 if duration_ms < 60_000 else 200            # protocol slot floors (R02 C1)
    return -(-duration_ms // floor)


class _L1Rule:
    """The L1 research arm's exit (scorer plan at entry: tp_pct, sl_pct, optional trailing / hold)."""

    def __init__(self, plan, options, params, entry_index, events):
        self.take = Fraction(str(plan['tp_pct'])) / 100
        self.stop = Fraction(str(plan['sl_pct'])) / 100
        self.trailing_pct, self.hold_s = plan.get('trailing_stop_pct'), plan.get('hold_seconds')
        self.clock, self.horizon_ms = options['clock_horizon'], params['exit_horizon_ms']
        self.entry_price = self.peak = None
        self.entry_index, self.events = entry_index, events

    def deadline(self, entry_time):
        return entry_time + -(-self.horizon_ms // 1000) if self.clock else None

    def trigger(self, j, entry_time, spent, mark):
        elapsed_ms = (self.events[j].block_time - entry_time) * 1000
        trailing = False
        if type(self.trailing_pct) in (int, float) and self.trailing_pct > 0:
            if self.entry_price is None:
                self.entry_price = self.peak = _spot_real(self.events[self.entry_index])
            price = _spot_real(self.events[j])
            self.peak = max(self.peak, price)
            trailing = self.peak > self.entry_price and price <= self.peak * (1 - Fraction(str(self.trailing_pct)) / 100)
        held = type(self.hold_s) is int and self.hold_s > 0 and elapsed_ms >= self.hold_s * 1000
        if mark <= spent * (1 - self.stop):
            return 'stop_loss'
        if trailing:
            return 'trailing_stop'
        if held:
            return 'max_hold'
        if mark >= spent * (1 + self.take):
            return 'take_profit'
        if not self.clock and elapsed_ms >= self.horizon_ms:
            return 'exit_horizon'
        return None


class _V2Rule:
    """The V2 harness ExitRule (stop loss, trailing, pre-migration, max hold, take profit; clock exit)."""

    def __init__(self, rule, events):
        self.rule, self.events, self.peak = rule, events, None

    def deadline(self, entry_time):
        return entry_time + self.rule['max_hold_s'] if self.rule.get('clock_exit') else None

    def trigger(self, j, entry_time, spent, mark):
        rule = self.rule
        ratio = mark / spent
        self.peak = mark if self.peak is None else max(self.peak, mark)
        held_s = self.events[j].block_time - entry_time
        trailing = rule['trailing'] is not None and self.peak > spent and mark <= self.peak * (1 - rule['trailing'])
        near = (rule['exit_progress_ppm'] is not None
                and self.events[j].state_after().progress_ppm >= rule['exit_progress_ppm'])
        if rule['stop_loss'] is not None and ratio <= 1 - rule['stop_loss']:
            return 'stop_loss'
        if trailing:
            return 'trailing_stop'
        if near:
            return 'pre_migration'
        if rule['max_hold_s'] is not None and not rule.get('clock_exit') and held_s >= rule['max_hold_s']:
            return 'max_hold'
        if rule['take_profit'] is not None and ratio >= 1 + rule['take_profit']:
            return 'take_profit'
        return None


def derive_hold(events, land, spent, tokens, rate, rule, latency_slots):
    """Own holding loop (same ordering as the frozen replay): the exit the rule implies, re-derived."""
    entry_time = events[land].block_time
    deadline = rule.deadline(entry_time)
    landing = None if deadline is None else deadline + _clock_latency_s(latency_slots)
    state = buy_exact_in(events[land].state_after(), spent, rate).after
    pending, trigger, j = None, None, land + 1
    while True:
        if pending is not None and (j >= len(events) or events[j].slot > pending):
            return dict(outcome='closed', sale='event_driven', exit_index=j - 1, landing_slot=pending,
                        trigger=trigger, state=state)
        if pending is None and landing is not None and (j >= len(events) or events[j].block_time > landing):
            return dict(outcome='closed', sale='timed', exit_index=j - 1, landing_time=landing, trigger=None,
                        state=state)
        if j >= len(events):
            return dict(outcome='open_at_end', sale=None, exit_index=len(events) - 1, trigger=None, state=state)
        try:
            state = _replay_real(state, events[j])
        except CurveError as exc:
            return dict(outcome='migrated_unpriced' if str(exc) == 'buy_crosses_migration_boundary'
                        else 'counterfactual_divergence', sale=None, exit_index=None, trigger=None, state=state)
        if state.remaining_base == 0:
            return dict(outcome='migrated_unpriced', sale=None, exit_index=None, trigger=None, state=state)
        if pending is None:
            try:
                mark = sell_exact_in(state, tokens, rate).amount_out
            except CurveError:
                mark = 0
            reason = rule.trigger(j, entry_time, spent, mark)
            if reason:
                pending, trigger = events[j].slot + latency_slots, dict(reason=reason, index=j, mark=mark)
        j += 1


def verify_cycle(events, row, params, spec=None):
    """Re-derive one cycle; return (checks, decomposition or None, mismatches)."""
    bad, checks = [], {}

    def check(name, ours, theirs):
        checks[name] = ours == theirs
        if ours != theirs:
            bad.append(f'{name}:ledger={ours}:bundle={theirs}')

    k, land = row['decision_index'], row['entry_index']
    if not (type(k) is int and type(land) is int and 0 <= k <= land < len(events)):
        return checks, None, ['indices_out_of_order_or_range']
    check('decision_slot', events[k].slot, row['decision_slot'])
    check('decision_signature', events[k].signature, row['decision_signature'])
    check('decision_block_time', events[k].block_time, row['decision_block_time'])
    check('entry_index', _landing(events, k, params['latency_slots']), land)
    check('entry_slot', events[land].slot, row['entry_slot'])
    check('entry_block_time', events[land].block_time, row['entry_block_time'])
    rate, evidence, problem = derive_fee_rate(events, k, row, params)
    if problem:
        return checks, None, bad + [problem]
    check('fee_rate_ppm', rate, row['fee_rate_ppm'])
    if evidence is not None:
        check('fee_rate_evidence', evidence, row.get('fee_rate_evidence'))
    state0 = events[land].state_after()
    try:
        buy = buy_exact_in(state0, row['spent'], rate)
    except CurveError as exc:
        return checks, None, bad + [f'buy_refused:{exc}']
    check('tokens', buy.amount_out, row['tokens'])
    own = 2 if row['outcome'] in ('closed', 'open_at_end') else 1
    check('failed_attempt_costs', params['failed_attempt_fee_lamports'] * own, row['failed_attempt_costs'])
    if row['outcome'] not in ('closed', 'open_at_end'):
        check('tx_costs', params['base_fee_lamports'] + params['priority_fee_lamports'], row['tx_costs'])
        return checks, None, bad
    if spec is None:
        return checks, None, bad + ['exit_rule_unknown']
    rule = (_L1Rule(row['exit_conditions'], spec['options'], params, land, events) if spec['kind'] == 'L1'
            else _V2Rule(spec['rule'], events))
    hold = derive_hold(events, land, row['spent'], buy.amount_out, rate, rule, params['latency_slots'])
    check('outcome', hold['outcome'], row['outcome'])
    check('exit_index', hold['exit_index'], row['exit_index'])
    if hold['outcome'] != row['outcome'] or hold['exit_index'] != row['exit_index']:
        return checks, None, bad
    last, timed = hold['exit_index'], hold['sale'] == 'timed'
    check('sale_kind', 'timed' if timed else 'not_timed', 'timed' if 'clock_exit' in row['notes'] else 'not_timed')
    if row['outcome'] == 'closed':
        if timed:
            check('exit_block_time', hold['landing_time'], row['exit_block_time'])
            check('exit_slot', events[last].slot + _slots_for_ms((hold['landing_time'] + 1 - events[last].block_time) * 1000)
                  + params['latency_slots'], row['exit_slot'])
        else:
            check('exit_slot', hold['landing_slot'], row['exit_slot'])
            trig = row.get('exit_trigger') or {}
            check('exit_trigger', (hold['trigger']['reason'], hold['trigger']['index'], hold['trigger']['mark']),
                  (trig.get('reason'), trig.get('index'), trig.get('mark')))
        check('hold_slots', events[last].slot - events[land].slot, row['hold_slots'])
    state = hold['state']
    try:
        sale = sell_exact_in(state, buy.amount_out, rate)
    except CurveError as exc:
        return checks, None, bad + [f'counterfactual_refused:{exc}']
    check('received', sale.amount_out, row['received'])
    check('tx_costs', 2 * (params['base_fee_lamports'] + params['priority_fee_lamports']), row['tx_costs'])
    pnl = row['received'] - row['spent'] - row['tx_costs'] - row['failed_attempt_costs']
    if row['outcome'] == 'closed':
        check('pnl_lamports', pnl, row['pnl_lamports'])
        cost = row['spent'] + row['tx_costs'] + row['failed_attempt_costs']
        checks['net_return'] = row['net_return'] is not None and abs(row['net_return'] - pnl / cost) < 1e-12
        if not checks['net_return']:
            bad.append('net_return')
    tokens = buy.amount_out
    mid_before_buy, mid_after_buy, mid_before_sale = _mid(state0), _mid(buy.after), _mid(state)
    buy_net, sell_gross = row['spent'] - buy.fee, sale.amount_out + sale.fee
    market_move = tokens * (mid_before_sale - mid_after_buy)
    slippage = ((buy_net - tokens * mid_before_buy) + (tokens * mid_before_sale - sell_gross)
                - tokens * (mid_after_buy - mid_before_buy))
    fees = buy.fee + sale.fee
    identity = market_move - slippage - fees - row['tx_costs'] - row['failed_attempt_costs']
    checks['decomposition_identity_exact'] = identity == pnl
    if identity != pnl:
        bad.append('decomposition_identity')
    decomposition = dict(market_move=_lamports(market_move), slippage=_lamports(slippage),
                         launchlab_buy_fee=buy.fee, launchlab_sell_fee=sale.fee,
                         tx_costs=row['tx_costs'], failed_attempt_costs=row['failed_attempt_costs'],
                         pnl=pnl, mid_before_buy=_price(mid_before_buy), mid_after_buy=_price(mid_after_buy),
                         mid_before_sale=_price(mid_before_sale),
                         sale='timed' if timed else 'event_driven' if hold['sale'] else 'open_at_end_mark',
                         real_events_during_hold=last - land)
    return checks, decomposition, bad


def _lamports(value):
    """Exact rational, reported in lamports to 3 decimals (the identity is checked exactly)."""
    return round(float(value), 3)


def _price(value):
    return float(value)


# ----------------------------------------------------------------- ledger and comparison
def _usd(series, row, pnl):
    if series is None or pnl is None or row.get('exit_block_time') is None:
        return None, 'no_series' if series is None else None
    point, _age, refusal = series.as_of(slot=row['exit_slot'], transaction_index=0,
                                        decision_ms=row['exit_block_time'] * 1000)
    if point is None:
        return None, refusal
    from bot.p4.sol_usd_series import price_usd
    return round(float(Fraction(pnl, LAMPORTS_PER_SOL) * price_usd(point)), 6), None


def _entry_for(trial_id, arm, pool, row, params, spec, events, plan, series):
    entry = dict(trial=trial_id, arm=arm, pool=pool, outcome=row['outcome'],
                 decision=dict(index=row['decision_index'], slot=row['decision_slot'],
                               signature=row['decision_signature'], block_time=row['decision_block_time']),
                 buy=dict(index=row['entry_index'], slot=row['entry_slot'], block_time=row['entry_block_time'],
                          spent_lamports=row['spent'], tokens=row['tokens'], fee_rate_ppm=row['fee_rate_ppm'],
                          fee_rate_source=row['fee_rate_source']),
                 sell=dict(index=row['exit_index'], slot=row['exit_slot'], block_time=row['exit_block_time'],
                           received_lamports=row['received'], trigger=row['exit_trigger']),
                 pnl_lamports=row['pnl_lamports'], net_return=row['net_return'])
    if events is None:
        entry.update(verified=False, mismatches=['pool_not_in_the_exported_pools'])
    elif row['outcome'] in ('closed', 'open_at_end') or row['outcome'].endswith('_unpriced') \
            or row['outcome'] == 'open_at_window_end':
        checks, decomposition, bad = verify_cycle(events, row, params, spec)
        if spec['kind'] == 'L1':
            plan_bad = ['l1_plan_not_re_derived'] if plan is None else _plan_check(row, spec, plan)
            checks['l1_exit_plan_re_derived'] = not plan_bad
            bad = bad + plan_bad
        entry.update(verified=not bad, checks=checks, decomposition=decomposition, mismatches=bad,
                     scope='full' if row['outcome'] in ('closed', 'open_at_end') else 'entry_only')
    else:
        entry.update(verified=None, mismatches=[], note='not_re_derived:' + row['outcome'])
    if row['outcome'] == 'closed':
        entry['pnl_usd'], entry['usd_refusal'] = _usd(series, row, row['pnl_lamports'])
    return entry


def derive_l1_plans(archive, timeline, params, series, history, indices):
    """{decision index: (exit_conditions, scorer_exit_plan)} from the FROZEN observer, built as in
    hrr.replay_pool and fed the causal histories in increasing order up to the largest index (R02 R-1)."""
    facts = hrr.creation_facts(archive)
    prior = 0
    if history is not None and facts['signed_creator_verified']:
        prior = history.prior_launches(facts['creator'], hrr._tx_key(archive.transactions[facts['creation_signature']]))
    observer = hrr._PoolObserver(archive, timeline, facts, params, series, prior)
    events, out = timeline.events, {}
    for index in range(max(indices) + 1):
        result = observer.observe(events[:index + 1])
        if index in indices:
            out[index] = (result['exit_conditions'], result.get('scorer_exit_plan'))
    return out


def _plan_check(row, spec, derived):
    plan, scorer = derived
    if plan is None:
        return ['l1_plan_not_available_at_the_decision']
    expected = dict(plan)
    if spec['options'].get('trailing_stop'):
        expected['trailing_stop_pct'] = (scorer or {}).get('trailing_stop_pct')
    if spec['options'].get('max_hold'):
        expected['hold_seconds'] = (scorer or {}).get('hold_seconds')
    return [] if expected == row['exit_conditions'] else [f"l1_exit_plan:ledger={expected}:bundle={row['exit_conditions']}"]


def build_ledger(pools_dir, bundles_dir, *, report_path=None, series=None):
    """Bundles checked and read ONE AT A TIME (only the rows with an entry and the pool counts are kept,
    R01 T-1 memory); pools then read ONE AT A TIME (with w1aux.lazy, one archive in memory)."""
    sums = _sums(bundles_dir)
    rows_by_pool, l1_runs, counts = {}, {}, {}
    for trial_id, sha in sorted(sums.items()):
        bundle = _load_bundle(bundles_dir, trial_id, sha)
        body = {k: v for k, v in bundle.items() if k != 'bundle_sha256'}
        if bundle['schema'] == L1_SCHEMA and hrr._sha(body) != bundle['bundle_sha256']:
            raise LedgerError(f'bundle_internal_hash_mismatch:{trial_id}')
        replayed = (bundle.get('sol_usd_series') or {}).get('sha256')
        if series is not None and replayed is not None and replayed != series.sha256:
            raise LedgerError(f'series_is_not_the_one_replayed:{trial_id}')
        if bundle['schema'] == V2_SCHEMA and bundle['flags'].get('sol_usd_used') is not False and replayed is None:
            raise LedgerError(f'v2_bundle_uses_sol_usd_without_a_series:{trial_id}')
        if bundle['schema'] == L1_SCHEMA:
            l1_runs[trial_id] = dict(params=hrr.ReplayParams(**bundle['params']),
                                     series=series if replayed is not None else None,
                                     derivable=replayed is None or series is not None,
                                     history=(bundle.get('creator_history') or {}).get('sha256'))
        _count_pools(counts, trial_id, bundle)
        for arm, pool, row, params, spec in cycles(trial_id, bundle):
            if row['entry_index'] is not None:
                rows_by_pool.setdefault(pool, []).append((trial_id, arm, row, params, spec))
        del bundle
    manifest_sha, _digests, pools, _manifest = hrr.load_fixtures(pools_dir)
    history = None
    if any(run['history'] for run in l1_runs.values()):
        history = hrr.CreatorHistory.from_archives([archive for _entry, archive in pools], 'manifest')
        if any(run['history'] not in (None, history.sha256) for run in l1_runs.values()):
            raise LedgerError('creator_history_differs_from_the_replayed_one')
    entries, mismatches, seen = [], [], set()
    for _entry, archive in pools:
        todo = rows_by_pool.get(archive.pool)
        if not todo:
            continue
        seen.add(archive.pool)
        summary, timeline = summarize(archive)
        try:
            timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
        except hrr.PoolExcluded:
            timeline = None
        plans = {}
        for trial_id, run in l1_runs.items():
            indices = {row['decision_index'] for t, _a, row, _p, _s in todo if t == trial_id}
            if indices and timeline is not None and run['derivable']:
                plans[trial_id] = derive_l1_plans(archive, timeline, run['params'], run['series'],
                                                  history if run['history'] else None, indices)
        for trial_id, arm, row, params, spec in todo:
            entries.append(_entry_for(trial_id, arm, archive.pool, row, params, spec,
                                      None if timeline is None else timeline.events,
                                      plans.get(trial_id, {}).get(row['decision_index']), series))
        del summary, timeline, plans
    for pool, todo in rows_by_pool.items():
        if pool not in seen:
            for trial_id, arm, row, params, spec in todo:
                entries.append(_entry_for(trial_id, arm, pool, row, params, spec, None, None, series))
    entries.sort(key=lambda e: (e['trial'], e['arm'], e['pool']))
    for e in entries:
        if e['mismatches']:
            mismatches.append(dict(trial=e['trial'], arm=e['arm'], pool=e['pool'], mismatches=e['mismatches']))
    comparison = compare_arms(entries, counts=counts)
    report = None
    if report_path is not None:
        doc = json.loads(Path(report_path).read_text(encoding='utf-8'))
        report = dict(sha256=_sha_bytes(Path(report_path).read_bytes()), decision=doc.get('decision'),
                      n_trials=doc.get('n_trials'), flags=doc.get('flags'),
                      quoted_not_recomputed=True)
    verified = sum(1 for e in entries if e.get('verified') is True)
    return dict(schema=SCHEMA, category='HISTORICAL_REPLAY', pools_manifest_sha256=manifest_sha,
                cycles_l1_plan_re_derived=sum(1 for e in entries if (e.get('checks') or {}).get('l1_exit_plan_re_derived')),
                bundles_sha256=sums, cycles_with_entry=len(entries), cycles_verified=verified,
                cycles_entry_only=sum(1 for e in entries if e.get('scope') == 'entry_only'),
                cycles_not_re_derived=sum(1 for e in entries if e.get('verified') is None),
                independence=INDEPENDENCE,
                verdict='PASS' if not mismatches else 'FAIL', mismatches=mismatches,
                comparison=comparison, w1_report=report, entries=entries,
                flags=dict(master_operational_trade=False, counted_in_master_gate=False,
                           financial_order_submitted=False, profitability_demonstrated=False))


def _count_pools(counts, trial_id, bundle):
    for arm, _pool, _row, _params, _spec in cycles(trial_id, bundle):
        key = f'{trial_id}:{arm}'
        counts[key] = counts.get(key, 0) + 1


def compare_arms(entries, bundles=None, *, counts=None):
    """Per trial and arm: entries, closed cycles, wins, total and mean P&L, cost decomposition sums.
    counts ({trial:arm: pools}, in bundle order) replaces bundles when they are not held in memory."""
    if counts is None:
        counts = {}
        for trial_id, bundle in bundles.items():
            _count_pools(counts, trial_id, bundle)
    table = {}
    for key, pools in counts.items():
        table[key] = dict(pools=pools, entries=0, closed=0, wins=0, pnl_lamports=0, market_move=0.0, slippage=0.0,
                          launchlab_fees=0, tx_and_failed_costs=0, unpriced=0)
    for e in entries:
        line = table[f"{e['trial']}:{e['arm']}"]
        line['entries'] += 1
        if e['outcome'] != 'closed':
            line['unpriced'] += 1
            continue
        line['closed'] += 1
        line['wins'] += e['pnl_lamports'] > 0
        line['pnl_lamports'] += e['pnl_lamports']
        d = e.get('decomposition')
        if d:
            line['market_move'] += d['market_move']
            line['slippage'] += d['slippage']
            line['launchlab_fees'] += d['launchlab_buy_fee'] + d['launchlab_sell_fee']
            line['tx_and_failed_costs'] += d['tx_costs'] + d['failed_attempt_costs']
    for line in table.values():
        line['mean_pnl_lamports'] = line['pnl_lamports'] / line['closed'] if line['closed'] else None
        line['market_move'] = round(line['market_move'], 3)
        line['slippage'] = round(line['slippage'], 3)
    return table


def markdown(ledger):
    lines = ['# W1 ledger (HISTORICAL_REPLAY, research only)', '',
             f"Verdict of the re-verification: **{ledger['verdict']}**: {ledger['cycles_verified']} / "
             f"{ledger['cycles_with_entry']} cycles with an entry re-derived identically "
             f"({ledger['cycles_entry_only']} entry only, unpriced; {ledger['cycles_not_re_derived']} not re-derived).",
             '', 'Independence: ' + ledger['independence'], '']
    if ledger['w1_report']:
        lines += [f"W1 decision (quoted from w1_report.json {ledger['w1_report']['sha256'][:12]}, not recomputed): "
                  f"**{ledger['w1_report']['decision']}**", '']
    lines += ['| trial:arm | pools | entries | closed | wins | P&L (SOL) | market move | slippage | LaunchLab fees | tx + failed |',
              '|---|---|---|---|---|---|---|---|---|---|']
    for key, line in sorted(ledger['comparison'].items()):
        lines.append(f"| {key} | {line['pools']} | {line['entries']} | {line['closed']} | {line['wins']} | "
                     f"{line['pnl_lamports'] / LAMPORTS_PER_SOL:.6f} | {line['market_move'] / LAMPORTS_PER_SOL:.6f} | "
                     f"{line['slippage'] / LAMPORTS_PER_SOL:.6f} | {line['launchlab_fees'] / LAMPORTS_PER_SOL:.6f} | "
                     f"{line['tx_and_failed_costs'] / LAMPORTS_PER_SOL:.6f} |")
    lines += ['', 'Not an operational Master trade; not counted toward the protected thresholds; '
              'a verified cycle is not evidence of profitability.']
    return '\n'.join(lines) + '\n'


def main(argv=None, *, out=None):
    import argparse
    import sys
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description='W1 BUY/SELL ledger (offline, read-only)')
    parser.add_argument('--pools', type=Path, required=True)
    parser.add_argument('--bundles', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--series', type=Path, help='the COLLECTED SOL/USD series used by the replay')
    parser.add_argument('--out', type=Path, required=True, help='directory for ledger.json and ledger.md')
    args = parser.parse_args(argv)
    if args.out.exists():
        raise LedgerError('output_directory_already_exists')
    series = None
    if args.series is not None:
        from bot.p4 import sol_usd_series as sus
        series = sus.load_series(args.series)
    ledger = build_ledger(args.pools, args.bundles, report_path=args.report, series=series)
    args.out.mkdir(parents=True)
    data = json.dumps(ledger, indent=1, sort_keys=True).encode() + b'\n'
    (args.out / 'ledger.json').write_bytes(data)
    (args.out / 'ledger.md').write_text(markdown(ledger), encoding='utf-8')
    out.write(json.dumps(dict(verdict=ledger['verdict'], cycles_with_entry=ledger['cycles_with_entry'],
                              cycles_verified=ledger['cycles_verified'], ledger_sha256=_sha_bytes(data),
                              mismatches=len(ledger['mismatches'])), sort_keys=True) + '\n')
    return 0 if ledger['verdict'] == 'PASS' else 4


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
