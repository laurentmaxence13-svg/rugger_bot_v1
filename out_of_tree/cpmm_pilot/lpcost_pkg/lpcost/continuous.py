"""lpcost 0.2 -- ONE continuous liquidity-provider position held over several days, valued day by day (decision R04-6,
24/11 21:27Z, R02 opinion anchored: receivable under C1 and C2). model.py (0.1, PASS TECHNIQUE R02) is unchanged and
reused (transactions, share_after_others, landing, worse states).

POSITION: notional stake = stake_ppm x the WSOL reserve of the DECISION state at start_time (frozen 5 000 ppm = 0.5 %;
no capital). Half of it (stake // 2) buys the base token on the worse landing state with the cpmmcost buy guard; the
deposit is proportional (amounts rounded up); the position is withdrawn once at end_time (rounded down, worse exit
state) and every base token held is sold on the worst of the 4 exit candidates, as model.lp_position.

THE WORD'S QUANTITY (C1): the GAP TO HOLDING the deposited amounts, net of ALL costs:
    G(t)  = V_LP(t) - V_HOLD(t) at the pool's observed spot: V_LP = 2 s(t) Q(t), V_HOLD = dep_base x Q/B + dep_quote,
            s(t) our pool fraction after the LP events of others; (B, Q) the LP-owned reserves of the marking state.
    gap   = G(end) - G(start) - costs ;  costs = entry swap (half - tokens x P_start: fee, impact, latency, worse state)
            + exit (marked LP holdings + left-overs - SOL received: withdrawal rounding, sale fee and impact)
            + transactions (6 x 105 000 at the frozen failures) + rents lost.
MARKS: start = the landing state of the deposit; end = the worse exit state; at each day boundary t_k (k = 1 .. n-1)
    the first state OBSERVED after t_k: the reserves logged before the first swap with block_time > t_k, with our
    fraction after the LP events strictly before that swap (exact; never bridges an LP event); the exit state if no
    swap follows before the exit landing.
DAILY VALUES (C2): day k = G(t_{k+1}) - G(t_k) - costs / n ; their sum is the gap exactly (Fractions).
EXACT IDENTITY (descriptive): net_abs = SOL received - stake - transactions - rents
                                      = gap + G(start) + tokens x (P_end - P_start)   (residual 0).
Labels: research only; never an operational Master trade, never counted for 50 / 20.
"""
from fractions import Fraction

from cpmmcost import model as CC
from cpmmx import curve
from lpcost import model as M

SCHEMA = 'lpcost-v0.2-continuous'
DAY_S = 86_400
STAKE_PPM = 5_000                                   # 0.5 % of the WSOL reserve read at the opening (R04-6)
MAX_STAKE_PPM = 5_000


def _mark(line, fees, share0, low_key, t, exit_state, exit_share, land_out):
    """(share, base, quote) of the first observed state after t (see MARKS)."""
    nxt = next((s for s in line.swaps if t < s.block_time <= land_out), None)
    if nxt is None:
        return exit_share, exit_state[0], exit_state[1]
    below = (nxt.slot, nxt.tx_index, nxt.order - Fraction(1, 2))            # every LP event strictly before nxt
    return M.share_after_others(line, share0, low_key, below), nxt.base_before, nxt.quote_before


def _gap(share, base, quote, dep_b, dep_q):
    return 2 * share * quote - Fraction(dep_b * quote, base) - dep_q


