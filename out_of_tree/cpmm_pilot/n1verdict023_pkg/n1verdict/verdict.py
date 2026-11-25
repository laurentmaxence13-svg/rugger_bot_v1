"""n1verdict 0.2.3 -- PROJECT (R02 12:42:09Z: prepared, NOT anchored until the owner text cda64700 and R02 check).
0.2.1 + two rules, both inactive when nothing is truncated or excluded (then the report is identical, SCHEMA kept):
  UNDECODED (R02): a position whose entry state or exit state is separated from its landing by a transaction that is
    still undecoded after cpmmrecon is unpriced, counted as the total loss (reasons undecoded_transaction_at_entry /
    _at_exit). Entry: an undecoded (slot, transactionIndex) strictly after the last swap executed at T0 (the decision
    state) and strictly before the first swap after the entry landing; exit: strictly after the last swap executed at
    the exit landing - 1 s and before the first swap after the exit landing (none: up to the end of the pages).
  G-0 EXCLUSION (cda64700 point (3): « the G-0 of N1 is the same as that of G2-3, applied to its three pools »; R02
    13:03Z, option (a), as b1a0d629): a named pool that pool_gate does not admit is excluded and published with its
    reasons; the floors then judge (2 pools: INCONCLUSIF, never STOP nor an error).
Below: the docstring of 0.2.1, unchanged.

n1verdict 0.2.1 -- verdict of the N1 pilot (trial 170) in the R04-6 design (24/11 21:27Z; R02 opinion anchored:
receivable under C1 and C2): ONE notional liquidity-provider position per pool of 0.5 % of the WSOL reserve read at
the opening (decision state at T0), opened at the start of day 0 and withdrawn at the end of day D-1 of the G2-3
window (lpcost.continuous_position). lpcost 0.2, cpmmcost, cpmmx and g23five 0.2 are imported UNCHANGED.

THE WORD (C1): the GAP TO HOLDING net of ALL costs. Pool-day k of pool p = mark change of the gap over day k minus the
position's costs / D (C2), in units of the pool's stake. The ABSOLUTE net in SOL is published, DESCRIPTIVE.
Declared scope: a NECESSARY condition only (the LP side beats holding the same tokens, net of costs), not an absolute
return; notional size; no capital.
UNPRICED POSITION (closed list of causes, as 0.1, R02 (a)): its D pool-days are counted as the total loss of the
stake and of the transactions (and of the rents when lost): each day -(1 + (transactions + rent) / stake) / D, the
stake being 0.5 % of the SOL reserve logged before the pool's last swap before T0. TO BE CONFIRMED BY R02 for R04-6.
Any other error stops the verdict. A guard refusal opens no position: its D days are published, not entries.
INFERENCE (g23five 0.2): block bootstrap of 2 CONSECUTIVE days per pool (block_days = 2), stratified by pool, 10 000
draws, seed int(sha of the N1 sheet[:8], 16); floors (>= 30 pool-days entered, >= 3 pools, Kish >= 2.5, no pool
> 50 %) else INCONCLUSIF before NO-GO; NO-GO if the upper one-sided 95 % bound < 0; GO_PILOTE only if the lower bound
> 0 on all the pools AND without the pool that CARRIES the result; otherwise INCONCLUSIF. G-0 not passed -> STOP.
0.2.1 (R02 reserve K-1): every pool has the same D pool-days, so "the pool with the most entries" would be a tie
broken by id (arbitrary); the guard removes instead the pool with the LARGEST SUM OF GAPS over its pool-days (ties by
id) -- the one that carries the result.
Multiplicity: alpha 0.05 one-sided per hypothesis at the pilot ("2 hypotheses on the same window"); Holm at the
confirmation.
"""
from fractions import Fraction

from cpmmcost import model as CC
from cpmmx import timeline as TL
from g23five import verdict as V
from lpcost import continuous as K, model as LP

SCHEMA = 'n1verdict-v0.2.1'                      # kept: identical report without truncation or exclusion
DAY_S = 86_400
BLOCK_DAYS = 2
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
    L2='nos propres échanges et dépôts ne sont pas rejoués dans les états suivants (part de 0,5 % de la réserve, '
       'couverte par les pires états à l\'entrée et à la sortie)',
    L3='le mot porte sur l\'écart à la détention net de tous les coûts : condition nécessaire, pas un rendement '
       'absolu ; le net absolu en SOL, qui inclut l\'exposition au prix, est descriptif',
)
SCOPE = ('taille notionnelle de 0,5 % de la réserve WSOL, aucun capital engagé ; une seule position par pool sur la '
         'fenêtre ; condition nécessaire (le côté LP bat la détention des mêmes jetons, coûts compris), jamais un '
         'rendement absolu')
MEANING = ('GO_PILOTE autorise seulement à PROPOSER une confirmation sur les MÊMES pools dans une fenêtre NOUVELLE ; il '
           'ne qualifie jamais la position LP au-delà de ces pools, de cette fenêtre et de cette configuration')
