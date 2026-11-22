"""cyclesplit: the reading's population rule, exact boundaries, whitelisted output, anchored input, frozen total."""
import gzip
import hashlib
import json
import socket
import tempfile
from pathlib import Path

import pytest

from bot.market import w1_collection
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from cyclesplit import split as C
from w1aux import dayj

PACK = Path('tests/fixtures/launchlab_sol_pools')          # run from the frozen tree (aff97638)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


def _write(tmp_path, bundle, name='L1.json.gz'):
    path = tmp_path / 'bundles' / name
    return path, w1_run._write_json(path, bundle)                       # the very writer of run_trials


def _synthetic(slots_closed, slots_other=()):
    pools = [dict(pool=f'p{i}', creation_slot=s, arms=dict(master=dict(outcome='closed'), reference=dict(outcome='no_entry')))
             for i, s in enumerate(slots_closed)]
    pools += [dict(pool=f'q{i}', creation_slot=s, arms=dict(master=dict(outcome=o), reference=dict(outcome='closed')))
              for i, (s, o) in enumerate(slots_other)]
    closed = len(slots_closed)
    return dict(pools=pools, totals=dict(master=dict(closed_cycles=closed), reference=dict(closed_cycles=len(slots_other))))


def test_exact_boundaries_of_the_reading_rule(tmp_path):
    s0 = 467_275_745
    lo, hi = w1_collection.bounds(s0)['evaluation']
    assert (lo, hi) == (467_678_545, 469_291_345)                       # the W1 range of R02's diagnosis
    bundle = _synthetic([s0, lo - 1, lo, lo + 5, hi - 1, hi, hi + 7],
                        [(lo, 'open_at_window_end'), (lo, 'no_entry'), (hi - 1, 'migrated_unpriced')])
    path, sha = _write(tmp_path, bundle)
    doc = C.run(path, sha, s0)
    assert doc['counts'] == dict(master_closed_before=2, master_closed_inside=3, master_closed_after=2,
                                 master_closed_total=7)
    assert tuple(doc) == C.KEYS and doc['evaluation'] == [lo, hi] and doc['bundle_file_sha256'] == sha


def test_only_the_master_arm_is_counted(tmp_path):
    lo, _hi = w1_collection.bounds(467_275_745)['evaluation']
    bundle = _synthetic([lo], [(lo, 'no_entry'), (lo, 'no_entry')])       # reference has 2 closed, master 1
    path, sha = _write(tmp_path, bundle)
    assert C.run(path, sha, 467_275_745)['counts']['master_closed_inside'] == 1


def test_refusals(tmp_path):
    path, sha = _write(tmp_path, _synthetic([1]))
    with pytest.raises(C.SplitError, match='bundle_is_not_the_anchored_one'):
        C.run(path, '0' * 64, 467_275_745)
    bad = _synthetic([1])
    bad['totals']['master']['closed_cycles'] = 2
    p2, s2 = _write(tmp_path, bad, 'bad.json.gz')
    with pytest.raises(C.SplitError, match='split_does_not_add_up_to_the_frozen_total'):
        C.run(p2, s2, 467_275_745)
    noslot = _synthetic([1])
    del noslot['pools'][0]['creation_slot']
    p3, s3 = _write(tmp_path, noslot, 'noslot.json.gz')
    with pytest.raises(C.SplitError, match='pool_without_creation_slot'):
        C.run(p3, s3, 467_275_745)


def test_on_a_real_frozen_l1_bundle_with_master_cycles(tmp_path, monkeypatch, capsys):
    """Real fixture bundle (the frozen run_replay call of run_trials, observer forced to ENTER so that the master arm
    closes cycles) written by w1_run._write_json; two S0 put the 3 pools before / inside / after the range."""
    def forced(self, history):
        index = len(history) - 1
        go = index >= 1
        decision = dict(intent='ENTER' if go else 'WAIT', blocking_reasons=[] if go else ['forced_test_wait'])
        return dict(shared=dict(index=index, forced_test=True, inputs_causal=True),
                    decisions={name: dict(decision) for name in hrr.ARMS},
                    exit_conditions=dict(tp_pct=7, sl_pct=5) if go else None, scorer_exit_plan={})
    monkeypatch.setattr(hrr._PoolObserver, 'observe', forced)
    series = tmp_path / 's.json'
    dayj._selfcheck_series(series)
    bundle = hrr.run_replay(PACK, w1_run.l1_params(), sus.load_series(series), w1_run.L1_EXIT,
                            hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'),
                            placebo_arm=True)
    total = bundle['totals']['master']['closed_cycles']
    assert total >= 1
    path, sha = _write(tmp_path, bundle)
    slots = sorted(p['creation_slot'] for p in bundle['pools'] if p['arms']['master']['outcome'] == 'closed')
    s0_all_inside = slots[0] - 402_800
    doc = C.run(path, sha, s0_all_inside)
    assert doc['counts'] == dict(master_closed_before=0, master_closed_inside=total, master_closed_after=0,
                                 master_closed_total=total)
    s0_all_before = slots[-1] + 1 - 402_800 + 1
    assert C.run(path, sha, s0_all_before)['counts']['master_closed_before'] == total
    s0_all_after = slots[0] - 2_015_600
    assert C.run(path, sha, s0_all_after)['counts']['master_closed_after'] == total
    assert C.main(['--bundle', str(path), '--bundle-sha256', sha, '--s0', str(s0_all_inside)]) == 0
    text = capsys.readouterr().out
    out = json.loads(text)
    assert tuple(out) == C.KEYS and tuple(out['counts']) == C.COUNTS
    for pool in bundle['pools']:
        assert pool['pool'] not in text
    for word in ('pnl', 'return', 'received', 'spent', 'lamports'):
        assert word not in text, word
