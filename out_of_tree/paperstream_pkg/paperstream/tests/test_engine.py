"""paperstream 0.3: streaming = frozen W1 L1 bundle (byte for byte), anchored SOL/USD series mandatory, no lookahead,
offline, labels, thresholds, journal."""
import gzip
import hashlib
import inspect
import json
import socket
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

import bot
from bot.market import replay as R
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from paperstream import engine as E
from w1aux import dayj
from w1aux.lazy import clear_cache, load_fixtures_lazy

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
STREAMTRADE_V01 = 'bc9227869d42c78523b76da78620ddaa5d03f9bd27fb780394bb6d5598625299'     # source sha256, paperstream 0.1
STREAM_REPLAY_V01 = '2a19990213eab82a6e0598730cda3690d15a99ba5a881a4a72e860969d1c8132'


@pytest.fixture
def series(tmp_path):
    """The synthetic COLLECTED series of the dayj selfcheck (one point before the frozen pack), and its file sha256."""
    path = tmp_path / 'series.json'
    dayj._selfcheck_series(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _records(series, tmp_path, streaming, name='j', **kwargs):
    return E.records(PACK, SHA, *series, streaming=streaming, journal_dir=tmp_path / name if streaming else None,
                     **kwargs)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


def _timelines():
    out = []
    try:
        for _e, archive in load_fixtures_lazy(PACK)[2]:
            summary, timeline = hrr.summarize(archive) if hasattr(hrr, 'summarize') else (None, None)
            from bot.market.collector import summarize
            summary, timeline = summarize(archive)
            try:
                timeline, _m = hrr.usable_timeline(archive, summary, timeline)
            except hrr.PoolExcluded:
                continue
            out.append(timeline)
    finally:
        clear_cache()
    return out


class EnterAt(R.Strategy):
    """Test strategy: enter at the n-th event; exit once n_hold events have passed, or never."""

    def __init__(self, n, n_hold=None, clock_s=None):
        self.n, self.n_hold, self.clock_s, self.seen = n, n_hold, clock_s, []

    def entry(self, history):
        self.seen.append(len(history))
        return 100_000_000 if len(history) == self.n else None

    def exit(self, history, position, mark):
        self.seen.append(len(history))
        return self.n_hold is not None and len(history) - 1 - position.entry_index >= self.n_hold

    def exit_deadline(self, position):
        return None if self.clock_s is None else position.entry_time + self.clock_s


def _same(a, b):
    return asdict(a) == asdict(b)


@pytest.mark.parametrize('n,n_hold,clock_s,latency', [(1, 2, None, 4), (3, 1, None, 0), (2, None, None, 4),
                                                      (2, None, 5, 4), (5, 50, None, 2), (10_000, None, None, 4)])
def test_stream_trade_equals_the_frozen_replay(n, n_hold, clock_s, latency):
    model = R.ExecutionModel(latency_slots=latency, fee_rate_estimator='causal_interval',
                             clock_exit_latency_s=None if clock_s is None else 1)
    for timeline in _timelines():
        batch = R.replay(timeline, EnterAt(n, n_hold, clock_s), model, quote_mint=R.WSOL_MINT)
        streamed = E.stream_replay(timeline, EnterAt(n, n_hold, clock_s), model, quote_mint=R.WSOL_MINT)
        assert _same(batch, streamed), (n, n_hold, clock_s, latency)


def test_the_strategy_never_sees_beyond_the_pushed_events():
    timeline = _timelines()[0]
    model = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')
    strategy = EnterAt(2, 3)
    trade = E.StreamTrade(timeline.pool, strategy, model, quote_mint=R.WSOL_MINT)
    for i, event in enumerate(timeline.events):
        trade.push(event)
        assert max(strategy.seen) <= i + 1                         # at most the events pushed so far
        if trade.phase == 'stopped':
            break
    trade.finish()
    with pytest.raises(E.StreamError, match='event_after_the_end'):
        trade.push(timeline.events[-1])


def test_an_event_from_the_past_is_refused():
    timeline = _timelines()[0]
    trade = E.StreamTrade(timeline.pool, EnterAt(10_000), R.ExecutionModel(), quote_mint=R.WSOL_MINT)
    late = timeline.events[-1]
    trade.push(late)
    early = replace(timeline.events[0], slot=late.slot - 1) if hasattr(timeline.events[0], '__dataclass_fields__') else None
    if early is None:
        pytest.skip('events are not dataclasses')
    with pytest.raises(E.StreamError, match='event_out_of_time_order'):
        trade.push(early)


@pytest.mark.parametrize('workers', [1, 2])
def test_streaming_bundle_is_byte_identical_to_the_frozen_l1_bundle(series, tmp_path, workers):
    batch, none = _records(series, tmp_path, False, workers=workers)
    streamed, journals = _records(series, tmp_path, True, workers=workers)
    assert none == [] and batch['bundle_sha256'] == streamed['bundle_sha256'] and E._canonical(batch) == E._canonical(streamed)
    assert hrr.replay is R.replay and hrr.replay_pool.__module__ == hrr.__name__          # frozen code restored
    frozen = hrr.run_replay(PACK, w1_run.l1_params(), sus.load_series(series[0]), w1_run.L1_EXIT,
                            hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'),
                            placebo_arm=True)
    assert batch['bundle_sha256'] == frozen['bundle_sha256']                               # THE W1 L1 call
    assert 'placebo_arm' in batch and 'creator_history' in batch and batch['sol_usd_series']['sha256'] == frozen['sol_usd_series']['sha256']
    arms = {j['arm'] for j in journals}
    assert arms == set(hrr.ARMS) | {hrr.PLACEBO_ARM}
    assert len(journals) == len(batch['pools']) * len(arms)


def test_the_series_is_mandatory_and_anchored(series, tmp_path):
    path, sha = series
    with pytest.raises(E.StreamError, match='sol_usd_series_required'):
        E.records(PACK, SHA, None, None, streaming=False)
    with pytest.raises(E.StreamError, match='sol_usd_series_required'):
        E.records(PACK, SHA, path, None, streaming=False)
    with pytest.raises(E.StreamError, match='sol_usd_series_missing'):
        E.records(PACK, SHA, tmp_path / 'absent.json', sha, streaming=False)
    with pytest.raises(E.StreamError, match='sol_usd_series_is_not_the_anchored_one'):
        E.records(PACK, SHA, path, '0' * 64, streaming=False)
    doc = json.loads(path.read_text())
    for label, acceptance in (('DECLARED', doc['acceptance']), ('COLLECTED', dict(max_age_ms=sus.MAX_AGE_MS, max_confidence_ppm=None))):
        other = tmp_path / f'other_{label}.json'
        other.write_text(json.dumps(dict(doc, label=label, acceptance=acceptance)))
        try:
            sus.load_series(other)
        except ValueError:
            continue                                                     # refused by the frozen loader already
        with pytest.raises(E.StreamError, match='w1_needs_a_collected_series_with_its_measured_acceptance'):
            E.records(PACK, SHA, other, hashlib.sha256(other.read_bytes()).hexdigest(), streaming=False)
    gz = tmp_path / 'series.json.gz'
    gz.write_bytes(gzip.compress(path.read_bytes()))
    bundle, _ = E.records(PACK, SHA, gz, hashlib.sha256(gz.read_bytes()).hexdigest(), streaming=False)
    assert bundle['sol_usd_series']['sha256'] == sus.load_series(path).sha256


def test_no_declared_rate(series, monkeypatch):
    assert w1_run.l1_params().sol_usd is None
    for word in ('sol_usd_rate', '--sol-usd-rate', 'sol_usd_provenance'):
        assert word not in inspect.getsource(E.main) and word not in inspect.getsource(E.records)
    monkeypatch.setattr(w1_run, 'l1_params', lambda: replace(hrr.ReplayParams(), sol_usd=150, sol_usd_provenance='declared'))
    with pytest.raises(E.StreamError, match='declared_sol_usd_rate_refused'):
        E.records(PACK, SHA, *series, streaming=False)


def test_stream_trade_is_unchanged_from_0_1():
    assert hashlib.sha256(inspect.getsource(E.StreamTrade).encode()).hexdigest() == STREAMTRADE_V01
    assert hashlib.sha256(inspect.getsource(E.stream_replay).encode()).hexdigest() == STREAM_REPLAY_V01


def _frozen(series_doc):
    return hrr.run_replay(PACK, w1_run.l1_params(), series_doc, w1_run.L1_EXIT,
                          hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'),
                          placebo_arm=True)


def test_unforced_observer_with_the_series_exact_rate_reason_counts(series, tmp_path):
    """R02 point 6 / 15:51Z point 3: observe() NOT replaced. The count of sol_usd_rate_unavailable is EQUAL in batch and
    stream and equal to the frozen engine's, per arm; at least one decision is taken (the placebo arm enters)."""
    batch, _ = _records(series, tmp_path, False)
    streamed, _j = _records(series, tmp_path, True)
    frozen = _frozen(sus.load_series(series[0]))
    for arm in frozen['totals']:
        n = [b['totals'][arm]['blocking_reasons'].get('sol_usd_rate_unavailable', 0) for b in (batch, streamed, frozen)]
        assert n[0] == n[1] == n[2] == 0, (arm, n)                    # the synthetic series covers every decision
        assert batch['totals'][arm]['decisions'] == streamed['totals'][arm]['decisions'] > 0
    assert streamed['totals'][hrr.PLACEBO_ARM]['entries'] >= 1           # a decision is taken, not only WAITs
    without = _frozen(None)['totals']['master']
    assert without['blocking_reasons']['sol_usd_rate_unavailable'] == without['decisions'] > 0   # the 0.1 blockage


@pytest.mark.parametrize('field', ['received', 'spent', 'tx_cost_buy', 'tx_cost_sell', 'failed', 'pnl',
                                   'row_spent', 'row_received', 'row_tx_costs'])
def test_zero_residual_is_defined_and_an_injected_residual_fails(series, tmp_path, field):
    bundle, journals = _records(series, tmp_path, True)
    closed = [(r, name, row) for r in bundle['pools'] for name, row in r['arms'].items() if row.get('pnl_lamports') is not None]
    assert closed and E.RECONCILED == ('SELL.received', 'BUY.spent', 'BUY.tx_cost', 'SELL.tx_cost',
                                       'row.failed_attempt_costs', 'row.pnl_lamports')
    record, arm, row = closed[0]
    journal = next(j for j in journals if j['pool'] == record['pool'] and j['arm'] == arm)
    assert E.residual(row, journal) == [] and E.reconcile(record, journals) >= 1
    bad_j, bad_row = json.loads(json.dumps(journal)), dict(row)
    buy = next(e for e in bad_j['events'] if e['kind'] == 'BUY')
    sell = next(e for e in bad_j['events'] if e['kind'] == 'SELL')
    if field == 'received':
        sell['received'] += 1
    elif field == 'spent':
        buy['spent'] += 1
    elif field == 'tx_cost_buy':
        buy['tx_cost'] += 1
    elif field == 'tx_cost_sell':
        sell['tx_cost'] += 1
    elif field == 'failed':
        bad_row['failed_attempt_costs'] += 1
    elif field.startswith('row_'):
        bad_row[field[4:]] += 1                                          # the frozen row against its journal
    else:
        bad_row['pnl_lamports'] += 1
    assert E.residual(bad_row, bad_j) != []
    others = [j for j in journals if j is not journal]
    with pytest.raises(E.StreamError, match='journal_does_not_reconcile'):
        E.reconcile(dict(record, arms=dict(record['arms'], **{arm: bad_row})), others + [bad_j])


def _cut_after(monkeypatch, n):
    """Simulated interruption: the frozen replay_pool raises after n pools (as a restarted machine would stop)."""
    original, done = hrr.replay_pool, []

    def cut(*args, **kwargs):
        if len(done) >= n:
            raise KeyboardInterrupt('simulated_restart')
        done.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(hrr, 'replay_pool', cut)


def test_checkpoint_cut_then_resume_is_byte_identical(series, tmp_path, monkeypatch):
    clean, clean_j = _records(series, tmp_path, True, name='clean')
    ck = tmp_path / 'ck'
    with monkeypatch.context() as m:
        _cut_after(m, 2)
        with pytest.raises(KeyboardInterrupt):
            _records(series, tmp_path, True, name='cut', checkpoint_dir=ck)
    assert hrr.replay is R.replay and hrr.replay_pool.__module__ == hrr.__name__
    bundle, journals, index = _records(series, tmp_path, True, name='resumed', checkpoint_dir=ck)
    assert bundle['bundle_sha256'] == clean['bundle_sha256'] and E._canonical(bundle) == E._canonical(clean)
    assert E._canonical(journals) == E._canonical(clean_j)
    assert index['counts'] == {'absent': 1, 'reused': 2} and len(index['entries']) == 3
    assert index['context']['mode'] == 'stream' and index['context']['manifest_sha256'] == SHA
    again, _j, index2 = _records(series, tmp_path, True, name='again', checkpoint_dir=ck)
    assert again['bundle_sha256'] == clean['bundle_sha256'] and index2['counts'] == {'reused': 3}
    with pytest.raises(E.StreamError, match='checkpoint_is_for_the_streaming_run_only'):
        E.records(PACK, SHA, *series, streaming=False, checkpoint_dir=tmp_path / 'ck2')
    assert not list(ck.glob('*.pkl'))                                    # canonical JSON only, no pickle


def test_checkpoint_with_forked_workers(series, tmp_path):
    clean, clean_j = _records(series, tmp_path, True, name='clean')
    ck = tmp_path / 'ck'
    first, j1, i1 = _records(series, tmp_path, True, name='w1', checkpoint_dir=ck, workers=2)
    second, j2, i2 = _records(series, tmp_path, True, name='w2', checkpoint_dir=ck, workers=2)
    assert first['bundle_sha256'] == second['bundle_sha256'] == clean['bundle_sha256']
    assert E._canonical(j1) == E._canonical(j2) == E._canonical(clean_j)
    assert i1['counts'] == {'absent': 3} and i2['counts'] == {'reused': 3}


def test_the_reported_sha_is_the_frozen_canonical_sha_of_run_trials(series, tmp_path):
    """R02 16:06Z: the bundle is not written, so the reported bundle_sha256 must be the frozen one: hrr._sha (the
    canonical JSON of hrr._canonical, used by run_replay and therefore by w1_run.run_trials) over the bundle without
    its own sha field, recomputed and equal to the frozen direct call."""
    bundle, _j = _records(series, tmp_path, True)
    doc = E._document(bundle, SHA, series[1], sus.load_series(series[0]))
    body = {k: v for k, v in bundle.items() if k != 'bundle_sha256'}
    assert doc['bundle_sha256'] == doc['bundle_sha256_recomputed'] == hrr._sha(body) == _frozen(sus.load_series(series[0]))['bundle_sha256']
    assert hrr._canonical(body) == json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert 'hrr.run_replay(pools_dir, l1_params(), series, L1_EXIT' in inspect.getsource(w1_run.run_trials)


def test_memory_guard_of_dayj_and_its_override(series, tmp_path, monkeypatch, capsys):
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha]
    monkeypatch.setattr(dayj, '_memory_available_mb', lambda: 1)
    with pytest.raises(E.StreamError, match='memory_projection_exceeds_available_owner_decision_needed'):
        E.main(['reference', *common, '--out', str(tmp_path / 'small')])
    assert not (tmp_path / 'small').exists()                             # refused before anything is written
    assert E.main(['reference', *common, '--memory-override', '--out', str(tmp_path / 'forced')]) == 0
    doc = json.loads((tmp_path / 'forced' / 'REFERENCE.json').read_text())
    assert doc['memory_override'] is True and doc['memory']['fits'] is False and doc['memory']['step'] == 'trials'
    monkeypatch.setattr(dayj, '_memory_available_mb', lambda: 10 ** 7)
    assert E.main(['reference', *common, '--out', str(tmp_path / 'fits')]) == 0
    assert json.loads((tmp_path / 'fits' / 'REFERENCE.json').read_text())['memory']['fits'] is True


