"""cpmmgen3 0.1 -- EXECUTABLE PROTOCOLS of generation 3 (GEN-3 v0.2, cf8a848a, RECEVABLE EN PROJET by R02 a3f194dc; task
T-R01-6 of R04, 23/11 22:03Z), frozen as code BEFORE any datum of their window. Synthetic pools only; nothing is read.

Two hypotheses OUTSIDE the « 10 min » family (no 10-minute price trigger), on ESTABLISHED Raydium CPMM pools, each one
trial (173 -> 175) under a NEW owner tranche distinct from text D, on a window DISJOINT from generations 1 and 2.
Order, exits, costs (cpmmcost 0.3, guard ON), placebo seed rule and pilot verdict are R-CP1's, imported from cpmmprereg
0.2 / cpmmcost 0.3 and NEVER modified.

G3-1 « écart inter-pools » (law of one price): pool A (0.25 % tier only) and its SIBLING B, a Raydium CPMM pool of the
     SAME mint quoted in WSOL (the only audited decoder). At swap i of A, with B's spot taken after B's last swap whose
     (slot, tx_index) <= that of swap i (causal; no age limit, as in GEN-3): spot_A / spot_B - 1 <= -b -> buy in A;
     own cooldown 3 600 s per A. B is NEVER traded: only its spot is read, with the fee shares of ITS AmmConfig (read
     and hashed with its slot) at any DECLARED Raydium CPMM tier (``sibling_fees``; cpmmcost.fees_from_amm_config stays
     the only fee source of a trade and keeps refusing any tier other than U-1's). b = the break-even barrier of the map (barmap 0.1, f99c456: tier 0.25 %, 100 SOL,
     priority 100 000, closed account) = 1.1217 %, imported, never retyped. The sibling of A is fixed at T0: the deepest
     OTHER qualifying pool of the same mint (quote reserve >= 100 SOL), ties by pool id. NON EVALUABLE (no sheet, no
     trial) without the population count of the pairs at T0, or with fewer than 10 mints that have a pair (R02).
G3-2 « approfondissement de liquidité »: an LP DEPOSIT (change_type 0) that takes the QUOTE reserve from R to at least
     2 R in its transaction (quote amount >= quote vault before) -> buy at the FIRST real swap of the pool after it
     (key order); own cooldown 3 600 s. The quote token index comes from the CPMM mint order (token_0 < token_1 as
     32-byte keys). NON EVALUABLE (no sheet, no trial, threshold never lowered) with fewer than 30 eligible deposits
     counted over [T0 - 7 d ; T0) (R02).
Alpha: pilot 0.05 each (n 155, word max GO_PILOTE); confirmation on a NEW window: alpha_3 = 0.025 x 2^-1 = 0.0125,
Holm over the KEPT hypotheses (K = 2: first step 0.00625, n_c = 279; K = 1: n_c = 238), valid under option (i) of
text D only (R02).
"""
import hashlib
import math
import random
from fractions import Fraction

from barmap import carte as MAP
from cpmmcost import model as CC
from cpmmprereg import rule as R
from cpmmx import curve
from cpmmx import events as EV
from cpmmx import timeline as TL

SCHEMA = 'cpmmgen3-v0.1'
HYPOTHESES = ('G3-1', 'G3-2')
TIER_A_PPM = 2_500                                  # G3-1 only targets pools A at 0.25 %
MIN_PAIR_RESERVE_LAMPORTS = 100 * 10 ** 9           # R02: two CPMM WSOL pools of >= 100 SOL
MIN_PAIRED_MINTS = 10                               # GEN-3: NON EVALUABLE below 10 pairs at T0
MIN_ELIGIBLE_DEPOSITS = 30                          # GEN-3 / R02: NON EVALUABLE below 30 deposits before T0
DEPOSIT, DEPTH_FACTOR = 0, 2
TRIALS_BEFORE_GEN3, TRIAL_CAP_GEN3 = 173, 175
ALPHA_PILOT = 0.05
ALPHA_GENERATION = 0.025 * 2 ** -(3 - 2)            # b4edc143 section 2: alpha_g = 0.025 x 2^-(g - 2)
PreregError = R.PreregError


def barrier():
    """b of G3-1: the map's break-even barrier at the declared baseline (computed by barmap, never retyped)."""
    b = MAP.BASELINE
    return MAP.cpmm_gross_required(tier=b['tier'], reserve_sol=b['reserve_sol'], priority=b['priority'],
                                   failure=b['failure'], rent=b['rent'], wsol_separate=b['wsol_separate'])


