"""cpmmprereg 0.2 (0.1 7e60f0b PASS R02 + R02 amendment A1: (c) the CPMM buy guard of cpmmcost 0.3 is ON, 20 000 ppm,
sensitivity 50 000; (b) the expected entries are ONLY the count of R-CP1 TRIGGERS over the 7 days BEFORE T0, no outcome;
(a) confirmation n with sigma_c = max(sigma observed at the pilot, 2.5 %), alpha 0.05 / 3, and CONFIRMÉ also needs a net
> 0 with 1 failure, a net > 0 at 10 slots and a difference to the placebo > 0) -- cpmmprereg 0.1 -- PRE-REGISTRATION of the CPMM pilot hypothesis R-CP1 on established Raydium CPMM pools (task CPMM-2),
frozen as code BEFORE any pilot datum (note v0.2 b4c6562c sections 2.2-2.5; cpmmcost 0.2 a611621 for every cost).
Fixtures / synthetic pools only; nothing reads collected data.

R-CP1 'rebound after a drop', decided at each real swap i of a pool (block time t_i, spot = quote / base reserve
after the swap, from the reserves the program logged, AmmConfig shares applied):
  (i)   P_i / P_ref - 1 <= -3 %, P_ref = spot after the LAST swap j with block_time_j <= t_i - 600 s (none: no decision);
  (ii)  at least 20 real swaps with block_time in ]t_i - 600 ; t_i];
  (iii) no position opened on this pool in the previous 3 600 s of block time.
Buy 0.1 SOL, landing 4 slots later (cpmmcost: H-1; 0.2: buy guard 20 000 ppm, a refused buy is charged, no entry). Exit: TP +2 % / SL -2 % of the
STAKE on the exact sale value, checked at every real swap after the landing (the sale lands 4 slots after the trigger),
otherwise the clock at 30 min (+ the frozen clock latency); then the closed account (C-a). Net = cpmmcost.position.
PAIRED PLACEBO: same pools, as many entries per pool as R-CP1, drawn uniformly among the pool's swaps that have a
reference swap, under the same constraint (iii); seed = sha256(freeze sheet sha + pool)[:8].
"""
import hashlib
import math
import random
import statistics
from fractions import Fraction
from statistics import NormalDist

from bot.p4 import historical_research_replay as hrr
from cpmmcost import model as CC
from cpmmx import timeline as TL
from w2arms import ce as W

SCHEMA = 'cpmmprereg-v0.2'
LOOKBACK_S = 600
DROP = Fraction(-3, 100)
MIN_SWAPS_IN_LOOKBACK = 20
COOLDOWN_S = 3_600
TP, SL = Fraction(2, 100), Fraction(-2, 100)
CLOCK_S = 1_800
CLOCK_LATENCY_S = hrr.clock_exit_latency_s(CC.LATENCY_SLOTS)
# power (declared before any datum; sigma is an ASSUMPTION for a +/-2 % bracket with slippage, not an estimate)
SIGMA_DECLARED = 0.025
DELTA_NET_PILOT = 0.005                 # minimal NET effect of interest, after the full cpmmcost costs (closed mode)
ALPHA_PILOT, ALPHA_CONFIRMATION, POWER = 0.05, 0.05 / 3, 0.80
MIN_ELIGIBLE_POOLS, DRAWN_POOLS = 20, 24
TRIALS_BEFORE, TRIAL_CAP = 168, 170
# amendment A1 of R02
COUNT_DAYS, DAY_S = 7, 86_400                         # (b) triggers counted over the 7 days before T0, never an outcome
SIGMA_FLOOR = SIGMA_DECLARED                          # (a) sigma_c = max(sigma observed at the pilot, 2.5 %)
CONFIRMATION_DRAWS = 10_000
CONFIRMATION_VERDICTS = ('CONFIRMÉ', 'NON CONFIRMÉ', 'INCONCLUSIF')
CONDITIONS = ('c1_lower_bound_of_the_mean_above_zero', 'c2_lower_bound_over_the_paired_placebo_above_zero',
              'c3_both_halves_positive', 'c4_every_position_priced_with_a_zero_residual',
              'c5_net_above_zero_at_10_slots_and_without_the_best_5',
              'a1_net_above_zero_with_1_failure', 'a1_difference_to_the_placebo_above_zero')


class PreregError(ValueError):
    pass


def spot_after(line, index, fees):
    base, quote = TL.after_swap(line.swaps[index], fees.protocol_fee_rate, fees.fund_fee_rate)
    return Fraction(quote, base)


def has_reference(line, i):
    t = line.swaps[i].block_time
    return any(s.block_time <= t - LOOKBACK_S for s in line.swaps[:i])


