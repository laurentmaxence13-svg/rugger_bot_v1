"""g1ind 0.4 -- DESCRIPTIVE report of the CPMM pilot (R-CP1 or B1) around the FROZEN G-1 function (T-R01-4, R04
decision of 23/11 21:30Z; note g1verif 071bb01). R03 calls it from cpmmpilot 0.1.1; nothing here is a verdict.

(1) G-1 = cpmmcost.model.pilot_verdict, called ONCE, unchanged, on every primary row (zero-sale rows of the runner included, K01); only its English
    ``meaning`` field is replaced by the sentence of the sheet (K02 option a, R02 decision f41c6cb0).
(2) K01, R02 decisions f41c6cb0, 34309238 and 21:44Z: an ENTERED position that cannot be priced is COUNTED at a zero
    sale in the CLOSED-account mode of cpmmcost 0.3 (C-a, the frozen CPMM model; closedacct is LaunchLab / W2):
    r = -(STAKE + (4 + failures of the run) x 105 000) / STAKE (buy, sale, WSOL close, cleanup; no rent lost), i.e.
    -100 420 000 lamports at the primary and -100 735 000 under Failures(1, 1, 1). The rows come from the runner
    (cpmmpilot.step1.zero_sale, status 'unpriced_zero_sale'); g1ind CHECKS their value exactly against this rule
    (cpmmcost constants), counts them everywhere (mean, bound, floors, metrics, placebo, sensitivities) and publishes
    their count and reasons. A RAW unpriced row (no net_return) or a wrong zero-sale value is an ERROR: never an
    exclusion.
(3) b31a3c47 metrics on the same population as the G-1 mean (every row, guard refusals and zero-sale rows included): win r > 0, loss
    r <= 0, net PF sum(r+) / |sum(r-)|, expectancy identity, drawdown in EXIT order in stakes and in SOL, fees split.
(4) paired gap primary - placebo, pool cluster bootstrap with the seed of the sheet (statistic of
    cpmmprereg.confirmation_verdict c2), one-sided 95 % bounds: DESCRIPTIVE at the pilot (a condition only at the
    confirmation).
(5) the closed robustness list of 7 (b31a3c47), each mean or NON MESURÉ when its input is not supplied.
(6) "sous la cible de puissance" when n_entered < n_required() of cpmmprereg (155).
(7) the closed vocabulary is checked on the whole document.
If G-0 is not passed (G-1 = STOP), NO number at all is published.
"""
from bot.p4 import historical_research_replay as hrr
from closedacct import model as CA
from cpmmcost import model as CC
from cpmmprereg import rule as R
from w2arms import ce as W

SCHEMA = 'g1ind-v0.4'
STAMP = 'DESCRIPTIF — PILOTE CPMM — SEUL LE MOT G-1 DE cpmmcost.pilot_verdict EST UNE DÉCISION'
NM = 'NON MESURÉ'
HYPOTHESES = ('RCP1', 'B1')
FORBIDDEN_WORDS = ('rentable', 'profitable', 'gagnant')       # identical to plbench.FORBIDDEN_WORDS (tested)
SHEET_MEANING = ('GO_PILOTE autorise seulement à PROPOSER la confirmation sur une fenêtre NOUVELLE ; il ne qualifie '
                 'jamais la stratégie au-delà de ce verdict')
ALPHA_DESCRIPTIVE = 0.05
LAMPORTS_PER_SOL = 10 ** 9
UNDER_TARGET = 'sous la cible de puissance'
# the closed robustness list of b31a3c47 (same keys as dashx.ROBUSTNESS); the ones computed from another frozen run of
# cpmmprereg.positions are SUPPLIED by cpmmpilot with the declared parameter checked here row by row
SUPPLIED = dict(
    latency_10_slots=lambda p: p.get('latency_slots') == CC.SENSITIVITY_LATENCY_SLOTS or p.get('unpriced') is not None,
    one_failure_per_tx=lambda p: (p.get('unpriced') is not None                       # K-2: the frozen CODE value
                                  or p['failures'] == dict(buy=CC.SENSITIVITY_FAILURES.buy,
                                                           sell=CC.SENSITIVITY_FAILURES.sell,
                                                           cleanup=CC.SENSITIVITY_FAILURES.cleanup)),
    rent_lost_vs_closed_account=lambda p: (p.get('unpriced') is not None or p.get('status') == 'guard_failed'
                                           or p['failures']['cleanup'] == CA.MAX_CLEANUP_ATTEMPTS),
    guard_5_percent=lambda p: p.get('guard_ppm') == CC.BUY_GUARD_SENSITIVITY_PPM or p.get('unpriced') is not None,
)
COMPUTED = ('without_5_best_pools', 'half_1_half_2')
ZERO_STATUS = 'unpriced_zero_sale'                          # cpmmpilot.step1.zero_sale (R03), the single source
ZERO_RULE = ('K01 (R02 f41c6cb0, 34309238, 21:44Z) : position entrée non valorisable comptée à une vente nulle en compte '
             'fermé cpmmcost 0.3 : -(mise + (4 + échecs de la série) x 105 000) lamports')
