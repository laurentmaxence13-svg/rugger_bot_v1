"""MASTER V2 research harness: native-SOL causal features, policy arm, accounting."""
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.market.collector import PoolArchive, summarize
from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import Position
from bot.master_v2 import harness as h
from bot.master_v2.features import native_features
from bot.p4 import historical_research_replay as hrr
from test_launchlab_market_events import FRESH, _event_from_fill

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
C7F9 = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
RATE = 12_500


def _archives():
    return {archive.pool: archive for _e, archive in hrr.load_fixtures(PACK)[2]}


def _chain(trades):
    """trades: (side, size, payer, block_time, slot); sell size = fraction of the payer's tokens."""
    state, events, held = FRESH, [], Counter()
    for i, (side, size, payer, block_time, slot) in enumerate(trades):
        if side == 'buy':
            fill = buy_exact_in(state, size, RATE)
            held[payer] += fill.amount_out
        else:
            amount = int(held[payer] * size)
            fill = sell_exact_in(state, amount, RATE)
            held[payer] -= amount
        event = _event_from_fill(fill, slot=slot, sig=f's{i:03d}')
        events.append(replace(event, fee_payer=payer, block_time=block_time))
        state = fill.after
    return events


FACTS = dict(creator='dev', creation_block_time=1000, creation_slot=100)


def test_native_features_on_a_hand_built_curve():
    events = _chain([('buy', 2 * 10**9, 'dev', 1000, 100), ('buy', 10**9, 'a', 1000, 100),
                     ('buy', 10**9, 'b', 1005, 110), ('sell', 0.5, 'a', 1040, 150),
                     ('buy', 3 * 10**9, 'c', 1050, 160)])
    f = native_features(events, FACTS)
    assert (f['age_s'], f['trades'], f['buys'], f['sells']) == (50, 5, 4, 1)
    assert (f['unique_buyers'], f['unique_sellers'], f['early_slot_payers']) == (3, 1, 1)
    assert f['buy_volume_lamports'] == 7 * 10**9
    assert f['sell_volume_lamports'] == events[3].amount_out + events[3].total_fee
    assert f['creator_bought_lamports'] == 2 * 10**9 and f['creator_sold_lamports'] == 0
    sold = events[-1].real_base_after
    assert f['creator_token_share'] == float(Fraction(events[0].amount_out, sold))
    assert f['top1_token_share'] == float(Fraction(events[4].amount_out, sold))
    assert f['quote_raised_lamports'] == events[-1].real_quote_after
    # Windows look back from the decision (t=1050) only: 10 s = the last buy; 30 s = the sell and
    # the last buy; 60 s = every event (all after t=990).
    assert f['trades_10s'] == 1 and f['net_flow_10s_lamports'] == 3 * 10**9
    assert f['trades_30s'] == 2 and f['buyers_30s'] == 1
    assert f['net_flow_30s_lamports'] == 3 * 10**9 - (events[3].amount_out + events[3].total_fee)
    assert f['trades_60s'] == 5 and f['buyers_60s'] == 3
    spot = lambda s: Fraction(s.quote_reserve, s.base_reserve)
    assert f['price_change_10s'] == float(spot(events[4].state_after()) / spot(events[3].state_after()) - 1)
    assert f['price_vs_launch'] == float(spot(events[4].state_after()) / spot(FRESH))
    assert f['seconds_since_previous_trade'] == 10 and f['drawdown_from_peak'] == 0.0


def test_features_read_nothing_after_the_decision():
    events = _chain([('buy', 10**9, 'a', 1000, 100), ('buy', 10**9, 'b', 1010, 110),
                     ('sell', 1.0, 'a', 1020, 120), ('buy', 5 * 10**9, 'c', 1030, 130)])
    prefix = native_features(events[:3], FACTS)
    other = _chain([('buy', 10**9, 'a', 1000, 100), ('buy', 10**9, 'b', 1010, 110),
                    ('sell', 1.0, 'a', 1020, 120), ('sell', 1.0, 'b', 1021, 121)])
    assert native_features(other[:3], FACTS) == prefix
    assert prefix['drawdown_from_peak'] > 0
    with pytest.raises(ValueError):
        native_features([], FACTS)


