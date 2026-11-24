"""n1verdict 0.1 -- verdict of the N1 pilot (trial 170): one liquidity-provider position of 0.1 SOL per pool and per
day on the 4 pools named by G2-3, over the G2-3 window and pages (R02: N1 RECEVABLE, notes 0b64abd6 and 2f2e0707;
lpcost 0.1 PASS TECHNIQUE; g23five 0.1.1 PASS). lpcost, cpmmcost, cpmmx and g23five are imported UNCHANGED.

POOL-DAYS (aligned on T0): day k = 0 .. D-1 starts at T0 + k x 86 400 s and ends at T0 + (k + 1) x 86 400 s; the
position is lpcost.lp_position(start_time, end_time) (clock landing after the frozen latency, worse states).
UNPRICED POOL-DAY (R02 (4)): when the pool's own data cannot price it (an LP event of others at a landing point, an
emptied exit state, an LP event on an empty vault, an unknown LP change, no pool state at the landing point), it is
PUBLISHED and counted as the TOTAL LOSS of the stake and of the round trip's transactions (and of the rents when the
cleanup failures lose them): -(STAKE + transactions + rent lost); with the frozen failures -100 630 000 lamports.
Any other error stops the verdict (it is a code or input defect, not a market outcome).
THE WORD (the G2-3 rules, g23five functions): G-0 not passed -> STOP; floors (>= 30 pool-days entered, >= 3 pools,
Kish >= 2.5, no pool > 50 %) else INCONCLUSIF; NO-GO if the upper one-sided 95 % bound < 0; GO_PILOTE only if the lower
bound > 0 on all the pools AND without the pool with the most entries; otherwise INCONCLUSIF. Bootstrap by pool-day
blocks stratified by pool (g23five.stratified_bounds), 10 000 draws, seed int(sha of the N1 sheet[:8], 16).
The criterion is the NET in SOL, price exposure included (R02 L3). hold_pnl and lp_vs_hold, the fee and inventory
estimates and the sensitivities are DESCRIPTIVE. Multiplicity: alpha 0.05 one-sided per hypothesis at the pilot (G2-3
and N1 are two hypotheses on the same window, correlated); Holm at the confirmation.
"""
from cpmmcost import model as CC
from cpmmx import timeline as TL
from g23five import verdict as V
from lpcost import model as LP

SCHEMA = 'n1verdict-v0.1'
DAY_S = 86_400
NM = 'NON MESURÉ'
UNPRICED = (
    (CC.CostError, 'lp_change_at_the_landing_point'),
    (LP.LpCostError, 'exit_state_empty'),
    (LP.LpCostError, 'pool_emptied_by_a_withdrawal'),
    (LP.LpCostError, 'lp_event_on_an_empty_vault'),
    (LP.LpCostError, 'unknown_lp_change_type'),
    (TL.TimelineError, 'no_pool_state_at_the_landing_point'),
)
LIMITS = dict(
    L1='la fraction f d\'un événement LP d\'autrui = montant / coffre BRUT (frais protocole et fonds inclus), alors que '
       'la part se calcule sur les réserves LP : léger biais',
    L2='nos propres échanges et dépôts ne sont pas rejoués dans les états suivants (part minime, couverte par les pires '
       'états)',
    L3='le net inclut l\'exposition au prix (hold_pnl) : c\'est le résultat en SOL, seul critère ; lp_vs_hold est '
       'descriptif',
)
MEANING = ('GO_PILOTE autorise seulement à PROPOSER une confirmation sur les MÊMES pools dans une fenêtre NOUVELLE ; il '
           'ne qualifie jamais la position LP au-delà de ces pools, de cette fenêtre et du protocole quotidien')
SENSITIVITIES = dict(one_failure_per_tx=dict(failures=CC.SENSITIVITY_FAILURES),
                     guard_50000=dict(buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM),
                     rent_lost=dict(failures=CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)))


class N1Error(ValueError):
    pass


def _unpriced(err):
    return any(isinstance(err, kind) and str(err) == reason for kind, reason in UNPRICED)


def total_loss_lamports(failures=CC.FROZEN_FAILURES):
    tx, rent = LP.transactions(failures)
    return -(LP.STAKE + tx + rent)


def pool_days(line, config, *, t0, d_days, failures=CC.FROZEN_FAILURES, buy_guard_ppm=CC.BUY_GUARD_PPM):
    """The D positions of one pool; the line must hold the pool's state BEFORE T0 (pre-T0 pages + window pages)."""
    if not any(s.block_time < t0 for s in line.swaps):
        raise N1Error('pre_t0_state_missing')
    rows = []
    for k in range(d_days):
        start, end = t0 + k * DAY_S, t0 + (k + 1) * DAY_S
        try:
            row = LP.lp_position(line, config, start_time=start, end_time=end, failures=failures,
                                 buy_guard_ppm=buy_guard_ppm)
        except (CC.CostError, LP.LpCostError, TL.TimelineError) as err:
            if not _unpriced(err):
                raise
            net = total_loss_lamports(failures)
            row = dict(pool=line.pool, start_time=start, end_time=end, status='unpriced_total_loss', entered=True,
                       unpriced=str(err), net_lamports=net, net_return=net / LP.STAKE, labels=list(LP.LABELS),
                       counts_for_operational_master=False)
        rows.append(dict(row, decision_time=start, day=k))
    return rows


