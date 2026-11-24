"""n1rot 0.1 on synthetic timelines only: daily volume / TVL, median of 7 days, T0 boundaries, declared thresholds,
the 4 named pools, NON ÉVALUABLE under 3 pools, and the CLI wiring (pages reading mocked)."""
import hashlib
import json
from fractions import Fraction

import pytest

from cpmmx.events import SwapEvent
from cpmmx.timeline import Swap, Timeline
from cpmmprereg.tests.test_rule import CONFIG
from n1rot import rotation as N

T0 = 10_000_000
DAY = 86_400
SOL = 10 ** 9


def swap(t, side, sol, reserve_sol, k=0):
    """A swap at time t moving `sol` lamports on the SOL side, pool SOL reserve `reserve_sol` before it."""
    if side == 'buy':
        e = SwapEvent('p', reserve_sol, 10 ** 15, sol, 10 ** 6, 0, 0, True, trade_fee=sol // 400, creator_fee=0,
                      creator_fee_on_input=True)
    else:
        e = SwapEvent('p', 10 ** 15, reserve_sol, 10 ** 6, sol, 0, 0, True, trade_fee=1, creator_fee=0,
                      creator_fee_on_input=True)
    return Swap('s%d_%d' % (t, k), t // 1, t, k, 0, side, 10 ** 15, reserve_sol, e)


def line(pool, swaps):
    return Timeline(pool, 'mint', 'wsol', tuple(sorted(swaps, key=lambda s: (s.block_time, s.tx_index))), (), ())


def steady(pool, rot, reserve=100 * SOL):
    """One buy then one sell per day, total SOL volume = rot x 2 x reserve."""
    out = []
    for j in range(7):
        t = T0 - (7 - j) * DAY + 100
        half = int(rot * 2 * reserve) // 2
        out += [swap(t, 'buy', half, reserve), swap(t + 10, 'sell', half, reserve + half, 1)]
    return line(pool, out)


def test_daily_volume_tvl_rotation_and_an_empty_day():
    s = [swap(T0 - 7 * DAY, 'buy', 30 * SOL, 100 * SOL),                    # first second of day -7: included
         swap(T0 - 7 * DAY + 5, 'sell', 10 * SOL, 130 * SOL, 1),
         swap(T0 - 7 * DAY - 1, 'buy', 99 * SOL, 100 * SOL),                # before the 7 days: ignored
         swap(T0 - 6 * DAY, 'buy', 7 * SOL, 120 * SOL),                     # first second of day -6, not day -7
         swap(T0 - 1, 'sell', 50 * SOL, 125 * SOL)]                         # last second before T0: day -1
    days = N.daily_rotation(line('p', s), T0)
    assert [d['day'] for d in days] == list(range(-7, 0))
    assert days[0] == dict(day=-7, swaps=2, volume_lamports=40 * SOL, tvl_lamports=200 * SOL,
                           rotation=Fraction(1, 5))                          # TVL from the FIRST swap's reserve
    assert days[6]['rotation'] == Fraction(50, 250) and days[6]['swaps'] == 1
    assert days[1]['swaps'] == 1 and days[1]['rotation'] == Fraction(7, 240)
    assert days[3] == dict(day=-4, swaps=0, volume_lamports=0, tvl_lamports=N.NM, rotation=0)
    assert N.median_rotation(days) == 0                                       # 3 active days of 7
    with pytest.raises(N.RotationError, match='after_t0'):
        N.daily_rotation(line('p', s + [swap(T0, 'buy', SOL, 100 * SOL)]), T0)
    with pytest.raises(N.RotationError, match='t0'):
        N.daily_rotation(line('p', s), float(T0))


def test_the_median_is_the_fourth_of_seven():
    days = [dict(rotation=Fraction(r, 100)) for r in (90, 10, 50, 30, 70, 20, 60)]
    assert N.median_rotation(days) == Fraction(50, 100)
    with pytest.raises(N.RotationError, match='seven'):
        N.median_rotation(days[:6])


def test_break_even_thresholds_from_the_frozen_costs():
    assert N.break_even_rotation(CONFIG) == Fraction(88, 21)                 # 880 000 / 210 000
    with_creator = dict(CONFIG, creator_fee_rate=500)
    assert N.break_even_rotation(with_creator) == Fraction(31, 7)            # 930 000 / 210 000
    assert N.threshold_value('dossier_15', CONFIG) == Fraction(15, 100)
    with pytest.raises(N.RotationError, match='declared'):
        N.threshold_value('other', CONFIG)
    with pytest.raises(N.CC.CostError):
        N.break_even_rotation(dict(CONFIG, trade_fee_rate=10_000))          # outside U-1


def named(rotations, reserve=100 * SOL):
    return [steady(p, r, reserve) for p, r in zip(N.NAMED_POOLS, rotations)]


def test_selection_keeps_pools_at_or_above_the_threshold_and_needs_3():
    out = N.select_n1(named([Fraction(15, 100), Fraction(16, 100), Fraction(149, 1000), 1]), CONFIG, T0,
                      threshold='dossier_15')
    assert out['kept'] == [N.NAMED_POOLS[0], N.NAMED_POOLS[1], N.NAMED_POOLS[3]]    # 15 % exactly is kept
    assert out['evaluable'] is True and out['conduct'] is None
    assert out['list_sha256'] == hashlib.sha256('\n'.join(out['kept']).encode()).hexdigest()
    assert out['lp_returns_computed'] is False and out['counts_for_operational_master'] is False
    assert [p['pool'] for p in out['pools']] == list(N.NAMED_POOLS)
    assert out['pools'][0]['median_rotation_exact'] == '3/20'
    # the same pools against the cost break-even (88/21 = 419 % / day): none kept -> NON ÉVALUABLE
    hard = N.select_n1(named([Fraction(15, 100), Fraction(16, 100), Fraction(149, 1000), 1]), CONFIG, T0,
                       threshold='cost_break_even')
    assert hard['kept'] == [] and hard['evaluable'] is False and hard['conduct'].startswith('NON ÉVALUABLE')
    edge = N.select_n1(named([Fraction(88, 21)] * 3 + [4], reserve=105 * SOL), CONFIG, T0, threshold='cost_break_even')
    assert edge['pools'][0]['median_rotation_exact'] == '88/21'                # exactly the bar: kept
    assert edge['kept'] == list(N.NAMED_POOLS[:3]) and edge['evaluable'] is True
    two = N.select_n1(named([1, 1, 0, 0]), CONFIG, T0, threshold='dossier_15')
    assert two['evaluable'] is False


def test_only_the_4_named_pools_once_each_and_a_declared_threshold():
    lines = named([1, 1, 1, 1])
    with pytest.raises(N.RotationError, match='declared'):
        N.select_n1(lines, CONFIG, T0, threshold='ten_percent')
    with pytest.raises(N.RotationError, match='4_pools'):
        N.select_n1(lines[:3], CONFIG, T0, threshold='dossier_15')
    with pytest.raises(N.RotationError, match='4_pools'):
        N.select_n1(lines[:3] + [steady('other', 1)], CONFIG, T0, threshold='dossier_15')
    with pytest.raises(N.RotationError, match='twice'):
        N.select_n1(lines + [lines[0]], CONFIG, T0, threshold='dossier_15')
    assert hashlib.sha256('\n'.join(N.NAMED_POOLS).encode()).hexdigest() == N.NAMED_LIST_SHA256


def test_cli_reads_the_pre_pages_of_the_named_pools_only(tmp_path, monkeypatch):
    from cpmmpilot import step1 as PILOT
    seen = {}

    def timelines(out, phase, rows):
        seen.update(out=out, phase=phase, pools=[r['pool'] for r in rows])
        return named([1, 1, 1, 0])

    monkeypatch.setattr(PILOT, 'timelines', timelines)
    monkeypatch.setattr(PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG, slot=slot))
    u2 = dict(selected=[dict(pool=p) for p in ('x',) + N.NAMED_POOLS])
    (tmp_path / 'u2.json').write_text(json.dumps(u2))
    N.main([str(tmp_path / 'out'), str(tmp_path / 'u2.json'), str(T0), '123', 'dossier_15',
            str(tmp_path / 'r.json')])
    doc = json.loads((tmp_path / 'r.json').read_text())
    assert seen == dict(out=str(tmp_path / 'out'), phase='pre', pools=list(N.NAMED_POOLS))   # 'x' never read
    assert doc['kept'] == list(N.NAMED_POOLS[:3]) and doc['evaluable'] is True and doc['skipped_transactions'] == 0
    monkeypatch.setattr(PILOT, 'timelines', lambda *a: pytest.fail('read'))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(selected=[dict(pool=p) for p in N.NAMED_POOLS[:3]])))
    with pytest.raises(N.RotationError, match='missing'):
        N.main([str(tmp_path / 'out'), str(tmp_path / 'u2.json'), str(T0), '1', 'dossier_15', str(tmp_path / 'r.json')])
