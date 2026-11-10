"""w1aux.rehearse (v2.2, R02 audit 7eae237e) and w1aux.lazy: no pilot or holdout return is ever read."""
import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from w1aux import rehearse as R

ENV = {'RUGGER_NO_DOTENV': '1'}
PACK = Path('tests/fixtures/launchlab_sol_pools')


def test_frozen_pack_rehearsal_eager_and_lazy_give_identical_bundles_and_no_pnl(tmp_path):
    eager = R.frozen_pack(out=tmp_path / 'e', environ=ENV)
    lazy = R.frozen_pack(out=tmp_path / 'l', lazy=True, environ=ENV)
    for s in (eager, lazy):
        assert s['kind'] == 'TECHNICAL_REHEARSAL_FROZEN_TEST_PACK' and s['ledger_verdict'] == 'PASS'
        assert s['cycles_verified'] == s['cycles_with_entry'] > 0 and s['mismatches'] == 0
        text = json.dumps(s).lower()
        assert 'pnl' not in text and 'net_return' not in text
    assert eager['bundles_sha256'] == lazy['bundles_sha256'] and eager['ledger_sha256'] == lazy['ledger_sha256']
    assert lazy['lazy_archives'] is True and eager['lazy_archives'] is False
    l1 = json.loads(gzip.decompress((tmp_path / 'l' / 'bundles' / 'L1.json.gz').read_bytes()))
    assert l1['params']['sol_usd_provenance'] == R.DECLARED_LABEL


def test_guards(tmp_path, monkeypatch):
    with pytest.raises(R.RehearsalError, match='RUGGER_NO_DOTENV'):
        R.frozen_pack(out=tmp_path / 'a', environ={})
    (tmp_path / 'b').mkdir()
    with pytest.raises(R.RehearsalError, match='output_directory_already_exists'):
        R.frozen_pack(out=tmp_path / 'b', environ=ENV)
    monkeypatch.setattr(R, 'FROZEN_PACK_MANIFEST_SHA256', '0' * 64)
    with pytest.raises(R.RehearsalError, match='not_the_frozen_test_pack'):
        R.frozen_pack(out=tmp_path / 'c', environ=ENV)


@pytest.mark.parametrize('slots, ok', [([464_661_843, 466_248_336], True), ([466_248_337], False),
                                       ([466_442_736], False), ([466_442_737, 467_275_744], True),
                                       ([467_275_745], False), ([1, None], False), ([], False), (['5'], False)])
def test_slot_guard(slots, ok):
    if ok:
        R.check_slots(slots)
    else:
        with pytest.raises(R.RehearsalError):
            R.check_slots(slots)


def _run_dir(tmp_path, window):
    run = tmp_path / 'run'
    run.mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps({'window': window}))
    return run


def test_export_only_accepts_only_the_exact_pilot_window(tmp_path, monkeypatch):
    from bot.market import backfill as bf
    for window in (dict(address=bf.LAUNCHLAB_PROGRAM, slot_min=466_226_737, slot_max=466_248_337),
                   dict(address=bf.LAUNCHLAB_PROGRAM, slot_min=466_226_736, slot_max=466_248_336),
                   dict(address='other', slot_min=466_226_737, slot_max=466_248_336)):
        run = _run_dir(tmp_path / str(len(list(tmp_path.iterdir()))), window)
        with pytest.raises(R.RehearsalError, match='export_only_accepts_only_the_pilot_window'):
            R.export_only(run_dir=run, out=tmp_path / 'never', environ=ENV)
    # the exact pilot window reaches the frozen export (stubbed here); counts only, pools directory deleted
    from bot.market import backfill_export as bx
    run = _run_dir(tmp_path / 'ok', dict(address=bf.LAUNCHLAB_PROGRAM, slot_min=466_226_737, slot_max=466_248_336))

    def fake_export(run_dir, pools, **kwargs):
        pools.mkdir()
        (pools / 'P.json.gz').write_bytes(b'x' * 10)
        (pools / 'MANIFEST.json').write_text(json.dumps({'pools': [{'file': 'P.json.gz', 'signatures': 7, 'trades': 3}]}))
    monkeypatch.setattr(bx, 'export_pools', fake_export)
    summary = R.export_only(run_dir=run, out=tmp_path / 'out', environ=ENV)
    assert summary['kind'] == 'PILOT_EXPORT_ONLY_COUNTS' and summary['pools'] == 1
    assert (summary['stored_signatures'], summary['decoded_trades'], summary['compressed_bytes']) == (7, 3, 10)
    assert not (tmp_path / 'out' / 'pools').exists() and summary['pools_directory_deleted']
    assert 'pnl' not in json.dumps(summary).lower()


def test_command_modes(tmp_path, monkeypatch):
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    with pytest.raises(R.RehearsalError, match='the_pilot_run_is_accepted_only_with_export_only'):
        R.main(['--run', str(tmp_path), '--out', str(tmp_path / 'x')], out=io.StringIO())
    with pytest.raises(R.RehearsalError, match='export_only_needs_the_pilot_run'):
        R.main(['--frozen-pack', '--export-only', '--out', str(tmp_path / 'y')], out=io.StringIO())
    with pytest.raises(SystemExit):
        R.main(['--pools', str(PACK), '--out', str(tmp_path / 'z')], out=io.StringIO())       # no arbitrary pools
    out = io.StringIO()
    assert R.main(['--frozen-pack', '--lazy', '--out', str(tmp_path / 'r')], out=out) == 0
    assert json.loads(out.getvalue())['ledger_verdict'] == 'PASS'


def test_lazy_archives_hold_one_pool_and_detect_changes(tmp_path):
    import shutil
    from bot.p4 import historical_research_replay as hrr
    from w1aux import lazy
    shutil.copytree(PACK, tmp_path / 'pack')
    eager = hrr.load_fixtures(tmp_path / 'pack')
    with lazy.lazy_archives():
        assert hrr.load_fixtures is lazy.load_fixtures_lazy
        lz = hrr.load_fixtures(tmp_path / 'pack')
    assert hrr.load_fixtures is not lazy.load_fixtures_lazy                     # restored
    assert lz[0] == eager[0] and lz[1] == eager[1] and lz[3] == eager[3]
    for (_e1, a), (_e2, b) in zip(eager[2], lz[2]):
        assert isinstance(b, lazy.LazyArchive) and set(vars(b)) == {'_path', '_pool', '_sha256'}   # holds nothing
        assert (b.pool, b.account, b.signatures, b.signatures_complete, b.transactions) == \
            (a.pool, a.account, a.signatures, a.signatures_complete, a.transactions)
        assert b.transactions is b.transactions                             # the one-pool cache
        with pytest.raises(lazy.LazyArchiveError, match='read_only'):
            b.transactions = {}
    first, second = lz[2][0][1], lz[2][1][1]
    second.transactions                                                     # the cache now holds another pool
    path = tmp_path / 'pack' / lz[2][0][0]['file']
    path.write_bytes(path.read_bytes() + b'\0')
    with pytest.raises(lazy.LazyArchiveError, match='archive_changed_on_disk'):
        first.transactions                                                  # re-read: sha checked again
    with pytest.raises(ValueError, match='fixture_sha256_mismatch'):
        lazy.load_fixtures_lazy(tmp_path / 'pack')