def positions(lines, config, *, pools, t0, d_days, **kw):
    if [line.pool for line in lines] != list(pools):
        raise N1Error('lines_must_be_the_named_pools_in_the_sheet_order')
    return [r for line in lines for r in pool_days(line, config, t0=t0, d_days=d_days, **kw)]


def _bounds(rows, field, t0, d_days, seed, draws):
    """Descriptive bounds of a decomposition field (priced entered rows only), same stratified bootstrap."""
    use = [dict(r, net_return=r['decomposition_lamports'][field] / LP.STAKE) for r in rows
           if r['status'] == 'entered']
    if not use:
        return dict(mean=NM, lower_bound_95=NM, upper_bound_95=NM, n=0)
    low, high = V.stratified_bounds(V.blocks(use, t0, d_days), seed=seed, draws=draws)
    return dict(mean=sum(r['net_return'] for r in use) / len(use), lower_bound_95=low, upper_bound_95=high, n=len(use))


def word(rows, *, t0, d_days, seed, draws):
    fl = V.floors(rows, t0, d_days)
    low, high = V.stratified_bounds(V.blocks(rows, t0, d_days), seed=seed, draws=draws)
    top = V.top_pool(rows)
    low_wo, high_wo = V.stratified_bounds(V.blocks([r for r in rows if r['pool'] != top], t0, d_days), seed=seed,
                                          draws=draws)
    if not fl['passed']:
        decision = 'INCONCLUSIF'
    elif high is not None and high < 0:
        decision = 'NO-GO'
    elif low is not None and low > 0 and low_wo is not None and low_wo > 0:
        decision = 'GO_PILOTE'
    else:
        decision = 'INCONCLUSIF'
    return dict(decision=decision, floors=fl, lower_bound_95=low, upper_bound_95=high,
                without_top_pool=dict(pool=top, lower_bound_95=low_wo, upper_bound_95=high_wo))


def report(lines, config, *, pools, g0_passed, freeze_sheet_sha256, t0, d_days, draws=V.DRAWS):
    V._check_sheet(freeze_sheet_sha256)
    if type(d_days) is not int or not V.MIN_D <= d_days <= V.MAX_D:
        raise N1Error('d_days_outside_7_30')
    if type(t0) is not int:
        raise N1Error('t0_must_be_an_integer_block_time')
    if len(pools) < V.MIN_SELECTED or len(set(pools)) != len(pools):
        raise N1Error('at_least_3_distinct_named_pools')
    doc = dict(schema=SCHEMA, estimand='N1 : position LP quotidienne de 0,1 SOL sur les pools nommés seulement',
               pools=list(pools), t0=t0, d_days=d_days, labels=list(LP.LABELS), counts_for_operational_master=False,
               meaning=MEANING, limits=dict(LIMITS), multiplicity='alpha 0,05 unilatéral par hypothèse au pilote '
               '(G2-3 et N1 : 2 hypothèses sur la même fenêtre, corrélées) ; Holm en confirmation')
    if g0_passed is not True:
        return V.G1.check_vocabulary(dict(doc, decision='STOP', reason='g0_decoder_not_passed', published_numbers=False))
    seed = int(freeze_sheet_sha256[:8], 16)
    rows = positions(lines, config, pools=pools, t0=t0, d_days=d_days)
    main = word(rows, t0=t0, d_days=d_days, seed=seed, draws=draws)
    entered = V.entries(rows)
    per_pool = {}
    for p in pools:
        mine = [r for r in rows if r['pool'] == p]
        per_pool[p] = dict(positions=len(mine), entries=len(V.entries(mine)),
                           unpriced_total_loss=sum(r['status'] == 'unpriced_total_loss' for r in mine),
                           guard_failed=sum(r['status'] == 'guard_failed' for r in mine),
                           mean_net_return=V._mean(mine) if mine else NM)
    priced = [r for r in rows if r['status'] == 'entered']
    sens = {}
    for name, kw in SENSITIVITIES.items():
        alt = positions(lines, config, pools=pools, t0=t0, d_days=d_days, **kw)
        low, high = V.stratified_bounds(V.blocks(alt, t0, d_days), seed=seed, draws=draws)
        sens[name] = dict(mean_net_return=V._mean(alt), lower_bound_95=low, upper_bound_95=high, verdict=None)
    target = V.R.n_required()
    doc.update(main, published_numbers=True, n=len(rows), n_entered=len(entered), mean_net_return=V._mean(rows),
               per_pool=per_pool, seed=seed, draws=draws,
               unpriced=dict(count=sum(r['status'] == 'unpriced_total_loss' for r in rows),
                             value_lamports=total_loss_lamports(),
                             reasons=sorted({r['unpriced'] for r in rows if r['status'] == 'unpriced_total_loss'})),
               descriptive=dict(hold_pnl=_bounds(rows, 'hold_pnl', t0, d_days, seed, draws),
                                lp_vs_hold=_bounds(rows, 'lp_vs_hold', t0, d_days, seed, draws),
                                fees_earned_estimate_lamports=(sum(r['fees_earned_estimate'] for r in priced)
                                                               / len(priced)) if priced else NM,
                                inventory_loss_estimate_lamports=(sum(r['inventory_loss_estimate'] for r in priced)
                                                                  / len(priced)) if priced else NM,
                                verdict=None),
               sensitivities=sens,
               power=dict(n_entered=len(entered), n_required=target,
                          flag=V.G1.UNDER_TARGET if len(entered) < target else None))
    return V.G1.check_vocabulary(doc)
