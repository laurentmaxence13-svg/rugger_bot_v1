"""w1loss: a closed list of descriptive tables, on hand-made documents with known answers."""
import gzip
import hashlib
import json

import pytest

from w1loss import analysis as A

START, END = 1_000, 2_000
SPENT = 100_000_000


def _row(pool, arm, *, gross, rate, fees, slot, reason='exit_horizon_clock', tx=210_000, slippage=0, hold=30,
         outcome='closed', trial='L1', verified=True):
    pnl = gross - slippage - sum(fees) - tx
    cost = SPENT + tx
    row = dict(trial=trial, arm=arm, pool=pool, outcome=outcome, verified=verified, mismatches=[],
               pnl_lamports=pnl if outcome == 'closed' else None, net_return=pnl / cost if outcome == 'closed' else None,
               buy=dict(slot=slot, block_time=10_000, spent_lamports=SPENT, fee_rate_ppm=rate),
               sell=dict(block_time=10_000 + hold, trigger=dict(reason=reason, index=1, mark=1)))
    if outcome == 'closed':
        row['decomposition'] = dict(market_move=gross, slippage=slippage, launchlab_buy_fee=fees[0],
                                    launchlab_sell_fee=fees[1], tx_costs=tx, failed_attempt_costs=0, pnl=pnl)
    return row


def _pool(name, slot, plan=(10, 5)):
    arms = {arm: dict(exit_conditions=dict(tp_pct=plan[0], sl_pct=plan[1])) for arm in ('master', 'reference', 'placebo_random')}
    return dict(pool=name, creation_slot=slot, creator='C' + name, arms=arms)


# master: three tiers; a: 1.25 %, b and c: 1.75 %, d: 3.75 % (fees in lamports, both sides)
MASTER = dict(a=dict(gross=4_000_000, rate=12_500, fees=(1_250_000, 1_250_000), slot=1_002, reason='take_profit'),
              b=dict(gross=-6_000_000, rate=17_500, fees=(1_750_000, 1_650_000), slot=1_030, reason='stop_loss'),
              c=dict(gross=1_000_000, rate=17_500, fees=(1_750_000, 1_760_000), slot=1_200),
              d=dict(gross=-2_000_000, rate=37_500, fees=(3_750_000, 3_600_000), slot=1_600, reason='stop_loss', hold=12))
CREATED = dict(a=1_000, b=1_010, c=1_100, d=1_100, e=1_300)


def _documents(tmp_path, *, reference=None, extra=(), verdict='PASS'):
    pools = [_pool(n, CREATED[n]) for n in sorted(CREATED)] + [_pool('out', START - 1), _pool('late', END)]
    entries = [_row(n, 'master', **kw) for n, kw in MASTER.items()]
    entries += [_row(n, 'reference', **kw) for n, kw in (reference or MASTER).items()]
    entries += [_row('a', 'placebo_random', gross=-1_000_000, rate=12_500, fees=(1_250_000, 1_240_000), slot=1_020),
                _row('d', 'placebo_random', gross=3_000_000, rate=37_500, fees=(3_750_000, 3_760_000), slot=1_700),
                _row('e', 'placebo_random', gross=500_000, rate=17_500, fees=(1_750_000, 1_750_000), slot=1_324)]
    entries += [_row('out', 'master', gross=9 * SPENT, rate=12_500, fees=(1, 1), slot=1_500),     # outside the range
                _row('a', 'master', gross=9 * SPENT, rate=12_500, fees=(1, 1), slot=1_500, trial='L1_event_horizon'),
                _row('a', 'immediate-snipe', gross=9 * SPENT, rate=12_500, fees=(1, 1), slot=1_500),
                _row('e', 'master', gross=0, rate=12_500, fees=(1, 1), slot=1_500, outcome='open_at_end')]
    entries += list(extra)
    bundle = gzip.compress(json.dumps(dict(pools=pools)).encode(), mtime=0)
    (tmp_path / 'L1.json.gz').write_bytes(bundle)
    ledger = dict(verdict=verdict, mismatches=[], w1_report=None, entries=entries,
                  bundles_sha256=dict(L1=hashlib.sha256(bundle).hexdigest()))
    raw = json.dumps(ledger).encode()
    (tmp_path / 'ledger.json').write_bytes(raw)
    return tmp_path / 'ledger.json', hashlib.sha256(raw).hexdigest(), tmp_path / 'L1.json.gz'


