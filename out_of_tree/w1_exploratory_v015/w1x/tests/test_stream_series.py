"""w1x.stream_series: the streaming series step writes the frozen step's files byte for byte.

Every case runs the FROZEN ``w1_run.pyth_entries`` + ``w1_run.sol_usd_series`` and the streaming step on the same
verified SOL/USD window (built from the two archived P0 push transactions of the frozen tests and hand-made
variants, in several segments) and compares the two written files, the returned values, or the exception.
"""
import copy
import gc
import gzip
import hashlib
import json
import random
import struct
import weakref
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import pyth_push as pp
from bot.market import w1_collection
from bot.master_v2 import w1_run as run
from tests import test_master_v2_w1_run as tw1
from tests import test_pyth_push as tpp
from w1x import stream_series as ss

FROZEN = (bf.read_segment, pp.updates, pp.evidence_sha256)
S0 = 466226774 - w1_collection.WARMUP_SLOTS - 10
A = tpp._entry(tpp.A)
PRICE_AT, PUBLISH_AT = 12 + 33, 12 + 53                  # in the UpdatePriceFeed data: i64 BE each


@pytest.fixture
def study(tmp_path, monkeypatch):
    path = tmp_path / 'study.json'
    path.write_text(json.dumps(dict(verdict='ACCEPTED', acceptance=dict(max_age_ms=65_000, max_confidence_ppm=1_000))))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(run, 'ANCHORED_STUDY_REPORT_SHA256', sha)      # this synthetic study only
    return path, sha


def _window(tmp_path, name='pyth'):
    """A verified, complete SOL/USD window over the W1 slots of S0 (the two archived transactions)."""
    b = w1_collection.bounds(S0)
    budget = bf.CreditBudget(1_000, 60_000, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / name / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=tw1._PythChain())
    manifest = bf.Backfill(rpc, bf.Window(pp.SOL_USD_ACCOUNT, b['slot_min'], b['slot_max']), tmp_path / name).run()
    assert manifest['complete']
    return tmp_path / name


