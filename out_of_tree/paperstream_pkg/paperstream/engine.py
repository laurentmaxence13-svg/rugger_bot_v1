"""paperstream 0.1 -- offline STREAMING PAPER engine of the frozen MASTER (plan v0.1 accepted by R02 with 7 conditions).
HISTORICAL_REPLAY ONLY: recorded LaunchLab events are pushed ONE BY ONE, in time order; nothing is sent, signed or read
from the network; no key; no economic conclusion (it reproduces a known replay: not a trial, N unchanged).

  python -B -m paperstream.engine reference --pools <pack> --manifest-sha256 <anchored> --out <DIR>   (batch, frozen)
  python -B -m paperstream.engine run --pools <pack> --manifest-sha256 <anchored> \
         --reference <REFERENCE.json> --reference-sha256 <anchored> --out <DIR>                        (streaming)

WHAT IS STREAMED. ``StreamTrade`` is a push-based copy of the state machine of the frozen ``bot.market.replay.replay``:
the strategy sees ``events[:k + 1]`` only, the history pushed so far (it cannot be given a later event: pushes are
checked for time order and refused after the end); a decision lands after the frozen latency, as soon as an event past
the landing slot arrives (or at the end); holding replays each pushed real trade on the shifted curve with the frozen
``_replay_real``; the exit, the clock exit, the migration stop and the final mark are those of ``replay``.
WHAT IS NOT CHANGED. ``streaming_engine()`` swaps ONLY the trade engine of the frozen ``hrr.replay_pool`` (the name
``replay`` inside ``bot.p4.historical_research_replay``) for the streaming one, inside a context manager that restores
it; the frozen MASTER arm (``ResearchArm``, the MASTER V2 scorer of W1), the observer, the costs, the trade rows, the
clock-exit rows, the migration and window rules are the frozen code, with the W1 L1 parameters (``w1_run.l1_params()``,
latency 4, clock horizon 30 s).
IDENTITY (R02 condition 3): ``reference`` writes the frozen BATCH records of the same input; ``run`` refuses a reference
that is not the anchored one and states whether the streaming records are BYTE-IDENTICAL (canonical JSON), no tolerance.
JOURNAL: one PAPER journal per pool and arm (DECISION / BUY / SELL / END), reconciled with the frozen trade row
(received - spent - tx - failed = P&L, zero residual).
LABELS (condition 4): category HISTORICAL_REPLAY; the protected thresholds are read from ``bot.master_decision.POLICY``
(50 qualified cycles, 20 creator groups; condition 5) and these replayed cycles NEVER count toward them.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path

from bot.market import replay as R
from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.master_decision import POLICY
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA = 'paperstream-v0.1'
CATEGORY = 'HISTORICAL_REPLAY'


class StreamError(RuntimeError):
    pass


class StreamTrade:
    """One strategy, one pool, events pushed one at a time; ``finish()`` returns the frozen TradeResult."""

    def __init__(self, pool, strategy, model, *, quote_mint):
        if quote_mint != R.WSOL_MINT:
            raise ValueError('quote_not_sol_cannot_be_priced_in_sol')
        self.strategy, self.model = strategy, model
        self.events, self.result = [], R.TradeResult(pool, 'no_entry')
        self.phase, self.done = 'seek', False
        self.journal = []

    # -- input guard: time order only, nothing after the end ----------------------------------------------
    def _accept(self, event):
        if self.done:
            raise StreamError('event_after_the_end')
        if self.events:
            last = self.events[-1]
            if event.slot < last.slot or event.block_time < last.block_time:
                raise StreamError('event_out_of_time_order')
        self.events.append(event)
        return len(self.events) - 1

    def push(self, event):
        j = self._accept(event)
        if self.phase == 'seek':
            amount = self.strategy.entry(tuple(self.events[:j + 1]))
            if amount:
                self._decide(j, amount)
            return
        if self.phase == 'landing':
            if event.slot > self.limit:
                if self._land(j - 1):
                    self._hold(j)
            return
        if self.phase == 'holding':
            self._hold(j)

    def finish(self):
        if self.done:
            return self.result
        if self.phase == 'landing':
            if self._land(len(self.events) - 1):
                self._hold_end()
        elif self.phase == 'holding':
            self._hold_end()
        self.done = True
        return self.result

    # -- the frozen replay() state machine, step by step -----------------------------------------------------
    def _decide(self, k, amount):
        events, model, result = self.events, self.model, self.result
        result.decision_index = k
        if model.fee_rate_ppm is None and model.fee_rate_estimator == 'causal_interval':
            rate, result.fee_rate_evidence = R.causal_fee_rate(events[:k + 1])
            result.fee_rate_source = 'pool_events_causal_interval'
        elif model.fee_rate_ppm is None:
            rate, result.fee_rate_source = R._event_rate(events[k]), 'pool_event_at_decision'
        else:
            rate, result.fee_rate_source = model.fee_rate_ppm, 'model'
        result.fee_rate_ppm = rate
        self.rate, self.amount, self.limit, self.phase = rate, amount, events[k].slot + model.latency_slots, 'landing'
        self.journal.append(dict(kind='DECISION', index=k, slot=events[k].slot, amount=amount, fee_rate_ppm=rate))

    def _land(self, land):
        events, result = self.events, self.result
        try:
            fill = buy_exact_in(events[land].state_after(), self.amount, self.rate)
        except CurveError as exc:
            result.outcome = 'no_entry'
            result.notes.append(f'entry_refused:{exc}')
            self._stop()
            return False
        self.position = R.Position(land, events[land].slot, events[land].block_time, self.amount, fill.amount_out)
        result.entry_index, result.spent, result.tokens = land, self.amount, fill.amount_out
        result.tx_costs = self.model.tx_cost
        self.state, self.pending_exit_slot, self.phase = fill.after, None, 'holding'
        self.journal.append(dict(kind='BUY', index=land, slot=events[land].slot, spent=self.amount,
                                 tokens=fill.amount_out, tx_cost=self.model.tx_cost, fee_rate_ppm=self.rate))
        for j in range(land + 1, len(events) - 1):                 # events already received after the landing slot
            if self.phase != 'holding':
                return False
            self._hold(j)
        return self.phase == 'holding'

    def _sell(self, exit_index, *, clock=None):
        result = self.result
        try:
            sale = sell_exact_in(self.state, self.position.tokens, self.rate)
        except CurveError as exc:
            result.outcome = 'counterfactual_divergence'
            result.notes.append(f'exit_refused:{exc}')
            return self._stop()
        result.outcome, result.exit_index = 'closed', exit_index
        result.received = sale.amount_out
        result.tx_costs += self.model.tx_cost
        result.hold_slots = self.events[exit_index].slot - self.position.entry_slot
        if clock is None:
            result.exit_landing_slot = self.pending_exit_slot
        else:
            result.notes.append('clock_exit')
            result.clock_exit = clock
        self.journal.append(dict(kind='SELL', index=exit_index, received=sale.amount_out, tx_cost=self.model.tx_cost,
                                 clock_exit=clock is not None))
        return self._stop()

    def _clock(self):
        if self.pending_exit_slot is not None or self.model.clock_exit_latency_s is None:
            return None, None
        deadline_of = getattr(self.strategy, 'exit_deadline', None)
        deadline = deadline_of(self.position) if deadline_of is not None else None
        return deadline, (None if deadline is None else deadline + self.model.clock_exit_latency_s)

    def _hold(self, j):
        events, result = self.events, self.result
        if self.pending_exit_slot is not None and events[j].slot > self.pending_exit_slot:
            return self._sell(j - 1)
        deadline, landing = self._clock()
        if landing is not None and events[j].block_time > landing:
            return self._sell(j - 1, clock=dict(deadline=deadline, landing_time=landing, last_index=j - 1))
        try:
            self.state = R._replay_real(self.state, events[j])
        except CurveError as exc:
            reason = str(exc)
            result.outcome = ('migrated_unpriced' if reason == 'buy_crosses_migration_boundary'
                              else 'counterfactual_divergence')
            result.notes.append(f'replay_stopped_at:{j}:{reason}')
            return self._stop()
        if self.state.remaining_base == 0:
            result.outcome = 'migrated_unpriced'
            return self._stop()
        if self.pending_exit_slot is None:
            try:
                mark = sell_exact_in(self.state, self.position.tokens, self.rate).amount_out
            except CurveError:
                mark = 0
            if self.strategy.exit(tuple(self.events[:j + 1]), self.position, mark):
                self.pending_exit_slot = events[j].slot + self.model.latency_slots
        return None

    def _hold_end(self):
        result, events = self.result, self.events
        last = len(events) - 1
        if self.pending_exit_slot is not None:
            return self._sell(last)
        deadline, landing = self._clock()
        if landing is not None:
            return self._sell(last, clock=dict(deadline=deadline, landing_time=landing, last_index=last))
        try:
            result.received = sell_exact_in(self.state, self.position.tokens, self.rate).amount_out
        except CurveError as exc:
            result.outcome = 'counterfactual_divergence'
            result.notes.append(f'mark_refused:{exc}')
            return self._stop()
        result.outcome = 'open_at_end'
        result.tx_costs += self.model.tx_cost
        result.exit_index = last
        result.hold_slots = events[-1].slot - self.position.entry_slot
        self.journal.append(dict(kind='MARK_AT_END', index=last, received=result.received))
        return self._stop()

    def _stop(self):
        self.phase = 'stopped'
        return None


JOURNALS = []


def stream_replay(timeline, strategy, model=R.ExecutionModel(), *, quote_mint):
    """Drop-in for the frozen ``replay``: the events are PUSHED one by one into a StreamTrade."""
    if not timeline.events:
        return R.TradeResult(timeline.pool, 'no_entry')
    if not timeline.complete:
        raise ValueError('timeline_incomplete')
    trade = StreamTrade(timeline.pool, strategy, model, quote_mint=quote_mint)
    for event in timeline.events:
        if trade.phase == 'stopped':
            break
        trade.push(event)
    result = trade.finish()
    JOURNALS.append(dict(pool=timeline.pool, arm=getattr(strategy, 'arm', None), events=trade.journal))
    return result


@contextlib.contextmanager
def streaming_engine():
    """Inside the block, the frozen hrr.replay_pool uses the streaming engine; restored afterwards."""
    original = hrr.replay
    hrr.replay = stream_replay
    try:
        yield
    finally:
        hrr.replay = original


def _canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), default=str)


def records(pools_dir, manifest_sha256, *, streaming):
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise StreamError('manifest_is_not_the_anchored_one')
    params = w1_run.l1_params()
    out, excluded = [], 0
    JOURNALS.clear()
    context = streaming_engine() if streaming else contextlib.nullcontext()
    try:
        with context:
            for _entry, archive in entries:
                try:
                    out.append(hrr.replay_pool(archive, params, quote_mint=R.WSOL_MINT, exit_options=w1_run.L1_EXIT))
                except hrr.PoolExcluded:
                    excluded += 1
    finally:
        clear_cache()
    return out, excluded, list(JOURNALS)


def reconcile(record, journals):
    """Each arm's trade row against its PAPER journal: received - spent - tx - failed = P&L, zero residual."""
    checked = 0
    for name, row in record['arms'].items():
        if row.get('pnl_lamports') is None:
            continue
        journal = next(j for j in journals if j['pool'] == record['pool'] and j['arm'] == name)
        buy = next(e for e in journal['events'] if e['kind'] == 'BUY')
        sell = next(e for e in journal['events'] if e['kind'] == 'SELL')
        residual = (sell['received'] - buy['spent'] - (buy['tx_cost'] + sell['tx_cost']) - row['failed_attempt_costs']
                    - row['pnl_lamports'])
        if residual != 0:
            raise StreamError('journal_does_not_reconcile')
        checked += 1
    return checked


