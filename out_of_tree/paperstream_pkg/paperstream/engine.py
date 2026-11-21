"""paperstream 0.4 -- offline STREAMING PAPER engine of the frozen MASTER (plan v0.1 accepted by R02 with 7 conditions;
0.2 per R02 decision 06181c21; 0.3 per R02 requirements of 15:51Z/15:52Z/15:52:53Z; 0.4 per R02 audit K-1..K-3). HISTORICAL_REPLAY ONLY: recorded LaunchLab events are pushed ONE BY ONE, in time order;
nothing is sent, signed or read from the network; no key; no economic conclusion (it reproduces a known replay: not a
trial, N unchanged).

  python -B -m paperstream.engine reference --pools <pack> --manifest-sha256 <anchored> \
         --sol-usd-series <series.json[.gz]> --sol-usd-series-sha256 <anchored> [--workers W] --out <DIR>      (batch)
  python -B -m paperstream.engine run       --pools <pack> --manifest-sha256 <anchored> \
         --sol-usd-series <series.json[.gz]> --sol-usd-series-sha256 <anchored> [--workers W] \
         [--reference <REFERENCE.json> --reference-sha256 <anchored>] [--expect-bundle-sha256 <anchored W1 L1>] \
         [--checkpoint <paperstream checkpoint DIR>] --out <DIR>                                             (stream)

0.3 (R02). (a) W1: the STREAM ALONE against the anchored L1 bundle sha (``--expect-bundle-sha256``, given on the command
line, never read from a file this run produces); ``--reference`` (batch) stays for the fixtures and P0. (b) Per-pool
CHECKPOINT, STREAMING ONLY, canonical JSON (no pickle, never the trials checkpoint): see ``Checkpoint``. (c) ZERO RESIDUAL
is defined by ``RECONCILED`` and ``reconcile``. (d) Firewall: the summary documents hold identities, closed cycles and
reason counts only: no return, no P&L, no hypothesis label.

0.4 (R02 K-1..K-3). The anchored W1 value is the sha256 of the FILE run/bundles/L1.json.gz written by
``w1_run._write_json`` (gzip, mtime 0, of the strict canonical JSON, bundle_sha256 field inside), not the bundle_sha256
field. The stream is compared on BOTH (``--expect-bundle-file-sha256`` AND ``--expect-bundle-json-sha256``, given
together): the file sha is obtained by calling ``w1_run._write_json`` itself into a temporary directory outside
``--out``, deleted afterwards; the json sha is the sha256 of the decompressed content (``_canonical_strict``), which does
not depend on zlib; ``zlib.ZLIB_RUNTIME_VERSION`` is published. rc=0 also requires the bundle_sha256 field to equal its
recomputation (``hrr._sha``). All bundle hashes use the strict serialization of run_trials (no default, no NaN).

0.2 (R02 06181c21). (1) The SOL/USD series is MANDATORY: the file's sha256 is checked BEFORE it is read, it is loaded by
the loader of the frozen W1 trials step (``sus.load_series``, as ``w1_run.run_trials``) under the same guard (COLLECTED,
measured acceptance) and passed IDENTICALLY to the batch and the streaming runs. (2) No declared SOL/USD rate: there is
no such input, and ``l1_params().sol_usd`` must be None. (3) ``StreamTrade`` and ``stream_replay`` are unchanged from
0.1 (source sha256 tested). (4) 0.1 looped over ``replay_pool`` itself, without the collection window, the creator
history and the placebo arm: 0.2 calls THE frozen ``hrr.run_replay`` with the arguments of the L1 bundle of
``w1_run.run_trials`` (``l1_params()``, the series, ``L1_EXIT``, ``CreatorHistory.from_archives(..., 'manifest')``,
``placebo_arm=True``), so that the batch bundle IS the frozen W1 L1 bundle (``--expect-bundle-sha256``).
WHAT IS STREAMED. ``StreamTrade`` is a push-based copy of the state machine of the frozen ``bot.market.replay.replay``:
the strategy sees ``events[:k + 1]`` only, the history pushed so far (pushes are checked for time order and refused after
the end); a decision lands after the frozen latency; holding replays each pushed real trade on the shifted curve with the
frozen ``_replay_real``; the exit, the clock exit, the migration stop and the final mark are those of ``replay``.
WHAT IS NOT CHANGED. ``streaming_engine()`` swaps ONLY the trade engine (the name ``replay`` inside
``bot.p4.historical_research_replay``) for the streaming one, and restores it; everything else is the frozen code.
LARGE PACKS (W1). ``--workers`` runs inside ``w1aux.lazy.lazy_archives()`` and ``w1aux.parallel.parallel_replays``
(forked workers inherit the swapped engine), WITHOUT checkpoint: no batch result can ever be served to the streaming run.
JOURNAL: one PAPER journal per pool and arm (DECISION / BUY / SELL / MARK_AT_END), written per pool by the process that
replayed it, reconciled with the frozen trade row (received - spent - tx - failed = P&L, zero residual).
IDENTITY: the frozen ``bundle_sha256`` AND the sha256 of the canonical JSON of the whole bundle, batch vs streaming, no
tolerance. Reported counts only (entries, outcomes, closed cycles per arm), no P&L in the summary documents.
LABELS: category HISTORICAL_REPLAY; the protected thresholds are read from ``bot.master_decision.POLICY`` (50 qualified
cycles, 20 creator groups) and these replayed cycles NEVER count toward them.
"""
import argparse
import contextlib
import hashlib
import inspect
import json
import os
import tempfile
import zlib
from dataclasses import asdict
from pathlib import Path

