"""Memory of the streaming SOL/USD series step on ENLARGED SYNTHETIC runs (asked by RUGGER 02, 2026-11-15).

No real collected data: every row is the archived P0 push transaction of the frozen tests
(tests/fixtures/pyth_push, about 17 KB of JSON, the size of a real transaction of the price account), with its own
signature, slot, block time and publish time, so that EVERY row gives a price point (the worst case for the
number of points). Segments of 5 000 rows, as in the W1 collection.

    python -B measure_series.py build  --segments N --out RUN_DIR      (a verified run, W1-shaped bounds)
    python -B measure_series.py stream --run-dir RUN_DIR --out DIR     (w1x.stream_series.series, the real step)
    python -B measure_series.py frozen --run-dir RUN_DIR --out DIR     (w1_run.pyth_entries + sol_usd_series)

``stream`` and ``frozen`` print one JSON line: rows, tx segments, peak memory (MB) of THIS fresh process, seconds
and the sha256 of the two files written. Run each in its own process. PYTHONPATH as for the package tests.
"""
import argparse
import gzip
import hashlib
import json
import resource
import struct
import sys
import time
from pathlib import Path

from bot.market import backfill as bf
from bot.market import pyth_push as pp
from bot.market import w1_collection
from bot.market.launchlab_events import b58encode
from bot.master_v2 import w1_run as run
from tests import test_master_v2_w1_run as tw1
from tests import test_pyth_push as tpp
from w1x import stream_series as ss

S0 = 466226774 - w1_collection.WARMUP_SLOTS - 10
ROWS = 5_000
PUBLISH_AT = 12 + 53
STUDY = dict(verdict='ACCEPTED', acceptance=dict(max_age_ms=65_000, max_confidence_ppm=1_000))


def build(segments, out):
    out = Path(out)
    b = w1_collection.bounds(S0)
    budget = bf.CreditBudget(1_000, 60_000, bf.COST_PRESETS[w1_collection.COSTS], ledger=out / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/', budget, opener=tw1._PythChain())
    manifest = bf.Backfill(rpc, bf.Window(pp.SOL_USD_ACCOUNT, b['slot_min'], b['slot_max']), out).run()
    assert manifest['complete']
    for seg in manifest['segments']:
        if seg['kind'] in ('tx', 'sig'):
            (out / seg['path']).unlink()
    entry = tpp._entry(tpp.A)
    ix = tpp._push_ix(entry)
    data = pp.b58decode(ix['data'])
    base = pp.updates(entry)[0]['publish_time']
    kept, signatures = [seg for seg in manifest['segments'] if seg['kind'] not in ('tx', 'sig')], []
    for number in range(segments):
        lines = []
        for i in range(number * ROWS, (number + 1) * ROWS):
            signature = f'synthetic{i:09d}'
            ix['data'] = b58encode(data[:PUBLISH_AT] + struct.pack('>q', base + i) + data[PUBLISH_AT + 8:])
            entry['slot'], entry['transactionIndex'], entry['blockTime'] = b['slot_min'] + i, 1, 1793993268 + i
            entry['transaction']['signatures'][0] = signature
            lines.append(json.dumps(dict(entry, signature=signature), separators=(',', ':')) + '\n')
            signatures.append(signature)
        raw = gzip.compress(''.join(lines).encode(), 6, mtime=0)
        name = f'tx-9{number:05d}.jsonl.gz'
        (out / name).write_bytes(raw)
        kept.append(dict(kind='tx', path=name, rows=ROWS, sha256=hashlib.sha256(raw).hexdigest()))
    raw = gzip.compress(''.join(json.dumps(dict(signature=s)) + '\n' for s in signatures).encode(), 6, mtime=0)
    (out / 'sig-900000.jsonl.gz').write_bytes(raw)
    kept.append(dict(kind='sig', path='sig-900000.jsonl.gz', rows=len(signatures), sha256=hashlib.sha256(raw).hexdigest()))
    manifest['segments'] = kept
    manifest['totals'].update(transactions=len(signatures), duplicate_signatures=0, failed_transactions=0)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    (out / 'study.json').write_text(json.dumps(STUDY))
    checked = bf.verify(out)
    assert checked['ok'] and checked['complete'], checked['problems']
    gz = sum((out / seg['path']).stat().st_size for seg in kept if seg['kind'] == 'tx')
    return dict(what='build', segments=segments, rows=len(signatures), gz_bytes=gz, manifest_sha256=checked['manifest_sha256'])


def measure(kind, run_dir, out):
    run_dir, out = Path(run_dir), Path(out)
    study = run_dir / 'study.json'
    sha = hashlib.sha256(study.read_bytes()).hexdigest()
    run.ANCHORED_STUDY_REPORT_SHA256 = sha                    # this synthetic study only, in this process only
    out.mkdir(parents=True)
    target = out / 'sol_usd_series.json.gz'
    started = time.time()
    if kind == 'stream':
        result = ss.series(run_dir, S0, study, sha, target)
        rows, points = result['entries'], result['points']
    else:
        entries = run.pyth_entries(run_dir, S0)
        series = run.sol_usd_series(entries, study, sha, target)
        rows, points = len(entries), len(series.points)
    manifest = json.loads((run_dir / 'manifest.json').read_text())
    return dict(what=kind, rows=rows, points=points, tx_segments=sum(seg['kind'] == 'tx' for seg in manifest['segments']),
                peak_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                seconds=round(time.time() - started, 1),
                files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())})


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='what', required=True)
    b = sub.add_parser('build')
    b.add_argument('--segments', type=int, required=True)
    b.add_argument('--out', type=Path, required=True)
    for name in ('stream', 'frozen'):
        p = sub.add_parser(name)
        p.add_argument('--run-dir', type=Path, required=True)
        p.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    doc = build(a.segments, a.out) if a.what == 'build' else measure(a.what, a.run_dir, a.out)
    sys.stdout.write(json.dumps(doc, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