def decisions(line, config):
    """Indices of the swaps where R-CP1 decides (causal: only swaps up to i are read)."""
    fees = CC.fees_from_amm_config(config)
    out, last_open = [], None
    for i, swap in enumerate(line.swaps):
        t = swap.block_time
        refs = [j for j in range(i) if line.swaps[j].block_time <= t - LOOKBACK_S]
        if not refs:
            continue
        recent = sum(1 for k in range(i + 1) if t - LOOKBACK_S < line.swaps[k].block_time <= t)
        if recent < MIN_SWAPS_IN_LOOKBACK:
            continue
        if last_open is not None and t - last_open < COOLDOWN_S:
            continue
        if spot_after(line, i, fees) / spot_after(line, refs[-1], fees) - 1 <= DROP:
            out.append(i)
            last_open = t
    return out


def placebo(line, count, freeze_sheet_sha256):
    """``count`` placebo entries drawn uniformly among the swaps with a reference, under the cooldown (iii)."""
    if type(freeze_sheet_sha256) is not str or len(freeze_sheet_sha256) != 64:
        raise PreregError('freeze_sheet_sha256_required')
    seed = int(hashlib.sha256((freeze_sheet_sha256 + line.pool).encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    candidates = [i for i in range(len(line.swaps)) if has_reference(line, i)]
    rng.shuffle(candidates)
    chosen = []
    for i in candidates:
        if len(chosen) == count:
            break
        t = line.swaps[i].block_time
        if all(abs(t - line.swaps[c].block_time) >= COOLDOWN_S for c in chosen):
            chosen.append(i)
    return sorted(chosen)


def exit_point(line, decision_index, config, *, latency_slots=CC.LATENCY_SLOTS, buy_failures=0):
    """(exit_slot, None) for TP / SL, (None, exit_time) for the clock; TP / SL on the stake, exact sale value.
    The declared latency (4, or 10 in sensitivity) moves the buy, the sale after a trigger and the clock latency alike."""
    if latency_slots not in CC.ALLOWED_LATENCIES or type(latency_slots) is not int:
        raise PreregError('latency_not_a_declared_value')
    fees = CC.fees_from_amm_config(config)
    decision = line.swaps[decision_index]
    land = decision.slot + latency_slots * (1 + buy_failures)
    on_input = CC.creator_side(line, decision_index)
    states = [CC._state(line, fees, slot_limit=land - 1), CC._state(line, fees, slot_limit=land)]
    tokens = min(CC._buy_on(s, fees, on_input).output_amount for s in states)
    deadline = decision.block_time + CLOCK_S
    for k, swap in enumerate(line.swaps):
        if swap.slot <= land or swap.block_time > deadline:
            continue
        base, quote = TL.after_swap(swap, fees.protocol_fee_rate, fees.fund_fee_rate)
        value = CC._sell_on((base, quote), tokens, fees, on_input).output_amount
        ratio = Fraction(value - CC.STAKE_LAMPORTS, CC.STAKE_LAMPORTS)
        if ratio >= TP or ratio <= SL:
            return swap.slot + latency_slots, None
    return None, deadline + hrr.clock_exit_latency_s(latency_slots)


def positions(line, config, indices, *, failures=CC.FROZEN_FAILURES, latency_slots=CC.LATENCY_SLOTS,
              buy_guard_ppm=CC.BUY_GUARD_PPM):
    """Primary: 0 failure, 4 slots, guard 20 000 ppm. Sensitivities: failures=Failures(1, 1, 0), latency_slots=10, the
    50 000 ppm guard. A guard-failed buy stays in the list (charged, not an entry); every row carries its decision time."""
    out = []
    for i in indices:
        exit_slot, exit_time = exit_point(line, i, config, latency_slots=latency_slots, buy_failures=failures.buy)
        try:
            row = CC.position(line, i, config, exit_slot=exit_slot, exit_time=exit_time, failures=failures,
                              latency_slots=latency_slots, buy_guard_ppm=buy_guard_ppm)
        except CC.CostError as exc:                         # e.g. data ends before the exit: published, never priced
            row = dict(pool=line.pool, decision_index=i, unpriced=str(exc))
        out.append(dict(row, decision_time=line.swaps[i].block_time))
    return out


def n_required(sigma=SIGMA_DECLARED, delta=DELTA_NET_PILOT, alpha=ALPHA_PILOT, power=POWER):
    z = NormalDist().inv_cdf(1 - alpha) + NormalDist().inv_cdf(power)
    return math.ceil((z * sigma / delta) ** 2)


def eligibility_stop(eligible_pools):
    """The rule fixed before step 0: too few pools -> STOP, declared INCONCLUSIVE, no trial consumed."""
    if type(eligible_pools) is not int or eligible_pools < 0:
        raise PreregError('invalid_eligible_count')
    if eligible_pools < MIN_ELIGIBLE_POOLS:
        return dict(decision='STOP_INCONCLUSIF', trial_consumed=False, pools=eligible_pools)
    if eligible_pools < DRAWN_POOLS:
        return dict(decision='PROCEED_ALL_NO_REPLACEMENT', trial_consumed=False, pools=eligible_pools)
    return dict(decision='PROCEED_DRAW_24', trial_consumed=False, pools=DRAWN_POOLS)


def power_stop(expected_entries):
    """Before step 1: an expected entry count below G-1's floor (30) declares the pilot underpowered in advance."""
    if type(expected_entries) is not int or expected_entries < 0:
        raise PreregError('invalid_expected_entries')
    if expected_entries < 30:
        return 'UNDERPOWERED_DECLARED_OWNER_DECIDES'
    if expected_entries < n_required():
        return 'BELOW_POWER_TARGET_PUBLISHED_AS_SUCH'
    return 'POWERED'


def trials(n_before=TRIALS_BEFORE):
    if type(n_before) is not int or n_before + 1 > TRIAL_CAP:
        raise PreregError('trial_cap_exceeded')
    return dict(n_before=n_before, n_after=n_before + 1, left=TRIAL_CAP - n_before - 1,
                rule='R-CP1 and its placebo are ONE trial, counted when evaluated; any variant or second universe '
                     'consumes the last one')


def halves(line, positions_, cut_time):
    """Net returns of the two time halves (decision block time < cut / >= cut); unpriced positions are listed apart."""
    first, second = [], []
    for p in positions_:
        if 'net_return' not in p:
            continue
        (first if line.swaps[p['decision_index']].block_time < cut_time else second).append(p['net_return'])
    return first, second


# -- amendment A1 (b): expected entries = the count of R-CP1 TRIGGERS over the 7 days BEFORE T0, no outcome -------------
def trigger_count(lines, config, t0):
    """R-CP1 decisions with block time in [T0 - 7 d ; T0) per pool of the U-2 list. Data at or after T0 is REFUSED (never
    filtered). Only ``decisions`` runs: no position, no exit, no net is computed. Swaps before T0 - 7 d may be given:
    they serve the 600 s reference and the cooldown (iii) only, and their decisions are not counted."""
    if type(t0) is not int:
        raise PreregError('t0_must_be_an_integer_block_time')
    start = t0 - COUNT_DAYS * DAY_S
    per_pool = {}
    for line in lines:
        if line.pool in per_pool:
            raise PreregError('pool_given_twice')
        if any(s.block_time >= t0 for s in line.swaps):
            raise PreregError('data_at_or_after_t0_refused')
        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time >= start)
    return dict(schema=SCHEMA, t0=t0, window=[start, t0], days=COUNT_DAYS, per_pool=per_pool,
                triggers=sum(per_pool.values()), outcomes_computed=False)


def expected_entries(count, pilot_days):
    """Triggers of the 7 days scaled to the pilot window of D days (floor; D = 7 is the count itself). A trigger that the
    buy guard will refuse cannot be known without an outcome, so it is not removed: declared optimistic for power."""
    if type(pilot_days) is not int or pilot_days < 1:
        raise PreregError('pilot_days_must_be_a_positive_integer')
    if count.get('outcomes_computed') is not False or count.get('days') != COUNT_DAYS:
        raise PreregError('not_a_trigger_count')
    return count['triggers'] * pilot_days // COUNT_DAYS


# -- amendment A1 (a): confirmation n and verdict ---------------------------------------------------------------------
def sigma_of_pilot(positions_):
    """Sample standard deviation of the net of every PRICED pilot position (guard-failed included, as in the mean)."""
    nets = [p['net_return'] for p in positions_ if 'net_return' in p]
    if len(nets) < 2:
        raise PreregError('sigma_needs_two_priced_positions')
    return statistics.stdev(nets)


def confirmation_n(sigma_pilot):
    if type(sigma_pilot) not in (int, float) or not sigma_pilot >= 0 or math.isinf(sigma_pilot):
        raise PreregError('invalid_sigma')
    sigma_c = max(float(sigma_pilot), SIGMA_FLOOR)
    return dict(sigma_pilot=float(sigma_pilot), sigma_c=sigma_c, alpha=ALPHA_CONFIRMATION, power=POWER,
                delta=DELTA_NET_PILOT, n=n_required(sigma=sigma_c, alpha=ALPHA_CONFIRMATION))


def _key(p):
    return p['pool'], p['decision_index']


def _mean(values):
    return sum(values) / len(values) if values else None


def confirmation_verdict(primary, *, placebo_, one_failure, ten_slots, cut_time, sigma_pilot, freeze_sheet_sha256,
                         draws=CONFIRMATION_DRAWS):
    """On a NEW window: dossier B c1 to c5 adapted to CPMM (pool clusters, alpha 0.05 / 3) and the two A1 conditions.
    n is the ENTERED positions of the primary; INCONCLUSIF below confirmation_n(sigma_pilot)."""
    if (type(freeze_sheet_sha256) is not str or len(freeze_sheet_sha256) != 64
            or any(c not in '0123456789abcdef' for c in freeze_sheet_sha256)):
        raise PreregError('freeze_sheet_sha256_required')
    if type(cut_time) is not int:
        raise PreregError('cut_time_must_be_anchored')
    keys = sorted(map(_key, primary))
    if sorted(map(_key, one_failure)) != keys or sorted(map(_key, ten_slots)) != keys:
        raise PreregError('sensitivities_are_not_the_same_decisions')
    if {p['pool'] for p in placebo_} - {p['pool'] for p in primary}:
        raise PreregError('placebo_outside_the_pools')
    need = confirmation_n(sigma_pilot)
    seed = int(freeze_sheet_sha256[:8], 16)
    rows = [dict(p, arm='rcp1') for p in primary] + [dict(p, arm='placebo') for p in placebo_]
    unpriced = sum('net_return' not in r for r in rows + list(one_failure) + list(ten_slots))
    priced = [r for r in rows if 'net_return' in r]
    groups = {}
    for r in priced:
        groups.setdefault(r['pool'], []).append(r)

    def mean_rcp1(rows_):
        return _mean([r['net_return'] for r in rows_ if r['arm'] == 'rcp1'])

    def diff(rows_):
        a = _mean([r['net_return'] for r in rows_ if r['arm'] == 'rcp1'])
        b = _mean([r['net_return'] for r in rows_ if r['arm'] == 'placebo'])
        return None if a is None or b is None else a - b
    low_mean = W.lower_bound(groups, mean_rcp1, seed=seed, draws=draws, alpha=ALPHA_CONFIRMATION)
    low_diff = W.lower_bound(groups, diff, seed=seed, draws=draws, alpha=ALPHA_CONFIRMATION)
    nets = [p['net_return'] for p in primary if 'net_return' in p]
    halves = [_mean([p['net_return'] for p in primary if 'net_return' in p and p['decision_time'] < cut_time]),
              _mean([p['net_return'] for p in primary if 'net_return' in p and p['decision_time'] >= cut_time])]
    slow = _mean([p['net_return'] for p in ten_slots if 'net_return' in p])
    one = _mean([p['net_return'] for p in one_failure if 'net_return' in p])
    without_best5 = _mean(sorted(nets)[:-5]) if len(nets) > 5 else None
    point_diff = diff(priced)
    values = (low_mean is not None and low_mean > 0,
              low_diff is not None and low_diff > 0,
              all(h is not None and h > 0 for h in halves),
              unpriced == 0 and bool(primary),
              slow is not None and slow > 0 and without_best5 is not None and without_best5 > 0,
              one is not None and one > 0,
              point_diff is not None and point_diff > 0)
    conditions = dict(zip(CONDITIONS, values))
    entered = sum(1 for p in primary if p.get('entered', True) and 'net_return' in p)
    if entered < need['n']:
        decision = 'INCONCLUSIF'
    elif all(values):
        decision = 'CONFIRMÉ'
    else:
        decision = 'NON CONFIRMÉ'
    return dict(schema=SCHEMA, decision=decision, n_entered=entered, n_required=need, unpriced=unpriced,
                guard_failed=sum(1 for p in primary if p.get('status') == 'guard_failed'), conditions=conditions,
                mean_net_return=_mean(nets), lower_bound=low_mean, lower_bound_minus_placebo=low_diff,
                difference_to_placebo=point_diff, halves=dict(cut_time=cut_time, means=halves),
                mean_net_return_10_slots=slow, mean_net_return_1_failure=one, mean_without_best_5=without_best5,
                draws=draws, seed=seed, labels=list(CC.LABELS), counts_for_operational_master=False,
                meaning='CONFIRMÉ is a result in historical PAPER on CPMM only; it never counts for the 50 cycles / '
                        '20 creators of the operational Master and is never a claim on real returns')