SENSITIVITIES = dict(one_failure_per_tx=dict(failures=CC.SENSITIVITY_FAILURES),
                     guard_50000=dict(buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM),
                     rent_lost=dict(failures=CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)))


class N1Error(ValueError):
    pass


class _Undecoded(Exception):
    pass


def _unpriced(err):
    return any(isinstance(err, kind) and str(err) == reason for kind, reason in UNPRICED)


def unpriced_stake(line, t0):
    """0.5 % of the SOL reserve logged before the pool's last swap before T0 (the stake when the position is unpriced)."""
    before = [s for s in line.swaps if s.block_time < t0]
    if not before:
        raise N1Error('pre_t0_state_missing')
    return before[-1].quote_before * K.STAKE_PPM // 1_000_000


def total_loss_per_day(stake, d_days, failures=CC.FROZEN_FAILURES):
    tx, rent = LP.transactions(failures)
    return -(Fraction(1) + Fraction(tx + rent, stake)) / d_days


def _span_hit(line, undecoded, low_time, landing):
    """An undecoded (slot, index) strictly after the last swap executed at low_time and strictly before the first swap
    after landing (no such swap: any later one)."""
    done = TL.executed(line, time_limit=low_time)
    low = done[-1].key[:2] if done else (-1, -1)
    after = [s for s in line.swaps if s.block_time > landing]
    high = after[0].key[:2] if after else None
    return any(low < u and (high is None or u < high) for u in undecoded)


def undecoded_reason(line, undecoded, *, t0, d_days, latency_slots=CC.LATENCY_SLOTS):
    """None, or the reason why an undecoded transaction separates the entry or the exit state from its landing."""
    if not undecoded:
        return None
    if _span_hit(line, undecoded, t0, LP.landing_time(t0, latency_slots)):
        return 'undecoded_transaction_at_entry'
    land_out = LP.landing_time(t0 + d_days * DAY_S, latency_slots)
    if _span_hit(line, undecoded, land_out - 1, land_out):
        return 'undecoded_transaction_at_exit'
    return None


def pool_days(line, config, *, t0, d_days, failures=CC.FROZEN_FAILURES, buy_guard_ppm=CC.BUY_GUARD_PPM,
              undecoded=()):
    """The D pool-days of the pool's single position; the line must hold the pool's state BEFORE T0.
    undecoded: (slot, transactionIndex) of the pool's transactions still undecoded after cpmmrecon (0.2.3)."""
    stake0 = unpriced_stake(line, t0)
    try:
        why = undecoded_reason(line, undecoded, t0=t0, d_days=d_days)
        if why is not None:
            raise _Undecoded(why)
        pos = K.continuous_position(line, config, start_time=t0, end_time=t0 + d_days * DAY_S, failures=failures,
                                    buy_guard_ppm=buy_guard_ppm)
    except (CC.CostError, LP.LpCostError, TL.TimelineError, _Undecoded) as err:
        if not (isinstance(err, _Undecoded) or _unpriced(err)):
            raise
        value = total_loss_per_day(stake0, d_days, failures)
        return [dict(pool=line.pool, day=k, decision_time=t0 + k * DAY_S, status='unpriced_total_loss', entered=True,
                     unpriced=str(err), net_return=float(value), stake_lamports=stake0) for k in range(d_days)], None
    rows = []
    for d in pos['days']:
        rows.append(dict(pool=line.pool, day=d['day'], decision_time=t0 + d['day'] * DAY_S, status=pos['status'],
                         entered=pos['entered'], net_return=float(d['gap_lamports'] / pos['stake_lamports']),
                         stake_lamports=pos['stake_lamports']))
    return rows, pos


def positions(lines, config, *, pools, t0, d_days, undecoded=None, **kw):
    if [line.pool for line in lines] != list(pools):
        raise N1Error('lines_must_be_the_named_pools_in_the_sheet_order')
    rows, whole = [], {}
    for line in lines:
        mine, pos = pool_days(line, config, t0=t0, d_days=d_days, undecoded=(undecoded or {}).get(line.pool, ()), **kw)
        rows += mine
        whole[line.pool] = pos
    return rows, whole


def top_gap_pool(rows):
    """K-1: the pool with the largest sum of gaps over its pool-days; ties by pool id."""
    sums = {}
    for r in rows:
        sums[r['pool']] = sums.get(r['pool'], 0) + r['net_return']
    return sorted(sums, key=lambda p: (-sums[p], p))[0] if sums else None


def word(rows, *, t0, d_days, seed, draws):
    fl = V.floors(rows, t0, d_days)
    low, high = V.stratified_bounds(V.blocks(rows, t0, d_days, BLOCK_DAYS), seed=seed, draws=draws)
    top = top_gap_pool(rows)
    low_wo, high_wo = V.stratified_bounds(V.blocks([r for r in rows if r['pool'] != top], t0, d_days, BLOCK_DAYS),
                                          seed=seed, draws=draws)
    if not fl['passed']:
        decision = 'INCONCLUSIF'
    elif high is not None and high < 0:
        decision = 'NO-GO'
    elif low is not None and low > 0 and low_wo is not None and low_wo > 0:
        decision = 'GO_PILOTE'
    else:
        decision = 'INCONCLUSIF'
    return dict(decision=decision, floors=fl, lower_bound_95=low, upper_bound_95=high,
                without_top_pool=dict(pool=top, rule='plus grande somme d\'écarts (K-1)', lower_bound_95=low_wo,
                                      upper_bound_95=high_wo))


