"""g1ind 0.1 on fixtures only: synthetic rows shaped like cpmmcost 0.3 positions, and one end-to-end run of the frozen
cpmmprereg / cpmmcost code on a synthetic CPMM pool (cpmmx simulator)."""
import pytest

from bot.p4 import historical_research_replay as hrr
from closedacct import model as CA
from cpmmcost import model as CC
from cpmmprereg import rule as R
from cpmmprereg.tests.test_rule import CONFIG, calm, drop_then, market
from g1ind import report as G
from w2arms import ce as W

SHEET = '0123456789abcdef' * 4
DRAWS = 400


def row(i, pools, net, *, status='entered', **extra):
    lamports = round(net * CC.STAKE_LAMPORTS)
    base = dict(pool='p%02d' % (i % pools), decision_index=i, decision_slot=1_000 + i, decision_time=100 + i,
                status=status, entered=status == 'entered', net_return=lamports / CC.STAKE_LAMPORTS,
                net_lamports=lamports, latency_slots=4, guard_ppm=CC.BUY_GUARD_PPM,
                failures=dict(buy=0, sell=0, cleanup=0))
    if status == 'entered':
        base['decomposition_share_of_stake'] = dict(price_move=net + 0.012, trade_and_creator_fees=-0.005,
                                                    price_impact=-0.002, transactions=-0.0021, wsol_close=-0.00105,
                                                    cleanup=-0.00105, rent_lost=0.0)
    base.update(extra)
    return base


def arms(n, pools, value, placebo_value=lambda i: -0.004):
    return ([row(i, pools, value(i)) for i in range(n)],
            [row(10_000 + i, pools, placebo_value(i)) for i in range(n)])


def run(primary, placebo, **kw):
    kw.setdefault('g0_passed', True)
    kw.setdefault('freeze_sheet_sha256', SHEET)
    kw.setdefault('draws', DRAWS)
    return G.report('RCP1', primary, placebo, **kw)


# -- (1) G-1 is the frozen function, unchanged ------------------------------------------------------------------------
def test_g1_is_the_frozen_function_called_once_on_the_priced_rows():
    p, pl = arms(40, 20, lambda i: 0.01 + 0.001 * (i % 5))
    out = run(p, pl)
    frozen = CC.pilot_verdict(p, g0_passed=True, freeze_sheet_sha256=SHEET, draws=DRAWS)
    assert {k: v for k, v in out['g1'].items() if k != 'meaning'} == {k: v for k, v in frozen.items() if k != 'meaning'}
    assert out['g1']['decision'] == 'GO_PILOTE' and out['g1']['meaning'] == G.SHEET_MEANING
    assert out['counts_for_operational_master'] is False and out['labels'] == list(CC.LABELS)
    neg = run(*arms(40, 20, lambda i: -0.05))
    assert neg['g1']['decision'] == 'NO-GO'
    with pytest.raises(G.ReportError):
        G.report('R-CP2', p, pl, g0_passed=True, freeze_sheet_sha256=SHEET)


def test_g0_not_passed_publishes_no_number():
    p, pl = arms(40, 20, lambda i: 0.01)
    out = run(p, pl, g0_passed=False)
    assert out['g1']['decision'] == 'STOP' and out['descriptive'] == G.NM
    assert not {'metrics_b31a3c47', 'paired_gap', 'robustness', 'power', 'placebo'} & set(out)


