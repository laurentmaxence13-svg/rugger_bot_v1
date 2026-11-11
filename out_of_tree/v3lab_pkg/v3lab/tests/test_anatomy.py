"""v3lab.anatomy: the exact identity of a closed cycle, the hindsight exit bound and the breakdowns."""
import io
import json
import random

import pytest

from bot.market.launchlab_curve import CurveState, buy_exact_in, sell_exact_in
from v3lab import __main__ as cli, anatomy, plan
from v3lab.evaluate import load_bundles
from v3lab.tests.test_v3lab import archives, visible          # noqa: F401  (fixtures)

TX = 105_000
STATE = CurveState(virtual_base=1_073_000_000_000_000, virtual_quote=30_000_000_000, real_base=40_000_000_000_000,
                   real_quote=1_200_000_000, total_base_sell=793_100_000_000_000)


def cycle(pool, segment, *, rate=12_500, spent=100_000_000, received=None, creator=None, entry_index=3,
          outcome='closed', created_slot=1, trades=50, path=None, state=STATE, failed=0):
    """A row shaped like ``runner.run_pool``'s, whose fill and instant sale come from the frozen curve."""
    buy = buy_exact_in(state, spent, rate)
    sale = sell_exact_in(buy.after, buy.amount_out, rate)
    received = sale.amount_out if received is None else received
    closed = outcome == 'closed'
    tx_costs = 2 * TX if closed else TX
    trade = dict(entry_index=entry_index, entry_signature='sig' + pool, outcome=outcome, spent=spent,
                 tokens=buy.amount_out, received=received if closed else 0, tx_costs=tx_costs,
                 failed_attempt_costs=failed, fee_rate_ppm=rate, hold_slots=100, exit_slot=created_slot + 200,
                 exit_trigger=dict(reason='max_hold_clock', index=entry_index + 2, mark=received),
                 pnl_lamports=received - spent - tx_costs - failed if closed else None)
    block = dict(cost_lamports=spent + 2 * TX, immediate_mark=sale.amount_out)
    if path is not None:
        block['path'] = path
    return dict(pool=pool, creator=creator or 'c' + pool, segment=segment, created_slot=created_slot, trades=trades,
                trade=trade, v3=block), buy, sale


def bundle(rows, trial='V3-01', role='reference'):
    return dict(trial=trial, role=role, policy='p', bundle_sha256='x', pools=rows)


def test_the_identity_is_exact_and_matches_the_frozen_curve_fees():
    for rate in (10_000, 12_500, 17_500, 25_000, 37_500):
        row, buy, sale = cycle('a', 'train', rate=rate, received=93_000_000)
        parts = anatomy.decompose(row)
        assert parts['buy_fee'] == buy.fee
        assert 0 <= sale.fee - parts['sell_fee_at_entry'] <= 1          # the documented 1-lamport ambiguity
        assert abs(parts['own_impact'] - (buy.amount_in - buy.fee - (sale.amount_out + sale.fee))) <= 1
        assert parts['drift'] == 93_000_000 - sale.amount_out
        assert parts['drift'] - sum(v for k, v in parts.items() if k != 'drift') == row['trade']['pnl_lamports']