from bot.market import replay as R
from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.master_decision import POLICY
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from w1aux import dayj, lazy, parallel

SCHEMA = 'paperstream-v0.4'
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


def _sha_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_anchored_series(path, sha256):
    """The SOL/USD series of the frozen W1 chain: anchored file, frozen loader, the guard of w1_run.run_trials."""
    if path is None or sha256 is None:
        raise StreamError('sol_usd_series_required')
    if not Path(path).is_file():
        raise StreamError('sol_usd_series_missing')
    if _sha_file(path) != sha256:
        raise StreamError('sol_usd_series_is_not_the_anchored_one')
    series = sus.load_series(path)
    if series.label != 'COLLECTED' or series.max_age_ms == sus.MAX_AGE_MS and series.max_confidence_ppm is None:
        raise StreamError('w1_needs_a_collected_series_with_its_measured_acceptance')
    return series


def streaming_code_sha256():
    """sha256 of the source of the streaming code path (StreamTrade, stream_replay, streaming_engine, the per-pool
    wrapper and the checkpoint) and of the frozen code fingerprint: any change invalidates every checkpoint entry."""
    parts = [inspect.getsource(o) for o in (StreamTrade, stream_replay, streaming_engine, _journaled_replay_pool,
                                             Checkpoint)]
    from bot.master_v2 import harness
    parts.append(harness.code_fingerprint())
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