# failures of each run (the zero-sale value depends on them; the other runs use the frozen 0 failures)
RUN_FAILURES = dict(primary=CC.FROZEN_FAILURES, placebo=CC.FROZEN_FAILURES, one_failure_per_tx=CC.SENSITIVITY_FAILURES)
# the frozen MEV grid (mevsens) is a LaunchLab sandwich model: no audited CPMM adaptation exists, so it stays NON MESURÉ
# (R02 34309238: confirmed, a declared gap to be filled by an audited CPMM model before any confirmation)
MEV_NOT_MEASURED = dict(value=NM, reason='grille MEV gelée sans adaptation CPMM auditée')
ROBUSTNESS = ('latency_10_slots', 'one_failure_per_tx', 'without_5_best_pools', 'rent_lost_vs_closed_account',
              'guard_5_percent', 'frozen_mev_grid', 'half_1_half_2')


class ReportError(ValueError):
    pass


def _mean(values):
    return sum(values) / len(values) if values else None


def _key(p):
    return p['pool'], p['decision_index']


def check_vocabulary(document):
    import json
    text = json.dumps(document, ensure_ascii=False, default=str).lower()
    found = [w for w in FORBIDDEN_WORDS if w in text]
    if found:
        raise ReportError('forbidden_word_in_output')       # the word itself is never echoed
    return document


# -- (2) K01 -----------------------------------------------------------------------------------------------------------
def zero_sale_lamports(failures=CC.FROZEN_FAILURES):
    """Closed-account zero sale of cpmmcost 0.3: the stake and the 4 transactions (buy, sale, WSOL close, cleanup) plus
    every failed attempt of the run; no rent lost (the cleanup gets it back)."""
    transactions = 3 + (1 if CC.WSOL_SEPARATE_CLOSE else 0) + failures.buy + failures.sell + failures.cleanup
    return -(CC.STAKE_LAMPORTS + transactions * CC.TX_FEE_LAMPORTS)


def counted(rows, run='primary'):
    """Every row counts. A raw unpriced row (no net_return) is refused; a zero-sale row must be an entry whose value is
    exactly the closed-account zero sale under the failures of its run."""
    expected = zero_sale_lamports(RUN_FAILURES.get(run, CC.FROZEN_FAILURES))
    for p in rows:
        if 'net_return' not in p:
            raise ReportError('raw_unpriced_row_needs_the_runner_zero_sale:' + run)
        if p.get('status') == ZERO_STATUS:
            if p.get('entered') is not True:
                raise ReportError('zero_sale_row_must_be_an_entry:' + run)
            if p['net_lamports'] != expected or p['net_return'] != expected / CC.STAKE_LAMPORTS:
                raise ReportError('zero_sale_value_is_not_the_rule:' + run)
    return list(rows)


def zero_sale_reasons(rows):
    out = {}
    for p in rows:
        if p.get('status') == ZERO_STATUS:
            reason = p.get('unpriced_reason', p.get('unpriced', NM))
            out[reason] = out.get(reason, 0) + 1
    return dict(count=sum(out.values()), reasons=out)


# -- (3) b31a3c47 -----------------------------------------------------------------------------------------------------
def exit_time(line, row):
    """Block time of the sale of a priced row, for the EXIT order of the drawdown. Clock exit: the declared time
    (deadline + clock latency, cpmmprereg.exit_point). Slot exit: block time of the swap that fired TP / SL (slot =
    declared - latency) + the same clock latency of the frozen replay (hrr.clock_exit_latency_s). A guard refusal has
    no sale: its time is the decision time (the fee is paid then). A zero-sale row has no known exit: its loss is
    placed at the latest exit the rule allows (decision + 1 800 s clock + clock latency of the primary)."""
    if row.get('status') == 'guard_failed':
        return line.swaps[row['decision_index']].block_time
    if row.get('status') == ZERO_STATUS:
        return row['decision_time'] + R.CLOCK_S + hrr.clock_exit_latency_s(CC.LATENCY_SLOTS)
    ex = row['exit']
    if ex['rule'] == 'clock':
        return ex['declared']
    fired = ex['declared'] - row['latency_slots']
    times = [s.block_time for s in line.swaps if s.slot == fired]
    if not times:
        raise ReportError('exit_swap_not_in_the_timeline')
    return times[0] + hrr.clock_exit_latency_s(row['latency_slots'])