# -- (2) unpriced rows -------------------------------------------------------------------------------------------------
def test_an_unpriced_row_is_an_entered_position_sold_for_zero_and_counted():
    # K01, R02 f41c6cb0: valued at 0 with the frozen closedacct zero-sale formula, COUNTED in the mean and the floors
    z = G.zero_valued(dict(pool='p03', decision_index=999, decision_time=900, unpriced='data_ends'))
    assert z['net_lamports'] == -(CC.STAKE_LAMPORTS + 3 * CC.TX_FEE_LAMPORTS + CC.TOKEN_ACCOUNT_RENT_LAMPORTS)
    assert z['net_return'] == z['net_lamports'] / CC.STAKE_LAMPORTS and z['entered'] is True
    assert z['status'] == G.ZERO_STATUS and z['unpriced'] == 'data_ends'
    assert z['net_return'] == pytest.approx(CA.net_return_closed(dict(migrated=True, value=0, tokens=None,
                                                                      cost=CC.STAKE_LAMPORTS + 315_000)))
    one = G.zero_valued(dict(pool='p03', decision_index=999), CC.SENSITIVITY_FAILURES)
    assert one['net_lamports'] == -(CC.STAKE_LAMPORTS + 5 * CC.TX_FEE_LAMPORTS + CC.TOKEN_ACCOUNT_RENT_LAMPORTS)
    p, pl = arms(40, 20, lambda i: 0.01)
    holed = p + [dict(pool='p03', decision_index=999, decision_time=900, unpriced='data_ends_before_exit')]
    out = run(holed, pl)
    assert out['unpriced']['count'] == 1 and out['unpriced']['rows'][0]['reason'] == 'data_ends_before_exit'
    assert out['unpriced']['rule'] == G.ZERO_RULE
    frozen = CC.pilot_verdict(p + [G.zero_valued(holed[-1])], g0_passed=True, freeze_sheet_sha256=SHEET, draws=DRAWS)
    assert {k: v for k, v in out['g1'].items() if k != 'meaning'} == {k: v for k, v in frozen.items() if k != 'meaning'}
    assert out['g1']['n'] == 41 and out['g1']['n_entered'] == 41
    assert out['g1']['mean_net_return'] == pytest.approx((40 * 0.01 + z['net_return']) / 41)
    assert out['metrics_b31a3c47']['population'] == 41
    assert out['metrics_b31a3c47']['fees_share_of_stake_entered']['zero_valued_positions'] == 1
    # it counts in the floors: 29 priced + 1 unpriced entries on 20 pools reach the 30-entry floor
    p29, pl29 = arms(29, 20, lambda i: 0.01)
    floor = run(p29 + [dict(pool='p05', decision_index=777, decision_time=50, unpriced='x')], pl29)
    assert floor['g1']['n_entered'] == 30 and floor['g1']['decision'] != 'INCONCLUSIF'
    # the placebo is valued under the same rule
    pz = run(p, pl + [dict(pool='p01', decision_index=20_000, decision_time=1, unpriced='x')])
    assert pz['placebo']['unpriced_valued_zero'] == 1 and pz['placebo']['positions'] == 41


# -- (3) b31a3c47 ------------------------------------------------------------------------------------------------------
def test_win_loss_pf_and_expectancy_follow_b31a3c47():
    rows = [row(0, 3, 0.02), row(1, 3, 0.0), row(2, 3, -0.01), row(3, 3, -0.03)]
    m = G.metrics(rows)
    assert m['win_rate'] == 0.25                                  # r = 0 is a loss
    assert m['mean_losing_return'] == pytest.approx((0.0 - 0.01 - 0.03) / 3)
    assert m['profit_factor'] == pytest.approx(0.02 / 0.04)
    assert m['expectancy'] == pytest.approx(-0.02 / 4) and m['expectancy_identity_checked'] is True
    assert G.metrics([row(0, 1, 0.01), row(1, 1, 0.0)])['profit_factor'] == G.NM      # no negative r: PF undefined
    assert G.metrics([])['population'] == 0


def test_guard_refusals_count_in_the_metrics_but_not_in_the_fee_split():
    refused = row(7, 3, -0.00105, status='guard_failed')
    assert 'decomposition_share_of_stake' not in refused
    m = G.metrics([row(0, 3, 0.01), refused])
    assert m['population'] == 2 and m['fees_share_of_stake_entered']['transactions'] == pytest.approx(-0.0021)
    assert m['fees_share_of_stake_entered']['guard_refusal_fee_per_position'] == pytest.approx(-0.00105)
    assert m['net_sol_total'] == pytest.approx((0.01 - 0.00105) * 0.1)


