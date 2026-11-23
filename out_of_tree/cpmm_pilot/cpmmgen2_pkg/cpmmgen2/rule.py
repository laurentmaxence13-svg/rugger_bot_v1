"""cpmmgen2 0.1 -- EXECUTABLE PROTOCOLS of generation 2 (GEN-2 v0.3, table anchored by R02 f4027134; owner relaunch of
23/11 relayed by R04, task T-R01-1), frozen as code BEFORE any datum of their window. Synthetic pools only.

Three hypotheses on ESTABLISHED Raydium CPMM pools, each one trial (170 -> 173, under the owner's text D), on a window
DISJOINT from generation 1 (R-CP1, B1). Universe, order, exits, costs (cpmmcost 0.3, guard ON) and pilot verdict are
R-CP1's, imported from cpmmprereg 0.2 / cpmmcost 0.3 and NEVER modified.

G2-1 « chute non routée » (family « 10 min »): R-CP1 conditions (i) drop <= -3 % vs the LAST swap <= t - 600 s, (ii) >= 20
     swaps in ]t - 600 ; t], (iii) own cooldown 3 600 s, AND the share of the SELL quote volume of ]t - 600 ; t] made
     by routed swaps (depth > 1) <= m1. m1 = population median, over [T0 - 7 d ; T0), of that share at the swaps where
     (i) and (ii) hold (no return, data >= T0 refused).
G2-2 « épuisement vendeur » (family « 10 min »): a trigger (i)+(ii) at t0 opens a wait of at most 1 800 s; the entry
     is the first swap t1 in ]t0 ; t0 + 1 800] with (a) net quote flow (buys in - sells out) of ]t1 - 300 ; t1] > 0 and
     (b) no spot of ]t1 - 300 ; t1] below the lowest spot of ]t0 - 600 ; t1 - 300]; cooldown (iii) applied at the
     trigger t0 (so also at t1 > t0: no trigger opens within 3 600 s of the last G2-2 entry);
     at most one entry per trigger; waits without entry are counted and published.
G2-3 « élargissement de la demande » (independent of the price trigger): at swap i, the number of DISTINCT BUYERS
     (fee payer of the buy transaction) in ]t - 600 ; t] >= 2 x b3(pool), own cooldown 3 600 s; b3(pool) = median
     over the 1 008 consecutive 600-s windows of [T0 - 7 d ; T0) of the distinct buyers of that pool; a pool with
     b3 = 0 is EXCLUDED (counted), never entered.
Alpha: pilot 0.05 each (n 155, word max GO_PILOTE); confirmation on a NEW window: Holm at alpha_2 = 0.025 (first step
0.025 / 3, n_c = 262) or, if the owner chooses it, 0.05 / 3 (n_c = 221).
"""
import hashlib
import math
import random
import statistics

from cpmmcost import model as CC
from cpmmprereg import rule as R

SCHEMA = 'cpmmgen2-v0.1'
HYPOTHESES = ('G2-1', 'G2-2', 'G2-3')
WAIT_S, CALM_S = 1_800, 300
BUYERS_MULTIPLIER = 2
WINDOWS_BEFORE_T0 = R.COUNT_DAYS * R.DAY_S // R.LOOKBACK_S          # 1 008
TRIALS_BEFORE_GEN2, TRIAL_CAP_GEN2 = 170, 173
ALPHA_PILOT = 0.05
CONFIRMATION = dict(holm=dict(alpha_family=0.025, first_step=0.025 / 3), bonferroni=dict(alpha_family=0.05,
                                                                                         first_step=0.05 / 3))
PreregError = R.PreregError


# -- shared pieces -----------------------------------------------------------------------------------------------------
def _window(line, i, seconds):
    t = line.swaps[i].block_time
    return [k for k in range(i + 1) if t - seconds < line.swaps[k].block_time <= t]


def drop_event(line, i, fees):
    """R-CP1 conditions (i) and (ii) at swap i, without the cooldown (causal: swaps up to i only)."""
    t = line.swaps[i].block_time
    refs = [j for j in range(i) if line.swaps[j].block_time <= t - R.LOOKBACK_S]
    if not refs or len(_window(line, i, R.LOOKBACK_S)) < R.MIN_SWAPS_IN_LOOKBACK:
        return False
    return R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 <= R.DROP


def quote_flow(swap):
    """Signed quote amount of a swap: + quote paid in by a buy, - quote paid out by a sale."""
    return swap.event.input_amount if swap.side == 'buy' else -swap.event.output_amount


def routed_share(line, i):
    """Share of the sell quote volume of ]t - 600 ; t] made by routed swaps (depth > 1); None without any sale."""
    sells = [line.swaps[k] for k in _window(line, i, R.LOOKBACK_S) if line.swaps[k].side == 'sell']
    total = sum(s.event.output_amount for s in sells)
    if not total:
        return None
    return sum(s.event.output_amount for s in sells if s.depth > 1) / total