def test_the_gross_of_a_net_sale_is_recovered_for_every_fee_rate():
    rng = random.Random(7)
    for _ in range(20_000):
        gross, rate = rng.randrange(1, 10**12), rng.choice((0, 1, 10_000, 12_500, 17_500, 25_000, 37_500, 100_000))
        net = gross - -(-gross * rate // 1_000_000)
        found = anatomy._gross_of_net(net, rate)
        assert found - -(-found * rate // 1_000_000) == net
        assert 0 <= gross - found <= 1                      # the smaller of two gross values with the same net


def test_a_row_that_breaks_the_identity_or_leaves_the_visible_segments_is_refused():
    row, _b, _s = cycle('a', 'train')
    for patch in (dict(pnl_lamports=row['trade']['pnl_lamports'] + 1), dict(tx_costs=TX), dict(fee_rate_ppm=None)):
        with pytest.raises(ValueError):
            anatomy.decompose(dict(row, trade=dict(row['trade'], **patch)))
    with pytest.raises(ValueError, match='negative_own_impact'):
        anatomy.decompose(dict(row, v3=dict(row['v3'], immediate_mark=row['trade']['spent'])))
    with pytest.raises(ValueError, match='row_outside_the_visible_segments'):
        anatomy.anatomy({'V3-01': bundle([row, cycle('z', 'holdout')[0]])}, n_boot=0)


def test_money_sums_the_components_and_ranks_the_loss_sources():
    silent, _b, sale = cycle('a', 'train')                              # nobody trades after us: drift 0
    down, _b2, _s2 = cycle('b', 'train', received=sale.amount_out - 5_000_000)
    up, _b3, _s3 = cycle('c', 'validation', received=sale.amount_out + 30_000_000)
    lost, _b4, _s4 = cycle('d', 'validation', outcome='counterfactual_divergence')
    out = anatomy.anatomy({'V3-01': bundle([silent, down, up, lost])}, n_boot=0)
    assert 'ASSUMED' in out['rent_basis']
    m = out['trials']['V3-01']['money']['all_visible']
    assert (m['entered'], m['closed'], m['decomposed']) == (4, 3, 3)
    assert m['non_closed'] == {'counterfactual_divergence': 1}
    assert sum(m['components_lamports'][k] * (1 if k == 'drift' else -1) for k in anatomy.COMPONENTS) == m['pnl_lamports']
    assert m['components_lamports']['drift'] == 25_000_000 and m['components_lamports']['tx_costs'] == 6 * TX
    d = m['drift']
    assert (d['positive_cycles'], d['zero_cycles'], d['negative_cycles']) == (1, 1, 1)
    assert m['rent_lost_today_lamports'] == 3 * anatomy.SPL_RENT_LAMPORTS
    assert m['pnl_with_rent_lamports'] == m['pnl_lamports'] - 3 * anatomy.SPL_RENT_LAMPORTS
    ranked = m['loss_sources_ranked']
    assert [r['lamports'] for r in ranked] == sorted((r['lamports'] for r in ranked), reverse=True)
    assert sum(r['share_of_gross_losses_pct'] for r in ranked) == pytest.approx(100)
    assert {r['source'] for r in ranked} >= {'buy_fee', 'sell_fee_at_entry', 'own_impact', 'tx_costs', 'negative_drift',
                                             'rent_lost_today'}
    train = out['trials']['V3-01']['money']['train']
    assert train['closed'] == 2 and train['components_lamports']['drift'] == -5_000_000
    assert out['trials']['V3-01']['money']['exploration']['pnl_pct'] is None


def test_the_census_sets_the_rent_and_the_token_class_groups():
    a, _b, _s = cycle('a', 'train')
    b, _b2, _s2 = cycle('b', 'train', creator='ca', created_slot=2)      # second pool of the same creator
    census = dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[], rows=[
        dict(pool='a', class_='executable_now', our_account_rent_lamports=2_039_280),
        dict(pool='b', class_='token2022_allowlisted', our_account_rent_lamports=2_074_080)])
    a['creator'] = 'ca'
    out = anatomy.anatomy({'V3-01': bundle([a, b])}, census, n_boot=0)
    m = out['trials']['V3-01']['money']['all_visible']
    assert m['rent_lost_today_lamports'] == 2_039_280 + 2_074_080 and 'census' in out['rent_basis']
    g = out['trials']['V3-01']['groups']
    assert set(g['token_class']) == {'executable_now', 'token2022_allowlisted'}
    assert g['creator_earlier_pools']['0']['entered'] == 1 and g['creator_earlier_pools']['1+']['entered'] == 1
    assert g['fee_rate_ppm']['12500']['closed'] == 2 and g['fee_rate_ppm']['12500']['small_sample'] is True
    assert g['events_before_entry']['4-9']['entered'] == 2
    missing = anatomy.anatomy({'V3-01': bundle([a, cycle('q', 'train')[0]])}, census, n_boot=0)
    assert missing['trials']['V3-01']['money']['all_visible']['rent_lost_today_lamports'] is None   # unknown class: no guess


def test_the_exit_bound_is_hindsight_on_the_probe_path_of_the_same_entry():
    cost = 100_210_000
    rows, probes = [], []
    for name, best in (('a', 1.80), ('b', 1.02), ('c', None)):
        row, _b, sale = cycle(name, 'train')
        path = [] if best is None else [[3, round(cost * 0.9)], [40, round(cost * best)], [300, round(cost * 0.5)]]
        probe_row = json.loads(json.dumps(row))
        probe_row['v3']['path'] = path
        rows.append(row)
        probes.append(probe_row)
    other = json.loads(json.dumps(rows[0]))
    other['pool'], other['trade']['entry_index'] = 'd', 9
    late = json.loads(json.dumps(other))
    late['trade']['entry_index'], late['v3']['path'] = 4, [[1, cost * 3]]       # not the same entry: never paired
    out = anatomy.anatomy({'V3-01': bundle(rows + [other]), 'V3-06': bundle(probes + [late], 'V3-06', 'probe')}, n_boot=0)
    e = out['trials']['V3-01']['exits']['all_visible']
    assert e['paired'] == 3 and 'HINDSIGHT' in e['label']
    instant = (rows[2]['v3']['immediate_mark'] - cost) / cost
    assert e['best_exit_mean'] == pytest.approx((0.80 + 0.02 + instant) / 3, abs=1e-6)
    assert e['best_exit_share_positive'] == pytest.approx(2 / 3)
    assert e['best_exit_gain_share_of_top1'] == pytest.approx(0.80 / 0.82, abs=1e-6)
    assert e['best_exit_mean_without_top1'] == pytest.approx((0.02 + instant) / 2, abs=1e-6)
    assert e['best_age_s']['median'] == 40 and e['best_age_s']['share_at_entry'] == pytest.approx(1 / 3)
    assert e['events_after_entry']['25'] == dict(mean=pytest.approx(2 / 3), median=1, share_none=pytest.approx(1 / 3))
    assert e['events_after_entry']['900']['mean'] == 2
    assert e['best_exit_mean_with_rent'] < e['best_exit_mean']
    listing = anatomy.anatomy({'V3-01': bundle(rows), 'V3-06': bundle(probes, 'V3-06', 'probe')},
                              positions_of='V3-01', n_boot=0)['positions']['rows']
    assert [r['pool'] for r in listing] == ['a', 'b', 'c'] and listing[0]['best_exit_age_s'] == 40
    assert listing[0]['events_during_hold'] == 2 and set(listing[0]['components_lamports']) == set(anatomy.COMPONENTS)


def test_on_bundles_of_a_real_run_every_closed_cycle_satisfies_the_identity(visible, tmp_path):   # noqa: F811
    directory, sha = visible
    out = tmp_path / 'runs'
    assert cli.main(['run', '--pack', str(directory), '--expect-manifest-sha', sha, '--registry',
                     str(tmp_path / 'reg.jsonl'), '--out', str(out), '--at', '2026-11-11T00:00:00+00:00'],
                    out=io.StringIO()) == 0
    bundles = load_bundles(out)
    document = anatomy.anatomy(bundles, positions_of='V3-01', n_boot=50)
    assert document['probe'] == 'V3-06' and set(document['trials']) == {row['id'] for row in plan.TRIALS}
    seen = 0
    for trial, body in document['trials'].items():
        m = body['money']['all_visible']
        closed = [r for r in bundles[trial]['pools'] if r['trade']['outcome'] == 'closed']
        seen += m['decomposed']
        assert m['closed'] == len(closed)
        assert m['pnl_lamports'] == sum(r['trade']['pnl_lamports'] for r in closed
                                        if r['v3'].get('immediate_mark') is not None)
        assert sum(m['components_lamports'][k] * (1 if k == 'drift' else -1)
                   for k in anatomy.COMPONENTS) == m['pnl_lamports']
    assert seen >= 4
    probe = document['trials']['V3-06']['exits']['all_visible']
    assert probe['paired'] >= 1 and probe['best_exit_mean'] >= probe['last_recorded_value_mean']
    text = anatomy.markdown(document)
    assert '### Où part l’argent' in text and '| V3-01 |' in text and 'rétrospective' in text
    json.dumps(document, allow_nan=False)
