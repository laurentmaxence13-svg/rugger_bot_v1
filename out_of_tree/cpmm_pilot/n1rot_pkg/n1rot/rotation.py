"""n1rot 0.2 -- ROTATION RULE of N1, FIXED BEFORE ANY MEASUREMENT (decision R04-4, 24/11; R02 note 0b64abd6), and the
script that measures it on the PRE-T0 pages of A2r only. Offline code; it is executed by R03 only after R02's audit.

WHAT IS MEASURED (descriptive market activity, NO LP return): for each of the 4 pools named by G2-3 and each of the 7
days [T0 - (7 - j) d ; T0 - (6 - j) d), j = 0..6:
  volume_j = sum of the SOL side of every swap of the day (buy: SOL paid in, input_amount; sell: SOL paid out,
             output_amount), in lamports, as the program logged it;
  tvl_j    = 2 x the SOL reserve logged before the FIRST swap of the day (LP-owned reserve, fees excluded);
  rotation_j = volume_j / tvl_j ; a day without any swap has rotation 0 (its tvl is NON MESURÉ).
The pool's rotation is the MEDIAN of its 7 daily rotations (the 4th of 7, exact fractions).
NOT computed: fees earned, inventory loss, price moves, any position or any net value. Data at or after T0 refused.

THE RULE (fixed here, before any measurement): a pool enters the N1 universe if its median rotation >= the declared
threshold; N1 is EVALUABLE only with >= 3 pools; otherwise NON ÉVALUABLE: no freeze sheet, trial 170 not consumed.
Declared thresholds (R02 chooses ONE before execution; no change after the measurement):
  'cost_break_even' (proposed): the rotation at which the LP part of the fees of ONE pool-day pays the frozen costs
      of the round trip at zero price move: (lpcost transactions + 2 x HALF x (trade + creator rate))
      / (STAKE x trade rate x (1 - protocol - fund shares)); 88 / 21 = 419 % / day with the U-1 rates and no creator
      fee; 31 / 7 = 443 % / day with a creator fee of 500 ppm. Rates from the AmmConfig as read and hashed.
  'dossier_15' : 15 % / day (dossier N1 b7d5d9c § 5: LP fees = sigma^2 / 8 at sigma = 5 % / day, fixed costs ignored).
0.2 (decision R04-6, 24/11 21:29Z): threshold 'r04_6_break_even', computed IN CODE and POOL BY POOL for the R04-6
  configuration (one position of 0.5 % of the WSOL reserve, held 12 days, one round trip amortised over 12 days):
      rot* = (6 transactions + entry swap cost + exit swap cost) / (12 x stake x trade rate x (1 - protocol - fund))
  with stake = 0.5 % of the WSOL reserve of the pool's LAST PRE-T0 state (time limit T0 - 1), the entry swap of
  stake // 2 on that state (fee, creator fee, impact) and the sale of the bought tokens back on the same state (zero
  price move). It is a NECESSARY condition only: below it the LP part of the fees cannot pay the costs even at a
  constant price. Fees earned are approximated by stake x LP rate x daily rotation x 12 (our fraction ~ stake / TVL).
"""
import hashlib
import json
from fractions import Fraction

from cpmmcost import model as CC
from cpmmx import curve
from lpcost import model as LP

SCHEMA = 'n1rot-v0.2'
DAY_S, DAYS, MIN_POOLS = 86_400, 7, 3
NM = 'NON MESURÉ'
NAMED_POOLS = ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr',
               'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh', 'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')
NAMED_LIST_SHA256 = '812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80'   # G2-3 sheet v0.5
THRESHOLDS = ('cost_break_even', 'dossier_15', 'r04_6_break_even')
R046_DAYS, R046_STAKE_PPM = 12, 5_000


class RotationError(ValueError):
    pass


def break_even_rotation(config):
    """Rotation per day at which one pool-day's LP fees pay the frozen round-trip costs at zero price move."""
    fees = CC.fees_from_amm_config(config)
    tx, _rent = LP.transactions()
    swap_fees = Fraction(2 * LP.HALF * (fees.trade_fee_rate + fees.creator_fee_rate), curve.FEE_DENOMINATOR)
    lp_rate = Fraction(fees.trade_fee_rate, curve.FEE_DENOMINATOR) * Fraction(
        curve.FEE_DENOMINATOR - fees.protocol_fee_rate - fees.fund_fee_rate, curve.FEE_DENOMINATOR)
    return (tx + swap_fees) / (LP.STAKE * lp_rate)


def break_even_rotation_r04_6(line, config, t0):
    """R04-6 rotation break-even of ONE pool, from its last pre-T0 state (see the module docstring)."""
    fees = CC.fees_from_amm_config(config)
    if any(t0 <= s.block_time for s in line.swaps):
        raise RotationError('data_at_or_after_t0_refused')
    base, quote = CC._state(line, fees, time_limit=t0 - 1)
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    stake = quote * R046_STAKE_PPM // 1_000_000
    half = stake // 2
    tokens = curve.swap_base_input(half, quote, base, fees, on_input).output_amount
    spot = Fraction(quote, base)
    entry = half - tokens * spot
    exit_ = tokens * spot - curve.swap_base_input(tokens, base, quote, fees, on_input).output_amount
    tx, _rent = LP.transactions()
    lp_rate = Fraction(fees.trade_fee_rate, curve.FEE_DENOMINATOR) * Fraction(
        curve.FEE_DENOMINATOR - fees.protocol_fee_rate - fees.fund_fee_rate, curve.FEE_DENOMINATOR)
    return (tx + entry + exit_) / (R046_DAYS * stake * lp_rate)