def _run(tmp_path, **kwargs):
    ledger, sha, bundle = _documents(tmp_path, **kwargs)
    sums = A.run(ledger, sha, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    return json.loads((tmp_path / 'out' / 'VENTILATION_W1.json').read_text(encoding='utf-8')), sums


def test_known_answers_for_the_master_arm(tmp_path, capsys):
    doc, sums = _run(tmp_path)
    assert capsys.readouterr() == ('', '')
    assert sums == {n: hashlib.sha256((tmp_path / 'out' / n).read_bytes()).hexdigest() for n in sums}
    assert (tmp_path / 'out' / 'VENTILATION_W1.md').read_text(encoding='utf-8').startswith('# ' + A.STAMP)
    m = doc['arms']['master']
    pnl = {n: kw['gross'] - sum(kw['fees']) - 210_000 for n, kw in MASTER.items()}
    assert m['T0_totals'] == dict(n=4, pnl_sum_lamports=sum(pnl.values()), gross_sum_lamports=-3_000_000,
                                  fees_sum_lamports=16_760_000, tx_sum_lamports=840_000, slippage_sum_lamports=0,
                                  failed_sum_lamports=0)
    assert list(m['T1_fee_tiers']) == ['12500', '17500', '37500']
    tier = m['T1_fee_tiers']['17500']
    assert tier['n'] == 2 and tier['mean_gross_return'] == pytest.approx(-0.025)
    assert tier['mean_fee_return'] == pytest.approx((3_400_000 + 3_510_000) / 2 / SPENT)
    assert tier['mean_net_return'] == pytest.approx((pnl['b'] + pnl['c']) / 2 / (SPENT + 210_000))
    assert tier['median_net_return'] == pytest.approx(pnl['b'] / (SPENT + 210_000)) and tier['win_rate'] == 0.0
    assert m['T1_fee_tiers']['12500']['win_rate'] == 1.0
    cf = {c['rate_ppm']: c for c in m['T2_counterfactual_fee_first_order']}
    assert sorted(cf) == [0, 2_500, 12_500]
    assert cf[0]['net_sum_lamports'] == pytest.approx(-3_000_000 - 840_000)                 # no curve fee at all
    assert cf[0]['mean_net_return'] == pytest.approx((-3_000_000 - 840_000) / 4 / (SPENT + 210_000))   # frozen denominator
    assert cf[0]['win_rate'] == 0.5
    expected = sum(pnl[n] + sum(kw['fees']) * (1 - 2_500 / kw['rate']) for n, kw in MASTER.items())
    assert cf[2_500]['net_sum_lamports'] == pytest.approx(expected)
    assert cf[12_500]['net_sum_lamports'] == pytest.approx(  # the lowest tier is unchanged, the others are scaled down
        pnl['a'] + sum(pnl[n] + sum(MASTER[n]['fees']) * (1 - 12_500 / MASTER[n]['rate']) for n in 'bcd'))
    assert m['T3_exit_reasons']['stop_loss']['n'] == 2 and m['T3_exit_reasons']['stop_loss']['mean_hold_s'] == 21.0
    assert m['T3_exit_reasons']['stop_loss']['median_hold_s'] == 12
    assert m['T4_entry_age_slots'] == {
        '[0,5)': dict(n=1, mean_gross_return=0.04, mean_net_return=pytest.approx(pnl['a'] / (SPENT + 210_000))),
        '[5,25)': dict(n=1, mean_gross_return=-0.06, mean_net_return=pytest.approx(pnl['b'] / (SPENT + 210_000))),
        '[50,150)': dict(n=1, mean_gross_return=0.01, mean_net_return=pytest.approx(pnl['c'] / (SPENT + 210_000))),
        '>=450': dict(n=1, mean_gross_return=-0.02, mean_net_return=pytest.approx(pnl['d'] / (SPENT + 210_000)))}
    thirds = m['T5_chronological_thirds']
    assert [t['n'] for t in thirds] == [1, 1, 2] and thirds[2]['first_slot'] == 1_200 and thirds[2]['last_slot'] == 1_600
    assert m['T7_gross_return'] == dict(p10=-0.06, p25=-0.06, p50=-0.02, p75=0.01, p90=0.04, share_positive=0.5)
    assert m['T8_scorer_plan'] == {'tp=10;sl=5': dict(n=4, mean_gross_return=-0.0075,
                                                     mean_net_return=pytest.approx(sum(pnl.values()) / 4 / (SPENT + 210_000)))}
    assert doc['reference_identical_to_master'] is True


def test_placebo_pairs_and_the_firewall(tmp_path):
    doc, _ = _run(tmp_path)
    p = doc['arms']['placebo_random']
    assert p['T0_totals']['n'] == 3                                          # the master-only rows are not read
    assert {k: v['n'] for k, v in p['T4_entry_age_slots'].items()} == {'[5,25)': 2, '>=450': 1}   # e: age 24 exactly
    assert [A._age_class(x) for x in (0, 4, 5, 24, 25, 449, 450, -1)] == [
        '[0,5)', '[0,5)', '[5,25)', '[5,25)', '[25,50)', '[150,450)', '>=450', 'negative']
    pair = doc['T6_paired_master_minus_placebo']
    assert pair['n'] == 2                                                    # pools a and d
    assert pair['mean_diff_gross_return'] == pytest.approx(((0.04 + 0.01) + (-0.02 - 0.03)) / 2)
    assert doc['firewall'] == dict(arms_read=['master', 'placebo_random', 'reference'], trial_read='L1',
                                   frozen_hypotheses_evaluated=False, age_classes_stop_at_slots=450)
    assert set(doc['arms']) == {'master', 'placebo_random'}
    assert doc['flags']['w1_figure_changed'] is False and doc['flags']['selection_made'] is False
    # 9 x the stake outside the range, in another trial or arm, or not closed: never read
    assert max(t['n'] for t in doc['arms']['master']['T1_fee_tiers'].values()) == 2


def test_a_reference_that_differs_from_the_master_is_flagged(tmp_path):
    reference = dict(MASTER, a=dict(MASTER['a'], gross=3_999_999))
    doc, _ = _run(tmp_path, reference=reference)
    assert doc['reference_identical_to_master'] is False
    assert 'Référence identique au MASTER : NON' in (tmp_path / 'out' / 'VENTILATION_W1.md').read_text(encoding='utf-8')


def test_guards(tmp_path):
    ledger, sha, bundle = _documents(tmp_path)
    with pytest.raises(A.BreakdownError, match='ledger_is_not_the_anchored_one'):
        A.run(ledger, '0' * 64, bundle, tmp_path / 'o1', evaluation_min=START, evaluation_max=END)
    (tmp_path / 'other.json.gz').write_bytes(gzip.compress(b'{"pools": []}', mtime=0))
    with pytest.raises(A.BreakdownError, match='bundle_is_not_the_one_the_ledger_recorded'):
        A.run(ledger, sha, tmp_path / 'other.json.gz', tmp_path / 'o2', evaluation_min=START, evaluation_max=END)
    (tmp_path / 'o3').mkdir()
    with pytest.raises(A.BreakdownError, match='output_exists'):
        A.run(ledger, sha, bundle, tmp_path / 'o3', evaluation_min=START, evaluation_max=END)
    with pytest.raises(A.BreakdownError, match='invalid_evaluation_range'):
        A.run(ledger, sha, bundle, tmp_path / 'o4', evaluation_min=END, evaluation_max=START)
    sub = tmp_path / 'fail'
    sub.mkdir()
    ledger, sha, bundle = _documents(sub, verdict='FAIL')
    with pytest.raises(A.BreakdownError, match='ledger_is_not_a_pass_without_report'):
        A.run(ledger, sha, bundle, sub / 'o', evaluation_min=START, evaluation_max=END)
    sub = tmp_path / 'unverified'
    sub.mkdir()
    bad = _row('c', 'placebo_random', gross=0, rate=17_500, fees=(1, 1), slot=1_150, verified=False)
    ledger, sha, bundle = _documents(sub, extra=[bad])
    with pytest.raises(A.BreakdownError, match='closed_cycle_not_verified_or_without_figures:c'):
        A.run(ledger, sha, bundle, sub / 'o', evaluation_min=START, evaluation_max=END)


def test_main_writes_the_two_files_and_their_sums(tmp_path):
    ledger, sha, bundle = _documents(tmp_path)
    assert A.main(['--ledger', str(ledger), '--ledger-sha256', sha, '--l1-bundle', str(bundle), '--evaluation-min',
                   str(START), '--evaluation-max', str(END), '--out', str(tmp_path / 'out')]) == 0
    sums = json.loads((tmp_path / 'out' / 'SHA256SUMS.json').read_text())
    assert sorted(sums) == ['VENTILATION_W1.json', 'VENTILATION_W1.md']
    assert all(hashlib.sha256((tmp_path / 'out' / n).read_bytes()).hexdigest() == s for n, s in sums.items())
