"""w1aux.stream_export: the streaming export writes the frozen export's files byte for byte.

Every case runs the FROZEN ``backfill_export.export_pools`` and the streaming one on the same verified
window (the three certified SOL pools of the frozen tests, 173 signatures of which 59 failed, plus
hand-made variants) and compares every file, the MANIFEST and the returned value.
"""
import gzip
import hashlib
import json
import random
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import backfill_export as bx
from tests import test_launchlab_backfill as tlb
from w1x import stream_export as se

FROZEN_EXPORT = bx.export_pools
POOLS = sorted(tlb._fixture_archives()[1])


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(bf, 'GSFA_PAGE', 25)
    monkeypatch.setattr(bf, 'GTFA_FULL_PAGE', 10)
    monkeypatch.setattr(bf, 'GTFA_SIG_PAGE', 40)


def _window(tmp_path, chain=None, *extra, name='w'):
    code, _ = tlb._run(tmp_path, chain or tlb.FakeChain(), *extra, out=name)
    assert code == 0
    return tmp_path / name


def _tree(path):
    return {p.name: p.read_bytes() for p in sorted(Path(path).iterdir())}


def _same(window, tmp_path, tag='x', buckets=3, workers=1, **kwargs):
    """Run both exports; they must give the same value and the same bytes. Returns the frozen value."""
    frozen = FROZEN_EXPORT(window, tmp_path / f'frozen_{tag}', **kwargs)
    mine = se.export_pools(window, tmp_path / f'stream_{tag}', buckets=buckets, workers=workers, **kwargs)
    assert mine == frozen
    assert _tree(tmp_path / f'stream_{tag}') == _tree(tmp_path / f'frozen_{tag}')
    assert not (tmp_path / f'stream_{tag}.stream_tmp').exists()             # the temporary directory is removed
    return frozen