def _entries(ck):
    return sorted(p for p in ck.glob('*.json'))


@pytest.mark.parametrize('change', ['batch_mode', 'other_series', 'other_code', 'altered_content', 'other_pool'])
def test_a_foreign_or_altered_entry_is_refused_and_recomputed(series, tmp_path, change):
    ck = tmp_path / 'ck'
    clean, _j, _i = _records(series, tmp_path, True, name='first', checkpoint_dir=ck)
    entry = _entries(ck)[0]
    pool = entry.name[:-len('.json')]
    doc = json.loads(entry.read_text())
    if change == 'altered_content':
        if doc['record'] is not None:
            doc['record']['trades'] += 1
        else:
            doc['excluded'] = ['tampered']
        entry.write_text(E._canonical_strict(doc))                       # sha line NOT updated
        expected = 'sha_mismatch'
    else:
        if change == 'batch_mode':
            doc['key']['mode'] = 'batch'
        elif change == 'other_series':
            doc['key']['sol_usd_series_sha256'] = '0' * 64
        elif change == 'other_code':
            doc['key']['streaming_code_sha256'] = '0' * 64
        else:
            doc['key']['pool'] = 'another'
        entry.write_text(E._canonical_strict(doc))
        (ck / (pool + '.sha256')).write_text(hashlib.sha256(entry.read_bytes()).hexdigest())   # a self-consistent sha
        expected = 'key_mismatch'
    bundle, _j, index = _records(series, tmp_path, True, name='second', checkpoint_dir=ck)
    assert index['last_states'][pool] == expected and index['counts'][expected] == 1
    assert bundle['bundle_sha256'] == clean['bundle_sha256']             # recomputed, identical
    assert json.loads(entry.read_text())['key']['mode'] == 'stream'      # the entry is rewritten with the right key


