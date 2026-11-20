"""slot_clock: the chain clock over a slot range, from the archives' slot and blockTime only."""
import gzip
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import slot_clock as SC                                      # noqa: E402


def _archive(directory, name, rows, transactions=None):
    directory.mkdir(exist_ok=True)
    with gzip.open(directory / f'{name}.json.gz', 'wt', encoding='utf-8') as h:
        json.dump(dict(version=1, pool=name, signatures=rows, transactions=transactions or {}), h)


def _run(pools, start, end):
    out = io.StringIO()
    SC.main(['--pools', str(pools), '--start', str(start), '--end', str(end)], out=out)
    return json.loads(out.getvalue())


def test_rate_over_the_range_only_and_transactions_fill_missing_rows(tmp_path):
    pools = tmp_path / 'pools'
    _archive(pools, 'a', [dict(signature='s1', slot=1_000, blockTime=10_000), dict(signature='s2', slot=5_000, blockTime=10_860),
                          dict(signature='s0', slot=10, blockTime=1)])                       # s0 outside the range
    _archive(pools, 'b', [dict(signature='s3', slot=3_000, blockTime=None)],
             dict(s3=dict(slot=3_000, blockTime=10_430), s4=dict(slot=9_000, blockTime=12_150)))  # s4 outside
    doc = _run(pools, 1_000, 6_000)
    assert (doc['files'], doc['points']) == (2, 3)
    assert doc['first'] == dict(slot=1_000, block_time=10_000, utc='1970-01-01T02:46:40+00:00')
    assert doc['last']['slot'] == 5_000 and doc['ms_per_slot'] == 215.0
    assert doc['evaluation_hours_at_that_rate'] == round(5_000 * 0.215 / 3600, 2)


def test_frozen_pack_rate_and_empty_range(tmp_path):
    import bot                                               # the frozen checkout aff97638, on PYTHONPATH
    fixtures = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    assert _run(fixtures, 1, 10 ** 12)['ms_per_slot'] == 215.47       # frozen pack, 2026-11-02
    doc = _run(tmp_path, 1, 2)
    assert doc == dict(files=0, points=0, start=1, end=2)
