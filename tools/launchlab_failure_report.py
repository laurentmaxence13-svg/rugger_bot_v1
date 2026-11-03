#!/usr/bin/env python3
"""Offline report: failed vs successful signatures listed for LaunchLab pool addresses.

Reads only committed signature listings (default: tests/fixtures/launchlab_sol_pools).
No network, no keys, no transaction, no archive is modified.

CAUTION: a pool-address signature listing is NOT the bot's order attempts. It mixes
every wallet's transactions touching the address (bots, retail, creator setup), and
failures there reflect other actors' slippage/compute/account errors. It cannot alone
estimate our own order failure probability.

  python -B tools/launchlab_failure_report.py [directory]
"""
import collections
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SLOT_BUCKETS = (0, 10, 50, 150)      # lower bounds of slot-age buckets from pool creation

CAVEAT = ('Address-level signatures are not the bot\'s order attempts; they cannot alone '
          'estimate our own order failure probability.')


def _bucket(age):
    chosen = SLOT_BUCKETS[0]
    for low in SLOT_BUCKETS:
        if age >= low:
            chosen = low
    return chosen


def _err_key(err):
    if isinstance(err, dict) and err:
        name = next(iter(err))
        return '%s:%s' % (name, json.dumps(err[name], sort_keys=True, separators=(',', ':')))
    return str(err)


def _rate(failed, total):
    return round(failed / total, 4) if total else None


def analyse_document(doc, name='?'):
    """Summarise one decoded archive; tolerates empty, partial or malformed data."""
    warnings = []
    if not isinstance(doc, dict):
        return {'pool': name, 'total': 0, 'failed': 0, 'succeeded': 0, 'failure_rate': None,
                'malformed_rows': 0, 'by_age': {}, 'error_kinds': {},
                'warnings': ['document is not an object']}
    rows = doc.get('signatures')
    if not isinstance(rows, list):
        rows, _ = [], warnings.append('signatures missing or not a list')
    good, malformed = [], 0
    for row in rows:
        if (isinstance(row, dict) and isinstance(row.get('slot'), int)
                and not isinstance(row.get('slot'), bool) and 'err' in row):
            good.append(row)
        else:
            malformed += 1
    if malformed:
        warnings.append('%d malformed signature row(s) ignored' % malformed)
    if doc.get('signatures_complete') is not True:
        warnings.append('listing not marked complete: counts may be partial and age 0 may not be creation')
    origin = min((r['slot'] for r in good), default=None)
    failed = [r for r in good if r['err'] is not None]
    buckets = collections.defaultdict(lambda: [0, 0])
    for row in good:
        cell = buckets[_bucket(row['slot'] - origin)]
        cell[0] += 1
        cell[1] += row['err'] is not None
    kinds = collections.Counter(_err_key(r['err']) for r in failed)
    pool = doc.get('pool') if isinstance(doc.get('pool'), str) else name
    return {
        'pool': pool, 'total': len(good), 'failed': len(failed),
        'succeeded': len(good) - len(failed), 'failure_rate': _rate(len(failed), len(good)),
        'first_slot': origin, 'last_slot': max((r['slot'] for r in good), default=None),
        'malformed_rows': malformed,
        'by_age': {'slots>=%d' % low: {'total': t, 'failed': f, 'failure_rate': _rate(f, t)}
                   for low, (t, f) in sorted(buckets.items())},
        'error_kinds': dict(sorted(kinds.items())),
        'warnings': warnings,
    }


def analyse_directory(directory):
    pools = []
    for path in sorted(Path(directory).glob('*.json.gz')):
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as handle:
                doc = json.load(handle)
        except (OSError, EOFError, ValueError) as exc:
            pools.append(analyse_document(None, path.name.split('.')[0]))
            pools[-1]['warnings'] = ['unreadable archive: %s' % type(exc).__name__]
            continue
        pools.append(analyse_document(doc, path.name.split('.')[0]))
    total = sum(p['total'] for p in pools)
    failed = sum(p['failed'] for p in pools)
    return {'caveat': CAVEAT, 'pool_count': len(pools), 'total': total, 'failed': failed,
            'failure_rate': _rate(failed, total), 'pools': pools}


def main(argv):
    directory = Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    print(json.dumps(analyse_directory(directory), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