def test_cli_reference_then_anchored_run(series, tmp_path, capsys):
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha]
    assert E.main(['reference', *common, '--out', str(tmp_path / 'ref')]) == 0
    ref_sha = capsys.readouterr().out.strip()
    ref = tmp_path / 'ref' / 'REFERENCE.json'
    assert ref_sha == hashlib.sha256(ref.read_bytes()).hexdigest()
    reference = json.loads(ref.read_text())
    assert reference['bundle_sha256'] == _records(series, tmp_path, False)[0]['bundle_sha256']
    assert reference['input']['sol_usd_series_file_sha256'] == sha and 'pnl_lamports' not in json.dumps(reference['counts'])
    with pytest.raises(E.StreamError, match='reference_is_not_the_anchored_one'):
        E.main(['run', *common, '--reference', str(ref), '--reference-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    with pytest.raises(E.StreamError, match='manifest_is_not_the_anchored_one'):
        E.main(['reference', *common[:2], '--manifest-sha256', '0' * 64, *common[4:], '--out', str(tmp_path / 'y')])
    with pytest.raises(SystemExit):
        E.main(['reference', *common[:4], '--out', str(tmp_path / 'z')])                  # series argument required
    capsys.readouterr()
    assert E.main(['run', *common, '--reference', str(ref), '--reference-sha256', ref_sha,
                   '--expect-bundle-sha256', reference['bundle_sha256'], '--out', str(tmp_path / 'run')]) == 0
    text = (tmp_path / 'run' / 'PAPERSTREAM.json').read_text()
    doc = json.loads(text)
    assert doc['identical_to_reference'] is True and doc['matches_expected_bundle'] is True
    assert doc['category'] == 'HISTORICAL_REPLAY' and doc['network'] is False and doc['trials_added'] == 0
    assert doc['reconciled_cycles'] == doc['closed_cycles_all_arms'] >= 1                  # placebo cycle on the pack
    for word in ('genuine', 'GENUINE', 'MASTER_CYCLE', 'operational_trade": true', 'LIVE', 'pnl', 'return', 'HW',
                 'hypothes', 'mark_'):
        assert word not in text, word                                   # firewall: identities and counts only
    assert doc['trials_added'] == 0 and doc['identity_check_not_a_trial'] is True
    assert not list((tmp_path / 'run').glob('*.gz'))                     # no bundle (no P&L) written
    capsys.readouterr()
    # W1 mode: the STREAM ALONE against the anchored sha, with a checkpoint outside the output
    assert E.main(['run', *common, '--expect-bundle-sha256', reference['bundle_sha256'], '--checkpoint',
                   str(tmp_path / 'ck'), '--out', str(tmp_path / 'alone')]) == 0
    alone = json.loads((tmp_path / 'alone' / 'PAPERSTREAM.json').read_text())
    assert alone['matches_expected_bundle'] is True and 'identical_to_reference' not in alone
    assert alone['checkpoint_counts'] == {'absent': 3}
    index = (tmp_path / 'alone' / 'CHECKPOINT_INDEX.json')
    assert alone['checkpoint_index_sha256'] == hashlib.sha256(index.read_bytes()).hexdigest()
    for word in ('pnl', 'return', 'HW'):
        assert word not in index.read_text(), word
    with pytest.raises(E.StreamError, match='nothing_to_compare_with'):
        E.main(['run', *common, '--out', str(tmp_path / 'none')])
    with pytest.raises(E.StreamError, match='reference_and_its_sha256_go_together'):
        E.main(['run', *common, '--reference', str(ref), '--out', str(tmp_path / 'half')])
    with pytest.raises(E.StreamError, match='checkpoint_inside_the_output'):
        E.main(['run', *common, '--expect-bundle-sha256', '1' * 64, '--checkpoint', str(tmp_path / 'in' / 'ck'),
                '--out', str(tmp_path / 'in')])
    capsys.readouterr()
    assert E.main(['run', *common, '--reference', str(ref), '--reference-sha256', ref_sha,
                   '--expect-bundle-sha256', '1' * 64, '--out', str(tmp_path / 'run2')]) == 1
    with pytest.raises(E.StreamError, match='output_exists'):
        E.main(['reference', *common, '--out', str(tmp_path / 'ref')])


def test_thresholds_are_the_protected_ones_and_never_counted():
    t = E.thresholds()
    assert (t['min_qualified_cycles'], t['min_creator_groups']) == (50, 20)
    assert t['these_cycles_count_toward_them'] is False and t['operational_master_entry'] is False
    from bot.master_decision import POLICY, MasterDecisionOrchestrator
    with pytest.raises(ValueError):
        MasterDecisionOrchestrator(dict(POLICY, min_qualified_cycles=49))   # the frozen code refuses a lower gate


def test_journal_reconciles_and_a_tampered_journal_is_refused(series, tmp_path):
    bundle, journals = _records(series, tmp_path, True)
    recs = bundle['pools']
    checked = sum(E.reconcile(r, journals) for r in recs)
    closed = sum(1 for r in recs for row in r['arms'].values() if row.get('pnl_lamports') is not None)
    assert checked == closed
    if closed:
        bad = json.loads(json.dumps(journals))
        for j in bad:
            for e in j['events']:
                if e['kind'] == 'SELL':
                    e['received'] += 1
        with pytest.raises(E.StreamError, match='journal_does_not_reconcile'):
            for r in recs:
                E.reconcile(r, bad)


def test_offline_no_sending_or_signing_module_is_imported(series, tmp_path):
    forbidden = ('bot.live.engine', 'bot.live.route', 'bot.live.route_dispatch', 'bot.live.cleanup', 'bot.live.safety',
                 'bot.live.journal', 'bot.live.cpmm_swap', 'bot.live.cpmm_exit', 'bot.live.helius_readonly_rpc')
    _records(series, tmp_path, True)
    assert not [m for m in forbidden if m in sys.modules]
    import inspect
    code = inspect.getsource(E).split('"""', 2)[2]
    for word in ('requests', 'urllib', 'websocket', 'http', 'sign', 'keypair', 'private', 'send_transaction'):
        assert word not in code, word


@pytest.mark.parametrize('enter_at', [1, 3, 8])
def test_forced_master_cycles_are_identical_and_reconcile(monkeypatch, enter_at, series, tmp_path):
    """The frozen MASTER never enters on the 3 frozen pools (WAIT): force the observer to say ENTER, the SAME way for
    the batch and the streaming runs, so that the frozen ResearchArm exits (TP 7 / SL 5, clock 30 s), the trade rows,
    the clock-exit rows and the journal reconciliation are exercised on real timelines."""
    def forced(self, history):
        index = len(history) - 1
        go = index >= enter_at
        decision = dict(intent='ENTER' if go else 'WAIT', blocking_reasons=[] if go else ['forced_test_wait'])
        return dict(shared=dict(index=index, forced_test=True, inputs_causal=True),
                    decisions={name: dict(decision) for name in hrr.ARMS},
                    exit_conditions=dict(tp_pct=7, sl_pct=5) if go else None, scorer_exit_plan={})
    monkeypatch.setattr(hrr._PoolObserver, 'observe', forced)
    batch, _ = _records(series, tmp_path, False)
    streamed, journals = _records(series, tmp_path, True)
    batch, streamed = batch['pools'], streamed['pools']
    outcomes = [row['outcome'] for r in batch for row in r['arms'].values()]
    assert any(o in ('closed', 'migrated_unpriced', 'open_at_end') for o in outcomes), outcomes
    assert E._canonical(batch) == E._canonical(streamed)
    closed = sum(1 for r in streamed for row in r['arms'].values() if row.get('pnl_lamports') is not None)
    assert sum(E.reconcile(r, journals) for r in streamed) == closed
    kinds = [e['kind'] for j in journals for e in j['events']]
    assert 'BUY' in kinds and ('SELL' in kinds or 'MARK_AT_END' in kinds)
    bad = json.loads(json.dumps(journals))
    for j in bad:
        for e in j['events']:
            if e['kind'] == 'SELL':
                e['received'] += 1
    with pytest.raises(E.StreamError, match='journal_does_not_reconcile'):
        for r in streamed:
            E.reconcile(r, bad)
