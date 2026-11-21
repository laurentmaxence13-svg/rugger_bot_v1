"""paperstream 0.5.1 -- memo_probe: memory the --fast-analyser memo would hold for ONE archive (R02 condition 1).

Offline, read-only, no replay, no decision, no result: it reads one archive (sha256 checked), builds the same entries
the memo keeps per transaction (the ``json.dumps(tx, separators=(',', ':'))`` string, the only large one; the other
memoized helpers keep booleans or small dicts), and reports sizes and the process memory before and after.

  python -B -m paperstream.memo_probe --archive <pool archive .json.gz> --sha256 <its sha256 from the MANIFEST>

Output (stdout, one JSON line, whitelisted keys): gz_bytes, json_bytes, transactions, dumps_bytes, dumps_per_gz_byte,
rss_before_mb, rss_after_mb, rss_delta_mb, hwm_mb. No pool id, no signature, no value of any transaction.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

KEYS = ('gz_bytes', 'json_bytes', 'transactions', 'dumps_bytes', 'dumps_per_gz_byte', 'rss_before_mb', 'rss_after_mb',
        'rss_delta_mb', 'hwm_mb')


def _status_mb(field):
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(field + ':'):
            return round(int(line.split()[1]) / 1024, 1)
    return None


def probe(archive, sha256):
    raw = Path(archive).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('archive_is_not_the_anchored_one')
    data = gzip.decompress(raw)
    doc = json.loads(data)
    transactions = list((doc.get('transactions') or {}).values())
    before = _status_mb('VmRSS')
    memo = {id(tx): (tx, json.dumps(tx, separators=(',', ':'))) for tx in transactions}
    after = _status_mb('VmRSS')
    dumps = sum(len(v[1]) for v in memo.values())
    out = dict(gz_bytes=len(raw), json_bytes=len(data), transactions=len(transactions), dumps_bytes=dumps,
               dumps_per_gz_byte=round(dumps / len(raw), 3), rss_before_mb=before, rss_after_mb=after,
               rss_delta_mb=None if before is None or after is None else round(after - before, 1),
               hwm_mb=_status_mb('VmHWM'))
    return {k: out[k] for k in KEYS}


def main(argv=None):
    p = argparse.ArgumentParser(prog='paperstream.memo_probe')
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    a = p.parse_args(argv)
    print(json.dumps(probe(a.archive, a.sha256), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