class Checkpoint:
    """Per-pool checkpoint of the STREAMING run only (R02 15:52:53Z): one canonical JSON entry per pool
    (``<pool>.json``: key, record or exclusion, PAPER journals) and its sha256 (``<pool>.sha256``, written after the
    entry is complete). An entry is reused ONLY if its key equals the expected key (mode "stream", streaming code sha,
    series sha, MANIFEST sha, params sha, pool) AND its file sha equals the sha line; otherwise the pool is recomputed
    and the reason is recorded (``status/<pool>.json``). No pickle; nothing of a batch run can match (mode)."""

    def __init__(self, directory, context):
        self.dir = Path(directory)
        self.context = dict(context, mode='stream')
        (self.dir / 'status').mkdir(parents=True, exist_ok=True)

    def key(self, pool):
        return dict(self.context, pool=pool)

    def _paths(self, pool):
        return self.dir / (pool + '.json'), self.dir / (pool + '.sha256')

    def get(self, pool):
        entry, sha = self._paths(pool)
        if not entry.exists() or not sha.exists():
            return None, 'absent'
        if _sha_file(entry) != sha.read_text(encoding='utf-8').strip():
            return None, 'sha_mismatch'
        doc = json.loads(entry.read_text(encoding='utf-8'))
        if doc.get('key') != self.key(pool):
            return None, 'key_mismatch'
        return doc, 'reused'

    def put(self, pool, record, excluded, journals):
        entry, sha = self._paths(pool)
        doc = dict(key=self.key(pool), record=record, excluded=excluded, journals=journals)
        for path, text in ((entry, _canonical_strict(doc)), (sha, None)):
            part = path.with_name(path.name + '.part')
            part.write_text(text if text is not None else _sha_file(entry), encoding='utf-8')
            os.replace(part, path)

    def status(self, pool, state):
        (self.dir / 'status' / (pool + '.json')).write_text(json.dumps(dict(pool=pool, state=state)), encoding='utf-8')

    def index(self):
        rows, states = {}, {}
        for path in sorted(self.dir.glob('*.sha256')):
            rows[path.name[:-len('.sha256')]] = path.read_text(encoding='utf-8').strip()
        for path in sorted((self.dir / 'status').glob('*.json')):
            row = json.loads(path.read_text(encoding='utf-8'))
            states[row['pool']] = row['state']
        counts = {}
        for state in states.values():
            counts[state] = counts.get(state, 0) + 1
        return dict(context=self.context, entries=rows, last_states=states, counts=dict(sorted(counts.items())))


def _canonical_strict(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _journaled_replay_pool(original, journal_dir, checkpoint=None):
    """Per-pool function used while streaming: the frozen replay_pool (or a verified checkpoint entry of the same key),
    then its PAPER journals written to one file by the process that replayed the pool."""
    def write(pool, journals):
        path = Path(journal_dir) / (pool + '.json')
        if path.exists():
            raise StreamError('journal_written_twice')
        part = path.with_name(path.name + '.part')
        part.write_text(json.dumps(journals, sort_keys=True), encoding='utf-8')
        os.replace(part, path)

    def replay_pool(archive, *args, **kwargs):
        pool = archive.pool
        if checkpoint is not None:
            doc, state = checkpoint.get(pool)
            checkpoint.status(pool, state)
            if doc is not None:
                write(pool, doc['journals'])
                if doc['excluded'] is not None:
                    raise hrr.PoolExcluded(doc['excluded'])
                return doc['record']
        start = len(JOURNALS)
        try:
            record = original(archive, *args, **kwargs)
        except hrr.PoolExcluded as exc:
            del JOURNALS[start:]
            if checkpoint is not None:
                checkpoint.put(pool, None, list(exc.reasons), [])
            write(pool, [])
            raise
        journals = json.loads(json.dumps(JOURNALS[start:]))
        del JOURNALS[start:]
        if checkpoint is not None:
            checkpoint.put(pool, record, None, journals)
        write(pool, journals)
        return record
    return replay_pool


@contextlib.contextmanager
def _journals_to(journal_dir, checkpoint=None):
    original = hrr.replay_pool
    hrr.replay_pool = _journaled_replay_pool(original, journal_dir, checkpoint)
    try:
        yield
    finally:
        hrr.replay_pool = original


def _read_journals(journal_dir):
    out = []
    for path in sorted(Path(journal_dir).glob('*.json')):
        out.extend(json.loads(path.read_text(encoding='utf-8')))
    return out


def l1_bundle(pools_dir, series):
    """THE frozen call of w1_run.run_trials for the L1 bundle (same arguments, same order)."""
    params = w1_run.l1_params()
    if params.sol_usd is not None:
        raise StreamError('declared_sol_usd_rate_refused')
    return hrr.run_replay(pools_dir, params, series, w1_run.L1_EXIT,
                          hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pools_dir)[2]], 'manifest'),
                          placebo_arm=True)


def checkpoint_context(manifest_sha256, series):
    return dict(streaming_code_sha256=streaming_code_sha256(), sol_usd_series_sha256=series.sha256,
                manifest_sha256=manifest_sha256,
                params_sha256=hashlib.sha256(_canonical_strict(dict(params=asdict(w1_run.l1_params()),
                                                                    exit=w1_run.L1_EXIT.record())).encode()).hexdigest())