def test_the_drawdown_follows_the_exit_order_in_stakes_and_sol():
    # entry order 0, 1, 2; exit order 0, 2, 1: -0.03 lands before the +0.05 recovery
    rows = [row(0, 1, 0.02), row(1, 1, 0.05), row(2, 1, -0.03)]
    dd = G.drawdown(rows, [10, 30, 20])
    assert dd == dict(stakes=pytest.approx(0.03), sol=pytest.approx(0.003), order='exit')
    assert G.drawdown(rows, [10, 20, 30])['stakes'] == pytest.approx(0.03)
    up = [row(0, 1, -0.03), row(1, 1, 0.05), row(2, 1, -0.01)]
    assert G.drawdown(up, [10, 30, 20])['stakes'] == pytest.approx(0.04)     # exit order: -0.03, -0.01 then +0.05
    assert G.drawdown(up, [10, 20, 30])['stakes'] == pytest.approx(0.03)     # entry order would hide 0.01
    assert G.metrics(rows)['max_drawdown'] == G.NM                           # no timeline: NON MESURÉ, no entry order


# -- (4) paired gap ----------------------------------------------------------------------------------------------------
def test_the_paired_gap_is_the_c2_statistic_over_pools_in_both_arms():
    p, pl = arms(60, 20, lambda i: 0.003 * ((i * 7) % 13 - 4) + 0.0001 * i, lambda i: -0.004 + 0.0007 * ((i * 5) % 11))
    pl = [x for x in pl if x['pool'] != 'p19']                            # one pool without placebo
    gap = G.paired_gap(p, pl, seed=int(SHEET[:8], 16), draws=DRAWS)
    kept = [x for x in p if x['pool'] != 'p19']
    assert gap['difference'] == pytest.approx(G._mean([x['net_return'] for x in kept])
                                              - G._mean([x['net_return'] for x in pl]))
    assert gap['pools_paired'] == 19 and gap['pools_primary_only'] == 1
    groups = {}
    for r in [dict(x, arm='primary') for x in kept] + [dict(x, arm='placebo') for x in pl]:
        groups.setdefault(r['pool'], []).append(r)

    def diff(rows):
        a = G._mean([r['net_return'] for r in rows if r['arm'] == 'primary'])
        b = G._mean([r['net_return'] for r in rows if r['arm'] == 'placebo'])
        return None if a is None or b is None else a - b
    assert gap['lower_bound_95_one_sided'] == W.lower_bound(groups, diff, seed=int(SHEET[:8], 16), draws=DRAWS,
                                                            alpha=0.05)
    assert gap['lower_bound_95_one_sided'] <= gap['difference'] <= gap['upper_bound_95_one_sided']
    assert gap['lower_bound_95_one_sided'] != W.lower_bound(groups, diff, seed=int(SHEET[:8], 16) + 1, draws=DRAWS,
                                                            alpha=0.05)            # the seed matters on these data
    assert G.paired_gap(p, [], seed=1, draws=DRAWS)['difference'] is None
    out = run(p, pl)
    assert out['paired_gap']['difference'] == gap['difference'] and out['placebo']['verdict'] is None