def _write_segment(path, rows):
    data = gzip.compress(''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode(), mtime=0)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _rebuild(window, groups, extra_signatures=()):
    """Rewrite the tx rows of a verified window as the given segments (and add signature rows); still verifies."""
    manifest = json.loads((window / 'manifest.json').read_text())
    for seg in manifest['segments']:
        if seg['kind'] == 'tx':
            (window / seg['path']).unlink()
    segments = []
    for number, rows in enumerate(groups):
        name = f'tx-9{number:05d}.jsonl.gz'
        segments.append(dict(kind='tx', path=name, rows=len(rows), sha256=_write_segment(window / name, rows)))
    for seg in manifest['segments']:
        if seg['kind'] == 'tx':
            continue
        if seg['kind'] == 'sig' and extra_signatures:
            rows = bf.read_segment(window / seg['path']) + [dict(signature=s) for s in extra_signatures]
            seg = dict(seg, rows=len(rows), sha256=_write_segment(window / seg['path'], rows))
            extra_signatures = ()
        segments.append(seg)
    everything = [row for rows in groups for row in rows]
    signatures = [row['signature'] for row in everything]
    manifest['segments'] = segments
    manifest['totals'].update(transactions=len(everything), duplicate_signatures=len(signatures) - len(set(signatures)),
                              failed_transactions=sum((r.get('meta') or {}).get('err') is not None for r in everything))
    (window / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    checked = bf.verify(window)
    assert checked['ok'] and checked['complete'], checked['problems']
    return manifest


def _rows(window):
    manifest = json.loads((window / 'manifest.json').read_text())
    return [row for seg in manifest['segments'] if seg['kind'] == 'tx' for row in bf.read_segment(window / seg['path'])]


def _synthetic(signature, pool, slot, index, *, err=None, payload='x'):
    return {'signature': signature, 'slot': slot, 'blockTime': 1_700_000_000 + slot, 'transactionIndex': index,
            'transaction': {'signatures': [signature], 'message': {'accountKeys': [pool]}},
            'meta': {'err': err, 'logMessages': [payload]}}


def test_the_three_certified_pools_are_written_byte_for_byte(tmp_path):
    window = _window(tmp_path)
    for number, (buckets, workers) in enumerate([(1, 1), (2, 1), (7, 2), (256, 1), (256, 3)]):
        export = _same(window, tmp_path, f'a{number}', buckets, workers)
    assert [p['pool'] for p in export['pools']] == POOLS and export['skipped'] == {}
    assert sum(p['signatures'] for p in export['pools']) == 173
    with_code = _same(window, tmp_path, 'code', collector_code=dict(sha256='c' * 64), entry_cutoff_gap_slots=162)
    assert with_code['collector_code'] == dict(sha256='c' * 64) and with_code['entry_cutoff_gap_slots'] == 162


def test_the_order_of_reading_does_not_matter_only_the_chain_order_does(tmp_path):
    window = _window(tmp_path)
    reference = FROZEN_EXPORT(window, tmp_path / 'reference')
    rows = _rows(window)
    random.Random(7).shuffle(rows)
    _rebuild(window, [rows[:40], rows[40:41], rows[41:120], rows[120:]])    # four segments, shuffled rows
    export = _same(window, tmp_path, 'shuffled', buckets=5, workers=2)
    assert [(p['pool'], p['sha256']) for p in export['pools']] == [(p['pool'], p['sha256']) for p in reference['pools']]


def test_pools_created_before_the_window_and_pools_not_quoted_in_sol(tmp_path, monkeypatch):
    first = min(tlb.ROWS.values(), key=lambda r: r['slot'])
    rpc = bf.open_rpc(tlb.URL, bf.CreditBudget(10**6, 10**9, bf.COST_PRESETS['public']), opener=tlb.FakeChain())
    manifest = bf.Backfill(rpc, bf.Window(tlb.ADDRESS, first['slot'] + 1, tlb.SLOT_MAX), tmp_path / 'late').run()
    assert manifest['complete']
    export = _same(tmp_path / 'late', tmp_path, 'late')
    assert export['skipped'] and set(export['skipped'].values()) == {'creation_not_in_window'}
    window = _window(tmp_path)
    real, usd1 = bx.creation_quote_mint, 'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB'
    monkeypatch.setattr(bx, 'creation_quote_mint', lambda tx, pool, mint: usd1 if pool == POOLS[0] else real(tx, pool, mint))
    for number, workers in enumerate((1, 2)):
        export = _same(window, tmp_path, f'usd{number}', workers=workers)
        assert export['skipped'] == {POOLS[0]: f'quote_not_sol:{usd1}'} and len(export['pools']) == 2


def test_duplicate_signatures_and_foreign_members_follow_the_frozen_rules(tmp_path):
    window = _window(tmp_path)
    rows = _rows(window)
    by_pool = {pool: [r for r in rows if pool in bx.account_keys(r)] for pool in POOLS}
    creation = {pool: min((r for r in members if (r.get('meta') or {}).get('err') is None),
                          key=lambda r: (r['slot'], r['transactionIndex'], r['signature']))
                for pool, members in by_pool.items()}
    trade = next(r for r in by_pool[POOLS[0]] if (r.get('meta') or {}).get('err') is None and r is not creation[POOLS[0]])
    altered = json.loads(json.dumps(trade))
    altered['meta']['logMessages'] = ['ALTERED COPY']
    first_slot = creation[POOLS[1]]['slot']
    extra = [
        json.loads(json.dumps(trade)),                                     # an exact duplicate of a trade
        altered,                                                           # same signature, another body, read LAST: it wins
        json.loads(json.dumps(creation[POOLS[0]])),                        # a duplicate of a creation
        _synthetic('SYN-FAILED-BEFORE', POOLS[1], first_slot - 1, 0, err={'InstructionError': [0, 'Custom']}),
        _synthetic('SYN-MEMBER', POOLS[1], tlb.SLOT_MAX, 9),               # a successful stranger naming the pool
        _synthetic('SYN-EARLY', POOLS[2], creation[POOLS[2]]['slot'] - 1, 0),   # successful BEFORE the creation
    ]
    _rebuild(window, [rows[:50], rows[50:] + extra], extra_signatures=['SYN-FAILED-BEFORE', 'SYN-MEMBER', 'SYN-EARLY'])
    export = _same(window, tmp_path, 'dup', buckets=4, workers=2)
    assert export['skipped'] == {POOLS[2]: 'earliest_transaction_is_not_the_creation'}
    kept = {p['pool']: p for p in export['pools']}
    archive = json.loads(gzip.decompress((tmp_path / 'stream_dup' / kept[POOLS[0]]['file']).read_bytes()))
    assert archive['transactions'][trade['signature']]['meta']['logMessages'] == ['ALTERED COPY']
    assert [r['signature'] for r in archive['signatures']].count(trade['signature']) == 3
    assert kept[POOLS[1]]['first_slot'] == first_slot - 1                  # the failed attempt stays listed
    # the same altered copy read FIRST loses against the original: the chain order ties are broken by reading rank
    again = _window(tmp_path, name='again')
    _rebuild(again, [[altered] + rows[:50], rows[50:]])
    export = _same(again, tmp_path, 'dup_first', buckets=4)
    archive = json.loads(gzip.decompress((tmp_path / 'stream_dup_first' / POOLS[0]).with_suffix('.json.gz').read_bytes()))
    assert archive['transactions'][trade['signature']]['meta'].get('logMessages') != ['ALTERED COPY']


def test_a_large_pool_goes_through_many_gzip_blocks_unchanged(tmp_path):
    window = _window(tmp_path)
    rows = _rows(window)
    rng = random.Random(11)
    big = [_synthetic(f'BIG{i:05d}', POOLS[1], tlb.SLOT_MAX, 100 + i,
                      payload=''.join(rng.choice('abcdefghij0123456789 ') for _ in range(1500)))
           for i in range(3000)]
    _rebuild(window, [rows, big[:1000], big[1000:]], extra_signatures=[r['signature'] for r in big])
    export = _same(window, tmp_path, 'big', buckets=2, workers=2)
    entry = next(p for p in export['pools'] if p['pool'] == POOLS[1])
    data = (tmp_path / 'stream_big' / entry['file']).read_bytes()
    assert entry['transactions'] > 3000 and len(gzip.decompress(data)) > 4_000_000


def test_the_frozen_refusals_are_the_same(tmp_path):
    tlb._run(tmp_path, tlb.FakeChain(drop_from_gsfa={sorted(tlb.ROWS)[0]}), out='incomplete')
    incomplete = tmp_path / 'incomplete'
    assert not bf.verify(incomplete)['complete']

    class Plain(tlb.FakeChain):
        def getTransaction(self, signature, options):
            body = dict(super().getTransaction(signature, options))
            body.pop('transactionIndex', None)
            return body
    no_index = _window(tmp_path, Plain(), '--bodies', 'rpc', name='plain')
    window = _window(tmp_path)
    cases = [(incomplete, {}, 'window_not_verified_or_incomplete'),
             (no_index, {}, 'transaction_index_missing_use_gtfa_bodies'),
             (window, dict(entry_cutoff_gap_slots=161), 'entry_cutoff_gap_slots_below_162'),
             (window, dict(entry_cutoff_gap_slots=79), 'entry_cutoff_gap_slots_below_162'),
             (window, dict(entry_cutoff_gap_slots='170'), 'entry_cutoff_gap_slots_below_162'),
             (window, dict(entry_cutoff_gap_slots=tlb.SLOT_MAX - tlb.SLOT_MIN), 'window_shorter_than_entry_cutoff_gap')]
    for number, (source, kwargs, message) in enumerate(cases):
        for export, tag in ((FROZEN_EXPORT, 'f'), (se.export_pools, 's')):
            with pytest.raises(bf.BackfillError, match=message):
                export(source, tmp_path / f'refused_{tag}{number}', **kwargs)
            assert not (tmp_path / f'refused_{tag}{number}').exists()         # nothing is written before the checks
    manifest = json.loads((window / 'manifest.json').read_text())
    manifest['window']['address'] = 'SomeOtherProgram1111111111111111111111111111'
    (window / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    for export in (FROZEN_EXPORT, se.export_pools):
        with pytest.raises(bf.BackfillError, match='export_needs_a_launchlab_program_window'):
            export(window, tmp_path / 'other')


def test_the_series_reference_is_copied_as_the_frozen_export_does(tmp_path):
    document = tlb.su.build_series(tlb._pool_window(tmp_path), pool=tlb.SOL_POOL, sol_vault=tlb.SOL_VAULT,
                                   usdc_vault=tlb.USDC_VAULT, swap_filter=tlb.CPMM, label='SYNTHETIC_TEST_FIXTURE')
    tlb.su.write_series(document, tmp_path / 'series.json.gz')
    window = _window(tmp_path, name='launch')
    export = _same(window, tmp_path, 'series', sol_usd_series=tmp_path / 'series.json.gz')
    assert export['sol_usd_series']['points'] == 2
    assert 'sol_usd_series.json.gz' in _tree(tmp_path / 'stream_series')


def test_the_chunked_gzip_stream_is_the_one_shot_stream(tmp_path):
    assert se.gzip_stream_is_the_one_shot_stream()
    rng = random.Random(3)
    parts = [json.dumps(dict(i=i, text=''.join(rng.choice('abc "\\\n{}0123456789') for _ in range(rng.randrange(1, 4000)))))
             for i in range(2500)]
    digest = se._write_archive(tmp_path / 'a.gz', iter(parts))
    expected = gzip.compress(''.join(parts).encode(), mtime=0)
    assert (tmp_path / 'a.gz').read_bytes() == expected and digest == hashlib.sha256(expected).hexdigest()
    assert len(expected) > 1_000_000
    signatures = [dict(signature='s2', err=None), dict(err={'a': 1}, signature='s1')]
    transactions = {'s2': json.dumps({'slot': 2, 'meta': {'err': None}}, separators=(',', ':'), sort_keys=True),
                    's"1': json.dumps({'slot': 1}, separators=(',', ':'), sort_keys=True)}
    archive = {'version': se.ARCHIVE_VERSION, 'pool': 'Po"ol', 'account': None, 'signatures': signatures,
               'signatures_complete': True, 'transactions': {k: json.loads(v) for k, v in transactions.items()}}
    assert ''.join(se._archive_parts('Po"ol', signatures, transactions)) == \
        json.dumps(archive, separators=(',', ':'), sort_keys=True)
    assert ''.join(se._archive_parts('P', [], {})) == json.dumps(
        {'version': se.ARCHIVE_VERSION, 'pool': 'P', 'account': None, 'signatures': [], 'signatures_complete': True,
         'transactions': {}}, separators=(',', ':'), sort_keys=True)


def test_the_replacement_lasts_only_for_the_block_and_guards_its_inputs(tmp_path, monkeypatch):
    window = _window(tmp_path)
    reference = FROZEN_EXPORT(window, tmp_path / 'reference')
    assert bx.export_pools is FROZEN_EXPORT
    with se.streaming_export(work_dir=tmp_path / 'work', buckets=4, workers=2):
        assert bx.export_pools is not FROZEN_EXPORT
        inside = bx.export_pools(window, tmp_path / 'inside', collector_code=None)   # what a frozen caller would do
    assert bx.export_pools is FROZEN_EXPORT and inside == reference
    assert _tree(tmp_path / 'inside') == _tree(tmp_path / 'reference') and not (tmp_path / 'work').exists()
    with pytest.raises(RuntimeError, match='boom'):
        with se.streaming_export():
            raise RuntimeError('boom')
    assert bx.export_pools is FROZEN_EXPORT
    (tmp_path / 'busy').mkdir()
    with pytest.raises(se.StreamExportError, match='work_directory_already_exists'):
        se.export_pools(window, tmp_path / 'p', work_dir=tmp_path / 'busy')
    for bad in (dict(buckets=0), dict(workers=0), dict(buckets=2.0)):
        with pytest.raises(se.StreamExportError, match='invalid_buckets_or_workers'):
            se.export_pools(window, tmp_path / 'p', **bad)
    monkeypatch.setattr(se, 'gzip_stream_is_the_one_shot_stream', lambda: False)
    with pytest.raises(se.StreamExportError, match='chunked_gzip_differs'):
        se.export_pools(window, tmp_path / 'p')
    assert not (tmp_path / 'p').exists()


def test_only_one_transaction_is_held_while_the_window_is_read(tmp_path, monkeypatch):
    """Passes 1 and 2 never keep the parsed transactions: only the keys of the created pools stay alive."""
    import gc
    import weakref
    window = _window(tmp_path)
    rows = _rows(window)
    _rebuild(window, [rows[i:i + 20] for i in range(0, len(rows), 20)])
    reference = FROZEN_EXPORT(window, tmp_path / 'reference')
    alive, peak = [], [0]

    class Signature(str):                                # a plain str cannot be weakly referenced; a dict neither
        pass
    real = se._rows

    def tracked(window_dir, manifest):
        for rank, entry in real(window_dir, manifest):
            entry['signature'] = Signature(entry['signature'])      # dies with the transaction that carries it
            alive.append(weakref.ref(entry['signature']))
            yield rank, entry
            del entry
            gc.collect()
            peak[0] = max(peak[0], sum(ref() is not None for ref in alive))
    monkeypatch.setattr(se, '_rows', tracked)
    export = se.export_pools(window, tmp_path / 'p', buckets=3)
    assert export == reference and _tree(tmp_path / 'p') == _tree(tmp_path / 'reference')
    assert len(alive) == 2 * len(rows) == 346                              # two passes over every transaction
    assert peak[0] <= len(POOLS) + 1                                       # the three creation keys and the one in hand
