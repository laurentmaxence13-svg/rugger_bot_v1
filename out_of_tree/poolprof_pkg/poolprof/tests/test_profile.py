"""poolprof: the profiled call is the frozen per-pool L1 replay; the output is the cProfile table only."""
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import bot
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from poolprof import profile as P
from w1aux import dayj

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()


@pytest.fixture
def series(tmp_path):
    path = tmp_path / 'series.json'
    dayj._selfcheck_series(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_rank_is_by_gz_size_largest_first():
    manifest = json.loads((PACK / 'MANIFEST.json').read_text())
    ranked = P.ranked_entries(PACK, manifest)
    sizes = [os.path.getsize(PACK / e['file']) for e in ranked]
    assert sizes == sorted(sizes, reverse=True) and len(ranked) == 3
    assert {e['file'] for e in ranked} == {e['file'] for e in manifest['pools']}


@pytest.mark.parametrize('rank', [1, 2, 3])
def test_the_profiled_call_is_the_frozen_l1_replay_of_that_pool(series, rank):
    doc, record = P.profile_pool(PACK, SHA, *series, rank, keep_record=True)
    archives = [a for _e, a in hrr.load_fixtures(PACK)[2]]
    bundle = hrr.run_replay(PACK, w1_run.l1_params(), sus.load_series(series[0]), w1_run.L1_EXIT,
                            hrr.CreatorHistory.from_archives(archives, 'manifest'), placebo_arm=True)
    frozen = {p['pool']: p for p in bundle['pools']}
    assert record == frozen[record['pool']]                                     # same frozen call, same record
    expected = P.ranked_entries(PACK, json.loads((PACK / 'MANIFEST.json').read_text()))[rank - 1]
    assert record['pool'] == expected['pool']


def test_the_output_is_the_profile_table_only(series):
    doc = P.profile_pool(PACK, SHA, *series, 1)
    assert set(doc) == {'schema', 'rank', 'input', 'fast_analyser', 'total_time_s', 'top_by_cumtime', 'label',
                        'contains_results'}
    assert doc['fast_analyser'] is False and doc['contains_results'] is False and doc['total_time_s'] > 0
    rows = doc['top_by_cumtime']
    assert 0 < len(rows) <= P.TOP and all(set(r) == {'function', 'ncalls', 'tottime', 'cumtime'} for r in rows)
    assert [r['cumtime'] for r in rows] == sorted((r['cumtime'] for r in rows), reverse=True)
    assert any('replay_pool' in r['function'] for r in rows)
    assert all('/' not in r['function'] for r in rows)                          # base names only, no paths
    text = json.dumps(doc)
    manifest = json.loads((PACK / 'MANIFEST.json').read_text())
    for entry in manifest['pools']:
        assert entry['pool'] not in text and entry['file'] not in text and entry['sha256'] not in text
    for word in ('pnl', 'received', 'spent', 'net_return'):
        assert word not in text


def test_every_input_is_anchored(series, tmp_path):
    with pytest.raises(P.ProfError, match='manifest_is_not_the_anchored_one'):
        P.profile_pool(PACK, '0' * 64, *series, 1)
    with pytest.raises(Exception, match='sha|anchored|series'):
        P.profile_pool(PACK, SHA, series[0], '0' * 64, 1)
    for rank in (0, 4, 50, '1'):
        with pytest.raises(P.ProfError, match='rank_out_of_range'):
            P.profile_pool(PACK, SHA, *series, rank)
    copy = tmp_path / 'pack'
    shutil.copytree(PACK, copy)
    manifest = json.loads((copy / 'MANIFEST.json').read_text())
    target = P.ranked_entries(copy, manifest)[0]['file']
    raw = bytearray((copy / target).read_bytes())
    raw[-1] ^= 1
    (copy / target).write_bytes(bytes(raw))
    with pytest.raises(P.ProfError, match='archive_is_not_the_manifest_one'):
        P.profile_pool(copy, SHA, *series, 1)


def test_cli_writes_once(series, tmp_path, capsys):
    args = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(series[0]),
            '--sol-usd-series-sha256', series[1], '--rank', '2', '--out', str(tmp_path / 'o')]
    assert P.main(args) == 0
    raw = (tmp_path / 'o' / 'POOLPROF.json').read_bytes()
    assert json.loads(capsys.readouterr().out)['sha256'] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(P.ProfError, match='output_exists'):
        P.main(args)


def test_the_collection_window_of_the_manifest_is_applied(series, tmp_path):
    copy = tmp_path / 'windowed'
    shutil.copytree(PACK, copy)
    manifest = json.loads((copy / 'MANIFEST.json').read_text())
    slots = sorted(tx['slot'] for _e, a in hrr.load_fixtures(PACK)[2] for tx in a.transactions.values())
    middle = slots[len(slots) // 2]
    manifest.update(entry_cutoff_slot=middle, window_slot_max=middle + 10_000)          # gap >= exit horizon
    (copy / 'MANIFEST.json').write_text(json.dumps(manifest))
    sha = hashlib.sha256((copy / 'MANIFEST.json').read_bytes()).hexdigest()
    archives = [a for _e, a in hrr.load_fixtures(copy)[2]]
    bundle = hrr.run_replay(copy, w1_run.l1_params(), sus.load_series(series[0]), w1_run.L1_EXIT,
                            hrr.CreatorHistory.from_archives(archives, 'manifest'), placebo_arm=True)
    frozen = {p['pool']: p for p in bundle['pools']}
    windowed = 0
    for rank in (1, 2, 3):
        _doc, record = P.profile_pool(copy, sha, *series, rank, keep_record=True)
        assert record == frozen[record['pool']] and record.get('window') is not None
        windowed += 1
    assert windowed == 3


def test_the_manifest_is_checked_before_anything_is_read(series):
    with pytest.raises(P.ProfError, match='manifest_is_not_the_anchored_one'):
        P.profile_pool(PACK, '0' * 64, series[0], '0' * 64, 1)                   # not the series error first
