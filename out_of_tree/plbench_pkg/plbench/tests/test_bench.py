"""plbench: the PAPER_LIVE chain end to end on the public fixtures, label SIMULATED_FEED, checks S-1..S-6 and stops."""
import hashlib
import json
import sys

import pytest

from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from papercost import engine as PC
from paperstream.tests.test_engine import PACK, _timelines
from plbench import bench as B
from rtgate import gate as RT
from w1aux import dayj


@pytest.fixture
def series(tmp_path):
    path = tmp_path / 'series.json'
    dayj._selfcheck_series(path)
    return sus.load_series(path)


@pytest.fixture(scope='module')
def busy():
    return max(_timelines(), key=lambda t: len(t.events))


def _sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


GOOD_LATENCY = [1, 2, 2, 3, 3, 3, 4, 4] * 5


def test_the_audited_files_are_checked(monkeypatch):
    found = B.frozen_check()
    assert set(found) == set(B.FROZEN_FILES) | {'python'}
    monkeypatch.setitem(B.FROZEN_FILES, 'rtgate', (RT, '0' * 64))
    with pytest.raises(B.BenchError, match='audited_file_differs:rtgate'):
        B.frozen_check()


def test_neutral_options_and_a_clean_feed_give_the_frozen_bundle(series):
    bundle, records, _rows = B._once(PACK, series, PC.Options.neutral(), None)
    frozen = B._bundle(PACK, series)
    assert _sha(bundle) == _sha(frozen) and bundle['bundle_sha256'] == frozen['bundle_sha256']
    assert all(r['status'] == RT.COMPLETE for r in records) and hrr.replay is not B.bench_replay
    assert {r['engine'] for r in records} == {'CostedTrade'}                     # papercost behind the gate


def test_a_clean_simulated_feed_passes_s1_to_s6(series):
    report = B.run_bench(PACK, series, latency_slots=GOOD_LATENCY)
    c = report['checks']
    assert report['label'] == 'SIMULATED_FEED' and report['counts_for_operational_master'] is False
    assert report['cycle_receipts'] == 0 and report['economic_claim'] is None
    assert c['S1_coverage']['value'] == 1.0 and c['S1_coverage']['passed']
    assert c['S2_rerun_identical']['passed'] and c['S4_no_signer']['passed']
    assert c['S3_latency']['value'] == dict(p95=4, p99=4) and c['S3_latency']['passed']
    assert c['S5_sol_usd_fresh']['passed'] and c['S6_costs_published']['passed']
    summary = c['S6_costs_published']['summary']
    assert set(summary) == {'rent_lost', 'closed', 'frozen'}
    assert summary['closed']['net_lamports'] > summary['rent_lost']['net_lamports'] or summary['closed']['counted'] == 0
    assert report['technical_success'] is True


def test_repaired_delivery_faults_change_nothing(series, busy):
    clean = B.run_bench(PACK, series, latency_slots=GOOD_LATENCY)
    noisy = B.run_bench(PACK, series, latency_slots=GOOD_LATENCY,
                        faults={busy.pool: dict(reverse_slots=True, dup=[3, 10, 40])})
    assert noisy['rows_sha256'] == clean['rows_sha256'] and noisy['checks']['S1_coverage']['value'] == 1.0


def test_a_lost_event_makes_the_pool_incomplete_valued_at_zero_and_fails_s1(series, busy):
    report = B.run_bench(PACK, series, latency_slots=GOOD_LATENCY, faults={busy.pool: dict(drop=[50])})
    s1 = report['checks']['S1_coverage']
    assert report['incomplete_pools'] == 1 and s1['value'] == pytest.approx(2 / 3) and not s1['passed']
    assert any(r.startswith('reserve_chain_break') for r in s1['incomplete_reasons'])
    assert report['technical_success'] is False
    _bundle, _records, rows = B._once(PACK, series, PC.Options.primary(), {busy.pool: dict(drop=[50])})
    flagged = [r for r in rows if r['incomplete']]
    assert flagged and all(r['outcome'] in ('counterfactual_divergence', 'no_entry') for r in flagged)
    for r in flagged:
        if r['outcome'] == 'counterfactual_divergence':
            assert r['costs']['rent_lost']['status'] == 'unpriced_counted_at_zero' and r['costs']['rent_lost']['counted']
    # an unhealed declared reconnect at the very start is incomplete too
    gap = B.run_bench(PACK, series, latency_slots=GOOD_LATENCY, faults={busy.pool: dict(gap_before=[20], drop=[20])})
    assert gap['incomplete_pools'] == 1