def _refuse_after_t0(line, t0):
    if any(s.block_time >= t0 for s in line.swaps):
        raise PreregError('data_at_or_after_t0_refused')


def _check_t0(t0):
    if type(t0) is not int:
        raise PreregError('t0_must_be_an_integer_block_time')


# -- G2-1 ----------------------------------------------------------------------------------------------------------------
def population_m1(lines, config, t0):
    """Median of the routed share at the drop events of [T0 - 7 d ; T0) of every pool; no return is computed."""
    _check_t0(t0)
    fees = CC.fees_from_amm_config(config)
    start, shares = t0 - R.COUNT_DAYS * R.DAY_S, []
    for line in lines:
        _refuse_after_t0(line, t0)
        for i, swap in enumerate(line.swaps):
            if swap.block_time >= start and drop_event(line, i, fees):
                share = routed_share(line, i)
                if share is not None:
                    shares.append(share)
    if not shares:
        raise PreregError('no_drop_event_before_t0_non_evaluable')
    return statistics.median(shares)


def decisions_g21(line, config, m1):
    fees = CC.fees_from_amm_config(config)
    out, last = [], None
    for i, swap in enumerate(line.swaps):
        if last is not None and swap.block_time - last < R.COOLDOWN_S:
            continue
        if drop_event(line, i, fees):
            share = routed_share(line, i)
            if share is not None and share <= m1:
                out.append(i)
                last = swap.block_time
    return out


# -- G2-2 ----------------------------------------------------------------------------------------------------------------
def decisions_g22(line, config):
    """(entries, waits_without_entry): entry indices and the number of triggers whose wait ended without an entry."""
    fees = CC.fees_from_amm_config(config)
    entries, empty, pending, last = [], 0, None, None
    for i, swap in enumerate(line.swaps):
        t = swap.block_time
        if pending is not None and t > pending + WAIT_S:
            empty, pending = empty + 1, None
        if pending is None:
            if (last is None or t - last >= R.COOLDOWN_S) and drop_event(line, i, fees):
                pending = t                               # cooldown (iii) at the trigger, hence also at t1 > t0
            continue
        if t <= pending:
            continue
        recent = _window(line, i, CALM_S)
        before = [k for k in range(i + 1) if pending - R.LOOKBACK_S < line.swaps[k].block_time <= t - CALM_S]
        if not before or sum(quote_flow(line.swaps[k]) for k in recent) <= 0:
            continue
        low_before = min(R.spot_after(line, k, fees) for k in before)
        if min(R.spot_after(line, k, fees) for k in recent) >= low_before:
            entries.append(i)
            last, pending = t, None
    if pending is not None:
        empty += 1
    return entries, empty


def placebo_g22(line, count, freeze_sheet_sha256, config):
    """Paired placebo: ``count`` swaps drawn uniformly among those within 1 800 s after a trigger (i)+(ii), cooldown."""
    if type(freeze_sheet_sha256) is not str or len(freeze_sheet_sha256) != 64:
        raise PreregError('freeze_sheet_sha256_required')
    fees = CC.fees_from_amm_config(config)
    triggers = [s.block_time for i, s in enumerate(line.swaps) if drop_event(line, i, fees)]
    candidates = [i for i, s in enumerate(line.swaps) if any(t0 < s.block_time <= t0 + WAIT_S for t0 in triggers)]
    rng = random.Random(int(hashlib.sha256((freeze_sheet_sha256 + line.pool).encode()).hexdigest()[:8], 16))
    rng.shuffle(candidates)
    chosen = []
    for i in candidates:
        if len(chosen) == count:
            break
        if all(abs(line.swaps[i].block_time - line.swaps[c].block_time) >= R.COOLDOWN_S for c in chosen):
            chosen.append(i)
    return sorted(chosen)