def drawdown(rows, exit_times):
    """Fixed-stake curve in EXIT order (exit time, then decision slot, then pool); largest peak-to-trough fall of the
    cumulative net, in stakes (sum of r_i) and in SOL (net lamports)."""
    stakes = sol = peak_s = peak_l = worst_s = worst_l = 0
    order = sorted(range(len(rows)), key=lambda i: (exit_times[i], rows[i]['decision_slot'], rows[i]['pool']))
    for i in order:
        stakes += rows[i]['net_return']
        sol += rows[i]['net_lamports']
        peak_s, peak_l = max(peak_s, stakes), max(peak_l, sol)
        worst_s, worst_l = max(worst_s, peak_s - stakes), max(worst_l, peak_l - sol)
    return dict(stakes=worst_s, sol=worst_l / LAMPORTS_PER_SOL, order='exit')


def metrics(rows, *, lines=None):
    n = len(rows)
    if not n:
        return dict(population=0)
    nets = [p['net_return'] for p in rows]
    wins = [r for r in nets if r > 0]
    losses = [r for r in nets if r <= 0]                         # r = 0 is a loss (b31a3c47)
    negative = -sum(r for r in nets if r < 0)
    win_rate = len(wins) / n
    mean_win, mean_loss, expectancy = _mean(wins), _mean(losses), _mean(nets)
    identity = win_rate * (mean_win or 0) + (1 - win_rate) * (mean_loss or 0)
    if abs(identity - expectancy) > 1e-12:
        raise ReportError('expectancy_identity_broken')
    entered = [p for p in rows if p.get('status') not in ('guard_failed', ZERO_STATUS)]
    keys = sorted({k for p in entered for k in p.get('decomposition_share_of_stake', {})})
    fees = {k: _mean([p['decomposition_share_of_stake'][k] for p in entered]) for k in keys}
    refused = [p for p in rows if p.get('status') == 'guard_failed']
    fees['guard_refusal_fee_per_position'] = _mean([p['net_return'] for p in refused]) if refused else NM
    fees['zero_sale_positions'] = sum(1 for p in rows if p.get('status') == ZERO_STATUS)
    if lines is None:
        dd = NM
    else:
        by_pool = {line.pool: line for line in lines}
        dd = drawdown(rows, [exit_time(by_pool[p['pool']], p) for p in rows])
    return dict(population=n, win_rate=win_rate, mean_winning_return=mean_win if wins else NM,
                mean_losing_return=mean_loss if losses else NM,
                profit_factor=(sum(wins) / negative) if negative else NM, expectancy=expectancy,
                expectancy_identity_checked=True, max_drawdown=dd, fees_share_of_stake_entered=fees,
                net_sol_total=sum(p['net_lamports'] for p in rows) / LAMPORTS_PER_SOL)


# -- (4) paired gap ----------------------------------------------------------------------------------------------------
def paired_gap(primary, placebo, *, seed, draws):
    """Mean(primary) - mean(placebo) over the pools present in BOTH arms, pool cluster bootstrap (statistic of c2)."""
    pools = {p['pool'] for p in primary} & {p['pool'] for p in placebo}
    rows = ([dict(p, arm='primary') for p in primary if p['pool'] in pools]
            + [dict(p, arm='placebo') for p in placebo if p['pool'] in pools])
    groups = {}
    for r in rows:
        groups.setdefault(r['pool'], []).append(r)

    def diff(rows_):
        a = _mean([r['net_return'] for r in rows_ if r['arm'] == 'primary'])
        b = _mean([r['net_return'] for r in rows_ if r['arm'] == 'placebo'])
        return None if a is None or b is None else a - b

    def neg(rows_):
        d = diff(rows_)
        return None if d is None else -d
    low = W.lower_bound(groups, diff, seed=seed, draws=draws, alpha=ALPHA_DESCRIPTIVE) if groups else None
    low_neg = W.lower_bound(groups, neg, seed=seed, draws=draws, alpha=ALPHA_DESCRIPTIVE) if groups else None
    return dict(difference=diff(rows) if rows else None, lower_bound_95_one_sided=low,
                upper_bound_95_one_sided=None if low_neg is None else -low_neg, pools_paired=len(pools),
                pools_primary_only=len({p['pool'] for p in primary} - pools),
                placebo_positions=sum(1 for p in placebo if p['pool'] in pools), status='DESCRIPTIF (c2 à la confirmation)')