def test_s3_is_fail_closed_and_s4_s5_fail_when_they_should(series, tmp_path, monkeypatch):
    assert B.run_bench(PACK, series)['checks']['S3_latency']['passed'] is False                  # not measured
    slow = B.run_bench(PACK, series, latency_slots=[5] * 10)['checks']['S3_latency']
    assert slow['value']['p95'] == 5 and not slow['passed']
    fresh = tmp_path / 'fresh.json'
    dayj._selfcheck_series(fresh)
    doc = json.loads(fresh.read_text())
    doc['points'][0]['block_time'] -= 3_600
    doc['points'][0]['publish_time'] -= 3_600
    stale = tmp_path / 'stale.json'
    stale.write_text(json.dumps(doc))
    s5 = B.run_bench(PACK, sus.load_series(stale), latency_slots=GOOD_LATENCY)['checks']['S5_sol_usd_fresh']
    assert s5['value'] == 1.0 and not s5['passed']
    monkeypatch.setitem(sys.modules, 'bot.live.signer', object())
    assert B.run_bench(PACK, series, latency_slots=GOOD_LATENCY)['checks']['S4_no_signer']['passed'] is False


def test_percentile_is_the_nearest_rank():
    assert B.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10 and B.percentile([1, 2, 3, 4], 50) == 2
    assert B.percentile(list(range(1, 101)), 95) == 95 and B.percentile([], 95) is None


CLEAN = dict(fingerprint='F', credits_used=10, credits_cap=1_000, modules=(), log_lines=('ok',),
             incomplete_share_24h=0.01, feed_gap_minutes=0, clock_drift_s=0.3, disk_used_share=0.2)


@pytest.mark.parametrize('change, stop', [
    (dict(fingerprint='G'), '0_code_or_environment_sha_changed'),
    (dict(credits_used=980), '1_credits_98_percent'),
    (dict(modules=('bot.live.signer',)), '2_signing_or_sending_module'),
    (dict(log_lines=('GET /?api-key=abc',)), '3_secret_in_a_log'),
    (dict(log_lines=('Authorization: Bearer x',)), '3_secret_in_a_log'),
    (dict(incomplete_share_24h=0.21), '4_incomplete_over_20_percent_24h'),
    (dict(feed_gap_minutes=31), '5_feed_cut_over_30_min_new_segment'),
    (dict(clock_drift_s=-2.5), '6_clock_drift_over_2_s_pause'),
    (dict(disk_used_share=0.9), '7_disk_90_percent'),
])
def test_each_hard_stop(change, stop):
    assert B.stops(CLEAN, 'F') == []
    assert B.stops(dict(CLEAN, **change), 'F') == [stop]


def test_the_feed_faults():
    t = max(_timelines(), key=lambda x: len(x.events))
    events = list(t.events)
    assert B.feed(events) == events
    assert len(B.feed(events, dict(drop=[1, 2]))) == len(events) - 2
    assert len(B.feed(events, dict(dup=[1]))) == len(events) + 1
    assert sorted(id(e) for e in B.feed(events, dict(reverse_slots=True))) == sorted(id(e) for e in events)
    marked = B.feed(events, dict(gap_before=[5]))
    assert marked[5] == ('gap', events[4].slot, events[5].slot)


def test_an_open_position_in_an_incomplete_pool_is_marked_unpriced(busy):
    # on the fixtures the frozen arms never hold a position when a gap could follow (only one placebo entry, on the
    # last event of a 2-event pool): the rule is shown on the bench engine itself with a forced entry
    from bot.market import replay as R
    from paperstream.tests.test_engine import EnterAt
    model = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')
    with B.bench_engine(PC.Options.neutral(), {busy.pool: dict(drop=[60])}):
        held = B.bench_replay(busy, EnterAt(5, None, None), model, quote_mint=R.WSOL_MINT)
        early = B.bench_replay(busy, EnterAt(80, None, None), model, quote_mint=R.WSOL_MINT)
    assert held.entry_index is not None and held.outcome == 'counterfactual_divergence'
    assert any(n.startswith('rtgate:INCOMPLETE:reserve_chain_break') for n in held.notes)
    row = dict(outcome=held.outcome, spent=held.spent, received=held.received, tx_costs=held.tx_costs,
               failed_attempt_costs=0, entry_index=held.entry_index, notes=held.notes)
    c = PC.row_costs(row, 'rent_lost')
    assert c['status'] == 'unpriced_counted_at_zero' and c['counted'] and c['parts']['sale_or_mark'] == 0
    assert early.entry_index is None and early.outcome == 'no_entry'          # the gap came before any entry


def test_s2_fails_when_the_fingerprint_changes_during_the_run(series, monkeypatch):
    real = B.fingerprint
    calls = []

    def drifting():
        calls.append(1)
        found = real()
        return found if len(calls) == 1 else dict(found, papercost='changed')
    monkeypatch.setattr(B, 'fingerprint', drifting)
    monkeypatch.setattr(B, 'frozen_check', lambda: B.fingerprint())
    report = B.run_bench(PACK, series, latency_slots=GOOD_LATENCY)
    assert report['checks']['S2_rerun_identical']['passed'] is False and report['technical_success'] is False