# -- (5) robustness ----------------------------------------------------------------------------------------------------
def test_supplied_sensitivities_must_be_the_same_decisions_with_the_declared_parameter():
    p, pl = arms(40, 20, lambda i: 0.01)
    slow = [dict(x, latency_slots=10, net_return=x['net_return'] - 0.003) for x in p]
    out = run(p, pl, sensitivities=dict(latency_10_slots=slow), cut_time=120)
    assert out['robustness']['latency_10_slots']['mean_net_return'] == pytest.approx(0.007)
    assert out['robustness']['one_failure_per_tx'] == G.NM
    assert out['robustness']['frozen_mev_grid'] == G.MEV_NOT_MEASURED
    with pytest.raises(G.ReportError, match='parameter'):
        run(p, pl, sensitivities=dict(latency_10_slots=p))                        # 4 slots labelled 10
    with pytest.raises(G.ReportError, match='same_decisions'):
        run(p, pl, sensitivities=dict(latency_10_slots=slow[:-1]))
    with pytest.raises(G.ReportError, match='unknown'):
        run(p, pl, sensitivities=dict(frozen_mev_grid=p))
    one = [dict(x, failures=dict(buy=1, sell=1, cleanup=0)) for x in p]
    assert run(p, pl, sensitivities=dict(one_failure_per_tx=one))['robustness']['one_failure_per_tx']['positions'] == 40
    with pytest.raises(G.ReportError, match='parameter'):
        run(p, pl, sensitivities=dict(one_failure_per_tx=[dict(x, failures=dict(buy=1, sell=0, cleanup=0)) for x in p]))
    lost = [dict(x, failures=dict(buy=0, sell=0, cleanup=CA.MAX_CLEANUP_ATTEMPTS)) for x in p]
    assert run(p, pl, sensitivities=dict(rent_lost_vs_closed_account=lost))['robustness'][
        'rent_lost_vs_closed_account']['positions'] == 40
    with pytest.raises(G.ReportError, match='parameter'):
        run(p, pl, sensitivities=dict(rent_lost_vs_closed_account=p))
    wide = [dict(x, guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM) for x in p]
    rob = run(p, pl, sensitivities=dict(guard_5_percent=wide))['robustness']['guard_5_percent']
    assert rob['unpriced_valued_zero'] == 0
    with pytest.raises(G.ReportError, match='parameter'):
        run(p, pl, sensitivities=dict(guard_5_percent=p))
    # a row that becomes unpriced in a sensitivity keeps its decision and is counted apart
    holed = slow[:-1] + [dict(pool=slow[-1]['pool'], decision_index=slow[-1]['decision_index'], unpriced='data_ends')]
    r = run(p, pl, sensitivities=dict(latency_10_slots=holed))['robustness']['latency_10_slots']
    assert (r['positions'], r['unpriced_valued_zero']) == (40, 1)
    assert r['mean_net_return'] == pytest.approx((39 * 0.007 + G.zero_valued(holed[-1])['net_return']) / 40)
    # the zero value of a run is charged under that run's failures
    one_holed = one[:-1] + [dict(pool=one[-1]['pool'], decision_index=one[-1]['decision_index'], unpriced='x')]
    r1 = run(p, pl, sensitivities=dict(one_failure_per_tx=one_holed))['robustness']['one_failure_per_tx']
    assert r1['mean_net_return'] == pytest.approx(
        (39 * 0.01 + G.zero_valued(one_holed[-1], CC.SENSITIVITY_FAILURES)['net_return']) / 40)


def test_without_the_5_best_pools_and_the_halves():
    p = [row(i, 8, 0.10 if i % 8 < 5 else -0.01) for i in range(16)]          # pools p00..p04 carry every gain
    rob = G.robustness(p, None, cut_time=108)
    assert rob['without_5_best_pools']['mean_net_return'] == pytest.approx(-0.01)
    assert rob['without_5_best_pools']['without_5_best_positions'] == pytest.approx(
        G._mean(sorted(x['net_return'] for x in p)[:-5]))
    assert rob['half_1_half_2']['first'] == pytest.approx(G._mean([x['net_return'] for x in p[:8]]))
    assert rob['half_1_half_2']['second'] == pytest.approx(G._mean([x['net_return'] for x in p[8:]]))
    assert G.robustness(p, None, cut_time=None)['half_1_half_2'] == G.NM
    assert G.robustness(p[:5], None, cut_time=1)['without_5_best_pools']['mean_net_return'] == G.NM