def _check_t0(t0):
    if type(t0) is not int:
        raise PreregError('t0_must_be_an_integer_block_time')


def _refuse_after_t0(line, t0):
    if any(s.block_time >= t0 for s in line.swaps):
        raise PreregError('data_at_or_after_t0_refused')


def _check_sheet(freeze_sheet_sha256):
    if (type(freeze_sheet_sha256) is not str or len(freeze_sheet_sha256) != 64
            or any(c not in '0123456789abcdef' for c in freeze_sheet_sha256)):
        raise PreregError('freeze_sheet_sha256_required')


def _rng(freeze_sheet_sha256, pool):
    return random.Random(int(hashlib.sha256((freeze_sheet_sha256 + pool).encode()).hexdigest()[:8], 16))


def _cooldown_draw(line, candidates, count, rng):
    rng.shuffle(candidates)
    chosen = []
    for i in candidates:
        if len(chosen) == count:
            break
        if all(abs(line.swaps[i].block_time - line.swaps[c].block_time) >= R.COOLDOWN_S for c in chosen):
            chosen.append(i)
    return sorted(chosen)


# -- G3-1 ----------------------------------------------------------------------------------------------------------------
def qualifying(record):
    """A pool of the U-2 list that can enter a pair: CPMM, quoted in WSOL, quote reserve >= 100 SOL at T0."""
    return (record['program'] == 'cpmm' and record['quote_mint'] == TL.WSOL
            and record['quote_reserve_lamports'] >= MIN_PAIR_RESERVE_LAMPORTS)


def pairs(records):
    """{pool A: sibling B} fixed at T0 from the U-2 records (pool, base_mint, quote_mint, program, trade_fee_rate,
    quote_reserve_lamports); A at 0.25 % only; B = the deepest OTHER qualifying pool of the same mint, ties by id."""
    by_mint = {}
    for r in records:
        if qualifying(r):
            by_mint.setdefault(r['base_mint'], []).append(r)
    out = {}
    for mint, rows in by_mint.items():
        if len(rows) < 2:
            continue
        for a in rows:
            if a['trade_fee_rate'] != TIER_A_PPM:
                continue
            others = sorted((r for r in rows if r['pool'] != a['pool']),
                            key=lambda r: (-r['quote_reserve_lamports'], r['pool']))
            out[a['pool']] = others[0]['pool']
    return out


def population_pairs(records):
    """R02 a3f194dc: the population count of the pairs at T0, BEFORE any freeze sheet; no return is read."""
    found = pairs(records)
    mints = {r['base_mint'] for r in records if r['pool'] in found}
    evaluable = len(mints) >= MIN_PAIRED_MINTS
    return dict(schema=SCHEMA, hypothesis='G3-1', qualifying_pools=sum(1 for r in records if qualifying(r)),
                directed_pairs=len(found), paired_mints=len(mints), minimum=MIN_PAIRED_MINTS, evaluable=evaluable,
                conduct=None if evaluable else 'NON ÉVALUABLE : aucune fiche de gel, aucun essai consommé',
                outcomes_computed=False)


def _sibling_index(line_a, line_b, i, start):
    """Index of B's last swap whose (slot, tx_index) <= that of A's swap i (pointer moves forward), or None."""
    target = line_a.swaps[i].slot, line_a.swaps[i].tx_index
    j = start
    while j + 1 < len(line_b.swaps) and (line_b.swaps[j + 1].slot, line_b.swaps[j + 1].tx_index) <= target:
        j += 1
    if j < 0:
        return None, j
    return j, j


def sibling_fees(config):
    """curve.Fees of the SIBLING B, for its spot only: AmmConfig read and hashed with its slot (as cpmmcost), trade
    rate among the declared Raydium CPMM tiers of the map (barmap.CPMM_TIERS_PPM); B is never traded."""
    sha, slot = config.get('sha256'), config.get('slot')
    if type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or type(slot) is not int:
        raise PreregError('sibling_amm_config_not_read_and_hashed')
    if config.get('trade_fee_rate') not in MAP.CPMM_TIERS_PPM:
        raise PreregError('sibling_tier_not_declared')
    return curve.Fees(config['trade_fee_rate'], config.get('creator_fee_rate', 0), config['protocol_fee_rate'],
                      config['fund_fee_rate'])