# -- (5) robustness ----------------------------------------------------------------------------------------------------
def robustness(primary, sensitivities, *, cut_time):
    """``primary``: every row of the primary run; a supplied sensitivity must hold the SAME decisions; every run counts
    its zero-sale rows (K01) and refuses a raw unpriced row."""
    keys = sorted(map(_key, primary))
    primary_priced = counted(primary)
    out = {k: NM for k in ROBUSTNESS}
    out['frozen_mev_grid'] = MEV_NOT_MEASURED
    for name, rows in (sensitivities or {}).items():
        if name not in SUPPLIED:
            raise ReportError('unknown_sensitivity:' + name)
        if sorted(map(_key, rows)) != keys:
            raise ReportError('sensitivity_is_not_the_same_decisions:' + name)
        if not all(SUPPLIED[name](p) for p in rows):
            raise ReportError('sensitivity_parameter_not_declared:' + name)
        values = counted(rows, name)
        out[name] = dict(mean_net_return=_mean([p['net_return'] for p in values]), positions=len(values),
                         zero_sale=zero_sale_reasons(values))
    by_pool = {}
    for p in primary_priced:
        by_pool.setdefault(p['pool'], []).append(p['net_return'])
    best = sorted(by_pool, key=lambda k: (-sum(by_pool[k]), k))[:5]
    nets = [p['net_return'] for p in primary_priced]
    out['without_5_best_pools'] = dict(
        mean_net_return=_mean([r for k, v in by_pool.items() if k not in best for r in v]) if len(by_pool) > 5 else NM,
        without_5_best_positions=_mean(sorted(nets)[:-5]) if len(nets) > 5 else NM)       # sheet c5 reading
    if type(cut_time) is not int:
        out['half_1_half_2'] = NM
    else:
        out['half_1_half_2'] = dict(cut_time=cut_time,
                                    first=_mean([p['net_return'] for p in primary_priced if p['decision_time'] < cut_time]),
                                    second=_mean([p['net_return'] for p in primary_priced
                                                  if p['decision_time'] >= cut_time]))
    return out


# -- the report ------------------------------------------------------------------------------------------------------
def report(hypothesis, primary, placebo, *, g0_passed, freeze_sheet_sha256, cut_time=None, sensitivities=None,
           lines=None, draws=CC.DRAWS):
    if hypothesis not in HYPOTHESES:
        raise ReportError('unknown_hypothesis')
    priced = counted(primary)                                 # K01: zero-sale rows COUNTED, raw unpriced refused
    placebo_priced = counted(placebo, 'placebo')              # the comparator under the same rule
    g1 = CC.pilot_verdict(priced, g0_passed=g0_passed, freeze_sheet_sha256=freeze_sheet_sha256, draws=draws)
    g1 = dict(g1, meaning=SHEET_MEANING)                      # K02 option (a): the sheet's sentence
    doc = dict(schema=SCHEMA, stamp=STAMP, hypothesis=hypothesis, g1=g1, labels=list(CC.LABELS),
               counts_for_operational_master=False)
    if not g1['published_numbers']:
        return check_vocabulary(dict(doc, descriptive=NM, reason='G-0 non passé : aucun chiffre publié'))
    target = R.n_required()
    doc.update(
        unpriced=dict(zero_sale_reasons(priced), rule=ZERO_RULE),
        power=dict(n_entered=g1['n_entered'], n_required=target,
                   flag=UNDER_TARGET if g1['n_entered'] < target else None),
        metrics_b31a3c47=metrics(priced, lines=lines),
        paired_gap=paired_gap(priced, placebo_priced, seed=g1['seed'], draws=draws),
        placebo=dict(positions=len(placebo_priced), zero_sale=zero_sale_reasons(placebo_priced),
                     mean_net_return=_mean([p['net_return'] for p in placebo_priced]), verdict=None),
        robustness=robustness(primary, sensitivities, cut_time=cut_time))
    return check_vocabulary(doc)