def continuous_position(line, config, *, start_time, end_time, stake_ppm=STAKE_PPM, failures=CC.FROZEN_FAILURES,
                        buy_guard_ppm=CC.BUY_GUARD_PPM, latency_slots=CC.LATENCY_SLOTS):
    if type(start_time) is not int or type(end_time) is not int or end_time <= start_time \
            or (end_time - start_time) % DAY_S:
        raise M.LpCostError('period_must_be_whole_days')
    if type(stake_ppm) is not int or not 0 < stake_ppm <= MAX_STAKE_PPM:
        raise M.LpCostError('stake_above_0_5_percent_of_the_reserve')
    if buy_guard_ppm not in CC.ALLOWED_BUY_GUARDS:
        raise M.LpCostError('buy_guard_not_a_declared_threshold')
    fees = CC.fees_from_amm_config(config)
    CC.frozen_check()
    if not line.swaps:
        raise M.LpCostError('no_swap_in_the_pool')
    n_days = (end_time - start_time) // DAY_S
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    land_in, land_out = M.landing_time(start_time, latency_slots), M.landing_time(end_time, latency_slots)
    tx_cost, rent_lost = M.transactions(failures)
    db, dq = CC._state(line, fees, time_limit=start_time)                     # decision state: the stake is read here
    stake = dq * stake_ppm // 1_000_000
    half = stake // 2
    keep = stake - half
    common = dict(pool=line.pool, start_time=start_time, end_time=end_time, n_days=n_days, stake_ppm=stake_ppm,
                  stake_lamports=stake, labels=list(M.LABELS), counts_for_operational_master=False,
                  failures=dict(buy=failures.buy, sell=failures.sell, cleanup=failures.cleanup))
    # 1. entry swap on the worse landing state, with the buy guard against the decision-state output
    buys = [(curve.swap_base_input(half, s[1], s[0], fees, on_input), s) for s in M._states(line, fees, land_in)]
    bought, (b0, q0) = min(buys, key=lambda pair: pair[0].output_amount)
    tokens = bought.output_amount
    if buy_guard_ppm is not None:
        expected = curve.swap_base_input(half, dq, db, fees, on_input).output_amount
        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:
            charged = (1 + failures.buy) * M.TX
            return dict(common, status='guard_failed', entered=False, net_lamports=-charged, gap_lamports=-charged,
                        days=[dict(day=k, gap_lamports=Fraction(-charged, n_days)) for k in range(n_days)],
                        guard_ppm=buy_guard_ppm, expected_tokens=expected, fill_tokens=tokens)
    # 2. proportional deposit, amounts rounded up
    share0 = min(Fraction(tokens, b0), Fraction(keep, q0))
    dep_b, dep_q = min(M._ceil(share0 * b0), tokens), min(M._ceil(share0 * q0), keep)
    left_b, left_q = tokens - dep_b, keep - dep_q
    p_start = Fraction(q0, b0)
    entry_cost = half - tokens * p_start
    # 3. exit: our fraction after others, withdrawal rounded down on the worse exit state, sale of every base token
    low_key = M._last_key(line, land_in)
    share_end = M.share_after_others(line, share0, low_key, M._last_key(line, land_out))
    exits = M._states(line, fees, land_out)
    b1, q1 = min(exits, key=lambda s: Fraction(s[1], s[0]))
    wd_b, wd_q = M._floor(share_end * b1), M._floor(share_end * q1)
    amount = wd_b + left_b
    candidates = []
    for b, q in exits:
        for bb, qq in ((b, q), (b - wd_b, q - wd_q)):
            if bb <= 0 or qq <= 0:
                raise M.LpCostError('exit_state_empty')
            candidates.append(curve.swap_base_input(amount, bb, qq, fees, on_input).output_amount if amount else 0)
    received = wd_q + left_q + min(candidates)
    p_end = Fraction(q1, b1)
    exit_cost = 2 * share_end * q1 + left_b * p_end + left_q - received
    costs = entry_cost + exit_cost + tx_cost + rent_lost
    # 4. marks and daily values
    marks = [_gap(share0, b0, q0, dep_b, dep_q)]
    for k in range(1, n_days):
        s, b, q = _mark(line, fees, share0, low_key, start_time + k * DAY_S, (b1, q1), share_end, land_out)
        marks.append(_gap(s, b, q, dep_b, dep_q))
    marks.append(_gap(share_end, b1, q1, dep_b, dep_q))
    days = [dict(day=k, day_start=start_time + k * DAY_S, day_end=start_time + (k + 1) * DAY_S,
                 mark_change_lamports=marks[k + 1] - marks[k], cost_share_lamports=-costs / n_days,
                 gap_lamports=marks[k + 1] - marks[k] - costs / n_days) for k in range(n_days)]
    gap = marks[-1] - marks[0] - costs
    if sum(d['gap_lamports'] for d in days) != gap:
        raise M.LpCostError('daily_values_do_not_sum_to_the_gap')
    net_abs = received - stake - tx_cost - rent_lost
    hold_move = tokens * (p_end - p_start)
    if net_abs != gap + marks[0] + hold_move:
        raise M.LpCostError('identity_residual')
    fees_est = M.fees_earned_estimate(line, fees, share_at_entry=Fraction(dep_q, q0), land_in=land_in,
                                      land_out=land_out)
    return dict(common, status='entered', entered=True, tokens_bought=tokens, deposited=dict(base=dep_b, quote=dep_q),
                left=dict(base=left_b, quote=left_q), withdrawn=dict(base=wd_b, quote=wd_q), received=received,
                share_at_entry=float(share0), share_at_exit=float(share_end), days=days, gap_lamports=gap,
                net_lamports=net_abs,
                decomposition_lamports=dict(mark_change=marks[-1] - marks[0], entry=-entry_cost, exit=-exit_cost,
                                            transactions=-tx_cost, rent_lost=-rent_lost, deposit_rounding=marks[0],
                                            hold_price_move=hold_move),
                fees_earned_estimate=float(fees_est), amm_config_sha256=config['sha256'])