def _descriptive(pos):
    if pos is None or pos['status'] != 'entered':
        return dict(status=pos['status'] if pos else 'unpriced_total_loss', net_return_absolute=NM, gap_return=NM)
    stake, d = pos['stake_lamports'], pos['decomposition_lamports']
    return dict(status='entered', stake_lamports=stake, net_return_absolute=float(Fraction(pos['net_lamports'], 1) / stake),
                gap_return=float(pos['gap_lamports'] / stake), hold_price_move_return=float(d['hold_price_move'] / stake),
                mark_change_return=float(d['mark_change'] / stake),
                costs_return=float(-(d['entry'] + d['exit'] + d['transactions'] + d['rent_lost']) / stake),
                fees_earned_estimate_lamports=pos['fees_earned_estimate'], verdict=None)


def report(lines, config, *, pools, g0_passed, freeze_sheet_sha256, t0, d_days, draws=V.DRAWS, undecoded=None,
           excluded=None):
    """0.2.3: undecoded = {pool: [(slot, index)]} still undecoded after cpmmrecon; excluded = {pool: G-0 reasons} of
    the named pools that pool_gate did not admit (their lines are absent, the others keep the sheet order)."""
    V._check_sheet(freeze_sheet_sha256)
    if type(d_days) is not int or not V.MIN_D <= d_days <= V.MAX_D or d_days % BLOCK_DAYS:
        raise N1Error('d_days_outside_7_30_or_odd')
    if type(t0) is not int:
        raise N1Error('t0_must_be_an_integer_block_time')
    if len(pools) < V.MIN_SELECTED or len(set(pools)) != len(pools):
        raise N1Error('at_least_3_distinct_named_pools')
    doc = dict(schema=SCHEMA, estimand='N1 (R04-6) : écart à la détention net de tous les coûts, pools nommés seulement',
               pools=list(pools), t0=t0, d_days=d_days, block_days=BLOCK_DAYS, stake_ppm=K.STAKE_PPM,
               labels=list(LP.LABELS), counts_for_operational_master=False, meaning=MEANING, scope=SCOPE,
               limits=dict(LIMITS), multiplicity='alpha 0,05 unilatéral par hypothèse au pilote (2 hypothèses sur la '
               'même fenêtre : G2-3 et N1, corrélées) ; Holm en confirmation')
    if g0_passed is not True:
        return V.G1.check_vocabulary(dict(doc, decision='STOP', reason='g0_decoder_not_passed', published_numbers=False))
    seed = int(freeze_sheet_sha256[:8], 16)
    excluded = dict(excluded or {})
    if set(excluded) - set(pools):
        raise N1Error('excluded_pool_not_named')
    kept = [p for p in pools if p not in excluded]
    rows, whole = positions(lines, config, pools=kept, t0=t0, d_days=d_days, undecoded=undecoded)
    main = word(rows, t0=t0, d_days=d_days, seed=seed, draws=draws)
    entered = V.entries(rows)
    per_pool = {p: dict(_descriptive(whole[p]), pool_days=len([r for r in rows if r['pool'] == p]),
                        entries=len(V.entries([r for r in rows if r['pool'] == p])),
                        mean_gap_return=V._mean([r for r in rows if r['pool'] == p])) for p in kept}
    for p in excluded:
        per_pool[p] = dict(status='excluded_by_g0', g0_reasons=list(excluded[p]), pool_days=0, entries=0)
    sens = {}
    for name, kw in SENSITIVITIES.items():
        alt, _w = positions(lines, config, pools=kept, t0=t0, d_days=d_days, undecoded=undecoded, **kw)
        low, high = V.stratified_bounds(V.blocks(alt, t0, d_days, BLOCK_DAYS), seed=seed, draws=draws)
        sens[name] = dict(mean_gap_return=V._mean(alt), lower_bound_95=low, upper_bound_95=high, verdict=None)
    target = V.R.n_required()
    doc.update(main, published_numbers=True, n=len(rows), n_entered=len(entered), mean_gap_return=V._mean(rows),
               per_pool=per_pool, seed=seed, draws=draws,
               unpriced=dict(pools=sorted(p for p in kept if whole[p] is None),
                             reasons=sorted({r['unpriced'] for r in rows if r['status'] == 'unpriced_total_loss'})),
               sensitivities=sens,
               power=dict(n_entered=len(entered), n_required=target,
                          flag=V.G1.UNDER_TARGET if len(entered) < target else None))
    if excluded:
        doc['g0_excluded'] = {p: list(excluded[p]) for p in pools if p in excluded}
    return V.G1.check_vocabulary(doc)
