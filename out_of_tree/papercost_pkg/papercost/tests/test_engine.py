"""papercost: full-cost PAPER engine on the public fixtures. Neutral options = the frozen engine byte for byte."""
import hashlib
import json
from dataclasses import asdict

import pytest

from bot.market import replay as R
from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from closedacct import model as CA
from landslip import guard as G
from papercost import engine as E
from paperstream.tests.test_engine import PACK, EnterAt, _timelines
from w1aux import dayj

MODEL = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')
STRATEGIES = [(1, 2, None), (2, None, None), (3, 1, None), (5, 50, None), (10, 5, None), (44, None, None),
              (62, 3, None), (10_000, None, None)]


@pytest.fixture(scope='module')
def timelines():
    return _timelines()


@pytest.fixture(scope='module')
def busy(timelines):
    return max(timelines, key=lambda t: len(t.events))


def _run(t, strategy, options):
    trade = E.CostedTrade(t.pool, strategy, MODEL, quote_mint=R.WSOL_MINT, options=options)
    for e in t.events:
        if trade.phase == 'stopped':
            break
        trade.push(e)
    return asdict(trade.finish())


def _frozen(t, strategy):
    return asdict(R.replay(t, strategy, MODEL, quote_mint=R.WSOL_MINT))


def _series(tmp_path):
    path = tmp_path / 'series.json'
    dayj._selfcheck_series(path)
    return sus.load_series(path)


def _bundle(series, options=None):
    archives = [a for _e, a in hrr.load_fixtures(PACK)[2]]
    args = (PACK, w1_run.l1_params(), series, w1_run.L1_EXIT, hrr.CreatorHistory.from_archives(archives, 'manifest'))
    if options is None:
        return hrr.run_replay(*args, placebo_arm=True)
    with E.costed_engine(options):
        return hrr.run_replay(*args, placebo_arm=True)


def _sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# -- options ------------------------------------------------------------------------------------------------------
def test_options_are_the_declared_ones():
    p, s, n = E.Options.primary(), E.Options.sensitivity(), E.Options.neutral()
    assert (p.buy_guard_ppm, p.sell_guard_ppm, p.h1, p.buy_failures, p.sell_failures) == (20_000, None, True, 0, 0)
    assert (s.buy_guard_ppm, s.sell_guard_ppm, s.buy_failures, s.sell_failures) == (50_000, 50_000, 1, 1)
    assert n.is_neutral and not p.is_neutral and not s.is_neutral
    for bad in (dict(buy_guard_ppm=10_000), dict(sell_guard_ppm=20_000), dict(buy_failures=4), dict(sell_failures=-1),
                dict(fail_ppm=1_000_000), dict(fail_ppm=10, buy_failures=1), dict(h1=1)):
        with pytest.raises(E.CostError):
            E.Options(**bad)
    assert (E.TX_FEE_LAMPORTS, E.RENT_LAMPORTS, E.WSOL_FLAT_LAMPORTS, E.MAX_FAILURES) == (105_000, 2_039_280, 5_000, 3)
    with pytest.raises(E.CostError, match='options_required'):
        with E.costed_engine(None):
            pass


def test_the_probability_draws_are_deterministic_and_bounded():
    o = E.Options(fail_ppm=500_000)
    draws = [o.failures('pool', 'buy', i) for i in range(200)]
    assert draws == [o.failures('pool', 'buy', i) for i in range(200)]
    assert set(draws) <= {0, 1, 2, 3} and 0 in draws and any(d > 0 for d in draws)
    assert E.Options(fail_ppm=0).failures('p', 'buy', 1) == 0 and E.Options(buy_failures=2).failures('p', 'buy', 1) == 2


# -- identity with the frozen engine -------------------------------------------------------------------------------
@pytest.mark.parametrize('n,n_hold,clock', STRATEGIES)
def test_neutral_options_are_the_frozen_trade_engine(timelines, n, n_hold, clock):
    for t in timelines:
        assert _run(t, EnterAt(n, n_hold, clock), E.Options.neutral()) == _frozen(t, EnterAt(n, n_hold, clock))