def records(pools_dir, manifest_sha256, series_path, series_sha256, *, streaming, journal_dir=None, workers=1,
            checkpoint_dir=None):
    """(bundle, journals): the frozen L1 bundle, computed by the frozen batch engine or by the streaming one."""
    if _sha_file(Path(pools_dir) / 'MANIFEST.json') != manifest_sha256:
        raise StreamError('manifest_is_not_the_anchored_one')
    series = load_anchored_series(series_path, series_sha256)
    if type(workers) is not int or workers < 1:
        raise StreamError('workers_must_be_a_positive_integer')
    if streaming and journal_dir is None:
        raise StreamError('journal_dir_required_when_streaming')
    if checkpoint_dir is not None and not streaming:
        raise StreamError('checkpoint_is_for_the_streaming_run_only')
    checkpoint = None if checkpoint_dir is None else Checkpoint(checkpoint_dir, checkpoint_context(manifest_sha256, series))
    JOURNALS.clear()
    with contextlib.ExitStack() as stack:
        if streaming:
            Path(journal_dir).mkdir(parents=True, exist_ok=False)
            stack.enter_context(streaming_engine())
            stack.enter_context(_journals_to(journal_dir, checkpoint))
        stack.enter_context(lazy.lazy_archives())
        if workers > 1:
            stack.enter_context(parallel.parallel_replays(workers))          # no checkpoint: nothing reused
        try:
            bundle = l1_bundle(pools_dir, series)
        finally:
            lazy.clear_cache()
    journals = _read_journals(journal_dir) if streaming else []
    if JOURNALS:
        raise StreamError('journal_not_written')
    if checkpoint is not None:
        return bundle, journals, checkpoint.index()
    return bundle, journals


RECONCILED = ('SELL.received', 'BUY.spent', 'BUY.tx_cost', 'SELL.tx_cost', 'row.failed_attempt_costs', 'row.pnl_lamports')


def residual(row, journal):
    """ZERO RESIDUAL, defined: for every closed cycle (frozen trade row with a P&L), from its PAPER journal,
    SELL.received - BUY.spent - (BUY.tx_cost + SELL.tx_cost) - row.failed_attempt_costs - row.pnl_lamports == 0,
    and the journal amounts equal the row's (BUY.spent == row.spent, SELL.received == row.received,
    BUY.tx_cost + SELL.tx_cost == row.tx_costs). Returns the list of non-zero differences."""
    buys = [e for e in journal['events'] if e['kind'] == 'BUY']
    sells = [e for e in journal['events'] if e['kind'] == 'SELL']
    if len(buys) != 1 or len(sells) != 1:
        return [('journal_shape', len(buys), len(sells))]
    buy, sell = buys[0], sells[0]
    checks = dict(pnl=sell['received'] - buy['spent'] - (buy['tx_cost'] + sell['tx_cost']) - row['failed_attempt_costs']
                  - row['pnl_lamports'],
                  spent=buy['spent'] - row['spent'], received=sell['received'] - row['received'],
                  tx_costs=buy['tx_cost'] + sell['tx_cost'] - row['tx_costs'])
    return [(name, value) for name, value in sorted(checks.items()) if value != 0]


def reconcile(record, journals):
    """Each closed cycle of the record against its PAPER journal (``residual``); raises on any non-zero residual."""
    checked = 0
    for name, row in record['arms'].items():
        if row.get('pnl_lamports') is None:
            continue
        found = [j for j in journals if j['pool'] == record['pool'] and j['arm'] == name]
        if len(found) != 1 or residual(row, found[0]):
            raise StreamError('journal_does_not_reconcile')
        checked += 1
    return checked


def thresholds():
    return dict(min_qualified_cycles=POLICY['min_qualified_cycles'], min_creator_groups=POLICY['min_creator_groups'],
                these_cycles_count_toward_them=False, operational_master_entry=False,
                reason='HISTORICAL_REPLAY cycles never count toward the protected thresholds')


