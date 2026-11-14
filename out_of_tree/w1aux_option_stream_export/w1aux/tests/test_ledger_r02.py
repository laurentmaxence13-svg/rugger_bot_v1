"""RUGGER 02 audit b6d9717a, tests 5452aaa0 (integrated verbatim, HTML entities decoded): consistent rewrites
of the fee rate (C-L1) and of a late timed exit (C-L2) must FAIL."""
import gzip, json
from fractions import Fraction
from w1aux import ledger as L
from w1aux.tests.test_ledger import rehearsal, _copy, _rewrite, _closed, PACK  # noqa: F401
from bot.market.launchlab_curve import buy_exact_in, sell_exact_in


def _consistent(row, events, params, *, rate=None, last=None, landing=None):
    rate = row['fee_rate_ppm'] if rate is None else rate
    last = row['exit_index'] if last is None else last
    land = row['entry_index']
    buy = buy_exact_in(events[land].state_after(), row['spent'], rate)
    st = buy.after
    for j in range(land + 1, last + 1):
        st = L._replay_real(st, events[j])
    sale = sell_exact_in(st, buy.amount_out, rate)
    row.update(fee_rate_ppm=rate, tokens=buy.amount_out, received=sale.amount_out, exit_index=last)
    if landing is not None:
        row.update(exit_block_time=landing, exit_slot=events[last].slot)
    row['pnl_lamports'] = row['received'] - row['spent'] - row['tx_costs'] - row['failed_attempt_costs']
    row['net_return'] = row['pnl_lamports'] / (row['spent'] + row['tx_costs'] + row['failed_attempt_costs'])


def test_gap_fee_rate_consistent_rewrite(rehearsal, tmp_path):
    _m, ev = L.timelines(PACK)
    bundles = _copy(rehearsal, tmp_path)
    def mutate(b):
        pool = next(p for p in b['pools'] if p['trade']['outcome'] == 'closed')
        row = pool['trade']
        _consistent(row, ev[pool['pool']], b['params'], rate=max(0, row['fee_rate_ppm'] - 5000))
    _rewrite(bundles, 'S1', mutate)
    led = L.build_ledger(PACK, bundles)
    print('FEE_RATE_REWRITE verdict', led['verdict'], led['mismatches'])
    assert led['verdict'] == 'FAIL'


def test_gap_late_timed_exit_consistent_rewrite(rehearsal, tmp_path):
    _m, ev = L.timelines(PACK)
    bundles = _copy(rehearsal, tmp_path)
    info = {}
    def mutate(b):
        for pool in b['pools']:
            row = pool['trade']
            if row['outcome'] != 'closed' or 'clock_exit' not in row['notes']:
                continue
            events = ev[pool['pool']]
            for extra in range(5, 4000, 5):
                landing = row['exit_block_time'] + extra
                last = max(j for j in range(row['entry_index'], len(events)) if events[j].block_time <= landing)
                if last > row['exit_index'] and (last + 1 == len(events) or events[last + 1].block_time > landing):
                    info.update(pool=pool['pool'], old=row['exit_block_time'], new=landing, oldi=row['exit_index'], newi=last)
                    _consistent(row, events, b['params'], last=last, landing=landing)
                    return
    _rewrite(bundles, 'S1', mutate)
    led = L.build_ledger(PACK, bundles)
    print('LATE_TIMED_EXIT', info, 'verdict', led['verdict'], led['mismatches'])
    assert info and led['verdict'] == 'FAIL'
