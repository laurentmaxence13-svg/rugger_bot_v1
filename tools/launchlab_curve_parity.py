#!/usr/bin/env python3
"""Offline parity check: recompute observed exact-in LaunchLab fills.

Reads only the three committed SOL pool fixtures (no network, no keys). For
every observed TradeEvent it decides whether the event is supported by the
exact-in arithmetic of ``bot.market.launchlab_curve`` and, if so, recomputes
output and fee from the signed pre-state, using the pool's fee schedule, and
reports exact integer mismatches. Unsupported events are counted, never
approximated.

  python -B tools/launchlab_curve_parity.py [--json]
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.market.collector import load_archive, summarize  # noqa: E402
from bot.market.launchlab_curve import (  # noqa: E402
    CurveError, FEE_DENOMINATOR, buy_exact_in, sell_exact_in,
)

PACK = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'


def fee_rate_interval(events):
    """Total fee rates (ppm) consistent with every event's observed ceil-fee."""
    low, high = 0, FEE_DENOMINATOR
    for event in events:
        basis, fee = event.quote_volume, event.total_fee
        low = max(low, ((fee - 1) * FEE_DENOMINATOR) // basis + 1 if fee > 0 else 0)
        high = min(high, (fee * FEE_DENOMINATOR) // basis)
    return low, high


def classify(event):
    """Return None when exact-in arithmetic applies, else the reason it does not."""
    if event.violations:
        return 'event_has_violations:' + ','.join(event.violations)
    if not event.exact_in:
        return 'exact_out_not_modelled'
    if event.pool_status != 0:
        return 'pool_not_in_curve_phase'
    return None


def recompute(event, rate_ppm):
    """Return (fill, None) or (None, reason) for one supported event."""
    state = event.state_before()
    try:
        fill = (buy_exact_in(state, event.amount_in, rate_ppm) if event.side == 'buy'
                else sell_exact_in(state, event.amount_in, rate_ppm))
    except CurveError as exc:
        return None, f'curve_refused:{exc}'
    return fill, None


def check_pool(entry, directory=PACK):
    archive = load_archive(directory, entry['pool'])
    _, timeline = summarize(archive)
    events = timeline.events
    low, high = fee_rate_interval(events)
    rate = entry['fee_rate_ppm']
    result = {
        'pool': entry['pool'], 'sha256': entry['sha256'], 'fee_rate_ppm': rate,
        'fee_rate_interval_ppm': [low, high], 'events': len(events),
        'supported': 0, 'unsupported': 0, 'unsupported_reasons': {},
        'matched': 0, 'mismatches': [], 'not_recomputable': [],
    }
    for _key, why in timeline.rejected:
        # Events rejected by the timeline (violations, other pool) are unsupported.
        result['events'] += 1
        result['unsupported'] += 1
        reason = 'timeline_rejected:' + why
        result['unsupported_reasons'][reason] = result['unsupported_reasons'].get(reason, 0) + 1
    for event in events:
        reason = classify(event)
        if reason:
            result['unsupported'] += 1
            result['unsupported_reasons'][reason] = result['unsupported_reasons'].get(reason, 0) + 1
            continue
        result['supported'] += 1
        fill, why = recompute(event, rate)
        if fill is None:
            result['not_recomputable'].append({'key': list(event.key), 'reason': why})
        elif (fill.amount_out, fill.fee, fill.after.real_base, fill.after.real_quote) == (
                event.amount_out, event.total_fee, event.real_base_after, event.real_quote_after):
            result['matched'] += 1
        else:
            result['mismatches'].append({
                'key': list(event.key), 'side': event.side,
                'expected': [event.amount_out, event.total_fee],
                'recomputed': [fill.amount_out, fill.fee]})
    return result


def run(directory=PACK):
    manifest = json.loads((Path(directory) / 'MANIFEST.json').read_text(encoding='utf-8'))
    pools = [check_pool(entry, directory) for entry in manifest['pools']]
    totals = {k: sum(p[k] for p in pools) for k in ('events', 'supported', 'unsupported', 'matched')}
    totals['mismatches'] = sum(len(p['mismatches']) for p in pools)
    totals['not_recomputable'] = sum(len(p['not_recomputable']) for p in pools)
    return {'pools': pools, 'totals': totals}


def main(argv):
    report = run()
    if '--json' in argv:
        print(json.dumps(report, indent=2))
    else:
        for p in report['pools']:
            print(f"{p['pool']} rate={p['fee_rate_ppm']}ppm events={p['events']} "
                  f"supported={p['supported']} unsupported={p['unsupported']} "
                  f"matched={p['matched']} mismatches={len(p['mismatches'])} "
                  f"not_recomputable={len(p['not_recomputable'])}")
        print('TOTAL', report['totals'])
    t = report['totals']
    return 0 if t['mismatches'] == 0 and t['not_recomputable'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
