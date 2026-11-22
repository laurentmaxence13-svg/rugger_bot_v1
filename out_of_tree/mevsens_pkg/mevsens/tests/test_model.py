"""mevsens: N-6 sensitivity on the public fixture curve states (declared scenarios, not calibrated)."""
import pytest

from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
from landslip import guard as G
from mevsens import model as M
from paperstream.tests.test_engine import _timelines

STAKE, RATE, SOL = 100_000_000, 10_000, 10 ** 9


@pytest.fixture(scope='module')
def states():
    busy = max(_timelines(), key=lambda t: len(t.events))
    return [busy.events[i].state_after() for i in (5, 20, 40, 70)]


def test_a_front_run_always_costs_us_tokens(states):
    for state in states:
        clean = M.fill_after_front_run(state, STAKE, RATE, 0)
        assert clean == buy_exact_in(state, STAKE, RATE).amount_out
        fills = [M.fill_after_front_run(state, STAKE, RATE, f) for f in (SOL // 100, SOL // 10, SOL, 5 * SOL)]
        assert all(f is not None for f in fills)
        assert clean > fills[0] > fills[1] > fills[2] > fills[3]
    with pytest.raises(M.MevError, match='invalid_front_run'):
        M.fill_after_front_run(states[0], STAKE, RATE, -1)


def test_under_the_guard_the_worst_sandwich_leaves_our_fill_at_the_minimum(states):
    for state in states:
        expected = buy_exact_in(state, STAKE, RATE).amount_out
        for guard in (G.BUY_GUARD_PPM, G.BUY_GUARD_SENSITIVITY_PPM):
            front, tokens = M.worst_buy_front_run(state, STAKE, RATE, guard)
            floor = G.minimum(expected, guard)
            assert tokens >= floor                                                # the buy still lands
            assert M.fill_after_front_run(state, STAKE, RATE, front + 1) < floor   # one lamport more: it fails
            assert 0 < front < M.F_MAX_LAMPORTS
        assert M.worst_buy_front_run(state, STAKE, RATE, G.BUY_GUARD_SENSITIVITY_PPM)[0] > \
            M.worst_buy_front_run(state, STAKE, RATE, G.BUY_GUARD_PPM)[0]           # a wider band invites more
        # without a guard, only the attacker's capital bounds the loss
        front, tokens = M.worst_buy_front_run(state, STAKE, RATE, None, f_max=50 * SOL)
        assert front == 50 * SOL and tokens < G.minimum(expected, G.BUY_GUARD_SENSITIVITY_PPM)


def test_a_sale_front_run_lowers_our_value(states):
    for state in states:
        tokens = buy_exact_in(state, STAKE, RATE).amount_out
        clean = M.sale_after_front_run(state, tokens, RATE, 0)
        assert clean == sell_exact_in(state, tokens, RATE).amount_out
        assert clean > M.sale_after_front_run(state, tokens, RATE, tokens) > M.sale_after_front_run(state, tokens, RATE, 5 * tokens)
    with pytest.raises(M.MevError, match='invalid_front_run'):
        M.sale_after_front_run(states[0], 1, RATE, -5)


def test_the_declared_scenarios_and_their_costs(states):
    names = [s['name'] for s in M.SCENARIOS]
    assert names == ['none', 'guarded_worst_case', 'quarter_of_trades', 'always_with_sale', 'tip_10k_per_tx',
                     'tip_100k_per_tx']
    buy_state, sale_state = states[1], states[2]
    costs = {s['name']: M.scenario_cost(s, buy_state, sale_state, STAKE, RATE) for s in M.SCENARIOS}
    assert costs['none']['total_lamports'] == 0 and costs['none']['sandwich_loss_lamports'] == 0
    worst = costs['guarded_worst_case']
    assert worst['sandwich_loss_lamports'] > 0 and worst['expected_loss_lamports'] == worst['sandwich_loss_lamports']
    # the guarded buy sandwich costs at most the guard band of the sale value (plus rounding)
    clean_sale = sell_exact_in(sale_state, buy_exact_in(buy_state, STAKE, RATE).amount_out, RATE).amount_out
    assert worst['sandwich_loss_lamports'] <= clean_sale * 21_000 // 1_000_000
    quarter = costs['quarter_of_trades']
    assert quarter['expected_loss_lamports'] == quarter['sandwich_loss_lamports'] * 250_000 // 1_000_000
    assert costs['always_with_sale']['sandwich_loss_lamports'] > worst['sandwich_loss_lamports']
    assert costs['tip_10k_per_tx']['total_lamports'] == 20_000 and costs['tip_100k_per_tx']['total_lamports'] == 200_000
    assert all(c['calibrated'] is False for c in costs.values())
    with pytest.raises(M.MevError, match='scenario_not_declared'):
        M.scenario_cost(dict(M.SCENARIOS[1], probability_ppm=500_000), buy_state, sale_state, STAKE, RATE)
