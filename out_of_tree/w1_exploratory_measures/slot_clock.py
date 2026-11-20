"""Read-only W1 chain-clock check: block_time vs slot over the evaluation range. No network, no result read.

Reads ONLY the 'slot' and 'blockTime' of each signature row (and, if absent, of the raw transaction) of the
exported pool archives; prints the slot span, the block_time span and the mean ms per slot. It never opens a
bundle, the ledger or the reading.

    python -B -I slot_clock.py --pools <root>/pools --start <evaluation_min> --end <evaluation_max>
"""
import argparse, datetime, gzip, json, sys
from pathlib import Path


def points(archive):
    seen = {}
    for row in archive.get('signatures') or []:
        if type(row.get('slot')) is int and type(row.get('blockTime')) is int:
            seen[row['signature']] = (row['slot'], row['blockTime'])
    for sig, tx in (archive.get('transactions') or {}).items():
        if sig not in seen and type((tx or {}).get('slot')) is int and type(tx.get('blockTime')) is int:
            seen[sig] = (tx['slot'], tx['blockTime'])
    return seen.values()


def main(argv=None, out=sys.stdout):
    p = argparse.ArgumentParser()
    p.add_argument('--pools', required=True, type=Path)
    p.add_argument('--start', required=True, type=int)
    p.add_argument('--end', required=True, type=int)
    a = p.parse_args(argv)
    lo = hi = None
    n = files = 0
    for path in sorted(a.pools.glob('*.json.gz')):
        files += 1
        with gzip.open(path, 'rt', encoding='utf-8') as h:
            archive = json.load(h)
        for slot, bt in points(archive):
            if a.start <= slot < a.end:
                n += 1
                if lo is None or slot < lo[0]:
                    lo = (slot, bt)
                if hi is None or slot > hi[0]:
                    hi = (slot, bt)
    doc = dict(files=files, points=n, start=a.start, end=a.end)
    if lo and hi and hi[0] > lo[0]:
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        doc.update(first=dict(slot=lo[0], block_time=lo[1], utc=iso(lo[1])),
                   last=dict(slot=hi[0], block_time=hi[1], utc=iso(hi[1])),
                   ms_per_slot=round((hi[1] - lo[1]) * 1000 / (hi[0] - lo[0]), 2),
                   evaluation_hours_at_that_rate=round((a.end - a.start) * (hi[1] - lo[1]) / (hi[0] - lo[0]) / 3600, 2))
    json.dump(doc, out, indent=1)
    out.write('\n')


if __name__ == '__main__':
    main()