def threshold_value(name, config):
    if name == 'cost_break_even':
        return break_even_rotation(config)
    if name == 'dossier_15':
        return Fraction(15, 100)
    raise RotationError('threshold_not_declared')


def _sol_amount(swap):
    return swap.event.input_amount if swap.side == 'buy' else swap.event.output_amount


def daily_rotation(line, t0):
    if type(t0) is not int:
        raise RotationError('t0_must_be_an_integer_block_time')
    if any(s.block_time >= t0 for s in line.swaps):
        raise RotationError('data_at_or_after_t0_refused')
    days = []
    for j in range(DAYS):
        low, high = t0 - (DAYS - j) * DAY_S, t0 - (DAYS - 1 - j) * DAY_S
        mine = [s for s in line.swaps if low <= s.block_time < high]
        if not mine:
            days.append(dict(day=j - DAYS, swaps=0, volume_lamports=0, tvl_lamports=NM, rotation=Fraction(0)))
            continue
        tvl = 2 * mine[0].quote_before
        if tvl <= 0:
            raise RotationError('empty_sol_reserve')
        volume = sum(_sol_amount(s) for s in mine)
        days.append(dict(day=j - DAYS, swaps=len(mine), volume_lamports=volume, tvl_lamports=tvl,
                         rotation=Fraction(volume, tvl)))
    return days


def median_rotation(days):
    if len(days) != DAYS:
        raise RotationError('seven_days_required')
    return sorted(d['rotation'] for d in days)[DAYS // 2]


def select_n1(lines, config, t0, *, threshold):
    """The N1 universe among the 4 pools named by G2-3 (no other pool: the window pages exist for these only)."""
    if threshold not in THRESHOLDS:
        raise RotationError('threshold_not_declared')
    pools = [line.pool for line in lines]
    if len(set(pools)) != len(pools):
        raise RotationError('pool_given_twice')
    if set(pools) != set(NAMED_POOLS):
        raise RotationError('exactly_the_4_pools_named_by_g2_3')
    if hashlib.sha256('\n'.join(NAMED_POOLS).encode()).hexdigest() != NAMED_LIST_SHA256:
        raise RotationError('named_list_altered')
    bar = None if threshold == 'r04_6_break_even' else threshold_value(threshold, config)
    by_pool = {line.pool: line for line in lines}
    rows, kept = [], []
    for pool in NAMED_POOLS:                                   # the sheet's order
        days = daily_rotation(by_pool[pool], t0)
        med = median_rotation(days)
        pool_bar = break_even_rotation_r04_6(by_pool[pool], config, t0) if bar is None else bar
        ok = med >= pool_bar
        if ok:
            kept.append(pool)
        rows.append(dict(pool=pool, median_rotation=float(med), median_rotation_exact=str(med), kept=ok,
                         threshold_value=float(pool_bar), threshold_exact=str(pool_bar),
                         days=[dict(d, rotation=float(d['rotation'])) for d in days]))
    evaluable = len(kept) >= MIN_POOLS
    return dict(schema=SCHEMA, t0=t0, window=[t0 - DAYS * DAY_S, t0], threshold=threshold,
                threshold_value=NM if bar is None else float(bar), threshold_exact=NM if bar is None else str(bar),
                threshold_per_pool=bar is None, amm_config_sha256=config['sha256'],
                pools=rows, kept=kept, list_sha256=hashlib.sha256('\n'.join(kept).encode()).hexdigest(),
                evaluable=evaluable,
                conduct=None if evaluable else 'NON ÉVALUABLE : aucune fiche N1, essai 170 non consommé',
                lp_returns_computed=False, labels=['MASTER_RESEARCH_PAPER', 'HISTORICAL_REPLAY', 'LP_SIDE_RESEARCH'],
                counts_for_operational_master=False)


def main(argv=None):
    """R03, after R02's audit only: python -B -m n1rot.rotation OUT U2_DOC.json T0_TIME T0_SLOT THRESHOLD RESULT.json
    OUT is the A2r collection root (pages OUT/collect/pre/<pool>/page_*.json.gz, cpmmpilot.step1 layout)."""
    import sys
    from cpmmpilot import step1 as PILOT
    out, u2_path, t0_time, t0_slot, threshold, result = (argv if argv is not None else sys.argv[1:])
    with open(u2_path) as fh:
        u2 = json.load(fh)
    rows = [r for r in u2['selected'] if r['pool'] in NAMED_POOLS]
    if {r['pool'] for r in rows} != set(NAMED_POOLS):
        raise RotationError('a_named_pool_is_missing_from_the_a2r_selection')
    lines = PILOT.timelines(out, 'pre', rows)
    config = PILOT.amm_config_for_rules(rows, int(t0_slot))
    doc = select_n1(lines, config, int(t0_time), threshold=threshold)
    doc['skipped_transactions'] = sum(len(line.skipped) for line in lines)
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False)
    with open(result, 'w') as fh:
        fh.write(text + '\n')
    print(hashlib.sha256((text + '\n').encode()).hexdigest(), result)


if __name__ == '__main__':
    main()
