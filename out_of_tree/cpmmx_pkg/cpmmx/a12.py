"""Criterion A-12 on one CPMM pool: every observed swap recomputed to the atomic unit, each gap explained.

  python -I -B -m cpmmx.a12 <pool.json[.gz]> [--protocol-fee-rate N --fund-fee-rate N]

Input (one pool, plain data): {"pool": ..., "base_mint": ..., "opened": [slot, block_time] or null,
"transactions": {signature: raw getTransaction result}}. Output: one JSON report on stdout. The
fee rates are read from the pool's own swaps (all of them: this is a check of the arithmetic, not
a causal estimate); the protocol and fund shares come from the pool's AmmConfig when given.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from cpmmx import VERSION, timeline

THRESHOLD = 0.999


def report(document, protocol_fee_rate=None, fund_fee_rate=None):
    opened = document.get('opened')
    line = timeline.build(document['pool'], document['transactions'], base_mint=document['base_mint'],
                          opened=None if opened is None else tuple(opened))
    out = dict(schema='cpmmx-a12-v1', cpmmx_version=VERSION, pool=line.pool, transactions=len(document['transactions']),
               swaps=len(line.swaps), lp_changes=len(line.lp_changes), skipped=[list(row) for row in line.skipped],
               fees={}, reproduction=None, continuity=None, passed=False, reasons=[])
    by_side = {}
    for side in ('buy', 'sell'):
        if not any(s.side == side for s in line.swaps):
            continue
        try:
            fees, on_input, evidence = timeline.infer_fees(line.swaps, side)
        except timeline.TimelineError as exc:
            out['fees'][side] = dict(error=str(exc))
            out['reasons'].append(f'fees_not_readable:{side}:{exc}')
            continue
        by_side[side] = (fees, on_input)
        out['fees'][side] = dict(trade_fee_rate=fees.trade_fee_rate, creator_fee_rate=fees.creator_fee_rate,
                                 creator_fee_on_input=on_input, evidence=evidence)
    checked = [s for s in line.swaps if s.side in by_side]
    if checked:
        part = timeline.Timeline(line.pool, line.base_mint, line.quote_mint, tuple(checked), line.lp_changes,
                                 line.skipped, line.opened)
        out['reproduction'] = timeline.reproduce(part, by_side)
    breaks = timeline.continuity(line, protocol_fee_rate or 0, fund_fee_rate or 0)
    skims = [b for b in breaks if b['skim'] is not None and b['reason'] == 'reserves_discontinuity']
    holes = [b for b in breaks if b['skim'] is None and b['reason'] == 'reserves_discontinuity']
    out['continuity'] = dict(
        shares_given=protocol_fee_rate is not None, breaks=len(breaks), lp_changes_between=sum(
            b['reason'] == 'lp_change_between' for b in breaks),
        input_side_only=len(skims), both_sides=len(holes), both_sides_indices=[b['index'] for b in holes][:50],
        # with no shares given: the protocol + fund fee each swap really paid, as a share of its trade fee (ppm)
        skim_share_of_trade_fee_ppm=sorted({b['skim'] * 1_000_000 // b['trade_fee'] for b in skims
                                             if b['trade_fee']})[:20])
    share = (out['reproduction'] or {}).get('share_exact')
    if line.skipped:
        out['reasons'].append('transactions_not_decoded')
    if holes:
        out['reasons'].append('reserve_chain_has_holes')
    if share is None or share < THRESHOLD:
        out['reasons'].append('reproduction_below_threshold')
    if len(checked) != len(line.swaps):
        out['reasons'].append('swaps_not_checked')
    out['passed'] = not out['reasons']
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='A-12 check of one CPMM pool')
    parser.add_argument('pool_file', type=Path)
    parser.add_argument('--protocol-fee-rate', type=int)
    parser.add_argument('--fund-fee-rate', type=int)
    a = parser.parse_args(argv)
    if (a.protocol_fee_rate is None) != (a.fund_fee_rate is None):
        parser.error('give both shares or none')
    raw = a.pool_file.read_bytes()
    data = gzip.decompress(raw) if a.pool_file.suffix == '.gz' else raw
    out = report(json.loads(data), a.protocol_fee_rate, a.fund_fee_rate)
    out['input_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0 if out['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