def test_neutral_options_give_the_frozen_bundle_byte_for_byte_and_the_frozen_value(tmp_path):
    series = _series(tmp_path)
    frozen = _bundle(series)
    neutral = _bundle(series, E.Options.neutral())
    assert _sha(neutral) == _sha(frozen) and neutral['bundle_sha256'] == frozen['bundle_sha256']
    for pool in frozen['pools']:
        for arm, row in pool['arms'].items():
            c = E.row_costs(row, 'frozen_assumption')
            if row['outcome'] in E.PRICED:
                assert c['net_lamports'] == row['received'] - row['spent'] - row['tx_costs'] - row['failed_attempt_costs']
    assert hrr.replay is not E.costed_replay                                      # the frozen engine is restored


# -- N-5 guard and H-1 -------------------------------------------------------------------------------------------
def test_the_buy_guard_refuses_a_fill_2_percent_below_the_decision_quote(busy):
    refused = []
    for n in range(1, 90):
        frozen = _frozen(busy, EnterAt(n, None, None))
        primary = _run(busy, EnterAt(n, None, None), E.Options.primary())
        if frozen['outcome'] != 'no_entry' and primary['outcome'] == 'no_entry':
            refused.append(n)
            assert E.NOTE + 'buy_slippage_guard_failed' in primary['notes']
            assert E.NOTE + 'failed:buy=1,sell=0' in primary['notes']                    # the failed tx is charged
            row = dict(outcome='no_entry', entry_index=None, notes=primary['notes'])
            assert E.row_costs(row, 'rent_lost')['net_lamports'] == -105_000
            assert primary['entry_index'] is None and primary['spent'] == 0
            k, rate, ev = primary['decision_index'], primary['fee_rate_ppm'], busy.events
            decision = buy_exact_in(ev[k].state_after(), 100_000_000, rate).amount_out
            limit = ev[k].slot + 4
            land = max(i for i, e in enumerate(ev) if e.slot <= limit)
            before = max(i for i in range(k, land + 1) if ev[i].slot < limit)
            worst = min(buy_exact_in(ev[i].state_after(), 100_000_000, rate).amount_out for i in {land, before})
            assert worst < G.minimum(decision, 20_000)                               # the H-1 fill is below the band
    assert len(refused) >= 5
    wider = [n for n in refused if _run(busy, EnterAt(n, None, None), E.Options(buy_guard_ppm=50_000))['outcome']
             != 'no_entry']
    assert wider and len(wider) < len(refused)                                      # 5 % admits some of them


def test_h1_keeps_the_fewer_tokens_of_the_landing_slot(busy):
    worse = 0
    for n in range(1, 90):
        frozen = _frozen(busy, EnterAt(n, None, None))
        h1 = _run(busy, EnterAt(n, None, None), E.Options(buy_guard_ppm=None))
        if frozen['tokens'] and h1['tokens'] != frozen['tokens']:
            assert h1['tokens'] < frozen['tokens']
            worse += 1
        no_h1 = _run(busy, EnterAt(n, None, None), E.Options(buy_guard_ppm=None, h1=False))
        assert no_h1 == frozen                                                    # H-1 off and guard off = frozen
    assert worse >= 5


# -- N-3 / N-4 failures ---------------------------------------------------------------------------------------------
def test_h1_at_the_sale_keeps_the_lower_value_of_the_sale_slot(busy):
    lower = 0
    for n in range(20, 40):
        for hold in (5, 8):
            off = _run(busy, EnterAt(n, hold, None), E.Options(buy_guard_ppm=None, h1=False))
            on = _run(busy, EnterAt(n, hold, None), E.Options(buy_guard_ppm=None, h1=True))
            if off['outcome'] == 'closed' and on['tokens'] == off['tokens']:
                assert on['received'] <= off['received']
                lower += on['received'] < off['received']
    assert lower >= 5