def counts(bundle):
    """Counts per arm (no P&L): decisions, entries, outcomes, closed cycles, blocking reasons."""
    keep = ('decisions', 'enter_decisions', 'entries', 'outcomes', 'closed_cycles', 'blocking_reasons')
    return {arm: {k: row[k] for k in keep} for arm, row in bundle['totals'].items()}


def _document(bundle, manifest_sha256, series_sha256, series, **extra):
    return dict(schema=SCHEMA, category=CATEGORY,
                params='w1_run.l1_params() + L1_EXIT + CreatorHistory(manifest) + placebo arm (the W1 L1 bundle call)',
                input=dict(manifest_sha256=manifest_sha256, sol_usd_series_file_sha256=series_sha256,
                           sol_usd_series_sha256=series.sha256, sol_usd_series_points=len(series.points)),
                pools=len(bundle['pools']), excluded=len(bundle.get('excluded_pools', [])),
                bundle_sha256=bundle['bundle_sha256'],
                bundle_sha256_recomputed=hrr._sha({k: v for k, v in bundle.items() if k != 'bundle_sha256'}),
                bundle_json_sha256=bundle_json_sha256(bundle),
                bundle_file_sha256=bundle_file_sha256(bundle), zlib_runtime_version=zlib.ZLIB_RUNTIME_VERSION,
                counts=counts(bundle), thresholds=thresholds(), network=False, trials_added=0,
                identity_check_not_a_trial=True, **extra)


def bundle_json_sha256(bundle):
    """sha256 of the decompressed content of run/bundles/L1.json.gz: the strict canonical JSON of w1_run._write_json."""
    return hashlib.sha256(_canonical_strict(bundle).encode()).hexdigest()


def bundle_file_sha256(bundle):
    """sha256 of the bundle file exactly as w1_run.run_trials writes it (``w1_run._write_json`` itself, into a temporary
    directory that is deleted afterwards; the bundle file holds P&L and is never kept)."""
    with tempfile.TemporaryDirectory(prefix='paperstream_bundle_') as tmp:
        return w1_run._write_json(Path(tmp) / 'bundles' / 'L1.json.gz', bundle)