def _write_segment(path, rows):
    data = gzip.compress(''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode(), mtime=0)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _rebuild(window, groups):
    """Rewrite the tx rows of a verified window as the given segments, and its signature listing; still verifies."""
    manifest = json.loads((window / 'manifest.json').read_text())
    everything = [row for rows in groups for row in rows]
    segments, listed = [], False
    for number, rows in enumerate(groups):
        name = f'tx-9{number:05d}.jsonl.gz'
        segments.append(dict(kind='tx', path=name, rows=len(rows), sha256=_write_segment(window / name, rows)))
    for seg in manifest['segments']:
        (window / seg['path']).unlink() if seg['kind'] == 'tx' else None
        if seg['kind'] == 'sig' and not listed:
            rows = [dict(signature=row['signature']) for row in everything]
            segments.append(dict(seg, rows=len(rows), sha256=_write_segment(window / seg['path'], rows)))
            listed = True
        elif seg['kind'] != 'tx':
            (window / seg['path']).unlink() if seg['kind'] == 'sig' else segments.append(seg)
    signatures = [row['signature'] for row in everything]
    manifest['segments'] = segments
    manifest['totals'].update(transactions=len(everything), duplicate_signatures=len(signatures) - len(set(signatures)),
                              failed_transactions=sum((r.get('meta') or {}).get('err') is not None
                                                      for r in everything if isinstance(r.get('meta'), (dict, type(None)))))
    (window / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    checked = bf.verify(window)
    assert checked['ok'] and checked['complete'], checked['problems']
    return manifest


def _row(n, *, slot, index, block_time=1793993268, publish=None, price=None, err=None, shard=None):
    """Variant n of the archived transaction A, as a stored row."""
    def transform(data):
        if publish is not None:
            data = data[:PUBLISH_AT] + struct.pack('>q', publish) + data[PUBLISH_AT + 8:]
        if price is not None:
            data = data[:PRICE_AT] + struct.pack('>q', price) + data[PRICE_AT + 8:]
        if shard is not None:
            data = data[:-34] + struct.pack('<H', shard) + data[-32:]
        return data
    entry = tpp._with_data(A, transform)
    entry['slot'], entry['transactionIndex'], entry['blockTime'] = slot, index, block_time
    entry['transaction']['signatures'][0] = f'signature{n:05d}'
    if err is not None:
        entry['meta']['err'] = err
    return dict(entry, signature=f'signature{n:05d}')


def _many(count, seed):
    """Rows in a shuffled order: rising, repeated and older publish times, failed transactions, missing times."""
    rng = random.Random(seed)
    base = pp.updates(A)[0]['publish_time']
    rows = []
    for n in range(count):
        rows.append(_row(n, slot=466226774 + n // 3, index=n % 3 * 7 + 1, block_time=1793993268 + n * 37,
                         publish=base + rng.choice((-5, 0, 0, 1, 2, 40, 700)) + n * rng.choice((0, 1, 30)),
                         price=9_000_000_000 + rng.randrange(10_000_000),
                         err={'InstructionError': [0, 'Custom']} if rng.random() < 0.15 else None))
    rng.shuffle(rows)
    return rows


def _groups(rows, sizes):
    out, at = [], 0
    for size in sizes:
        out.append(rows[at:at + size])
        at += size
    return out + ([rows[at:]] if rows[at:] else [])


def _attempt(call):
    try:
        return 'value', call()
    except Exception as exc:                               # the exception itself is part of what is compared
        return type(exc).__name__, str(exc)


def _both(window, tmp_path, study, tag, s0=S0):
    """Run the frozen step and the streaming step; same files, same values or same exception. Returns the frozen outcome."""
    report, sha = study
    frozen_out, stream_out = tmp_path / f'frozen_{tag}' / 's.json.gz', tmp_path / f'stream_{tag}' / 's.json.gz'

    def frozen():
        entries = run.pyth_entries(window, s0)
        series = run.sol_usd_series(entries, report, sha, frozen_out)
        return dict(series_sha256=series.sha256, points=len(series.points), entries=len(entries))

    def stream():
        result = ss.series(window, s0, report, sha, stream_out)
        assert result.pop('run_manifest_sha256') == hashlib.sha256((window / 'manifest.json').read_bytes()).hexdigest()
        return result
    expected, got = _attempt(frozen), _attempt(stream)
    assert got == expected
    files = lambda d: {p.name: p.read_bytes() for p in sorted(d.iterdir())} if d.exists() else {}
    assert files(stream_out.parent) == files(frozen_out.parent)
    assert (bf.read_segment, pp.updates, pp.evidence_sha256) == FROZEN          # always restored
    return expected


def test_the_archived_window_gives_the_frozen_files(tmp_path, study):
    kind, value = _both(_window(tmp_path), tmp_path, study, 'a')
    assert kind == 'value' and value['points'] == 2 and value['entries'] == 2
    written = sorted(p.name for p in (tmp_path / 'stream_a').iterdir())
    assert written == ['s.json.gz', 's.json.gz.decoding.json']


@pytest.mark.parametrize('seed,sizes', [(1, (1, 2, 3, 50)), (2, (40, 1)), (3, (7,) * 12), (4, ())])
def test_many_rows_in_any_segments_give_the_frozen_files(tmp_path, study, seed, sizes):
    window = _window(tmp_path)
    rows = _many(90, seed)
    _rebuild(window, _groups(rows, sizes))
    kind, value = _both(window, tmp_path, study, 'm')
    assert kind == 'value' and value['entries'] == 90 and 2 < value['points'] < 90
    decoding = json.loads((tmp_path / 'stream_m' / 's.json.gz.decoding.json').read_text())
    assert decoding['not_newer'] > 0 and decoding['updates'] < 90 and decoding['refusals_by_utc_hour']


ADVERSE = {
    'duplicate_chain_position': lambda: [_row(1, slot=10, index=1), _row(2, slot=10, index=1, publish=1_900_000_000)],
    'non_positive_price': lambda: [_row(1, slot=10, index=1), _row(2, slot=11, index=1, price=0)],
    'unexpected_shard': lambda: [_row(1, slot=10, index=1), _row(2, slot=11, index=1, shard=1)],
    'chain_position_required': lambda: [_row(1, slot=10, index=1), dict(_row(2, slot=11, index=1), transactionIndex=None)],
    # the first faulty row in reading order decides: decoding error before a later missing position, and the reverse
    'unexpected_shard ': lambda: [_row(1, slot=10, index=1, shard=1), dict(_row(2, slot=11, index=1), slot='11')],
    'chain_position_required ': lambda: [dict(_row(1, slot=10, index=1), slot='10'), _row(2, slot=11, index=1, shard=1)],
    # a row without a chain position is never decoded, even when its data are wrong
    'chain_position_required  ': lambda: [{k: v for k, v in _row(1, slot=10, index=1, shard=1).items() if k != 'transactionIndex'}],
    'several_updates_of_one_feed_in_one_transaction': lambda: [_double()],
    'unexpected_instruction_length': lambda: [_cut()],
}


def _double():
    row = _row(1, slot=10, index=1)
    row['transaction']['message']['instructions'].append(copy.deepcopy(tpp._push_ix(row)))
    return row


def _cut():
    from bot.market.launchlab_events import b58encode
    row = _row(1, slot=10, index=1)
    ix = tpp._push_ix(row)
    ix['data'] = b58encode(pp.b58decode(ix['data'])[:-1])
    return row


@pytest.mark.parametrize('expected', sorted(ADVERSE))
def test_adverse_rows_raise_the_frozen_exception_and_write_nothing_more(tmp_path, study, expected):
    window = _window(tmp_path)
    _rebuild(window, [[row] for row in ADVERSE[expected]()])
    kind, text = _both(window, tmp_path, study, 'x')
    assert kind == 'PythPushError' and text == expected.strip()


@pytest.mark.parametrize('change', ['no_meta', 'meta_none', 'meta_empty', 'failed', 'no_block_time', 'block_time_text',
                                    'failed_with_bad_data', 'no_update'])
def test_unusual_rows_are_read_as_the_frozen_code_reads_them(tmp_path, study, change):
    window = _window(tmp_path)
    rows = _many(12, 9)
    odd = _row(100, slot=466226999, index=3, publish=1_900_000_000)
    if change == 'no_meta':
        del odd['meta']
    elif change == 'meta_none':
        odd['meta'] = None
    elif change == 'meta_empty':
        odd['meta'] = {}
    elif change == 'failed':
        odd['meta']['err'] = 'AccountInUse'
    elif change == 'no_block_time':
        del odd['blockTime']
    elif change == 'block_time_text':
        odd['blockTime'] = '1793993268'
    elif change == 'failed_with_bad_data':                # a failed transaction is never decoded
        odd = dict(_row(100, slot=466226999, index=3, shard=1))
        odd['meta']['err'] = 'AccountInUse'
    elif change == 'no_update':                           # a transaction of the account without any push update
        odd['transaction']['message']['instructions'] = []
    _rebuild(window, _groups(rows + [odd], (5, 5)))
    kind, value = _both(window, tmp_path, study, 'u')
    if change == 'block_time_text':                       # refused by the frozen series validation, nothing written
        assert (kind, value) == ('ValueError', 'sol_usd_point_values') and not (tmp_path / 'stream_u').exists()
    else:
        points = 5 if change in ('failed', 'failed_with_bad_data', 'no_update') else 6
        assert (kind, value['entries'], value['points']) == ('value', 13, points)
        hourly = json.loads((tmp_path / 'stream_u' / 's.json.gz.decoding.json').read_text())['refusals_by_utc_hour']
        assert bool(hourly) == (change != 'no_block_time')            # one missing block time: no hourly table


def test_window_checks_are_the_frozen_ones(tmp_path, study):
    window = _window(tmp_path)
    assert _both(window, tmp_path, study, 's0', s0=S0 + 1) == ('W1RunError', 'not_the_w1_sol_usd_window')
    manifest = json.loads((window / 'manifest.json').read_text())
    (window / 'manifest.json').write_text(json.dumps(dict(manifest, complete=False), indent=1, sort_keys=True))
    assert _both(window, tmp_path, study, 'inc') == ('W1RunError', 'sol_usd_window_not_verified_or_incomplete')
    (window / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    segment = next(window / seg['path'] for seg in manifest['segments'] if seg['kind'] == 'tx')
    segment.write_bytes(segment.read_bytes() + b' ')                     # a changed segment no longer verifies
    assert _both(window, tmp_path, study, 'sha') == ('W1RunError', 'sol_usd_window_not_verified_or_incomplete')


def test_study_report_checks_are_the_frozen_ones(tmp_path, study):
    window = _window(tmp_path)
    report, sha = study
    assert _both(window, tmp_path, (report, '0' * 64), 'pin') == ('W1RunError', 'age_study_report_is_not_the_anchored_one')
    report.write_text(json.dumps(dict(verdict='REJECTED', acceptance=None)))
    assert _both(window, tmp_path, (report, sha), 'changed') == ('W1RunError', 'age_study_report_is_not_the_anchored_one')


def test_slim_rows_keep_no_transaction_body(tmp_path):
    window = _window(tmp_path)
    _rebuild(window, _groups(_many(30, 5), (10, 10)))
    full = [row for seg in json.loads((window / 'manifest.json').read_text())['segments'] if seg['kind'] == 'tx'
            for row in bf.read_segment(window / seg['path'])]
    with ss.streaming_series():
        slim = [row for seg in json.loads((window / 'manifest.json').read_text())['segments'] if seg['kind'] == 'tx'
                for row in bf.read_segment(window / seg['path'])]
        assert [pp.updates(row) for row in slim] == [FROZEN[1](row) for row in full]
        assert [pp.evidence_sha256(row) for row in slim if pp.updates(row)] == [FROZEN[2](row) for row in full if FROZEN[1](row)]
        assert pp.updates(full[0]) == FROZEN[1](full[0]) and pp.evidence_sha256(full[0]) == FROZEN[2](full[0])   # full rows: frozen
        with pytest.raises(ss.StreamSeriesError, match='default_feed_only'):
            pp.updates(slim[0], feed_id='00' * 32)
        failed = next(row for row in slim if (row.get('meta') or {}).get('err') is not None)
        with pytest.raises(ss.StreamSeriesError, match='evidence_asked_for_a_row_without_update'):
            pp.evidence_sha256(failed)
    for row in slim:
        assert set(row) <= {'signature', 'slot', 'transactionIndex', 'blockTime', 'meta', ss._UPDATES, ss._EVIDENCE}
        assert set(row['meta']) == {'err'}
    assert len(json.dumps([{k: v for k, v in r.items() if k[0] != '\x00'} for r in slim])) * 20 < len(json.dumps(full))


def test_a_parsed_segment_is_released_before_the_next_one(tmp_path, monkeypatch):
    window = _window(tmp_path)
    _rebuild(window, _groups(_many(40, 6), (10, 10, 10)))

    class Row(dict):                                      # a dict that can be weakly referenced
        pass
    seen, alive_at_read = [], []

    def read(path):
        gc.collect()
        alive_at_read.append(sum(ref() is not None for ref in seen))
        rows = [Row(row) for row in FROZEN[0](path)]
        seen.extend(weakref.ref(row) for row in rows)
        return rows
    monkeypatch.setattr(bf, 'read_segment', read)
    with ss.streaming_series():
        tx = [seg for seg in json.loads((window / 'manifest.json').read_text())['segments'] if seg['kind'] == 'tx']
        slim = [row for seg in tx for row in bf.read_segment(window / seg['path'])]
    gc.collect()
    assert len(slim) == 40 and len(seen) == 40
    assert alive_at_read == [0] * len(tx) and not any(ref() is not None for ref in seen)


def test_block_restores_the_frozen_functions_and_is_not_reentrant():
    with pytest.raises(ZeroDivisionError):
        with ss.streaming_series():
            assert (bf.read_segment, pp.updates, pp.evidence_sha256) != FROZEN
            with pytest.raises(ss.StreamSeriesError, match='not_reentrant'):
                with ss.streaming_series():
                    pass
            1 / 0
    assert (bf.read_segment, pp.updates, pp.evidence_sha256) == FROZEN


def test_series_refuses_an_existing_output_and_a_verification_that_differs(tmp_path, study, monkeypatch):
    window = _window(tmp_path)
    _rebuild(window, _groups(_many(20, 7), (10,)))
    report, sha = study
    out = tmp_path / 'o' / 's.json.gz'
    out.parent.mkdir()
    out.write_bytes(b'x')
    with pytest.raises(ss.StreamSeriesError, match='output_exists'):
        ss.series(window, S0, report, sha, out)
    out.unlink()
    Path(str(out) + '.decoding.json').write_bytes(b'x')
    with pytest.raises(ss.StreamSeriesError, match='output_exists'):
        ss.series(window, S0, report, sha, out)
    Path(str(out) + '.decoding.json').unlink()
    slim = ss._slim
    monkeypatch.setattr(ss, '_slim', lambda row, u, e: dict(slim(row, u, e), meta=None))     # a slim row losing its error flag
    with pytest.raises(ss.StreamSeriesError, match='verification_differs_on_slim_rows'):
        ss.series(window, S0, report, sha, out)
    assert not out.exists() and (bf.read_segment, pp.updates, pp.evidence_sha256) == FROZEN