class _Script(h.Policy):
    name = 'test-script'

    def __init__(self, enter_at=None, abstain_at=None):
        self.enter_at, self.abstain_at = enter_at, abstain_at

    def params(self):
        return dict(enter_at=self.enter_at, abstain_at=self.abstain_at)

    def decide(self, features, facts):
        if self.abstain_at is not None and features['trades'] - 1 >= self.abstain_at:
            return 'NO_TRADE', ['scripted_abstention']
        if self.enter_at is not None and features['trades'] - 1 >= self.enter_at:
            return 'ENTER', ['scripted_entry']
        return 'WAIT', ['scripted_wait']


def test_never_entering_policy_has_no_cycle_and_full_journal():
    doc = h.run_policy(PACK, _Script(), h.ExitRule(max_hold_s=30))
    assert doc['outcomes'] == {'no_entry': 3} and doc['metrics']['n'] == 0
    assert doc['flags']['sol_usd_used'] is False and doc['flags']['counted_in_master_gate'] is False
    for pool in doc['pools']:
        _summary, timeline = summarize(_archives()[pool['pool']])
        last_of_tx = {e.signature: i for i, e in enumerate(timeline.events)}
        assert [row['index'] for row in pool['journal']] == sorted(set(last_of_tx.values()))
    assert doc == h.run_policy(PACK, _Script(), h.ExitRule(max_hold_s=30))


def test_abstention_is_final():
    doc = h.run_policy(PACK, _Script(abstain_at=3, enter_at=5), h.ExitRule(max_hold_s=30))
    for pool in doc['pools']:
        intents = [row['intent'] for row in pool['journal']]
        assert 'ENTER' not in intents and intents.count('NO_TRADE') <= 1
        if 'NO_TRADE' in intents:
            assert intents[-1] == 'NO_TRADE'


def test_forced_cycle_accounting_matches_the_audited_l1_rules():
    params = hrr.ReplayParams(failed_attempt_fee_lamports=7_000)
    archive = _archives()[C7F9]
    record = h.run_policy_pool(archive, _Script(enter_at=10), h.ExitRule(max_hold_s=5), params,
                               quote_mint=WSOL_MINT)
    trade = record['trade']
    assert trade['spent'] == hrr.ENTRY_LAMPORTS and trade['fee_rate_source'] == 'pool_events_causal_interval'
    assert trade['tx_costs'] == 2 * 105_000 and trade['failed_attempt_costs'] == 14_000
    value = trade['received'] - trade['spent'] - trade['tx_costs'] - trade['failed_attempt_costs']
    if trade['outcome'] == 'closed':
        assert trade['pnl_lamports'] == value and trade['exit_trigger']['reason'] == 'max_hold'
    else:
        assert trade['pnl_lamports'] is None and trade['mark_pnl_lamports'] == value
    assert record['journal'][-1]['intent'] == 'ENTER'


def _arm(rule):
    return h.PolicyArm(_Script(), rule, FACTS, Counter(), 1_000)


@pytest.mark.parametrize('marks,held,expected', [
    ([700], 1, 'stop_loss'), ([1_500], 1, 'take_profit'), ([1_000], 600, 'max_hold'),
    ([1_300, 1_100], 1, 'trailing_stop'), ([1_300, 1_200], 1, None), ([900, 850], 1, None),
    ([1_300, 700], 600, 'stop_loss'),
    ([950, 800], 1, None),                    # trailing armed only once the mark exceeded the spend
    ([2_000, 1_500], 1, 'trailing_stop'),     # trailing before take profit (operational precedence)
    ([1_500], 600, 'max_hold'),               # maximum hold before take profit
])
def test_exit_rule_precedence(marks, held, expected):
    rule = h.ExitRule(take_profit=0.45, stop_loss=0.25, trailing=0.15, max_hold_s=600)
    arm = _arm(rule)
    position = Position(0, 1, 100, 1_000, 5)
    trigger = None
    for step, mark in enumerate(marks):
        arm.exit_trigger = None
        last = step == len(marks) - 1
        if arm.exit([SimpleNamespace(block_time=100 + (held if last else 0))], position, mark):
            trigger = arm.exit_trigger['reason']
    assert trigger == expected


