"""Criterion C-1 / A-12 of the CPMM protocol: every observed swap recomputed to the atomic unit.

  python -I -B -m cpmmx.a12 <pool.json[.gz]>                 one pool -> one JSON report on stdout
  python -I -B -m cpmmx.a12 --combine <report.json> ...      the verdict over several pool reports

Pool input (plain data): {"pool", "base_mint", "opened": [slot, block_time] | null,
"transactions": {signature: raw transaction}, "amm_config": {"trade_fee_rate", "creator_fee_rate",
"protocol_fee_rate", "fund_fee_rate"}}. The rates are READ from the pool's AmmConfig account
(``creator_fee_rate`` 0 when the pool has creator fees disabled); the side of the creator fee is the
one each event logged. Rates deduced from the swaps themselves are a cross-check only (C-3): the
config must lie inside every deduced interval. A pool passes only with its config, every transaction
decoded, an unbroken reserve chain (C-2) and at least 99 % of its swaps reproduced. An unexplained
change of a reserve (a swap missing from the collection, or tokens sent straight to a vault, which
leaves no event) breaks the chain and excludes the pool.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from cpmmx import VERSION, curve, timeline

POOL_THRESHOLD, TOTAL_THRESHOLD = 0.99, 0.999
MIN_SWAPS, MIN_POOLS, MIN_EXACT_OUTPUT = 1000, 5, 50
RATES = ('trade_fee_rate', 'creator_fee_rate', 'protocol_fee_rate', 'fund_fee_rate')


def _inside(interval, value):
    return interval is None or interval[0] <= value <= interval[1]


def report(document):
    opened = document.get('opened')
    line = timeline.build(document['pool'], document['transactions'], base_mint=document['base_mint'],
                          opened=None if opened is None else tuple(opened))
    swaps = line.swaps
    out = dict(schema='cpmmx-a12-v2', cpmmx_version=VERSION, pool=line.pool, transactions=len(document['transactions']),
               swaps=len(swaps), exact_output_swaps=sum(not s.event.base_input for s in swaps),
               called_by_another_program=sum(s.depth > 1 for s in swaps), lp_changes=len(line.lp_changes),
               creator_fee_sides=sorted({s.event.creator_fee_on_input for s in swaps if s.event.creator_fee}),
               skipped=[list(row) for row in line.skipped], amm_config=None, reproduction=None, continuity=None,
               deduced_rates={}, passed=False, reasons=[])
    config = document.get('amm_config')
    if config is None or any(type(config.get(name)) is not int for name in RATES):
        out['reasons'].append('amm_config_missing')
        return out
    out['amm_config'] = {name: config[name] for name in RATES}
    fees = curve.Fees(**out['amm_config'])
    out['reproduction'] = timeline.reproduce(line, {side: (fees, None) for side in ('buy', 'sell')})
    breaks = timeline.continuity(line, fees.protocol_fee_rate, fees.fund_fee_rate)
    broken = [b for b in breaks if b['reason'] == 'reserves_discontinuity']
    out['continuity'] = dict(breaks=len(broken), lp_changes_between=len(breaks) - len(broken),
                             one_side_only=sum(b['skim'] is not None for b in broken),
                             indices=[b['index'] for b in broken][:50])
    for side in ('buy', 'sell'):                             # C-3: cross-check, never the source of the rates
        if not any(s.side == side for s in swaps):
            continue
        try:
            _fees, on_input, evidence = timeline.infer_fees(swaps, side)
        except timeline.TimelineError as exc:
            out['deduced_rates'][side] = dict(error=str(exc))
            if str(exc) in ('fee_rate_changed_within_the_swaps', 'creator_fee_side_changed'):
                out['reasons'].append(f'fee_rate_changed:{side}')
            continue
        out['deduced_rates'][side] = dict(creator_fee_on_input=on_input, evidence=evidence)
        if on_input:
            agree = _inside(evidence['combined_rate_interval'], fees.trade_fee_rate + fees.creator_fee_rate)
        else:
            agree = _inside(evidence['trade_rate_interval'], fees.trade_fee_rate) and _inside(
                evidence['creator_rate_interval'], fees.creator_fee_rate)
        if not agree:
            out['reasons'].append(f'config_outside_deduced_interval:{side}')
    share = out['reproduction']['share_exact']
    if line.skipped:
        out['reasons'].append('transactions_not_decoded')
    if broken:
        out['reasons'].append('reserve_chain_broken')
    if share is None or share < POOL_THRESHOLD:
        out['reasons'].append('reproduction_below_pool_threshold')
    out['passed'] = not out['reasons']
    return out


def combine(reports):
    """The C-1 verdict over pool reports: excluded pools are counted, never dropped silently."""
    kept = [r for r in reports if r['passed']]
    swaps = sum(r['swaps'] for r in kept)
    exact = sum(r['reproduction']['exact'] for r in kept)
    out = dict(schema='cpmmx-a12-verdict-v1', cpmmx_version=VERSION, pools=len(reports), pools_kept=len(kept),
               pools_excluded={r['pool']: r['reasons'] for r in reports if not r['passed']}, swaps=swaps, exact=exact,
               share_exact=None if not swaps else exact / swaps,
               exact_output_swaps=sum(r['exact_output_swaps'] for r in kept),
               called_by_another_program=sum(r['called_by_another_program'] for r in kept),
               lp_changes=sum(r['lp_changes'] for r in kept),
               creator_fee_sides=sorted({side for r in kept for side in r['creator_fee_sides']}), reasons=[])
    checks = (('fewer_pools_than_required', len(kept) >= MIN_POOLS), ('fewer_swaps_than_required', swaps >= MIN_SWAPS),
              ('reproduction_below_threshold', bool(swaps) and exact / swaps >= TOTAL_THRESHOLD),
              ('too_few_exact_output_swaps', out['exact_output_swaps'] >= MIN_EXACT_OUTPUT),
              ('no_liquidity_change', out['lp_changes'] >= 1),
              ('no_call_by_another_program', out['called_by_another_program'] >= 1))
    out['reasons'] = [name for name, ok in checks if not ok]
    out['passed'] = not out['reasons']
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='A-12 / C-1 check of CPMM pools')
    parser.add_argument('files', type=Path, nargs='+')
    parser.add_argument('--combine', action='store_true')
    a = parser.parse_args(argv)
    if a.combine:
        out = combine([json.loads(path.read_text(encoding='utf-8')) for path in a.files])
        out['inputs_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in a.files}
    else:
        if len(a.files) != 1:
            parser.error('one pool file, or --combine with several reports')
        raw = a.files[0].read_bytes()
        out = report(json.loads(gzip.decompress(raw) if a.files[0].suffix == '.gz' else raw))
        out['input_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0 if out['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