def test_a_failed_buy_lands_4_slots_later_and_is_charged(busy):
    for n in (5, 10, 20, 40):
        base = _run(busy, EnterAt(n, None, None), E.Options(buy_guard_ppm=None, h1=False))
        late = _run(busy, EnterAt(n, None, None), E.Options(buy_guard_ppm=None, h1=False, buy_failures=1))
        if base['entry_index'] is None:
            continue
        k = late['decision_index']
        limit = busy.events[k].slot + 8
        land = max(i for i, e in enumerate(busy.events) if e.slot <= limit)
        assert late['entry_index'] == land
        assert late['tokens'] == buy_exact_in(busy.events[land].state_after(), 100_000_000, late['fee_rate_ppm']).amount_out
        assert E.NOTE + 'failed:buy=1,sell=0' in late['notes']


def test_a_failed_sale_is_resent_4_slots_later(busy):
    for n, hold in ((2, 3), (5, 2), (10, 5)):
        base = _run(busy, EnterAt(n, hold, None), E.Options(buy_guard_ppm=None, h1=False))
        late = _run(busy, EnterAt(n, hold, None), E.Options(buy_guard_ppm=None, h1=False, sell_failures=1))
        if base['outcome'] != 'closed':
            continue
        assert late['exit_landing_slot'] == base['exit_landing_slot'] + 4
        assert E.NOTE + 'failed:buy=0,sell=1' in late['notes']
        assert late['exit_index'] >= base['exit_index']


def test_the_sale_guard_resends_4_slots_later_at_most_3_times_then_sells(busy, monkeypatch):
    # no 5 % drop follows an exit decision in the fixtures; the mechanism is shown with a 1 ppm guard (test only)
    monkeypatch.setattr(G, 'ALLOWED_SELL_GUARDS', (None, 1, G.SELL_GUARD_SENSITIVITY_PPM))
    neutral = E.Options(buy_guard_ppm=None, h1=False)
    three = two = 0
    for n in range(4, 40):
        base = _run(busy, EnterAt(n, 2, None), neutral)
        guarded = _run(busy, EnterAt(n, 2, None), E.Options(buy_guard_ppm=None, h1=False, sell_guard_ppm=1))
        if base['outcome'] != 'closed':
            continue
        failed = int([x for x in guarded['notes'] if x.startswith(E.NOTE + 'failed:')][0].split('sell=')[1])
        assert 0 <= failed <= G.SELL_MAX_FAILURES
        if failed:
            assert guarded['exit_landing_slot'] == base['exit_landing_slot'] + 4 * failed
            assert guarded['outcome'] == 'closed'                                  # sold in the end
        three += failed == 3
        two += failed in (1, 2)
    assert three >= 1 and two >= 1
    # with the declared 5 % guard nothing moves on these pools: the primary sale is unchanged
    for n in (6, 9, 20):
        assert _run(busy, EnterAt(n, 2, None), E.Options(buy_guard_ppm=None, h1=False, sell_guard_ppm=50_000))[
            'received'] == _run(busy, EnterAt(n, 2, None), neutral)['received']


# -- costs on the rows ----------------------------------------------------------------------------------------------
def _row(**over):
    row = dict(outcome='closed', spent=100_000_000, tokens=10, received=103_000_000, tx_costs=210_000,
               failed_attempt_costs=0, entry_index=3, notes=[])
    row.update(over)
    return row