def _write(out, name, doc):
    path = out / name
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, default=str) + '\n', encoding='utf-8')
    return _sha_file(path)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='paperstream.engine')
    sub = parser.add_subparsers(dest='command', required=True)
    ref = sub.add_parser('reference')
    run = sub.add_parser('run')
    for p in (ref, run):
        p.add_argument('--pools', type=Path, required=True)
        p.add_argument('--manifest-sha256', required=True)
        p.add_argument('--sol-usd-series', type=Path, required=True)
        p.add_argument('--sol-usd-series-sha256', required=True)
        p.add_argument('--workers', type=int, default=1)
        p.add_argument('--memory-override', action='store_true',
                       help='skip the dayj memory guard: NOT usable without the written agreement of R02')
        p.add_argument('--out', type=Path, required=True)
    run.add_argument('--reference', type=Path)
    run.add_argument('--reference-sha256')
    run.add_argument('--expect-bundle-file-sha256', help='sha256 of the anchored run/bundles/L1.json.gz file')
    run.add_argument('--expect-bundle-json-sha256', help='sha256 of its decompressed content')
    run.add_argument('--expect-bundle-field-sha256',
                     help='its internal bundle_sha256 field: an EXTRA check, never a substitute for file + json')
    run.add_argument('--checkpoint', type=Path)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise StreamError('output_exists')
    reference = None
    if a.command == 'run':
        if (a.reference is None) != (a.reference_sha256 is None):
            raise StreamError('reference_and_its_sha256_go_together')
        if (a.expect_bundle_file_sha256 is None) != (a.expect_bundle_json_sha256 is None):
            raise StreamError('bundle_file_and_json_sha256_go_together')
        if a.reference is None and a.expect_bundle_file_sha256 is None:
            raise StreamError('nothing_to_compare_with')
        if a.expect_bundle_field_sha256 is not None and a.expect_bundle_file_sha256 is None:
            raise StreamError('bundle_field_sha256_is_an_extra_check_not_a_substitute')
        if Path(tempfile.gettempdir()).resolve().is_relative_to(a.out.resolve()):
            raise StreamError('temporary_directory_inside_the_output')
        if a.checkpoint is not None and a.checkpoint.resolve().is_relative_to(a.out.resolve()):
            raise StreamError('checkpoint_inside_the_output')
        if a.reference is not None:
            raw = a.reference.read_bytes()
            if hashlib.sha256(raw).hexdigest() != a.reference_sha256:
                raise StreamError('reference_is_not_the_anchored_one')
            reference = json.loads(raw)
            if reference.get('input', {}).get('manifest_sha256') != a.manifest_sha256 or \
                    reference['input'].get('sol_usd_series_file_sha256') != a.sol_usd_series_sha256:
                raise StreamError('reference_of_another_input')
    series = load_anchored_series(a.sol_usd_series, a.sol_usd_series_sha256)
    try:                                         # the dayj guard of the trials step, projected from the MANIFEST
        memory = dayj.memory_guard('trials', a.pools, a.memory_override)
    except dayj.DayJError as exc:
        raise StreamError(str(exc)) from None
    a.out.mkdir(parents=True)
    if a.command == 'reference':
        bundle, _j = records(a.pools, a.manifest_sha256, a.sol_usd_series, a.sol_usd_series_sha256,
                             streaming=False, workers=a.workers)
        doc = _document(bundle, a.manifest_sha256, a.sol_usd_series_sha256, series,
                        engine='frozen batch replay (bot.market.replay.replay)', memory=memory,
                        memory_override=a.memory_override)
        print(_write(a.out, 'REFERENCE.json', doc))
        return 0
    result = records(a.pools, a.manifest_sha256, a.sol_usd_series, a.sol_usd_series_sha256, streaming=True,
                     journal_dir=a.out / 'journals', workers=a.workers, checkpoint_dir=a.checkpoint)
    bundle, journals = result[0], result[1]
    reconciled = sum(reconcile(r, journals) for r in bundle['pools'])
    closed = sum(1 for r in bundle['pools'] for row in r['arms'].values() if row.get('pnl_lamports') is not None)
    doc = _document(bundle, a.manifest_sha256, a.sol_usd_series_sha256, series,
                    engine='paperstream StreamTrade (events pushed one by one)', memory=memory,
                    memory_override=a.memory_override, reconciled_cycles=reconciled,
                    closed_cycles_all_arms=closed,
                    journals_sha256=hashlib.sha256(_canonical(journals).encode()).hexdigest())
    doc['bundle_sha256_consistent'] = doc['bundle_sha256'] == doc['bundle_sha256_recomputed']
    ok = reconciled == closed and doc['bundle_sha256_consistent']
    if reference is not None:
        doc['reference_sha256'] = a.reference_sha256
        doc['identical_to_reference'] = (doc['bundle_sha256'] == reference['bundle_sha256']
                                         and doc['bundle_json_sha256'] == reference['bundle_json_sha256'])
        ok = ok and doc['identical_to_reference']
    if a.expect_bundle_file_sha256 is not None:
        doc['expected_bundle_file_sha256'] = a.expect_bundle_file_sha256
        doc['expected_bundle_json_sha256'] = a.expect_bundle_json_sha256
        doc['matches_expected_bundle_file'] = doc['bundle_file_sha256'] == a.expect_bundle_file_sha256
        doc['matches_expected_bundle_json'] = doc['bundle_json_sha256'] == a.expect_bundle_json_sha256
        ok = ok and doc['matches_expected_bundle_file']
        ok = ok and doc['matches_expected_bundle_json']
    if a.expect_bundle_field_sha256 is not None:
        doc['expected_bundle_field_sha256'] = a.expect_bundle_field_sha256
        doc['matches_expected_bundle_field'] = doc['bundle_sha256'] == a.expect_bundle_field_sha256
        ok = ok and doc['matches_expected_bundle_field']
    if a.checkpoint is not None:
        index = result[2]
        doc['checkpoint_index_sha256'] = _write(a.out, 'CHECKPOINT_INDEX.json', index)
        doc['checkpoint_counts'] = index['counts']
    print(_write(a.out, 'PAPERSTREAM.json', doc))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
