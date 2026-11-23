"""cpmmprereg 0.1 -- PRE-REGISTRATION of the CPMM pilot hypothesis R-CP1 on established Raydium CPMM pools (task CPMM-2),
frozen as code BEFORE any pilot datum (note v0.2 b4c6562c sections 2.2-2.5; cpmmcost 0.2 a611621 for every cost).
Fixtures / synthetic pools only; nothing reads collected data.

R-CP1 'rebound after a drop', decided at each real swap i of a pool (block time t_i, spot = quote / base reserve
after the swap, from the reserves the program logged, AmmConfig shares applied):
  (i)   P_i / P_ref - 1 <= -3 %, P_ref = spot after the LAST swap j with block_time_j <= t_i - 600 s (none: no decision);
  (ii)  at least 20 real swaps with block_time in ]t_i - 600 ; t_i];
  (iii) no position opened on this pool in the previous 3 600 s of block time.
Buy 0.1 SOL, landing 4 slots later (cpmmcost: H-1, guard-free CPMM buy as in the note). Exit: TP +2 % / SL -2 % of the
STAKE on the exact sale value, checked at every real swap after the landing (the sale lands 4 slots after the trigger),
otherwise the clock at 30 min (+ the frozen clock latency); then the closed account (C-a). Net = cpmmcost.position.
PAIRED PLACEBO: same pools, as many entries per pool as R-CP1, drawn uniformly among the pool's swaps that have a
reference swap, under the same constraint (iii); seed = sha256(freeze sheet sha + pool)[:8].
"""
import hashlib
import math
import random
from fractions import Fraction
from statistics import NormalDist

from bot.p4 import historical_research_replay as hrr
from cpmmcost import model as CC
from cpmmx import timeline as TL

SCHEMA = 'cpmmprereg-v0.1'
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


def exit_point(line, decision_index, config):
    """(exit_slot, None) for TP / SL, (None, exit_time) for the clock; TP / SL on the stake, exact sale value."""
    fees = CC.fees_from_amm_config(config)
    decision = line.swaps[decision_index]
    land = decision.slot + CC.LATENCY_SLOTS
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
            return swap.slot + CC.LATENCY_SLOTS, None
    return None, deadline + CLOCK_LATENCY_S


def positions(line, config, indices):
    out = []
    for i in indices:
        exit_slot, exit_time = exit_point(line, i, config)
        try:
            out.append(CC.position(line, i, config, exit_slot=exit_slot, exit_time=exit_time))
        except CC.CostError as exc:                         # e.g. data ends before the exit: published, never priced
            out.append(dict(pool=line.pool, decision_index=i, unpriced=str(exc)))
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
