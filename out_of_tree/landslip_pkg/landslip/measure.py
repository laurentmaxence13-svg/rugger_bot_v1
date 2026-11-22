"""landslip 0.1 -- OFFLINE measurement of N-4 (landing) and of the material for N-5 (slippage) on transactions ALREADY
collected (task P3-b; definitions and data rules of R02, AUDIT_MODELE_COUTS_PAPER_CB_R02_v1_0.md, 0167b2d1).

  python -B -m landslip.measure --pack <P0 VISIBLE pack aca7de08> --manifest-sha256 <anchored> --out <NEW DIR>

DATA (R02, decision 1): development and first measurement on the P0 VISIBLE pack only; W1 only after R02's PASS of
this code, under A2, DESCRIPTIVE, never to tune a strategy parameter; NEVER the holdout 9f19ccac (refused here by its
prefix as well as by the anchored MANIFEST sha).

WHAT IS MEASURED (counts only, no pool, no signature, no amount, no slot is written):
* (i) failure share of OTHER traders' LaunchLab BUYS by declared priority: every collected transaction whose logs show a
  LaunchLab frame whose own instruction is ``BuyExactIn`` or ``BuyExactOut`` (the log line of THAT frame, read with a
  program stack, so that an inner Token ``Instruction:`` line is never taken for LaunchLab's), split by ``meta.err``
  (failed or not) and by the compute-unit price of its top-level ComputeBudget ``SetComputeUnitPrice`` (micro-lamports
  per CU; 'none' when absent): buckets none, 0, (0, 10 000], (10 000, 100 000], (100 000, 1 000 000], > 1 000 000;
* (ii) reaction gap of other traders: for every decoded BUY event (the frozen ``launchlab_events`` decoder, inner
  instructions) of a pool, the number of slots since the previous event of that pool (the earliest moment a reacting
  order could have been decided): 0, 1, 2, 3, 4, 5-8, 9-32, > 32.
WHAT IS NOT MEASURED: OUR own landing. No order of ours exists; (i) and (ii) describe other traders only and are
inputs for a declared sensitivity, never a measurement of our inclusion probability.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from bot.market import launchlab_events as LE
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA = 'landslip-counts-v0.1'
LAUNCHLAB = LE.LAUNCHLAB_PROGRAM
COMPUTE_BUDGET = 'ComputeBudget111111111111111111111111111111'
HOLDOUT_PREFIX = '9f19ccac'
BUY_INSTRUCTIONS = ('BuyExactIn', 'BuyExactOut')
PRIORITY_BUCKETS = ('none', '0', '1-10000', '10001-100000', '100001-1000000', '>1000000')
GAP_BUCKETS = ('0', '1', '2', '3', '4', '5-8', '9-32', '>32')


class MeasureError(RuntimeError):
    pass


def launchlab_instructions(log_messages):
    """Names logged by LaunchLab frames themselves (program stack), one per LaunchLab frame, in order."""
    stack, names, named = [], [], []
    for line in log_messages or ():
        if line.startswith('Program ') and ' invoke [' in line:
            stack.append(line.split(' ')[1])
            named.append(False)
        elif line.startswith('Program ') and (line.endswith(' success') or ' failed' in line):
            if stack and line.split(' ')[1] == stack[-1]:
                stack.pop()
                named.pop()
        elif line.startswith('Program log: Instruction: ') and stack and stack[-1] == LAUNCHLAB and not named[-1]:
            names.append(line[len('Program log: Instruction: '):])
            named[-1] = True
    return names


def _keys(tx):
    keys = tx['transaction']['message']['accountKeys']
    return [k if type(k) is str else k['pubkey'] for k in keys]


def unit_price(tx):
    """Micro-lamports per CU of the top-level SetComputeUnitPrice, or None when the transaction declares none."""
    keys = _keys(tx)
    price = None
    for ix in tx['transaction']['message']['instructions']:
        program = ix.get('programId') or keys[ix['programIdIndex']]
        if program != COMPUTE_BUDGET or 'data' not in ix:
            continue
        raw = LE.b58decode(ix['data'])
        if len(raw) == 9 and raw[0] == 3:
            price = struct.unpack('<Q', raw[1:])[0]
    return price


def priority_bucket(price):
    if price is None:
        return 'none'
    if price == 0:
        return '0'
    for bound, name in ((10_000, '1-10000'), (100_000, '10001-100000'), (1_000_000, '100001-1000000')):
        if price <= bound:
            return name
    return '>1000000'


def gap_bucket(gap):
    if gap < 0:
        raise MeasureError('events_out_of_order')
    if gap <= 4:
        return str(gap)
    if gap <= 8:
        return '5-8'
    if gap <= 32:
        return '9-32'
    return '>32'


def measure_archive(archive, counts):
    events = []
    for tx in archive.transactions.values():
        names = launchlab_instructions(tx['meta'].get('logMessages'))
        if any(name in BUY_INSTRUCTIONS for name in names):
            failed = 'failed' if tx['meta'].get('err') is not None else 'ok'
            counts['buys_by_priority'][priority_bucket(unit_price(tx))][failed] += 1
        events.extend(e for e in LE.extract_trade_events(tx) if e.pool == archive.pool)
    events.sort(key=lambda e: (e.slot, e.signature, e.event_index))
    for previous, event in zip(events, events[1:]):
        if event.side == 'buy':                   # lowercase in the decoder (its docstring says BUY)
            counts['buy_reaction_gap_slots'][gap_bucket(event.slot - previous.slot)] += 1


def measure(pack, manifest_sha256):
    if type(manifest_sha256) is not str or manifest_sha256.startswith(HOLDOUT_PREFIX):
        raise MeasureError('holdout_refused')
    found, _digests, entries, _manifest = load_fixtures_lazy(pack)
    if found != manifest_sha256:
        raise MeasureError('manifest_is_not_the_anchored_one')
    counts = dict(buys_by_priority={b: dict(ok=0, failed=0) for b in PRIORITY_BUCKETS},
                  buy_reaction_gap_slots={b: 0 for b in GAP_BUCKETS})
    pools = 0
    try:
        for _entry, archive in entries:
            pools += 1
            measure_archive(archive, counts)
    finally:
        clear_cache()
    return dict(schema=SCHEMA, pools=pools, input=dict(manifest_sha256=manifest_sha256), **counts,
                measures_our_landing=False, label='HISTORICAL_REPLAY', descriptive_only=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='landslip.measure')
    parser.add_argument('--pack', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise MeasureError('output_exists')
    doc = measure(a.pack, a.manifest_sha256)
    a.out.mkdir(parents=True)
    raw = (json.dumps(doc, sort_keys=True, indent=1) + '\n').encode()
    (a.out / 'LANDSLIP_COUNTS.json').write_bytes(raw)
    print(json.dumps(dict(sha256=hashlib.sha256(raw).hexdigest(), pools=doc['pools']), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