# -- G2-3 ----------------------------------------------------------------------------------------------------------------
def fee_payer(tx):
    """The fee payer (first account key) of a raw transaction; known when the transaction is seen."""
    try:
        key = tx['transaction']['message']['accountKeys'][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise PreregError('transaction_without_account_keys') from exc
    key = key.get('pubkey') if isinstance(key, dict) else key
    if type(key) is not str or not key:
        raise PreregError('invalid_fee_payer')
    return key


def buyers(line, txs):
    """Fee payer of each BUY swap (None for sales), from the raw transactions of the collection."""
    return [fee_payer(txs[s.signature]) if s.side == 'buy' else None for s in line.swaps]


def baseline_b3(line, txs, t0):
    """Median, over the 1 008 consecutive 600-s windows of [T0 - 7 d ; T0), of the distinct buyers of the pool."""
    _check_t0(t0)
    _refuse_after_t0(line, t0)
    payer = buyers(line, txs)
    start = t0 - R.COUNT_DAYS * R.DAY_S
    counts = []
    for k in range(WINDOWS_BEFORE_T0):
        low, high = start + k * R.LOOKBACK_S, start + (k + 1) * R.LOOKBACK_S
        counts.append(len({payer[i] for i, s in enumerate(line.swaps) if payer[i] and low <= s.block_time < high}))
    return statistics.median(counts)


def decisions_g23(line, txs, b3):
    """Indices where the distinct buyers of ]t - 600 ; t] reach 2 x b3; a pool with b3 = 0 is excluded (empty list)."""
    if b3 == 0:
        return []
    payer = buyers(line, txs)
    out, last = [], None
    for i, swap in enumerate(line.swaps):
        if last is not None and swap.block_time - last < R.COOLDOWN_S:
            continue
        distinct = {payer[k] for k in _window(line, i, R.LOOKBACK_S) if payer[k]}
        if len(distinct) >= BUYERS_MULTIPLIER * b3:
            out.append(i)
            last = swap.block_time
    return out


# -- trigger counts before T0 (A1 (b) method), trials, confirmation -----------------------------------------------------
def trigger_count(decide, lines, t0):
    """``decide(line) -> indices``; counts the decisions of [T0 - 7 d ; T0) only; data >= T0 refused; no outcome."""
    _check_t0(t0)
    start, per_pool = t0 - R.COUNT_DAYS * R.DAY_S, {}
    for line in lines:
        if line.pool in per_pool:
            raise PreregError('pool_given_twice')
        _refuse_after_t0(line, t0)
        per_pool[line.pool] = sum(1 for i in decide(line) if line.swaps[i].block_time >= start)
    return dict(schema=SCHEMA, t0=t0, window=[start, t0], days=R.COUNT_DAYS, per_pool=per_pool,
                triggers=sum(per_pool.values()), outcomes_computed=False)


def trials(hypothesis, n_before):
    if hypothesis not in HYPOTHESES:
        raise PreregError('unknown_hypothesis')
    if type(n_before) is not int or n_before < TRIALS_BEFORE_GEN2 or n_before + 1 > TRIAL_CAP_GEN2:
        raise PreregError('trial_cap_exceeded_or_not_authorised')
    return dict(hypothesis=hypothesis, n_before=n_before, n_after=n_before + 1, cap=TRIAL_CAP_GEN2,
                rule='one trial per hypothesis, counted when its window is evaluated; cap 173 only under the text D')


def confirmation_n(sigma_pilot, choice='holm'):
    if choice not in CONFIRMATION:
        raise PreregError('confirmation_choice_is_the_owners')
    if type(sigma_pilot) not in (int, float) or not sigma_pilot >= 0 or math.isinf(sigma_pilot):
        raise PreregError('invalid_sigma')
    sigma_c = max(float(sigma_pilot), R.SIGMA_FLOOR)
    alpha = CONFIRMATION[choice]['first_step']
    return dict(choice=choice, sigma_c=sigma_c, alpha_first_step=alpha, n=R.n_required(sigma=sigma_c, alpha=alpha))


def bootstrap_p(groups, *, seed, draws=R.CONFIRMATION_DRAWS):
    """One-sided p of 'mean net > 0': share of pool-cluster resamples whose mean is <= 0."""
    keys = sorted(groups)
    if not keys:
        return None
    rng, low = random.Random(seed), 0
    for _ in range(draws):
        rows = [r for _k in keys for r in groups[keys[rng.randrange(len(keys))]]]
        low += (sum(rows) / len(rows)) <= 0
    return low / draws


def holm(p_values, choice='holm'):
    """Holm step-down over the hypotheses of the generation: {name: True if rejected (mean > 0 retained)}."""
    alpha = CONFIRMATION[choice]['alpha_family']
    order = sorted((p, name) for name, p in p_values.items() if p is not None)
    k, out = len(order), {name: False for name in p_values}
    if choice == 'bonferroni':
        return {name: p is not None and p <= alpha / max(len(p_values), 1) for name, p in p_values.items()}
    for rank, (p, name) in enumerate(order):
        if p > alpha / (k - rank):
            break
        out[name] = True
    return out


def withdrawn_if_family_negative(r_cp1_verdict, b1_verdict):
    """Pre-declared elimination rule (a21f90f3 section 2): both NEGATIVE -> G2-1 and G2-2 withdrawn, G2-3 alone."""
    if r_cp1_verdict == 'NO-GO' and b1_verdict == 'NO-GO':
        return dict(kept=('G2-3',), withdrawn=('G2-1', 'G2-2'), k=1)
    return dict(kept=HYPOTHESES, withdrawn=(), k=3)


# same exits, costs, placebo construction (G2-1, G2-3), positions, power stop and pilot verdict as R-CP1
positions, placebo, power_stop, expected_entries = R.positions, R.placebo, R.power_stop, R.expected_entries
pilot_verdict = CC.pilot_verdict
