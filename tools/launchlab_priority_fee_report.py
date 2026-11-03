#!/usr/bin/env python3
"""Offline report: observed network fees of archived LaunchLab SOL-pool transactions.

Reads only the committed fixture archives (no network, no keys, no write).
Reports the distribution of the observed ``meta.fee`` (lamports) per pool and per
slot-age bin (slots since the pool's first archived transaction), and, where the
ComputeBudget instructions decode, the declared compute-unit price and limit.

LIMITS: observational. A fee paid by a transaction that landed says nothing about
the fee needed to win a slot, and it is not a recommended execution setting.

  python -B tools/launchlab_priority_fee_report.py [archive_dir]
"""
import gzip
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
COMPUTE_BUDGET = 'ComputeBudget111111111111111111111111111111'
BASE_FEE_PER_SIGNATURE = 5000  # lamports, protocol constant
AGE_BINS = ((0, 5), (5, 20), (20, 100), (100, None))  # slots since first tx, [lo, hi)
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58decode(text):
    number = 0
    for ch in text:
        number = number * 58 + _B58.index(ch)
    raw = number.to_bytes((number.bit_length() + 7) // 8, 'big')
    return b'\x00' * (len(text) - len(text.lstrip('1'))) + raw


def decode_compute_budget(tx):
    """Return (unit_price_micro_lamports or None, unit_limit or None); None if undecodable."""
    message = tx.get('transaction', {}).get('message', {})
    keys = message.get('accountKeys') or []
    price = limit = None
    for ins in message.get('instructions', []):
        index = ins.get('programIdIndex')
        key = keys[index] if isinstance(index, int) and index < len(keys) else None
        if isinstance(key, dict):
            key = key.get('pubkey')
        if key != COMPUTE_BUDGET:
            continue
        try:
            data = b58decode(ins.get('data', ''))
        except ValueError:
            continue
        if data[:1] == b'\x03' and len(data) == 9:
            price = int.from_bytes(data[1:], 'little')
        elif data[:1] == b'\x02' and len(data) == 5:
            limit = int.from_bytes(data[1:], 'little')
    return price, limit


def quantiles(values):
    if not values:
        return None
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]
    return {'n': len(ordered), 'min': ordered[0], 'median': pick(0.5), 'p90': pick(0.9),
            'max': ordered[-1], 'mean': round(statistics.fmean(ordered), 1)}


def age_label(lo, hi):
    return f'{lo}+' if hi is None else f'{lo}-{hi - 1}'


def report_archive(path):
    archive = json.loads(gzip.open(path, 'rt').read())
    txs = [tx for tx in archive['transactions'].values() if tx and tx.get('meta')]
    first = min(tx['slot'] for tx in txs)
    bins = {age_label(*b): [] for b in AGE_BINS}
    fees, declared, priced, undecoded, failed = [], [], 0, 0, 0
    for tx in txs:
        fee = tx['meta']['fee']
        if tx['meta'].get('err') is not None:
            failed += 1
        fees.append(fee)
        age = tx['slot'] - first
        for lo, hi in AGE_BINS:
            if age >= lo and (hi is None or age < hi):
                bins[age_label(lo, hi)].append(fee)
        price, limit = decode_compute_budget(tx)
        if price is None:
            undecoded += 1
            continue
        priced += 1
        # Priority part of the fee = price * limit / 1e6 (ceil), when both are declared.
        if limit:
            declared.append({'price': price, 'limit': limit, 'fee': fee,
                             'implied_priority': -(-price * limit // 1_000_000)})
    return {
        'pool': archive['pool'], 'transactions': len(txs), 'failed': failed,
        'fee_lamports': quantiles(fees),
        'fee_by_slot_age': {k: quantiles(v) for k, v in bins.items()},
        'with_unit_price': priced, 'without_unit_price': undecoded,
        'unit_price_micro_lamports': quantiles([d['price'] for d in declared]),
        'fee_above_base_5000': sum(1 for f in fees if f > BASE_FEE_PER_SIGNATURE),
        'implied_vs_observed_mismatch': sum(
            1 for d in declared if d['fee'] < d['implied_priority']),
    }


def main(argv):
    directory = Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    pools = [report_archive(p) for p in sorted(directory.glob('*.json.gz'))]
    print(json.dumps({'directory': str(directory), 'pools': pools,
                      'limits': 'observational only; not a winning-fee estimate'},
                     indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