@pytest.mark.parametrize('kwargs', [dict(stop_loss=1.0), dict(trailing=0), dict(take_profit=-0.1),
                                    dict(max_hold_s=0), dict(max_hold_s=1.5), dict(stop_loss='0.2')])
def test_invalid_exit_rules_are_refused(kwargs):
    with pytest.raises(ValueError):
        h.ExitRule(**kwargs)


def test_invalid_intent_is_refused():
    class Bad(_Script):
        def decide(self, features, facts):
            return 'BUY', []
    with pytest.raises(ValueError, match='invalid_policy_intent'):
        h.run_policy(PACK, Bad(), h.ExitRule(max_hold_s=30))


def test_later_transactions_never_change_earlier_decisions():
    archive = _archives()[C7F9]
    params = hrr.ReplayParams()
    full = h.run_policy_pool(archive, _Script(), h.ExitRule(max_hold_s=30), params, quote_mint=WSOL_MINT)
    cut_row = full['journal'][20]
    cut = (cut_row['slot'], archive.transactions[cut_row['signature']]['transactionIndex'])
    kept = {s: tx for s, tx in archive.transactions.items() if (tx['slot'], tx['transactionIndex']) <= cut}
    rows = [r for r in archive.signatures if r['signature'] in kept or r.get('err') is not None]
    truncated = PoolArchive(archive.pool, archive.account, rows, True, kept)
    short = h.run_policy_pool(truncated, _Script(), h.ExitRule(max_hold_s=30), params, quote_mint=WSOL_MINT)
    assert short['journal'] == full['journal'][:len(short['journal'])] and len(short['journal']) == 21


def test_creator_is_never_the_top_holder_feature():
    events = _chain([('buy', 5 * 10**9, 'dev', 1000, 100), ('buy', 10**9, 'a', 1001, 101)])
    f = native_features(events, FACTS)
    sold = events[-1].real_base_after
    assert f['top1_token_share'] == float(Fraction(events[1].amount_out, sold))
    assert f['creator_token_share'] > f['top1_token_share']


def test_no_decision_in_the_middle_of_a_transaction():
    events = _chain([('buy', 10**9, 'a', 1000, 100), ('buy', 10**9, 'b', 1001, 101),
                     ('buy', 10**9, 'c', 1001, 101)])
    events[2] = replace(events[2], signature=events[1].signature, event_index=1)
    arm = h.PolicyArm(_Script(enter_at=1), h.ExitRule(max_hold_s=5), FACTS,
                      Counter(e.signature for e in events), 10**8)
    assert arm.entry(events[:2]) is None
    assert [row['index'] for row in arm.journal] == []
    assert arm.entry(events[:3]) == 10**8
    assert [row['index'] for row in arm.journal] == [2]


def test_preregistration_covers_the_exit_rule():
    a = h.run_policy(PACK, _Script(), h.ExitRule(max_hold_s=30))
    b = h.run_policy(PACK, _Script(), h.ExitRule(max_hold_s=31))
    assert a['preregistration_sha256'] != b['preregistration_sha256']


def test_position_open_at_migration_is_unpriced_in_the_harness(monkeypatch):
    from test_l1_p0_fixes import _migrating
    monkeypatch.setattr(h, 'summarize', _migrating(18))
    record = h.run_policy_pool(_archives()[C7F9], _Script(enter_at=10), h.ExitRule(max_hold_s=3600),
                               hrr.ReplayParams(), quote_mint=WSOL_MINT)
    assert 'migration' in record and record['trade']['outcome'] == 'migrated_unpriced'
    assert record['trade']['pnl_lamports'] is None and record['trade']['mark_pnl_lamports'] is not None