def gap(line_a, i, fees_a, line_b, j, fees_b):
    """spot_A after swap i / spot_B after swap j - 1, exact."""
    return R.spot_after(line_a, i, fees_a) / R.spot_after(line_b, j, fees_b) - 1


def decisions_g31(line_a, line_b, config_a, config_b, b=None):
    if line_a.base_mint != line_b.base_mint or line_a.quote_mint != TL.WSOL or line_b.quote_mint != TL.WSOL:
        raise PreregError('sibling_is_not_the_same_mint_in_wsol')
    if line_a.pool == line_b.pool:
        raise PreregError('sibling_is_the_pool_itself')
    if config_a['trade_fee_rate'] != TIER_A_PPM:
        raise PreregError('pool_a_not_at_the_0_25_tier')
    limit = Fraction(barrier() if b is None else b)
    fees_a, fees_b = CC.fees_from_amm_config(config_a), sibling_fees(config_b)
    out, last, pointer = [], None, -1
    for i, swap in enumerate(line_a.swaps):
        j, pointer = _sibling_index(line_a, line_b, i, pointer)
        if j is None or (last is not None and swap.block_time - last < R.COOLDOWN_S):
            continue
        if gap(line_a, i, fees_a, line_b, j, fees_b) <= -limit:
            out.append(i)
            last = swap.block_time
    return out


def placebo_g31(line_a, line_b, count, freeze_sheet_sha256):
    """Paired placebo of A: ``count`` swaps of A drawn uniformly among those where B already has a state, cooldown."""
    _check_sheet(freeze_sheet_sha256)
    candidates, pointer = [], -1
    for i in range(len(line_a.swaps)):
        j, pointer = _sibling_index(line_a, line_b, i, pointer)
        if j is not None:
            candidates.append(i)
    return _cooldown_draw(line_a, candidates, count, _rng(freeze_sheet_sha256, line_a.pool))


def trigger_count_g31(pair_lines, configs, t0):
    """Decisions of [T0 - 7 d ; T0) of every (A, B) pair; data >= T0 of A OR B refused; no outcome."""
    _check_t0(t0)
    start, per_pool = t0 - R.COUNT_DAYS * R.DAY_S, {}
    for line_a, line_b in pair_lines:
        if line_a.pool in per_pool:
            raise PreregError('pool_given_twice')
        _refuse_after_t0(line_a, t0)
        _refuse_after_t0(line_b, t0)
        idx = decisions_g31(line_a, line_b, configs[line_a.pool], configs[line_b.pool])
        per_pool[line_a.pool] = sum(1 for i in idx if line_a.swaps[i].block_time >= start)
    return dict(schema=SCHEMA, hypothesis='G3-1', t0=t0, window=[start, t0], days=R.COUNT_DAYS, per_pool=per_pool,
                triggers=sum(per_pool.values()), outcomes_computed=False)


# -- G3-2 ----------------------------------------------------------------------------------------------------------------
def b58decode(text):
    number = 0
    for char in text:
        if char not in EV._ALPHABET:
            raise PreregError('invalid_base58')
        number = number * 58 + EV._ALPHABET.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, 'big')
    key = b'\0' * (len(text) - len(text.lstrip('1'))) + raw
    if len(key) != 32:
        raise PreregError('mint_is_not_a_32_byte_key')
    return key


def quote_index(line):
    """0 if the quote mint is token_0 of the CPMM pool (token_0 < token_1 as 32-byte keys), else 1."""
    return 0 if b58decode(line.quote_mint) < b58decode(line.base_mint) else 1


def eligible(event, q):
    """A deposit that takes the quote reserve from R to at least 2 R in its transaction."""
    before = (event.token_0_vault_before, event.token_1_vault_before)[q]
    amount = (event.token_0_amount, event.token_1_amount)[q]
    return event.change_type == DEPOSIT and before > 0 and before + amount >= DEPTH_FACTOR * before


def _first_swap_after(line, key):
    for i, swap in enumerate(line.swaps):
        if swap.key > key:
            return i
    return None


def deposit_points(line):
    """[(lp key, index of the first real swap after it)] of the eligible deposits; no swap after -> not listed."""
    q = quote_index(line)
    out = []
    for slot, tx_index, order, event in line.lp_changes:
        if eligible(event, q):
            i = _first_swap_after(line, (slot, tx_index, order))
            if i is not None:
                out.append(((slot, tx_index, order), i))
    return out