def test_row_costs_both_modes_and_the_decomposition():
    lost = E.row_costs(_row(), 'rent_lost')
    closed = E.row_costs(_row(), 'closed')
    assert sum(lost['parts'].values()) == lost['net_lamports']
    assert lost['net_lamports'] == 103_000_000 - 100_000_000 - 210_000 - 2 * 5_000 - 2_039_280
    assert closed['net_lamports'] == 103_000_000 - 100_000_000 - 210_000 - 2 * 5_000 - 105_000
    assert E.row_costs(_row(), 'closed', cleanup_failures=1)['net_lamports'] == closed['net_lamports'] - 105_000
    left_open = E.row_costs(_row(), 'closed', cleanup_failures=3)
    assert left_open['net_lamports'] == lost['net_lamports'] - 3 * 105_000
    assert E.row_costs(_row(), 'rent_lost', wsol=105_000)['net_lamports'] == lost['net_lamports'] - 2 * 100_000
    assert E.row_costs(_row(), 'frozen_assumption')['net_lamports'] == 103_000_000 - 100_000_000 - 210_000
    ce = CA.net_return_closed(dict(migrated=False, value=103_000_000, tokens=10, cost=100_000_000 + 210_000 + 10_000))
    assert closed['net_return'] == pytest.approx(ce)
    with pytest.raises(E.CostError, match='unknown_mode'):
        E.row_costs(_row(), 'open')
    with pytest.raises(E.CostError, match='invalid_cleanup_failures'):
        E.row_costs(_row(), 'closed', cleanup_failures=4)


def test_n8_open_positions_are_marked_and_counted_unpriced_at_zero_and_guard_failures_charged():
    for outcome in ('open_at_end', 'open_at_window_end'):
        c = E.row_costs(_row(outcome=outcome), 'rent_lost')
        assert c['status'] == 'marked_and_counted' and c['counted']
        assert c['net_lamports'] == E.row_costs(_row(), 'rent_lost')['net_lamports']
    for outcome in ('migrated_unpriced', 'counterfactual_divergence'):
        for mode in E.MODES:
            c = E.row_costs(_row(outcome=outcome, tx_costs=105_000), mode)
            assert c['status'] == 'unpriced_counted_at_zero' and c['counted']
            assert c['net_lamports'] == -100_000_000 - 105_000 - 5_000 - 2_039_280      # rent lost in both modes
    refused = E.row_costs(dict(outcome='no_entry', spent=0, received=0, tx_costs=0, entry_index=None,
                               notes=[E.NOTE + 'failed:buy=1,sell=0', E.NOTE + 'buy_slippage_guard_failed']), 'closed')
    assert refused['status'] == 'guard_failed' and refused['net_lamports'] == -105_000 and refused['counted']
    nothing = E.row_costs(dict(outcome='no_entry', entry_index=None, notes=[]), 'rent_lost')
    assert nothing['counted'] is False and nothing['net_lamports'] == 0
    failed = E.row_costs(_row(notes=[E.NOTE + 'failed:buy=1,sell=2']), 'rent_lost')
    assert failed['net_lamports'] == E.row_costs(_row(), 'rent_lost')['net_lamports'] - 3 * 105_000


def test_the_summary_counts_every_row_and_is_never_a_master_trade(tmp_path):
    bundle = _bundle(_series(tmp_path), E.Options.primary())
    for mode in E.MODES:
        s = E.costed_bundle_summary(bundle, mode)
        assert s['label'] == 'HISTORICAL_REPLAY' and s['counts_for_operational_master'] is False
        for arm, block in s['arms'].items():
            assert block['rows'] == len(bundle['pools']) and sum(block['statuses'].values()) == block['rows']
            costs = [E.row_costs(pool['arms'][arm], mode) for pool in bundle['pools']]
            assert block['counted'] == sum(c['counted'] for c in costs)
            assert block['net_lamports'] == sum(c['net_lamports'] for c in costs if c['counted'])
    synthetic = dict(pools=[dict(arms=dict(master=_row(outcome='open_at_end'))), dict(arms=dict(master=_row()))])
    assert E.costed_bundle_summary(synthetic, 'rent_lost')['arms']['master']['counted'] == 2      # the mark counts


def test_a_modified_paperstream_engine_is_refused(monkeypatch):
    monkeypatch.setattr(E, 'PAPERSTREAM_ENGINE_SHA256', '0' * 64)
    with pytest.raises(E.CostError, match='paperstream_engine_is_not_the_audited_0_4'):
        with E.costed_engine(E.Options.primary()):
            pass