def thresholds():
    return dict(min_qualified_cycles=POLICY['min_qualified_cycles'], min_creator_groups=POLICY['min_creator_groups'],
                these_cycles_count_toward_them=False, operational_master_entry=False,
                reason='HISTORICAL_REPLAY cycles never count toward the protected thresholds')


def _document(recs, excluded, manifest_sha256, **extra):
    return dict(schema=SCHEMA, category=CATEGORY, params='w1_run.l1_params() + L1_EXIT (latency 4, clock 30 s)',
                input=dict(manifest_sha256=manifest_sha256), pools=len(recs), excluded=excluded,
                records_sha256=hashlib.sha256(_canonical(recs).encode()).hexdigest(), thresholds=thresholds(),
                network=False, trials_added=0, **extra)


def _write(out_dir, name, doc):
    out = Path(out_dir)
    if out.exists():
        raise StreamError('output_exists')
    out.mkdir(parents=True)
    path = out / name
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, default=str) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='paperstream.engine')
    sub = parser.add_subparsers(dest='command', required=True)
    ref = sub.add_parser('reference')
    run = sub.add_parser('run')
    for p in (ref, run):
        p.add_argument('--pools', type=Path, required=True)
        p.add_argument('--manifest-sha256', required=True)
        p.add_argument('--out', type=Path, required=True)
    run.add_argument('--reference', type=Path, required=True)
    run.add_argument('--reference-sha256', required=True)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise StreamError('output_exists')
    if a.command == 'reference':
        recs, excluded, _j = records(a.pools, a.manifest_sha256, streaming=False)
        doc = _document(recs, excluded, a.manifest_sha256, engine='frozen batch replay (bot.market.replay.replay)',
                        records=recs)
        print(_write(a.out, 'REFERENCE.json', doc))
        return 0
    raw = a.reference.read_bytes()
    if hashlib.sha256(raw).hexdigest() != a.reference_sha256:
        raise StreamError('reference_is_not_the_anchored_one')
    reference = json.loads(raw)
    if reference.get('input', {}).get('manifest_sha256') != a.manifest_sha256:
        raise StreamError('reference_of_another_input')
    recs, excluded, journals = records(a.pools, a.manifest_sha256, streaming=True)
    reconciled = sum(reconcile(r, journals) for r in recs)
    doc = _document(recs, excluded, a.manifest_sha256, engine='paperstream StreamTrade (events pushed one by one)',
                    reference_sha256=a.reference_sha256,
                    identical_to_reference=_canonical(recs) == _canonical(reference['records']),
                    reconciled_cycles=reconciled, records=recs, journals=journals)
    print(_write(a.out, 'PAPERSTREAM.json', doc))
    return 0 if doc['identical_to_reference'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