def decisions_g32(line):
    out, last = [], None
    for _key, i in deposit_points(line):
        t = line.swaps[i].block_time
        if last is not None and t - last < R.COOLDOWN_S:          # also merges deposits before the same swap
            continue
        out.append(i)
        last = t
    return out


def population_deposits(lines, t0):
    """R02 a3f194dc: eligible deposits over [T0 - 7 d ; T0) (time of the first swap after each), every pool; data
    >= T0 refused; no outcome. NON EVALUABLE below 30, declared beforehand, threshold never lowered."""
    _check_t0(t0)
    start, per_pool = t0 - R.COUNT_DAYS * R.DAY_S, {}
    for line in lines:
        if line.pool in per_pool:
            raise PreregError('pool_given_twice')
        _refuse_after_t0(line, t0)
        per_pool[line.pool] = sum(1 for _k, i in deposit_points(line) if line.swaps[i].block_time >= start)
    count = sum(per_pool.values())
    evaluable = count >= MIN_ELIGIBLE_DEPOSITS
    return dict(schema=SCHEMA, hypothesis='G3-2', t0=t0, window=[start, t0], per_pool=per_pool, deposits=count,
                minimum=MIN_ELIGIBLE_DEPOSITS, evaluable=evaluable,
                conduct=None if evaluable else 'NON ÉVALUABLE : aucune fiche de gel, aucun essai consommé',
                outcomes_computed=False)


def trigger_count_g32(lines, t0):
    """Decisions (cooldown applied) of [T0 - 7 d ; T0); data >= T0 refused; no outcome."""
    _check_t0(t0)
    start, per_pool = t0 - R.COUNT_DAYS * R.DAY_S, {}
    for line in lines:
        if line.pool in per_pool:
            raise PreregError('pool_given_twice')
        _refuse_after_t0(line, t0)
        per_pool[line.pool] = sum(1 for i in decisions_g32(line) if line.swaps[i].block_time >= start)
    return dict(schema=SCHEMA, hypothesis='G3-2', t0=t0, window=[start, t0], days=R.COUNT_DAYS, per_pool=per_pool,
                triggers=sum(per_pool.values()), outcomes_computed=False)


# -- trials, confirmation ----------------------------------------------------------------------------------------------
def trials(hypothesis, n_before):
    if hypothesis not in HYPOTHESES:
        raise PreregError('unknown_hypothesis')
    if type(n_before) is not int or n_before < TRIALS_BEFORE_GEN3 or n_before + 1 > TRIAL_CAP_GEN3:
        raise PreregError('trial_cap_exceeded_or_not_authorised')
    return dict(hypothesis=hypothesis, n_before=n_before, n_after=n_before + 1, cap=TRIAL_CAP_GEN3,
                rule='one trial per hypothesis, counted at the START of the collection of its window (certificate '
                     'd34c2c4e); cap 175 only under a NEW owner tranche distinct from text D, with its own credits')


def confirmation_n(sigma_pilot, kept=2):
    """n_c with sigma_c = max(sigma of the pilot, 2.5 %), Holm first step alpha_3 / K (K = number of kept hypotheses)."""
    if kept not in (1, 2):
        raise PreregError('kept_hypotheses_must_be_1_or_2')
    if type(sigma_pilot) not in (int, float) or not sigma_pilot >= 0 or math.isinf(sigma_pilot):
        raise PreregError('invalid_sigma')
    sigma_c = max(float(sigma_pilot), R.SIGMA_FLOOR)
    alpha = ALPHA_GENERATION / kept
    return dict(kept=kept, sigma_c=sigma_c, alpha_first_step=alpha, n=R.n_required(sigma=sigma_c, alpha=alpha),
                valid_under='option (i) of text D only (R02 a3f194dc); recomputed under option (ii)')


def holm(p_values):
    """Holm step-down at alpha_3 over ALL the kept hypotheses ({name: p}); no p (INCONCLUSIF) counts as p = 1."""
    full = {name: (1.0 if p is None else p) for name, p in p_values.items()}
    k, out = len(full), {name: False for name in full}
    for rank, (p, name) in enumerate(sorted((p, name) for name, p in full.items())):
        if p > ALPHA_GENERATION / (k - rank):
            break
        out[name] = True
    return out


# same exits, costs, positions, power stop and pilot verdict as R-CP1; G3-2 placebo = R-CP1's construction
positions, placebo_g32, power_stop, expected_entries = R.positions, R.placebo, R.power_stop, R.expected_entries
pilot_verdict = CC.pilot_verdict