# -- (6) power target, (7) vocabulary ----------------------------------------------------------------------------------
def test_under_the_power_target_below_155_entries():
    assert R.n_required() == 155
    p, pl = arms(154, 20, lambda i: 0.01)
    assert run(p, pl)['power'] == dict(n_entered=154, n_required=155, flag=G.UNDER_TARGET)
    p, pl = arms(155, 20, lambda i: 0.01)
    assert run(p, pl)['power']['flag'] is None


def test_the_closed_vocabulary_is_enforced_and_identical_to_plbench():
    from plbench import bench as PB
    assert G.FORBIDDEN_WORDS == PB.FORBIDDEN_WORDS
    for word in G.FORBIDDEN_WORDS:
        with pytest.raises(G.ReportError) as exc:
            G.check_vocabulary(dict(note='x ' + word.upper()))
        assert word not in str(exc.value)
    p, pl = arms(40, 20, lambda i: 0.01)
    PB.assert_closed_vocabulary(run(p, pl))
    leaked = p + [dict(pool='p01', decision_index=998, unpriced='note ' + G.FORBIDDEN_WORDS[2])]
    with pytest.raises(G.ReportError):
        run(leaked, pl)                                                  # the whole document is checked


# -- end to end on the frozen code -------------------------------------------------------------------------------------
def test_end_to_end_on_a_synthetic_pool_with_the_frozen_rule():
    line = market(drop_then(calm(710, 3_000)))
    idx = R.decisions(line, CONFIG)
    primary = R.positions(line, CONFIG, idx)
    placebo = R.positions(line, CONFIG, R.placebo(line, len(idx), SHEET))
    assert primary and all('net_return' in p for p in primary)
    out = G.report('RCP1', primary, placebo, g0_passed=True, freeze_sheet_sha256=SHEET, lines=[line], draws=DRAWS,
                   cut_time=1_000)
    assert out['g1']['decision'] == 'INCONCLUSIF'                     # 1 pool: below the floors, never NO-GO
    assert out['power']['flag'] == G.UNDER_TARGET
    p = primary[0]
    t = G.exit_time(line, p)
    if p['exit']['rule'] == 'clock':
        assert t == p['exit']['declared']
    else:
        fired = p['exit']['declared'] - p['latency_slots']
        assert t == min(s.block_time for s in line.swaps if s.slot == fired) + hrr.clock_exit_latency_s(4)
    assert out['metrics_b31a3c47']['max_drawdown']['order'] == 'exit'
    slow = R.positions(line, CONFIG, idx, latency_slots=10)
    again = G.report('RCP1', primary, placebo, g0_passed=True, freeze_sheet_sha256=SHEET, lines=[line], draws=DRAWS,
                     sensitivities=dict(latency_10_slots=slow))
    assert again['robustness']['latency_10_slots']['positions'] == len(primary)


def test_a_slot_exit_reads_the_block_time_of_the_firing_swap():
    line = market(drop_then(calm(710, 3_000)))
    s = line.swaps[40]
    fake = dict(status='entered', latency_slots=4, exit=dict(rule='slot', declared=s.slot + 4))
    assert G.exit_time(line, fake) == s.block_time + hrr.clock_exit_latency_s(4)
    with pytest.raises(G.ReportError):
        G.exit_time(line, dict(fake, exit=dict(rule='slot', declared=10 ** 9)))
    refused = dict(status='guard_failed', decision_index=40)
    assert G.exit_time(line, refused) == s.block_time
    zero = G.zero_valued(dict(pool=line.pool, decision_index=40, decision_time=s.block_time, unpriced='x'))
    assert G.exit_time(line, zero) == s.block_time + R.CLOCK_S + hrr.clock_exit_latency_s(4)
    assert G.exit_time(line, dict(status='entered', exit=dict(rule='clock', declared=4_321))) == 4_321
