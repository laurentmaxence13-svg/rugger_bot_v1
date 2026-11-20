"""cdgate: frozen C-D rule, gate, HW1 firewall (>= 600 s counted, never replayed), decomposition, output whitelist."""
import hashlib
import inspect
import json
from collections import namedtuple
from pathlib import Path

import pytest

import bot
from cdgate import gate as G
from latelab import study as LL

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
Ev = namedtuple('Ev', 'slot signature')


def test_frozen_rule_constants():
    assert G.RULE == dict(id='TP7_SL5_CLOCK30', take_profit=0.07, stop_loss=0.05, clock_s=30)
    assert (G.LATE_SLOTS, G.LOW_TIER_PPM, G.HW1_AGE_S) == (450, 2_500, 600)
    assert G.STAKE_LAMPORTS == 100_000_000 and G.LL.MIN_N == 30


def test_decision_is_the_first_whole_event_at_450_slots():
    events = [Ev(100, 'a'), Ev(549, 'b'), Ev(550, 'c'), Ev(550, 'c'), Ev(551, 'd')]
    assert G.decision_index(events, 100) == 3                       # slot 550 = age 450; last event of tx 'c'
    assert G.decision_index(events[:2], 100) is None
    assert G.decision_index([Ev(549, 'x'), Ev(551, 'y')], 100) == 1


def test_eligibility_is_the_causal_rate_at_most_2500(monkeypatch):
    seen = []

    def fake(events):
        seen.append(len(events))
        return fake.rate, {}
    monkeypatch.setattr(G, 'causal_fee_rate', fake)
    events = list(range(10))
    for rate, ok in ((2_500, True), (2_501, True), (2_502, True), (2_749, True), (2_750, False), (3_000, False),
                     (0, True), (10_000, False)):
        fake.rate = rate
        assert G.eligible(events, 4) == (ok, rate)
    assert set(seen) == {5}                                         # events up to the decision only


def test_decomposition_of_one_position():
    outcome = dict(migrated=False, value=100_000_000, cost=100_210_000, tokens=1, reason='clock')
    d = G.decompose(outcome, 2_500)
    assert d['tx'] == pytest.approx(0.0021) and d['rent'] == pytest.approx(2_039_280 / 1e8)
    assert d['curve_fees'] == pytest.approx((250_000 + 250_627) / 1e8)
    assert d['gross'] == pytest.approx((250_000 + 250_627) / 1e8)
    m = G.decompose(dict(migrated=True, value=None, cost=100_210_000, tokens=1, reason=None), 2_500)
    assert m['gross'] is None and m['curve_fees'] == pytest.approx(0.0025)


def _row(value, cluster):
    return dict(cluster=cluster, outcome=dict(migrated=False, value=value, reason='clock', cost=100_210_000, tokens=1),
                rate=2_500, slippage=0.01, latency10=None)


def test_gate_rule():
    up = [_row(103_000_000, f'c{i % 25}') for i in range(40)]
    assert G.gate(up)['gate']['c_d_stays_candidate'] is True
    assert G.gate(up[:29])['gate']['c_d_stays_candidate'] is False                    # n < 30
    down = [_row(80_000_000, f'c{i % 25}') for i in range(40)]
    g = G.gate(down)
    assert g['interval_95']['high'] < 0 and g['gate']['c_d_stays_candidate'] is False
    mixed = G.gate([_row(80_000_000 if i % 2 else 122_000_000, f'c{i % 25}') for i in range(40)])
    assert mixed['mean_net_return'] < 0 <= mixed['interval_95']['high']                 # a negative mean is not refuted
    assert mixed['gate']['c_d_stays_candidate'] is True
    assert G.gate([])['gate']['c_d_stays_candidate'] is False


def test_firewall_in_the_code():
    code = inspect.getsource(G).split('"""', 2)[2]
    for name in ('real_base', 'real_quote', 'progress', 'signer', 'signed', 'native_features', 'master_v2', "'sell'",
                 'top5', 'peak', 'maximum', 'drawdown', 'price_vs', 'age:600'):
        assert name not in code, name
    assert code.count('state_after') == 1 and 'state_after' in inspect.getsource(G.slippage)   # slippage only
    assert 'causal_fee_rate(events[:k + 1])' in inspect.getsource(G.eligible)


def _span(monkeypatch):
    monkeypatch.setattr(LL, 'EVAL_MIN', 1)
    monkeypatch.setattr(LL, 'CUT_SLOT', 10 ** 12)
    monkeypatch.setattr(LL, 'EVAL_MAX', 10 ** 12 + 1)


def test_entries_at_or_after_600s_are_counted_never_replayed(tmp_path, monkeypatch):
    _span(monkeypatch)
    monkeypatch.setattr(G, 'LATE_SLOTS', 3)                       # short frozen pools reach the decision
    monkeypatch.setattr(G, 'LOW_TIER_PPM', 999_999)               # every pool eligible
    monkeypatch.setattr(G, 'HW1_AGE_S', 0)                        # every decision counts as >= 600 s
    monkeypatch.setattr(G, 'decision_points', lambda *a: [])      # no placebo: any replay would be a C-D entry
    def guard(timeline, k, actors, model, rule):
        raise AssertionError('a C-D entry at or after 600 s was replayed')
    monkeypatch.setattr(G, 'run_rule', guard)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    assert G.main(['--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')]) == 0
    doc = json.loads((tmp_path / 'o' / 'CDGATE.json').read_text())
    c = doc['c_d']
    assert c['n'] == 0 and c['cycles']['at_or_after_600s_counted_not_read'] > 0
    assert c['cycles']['share_at_or_after_600s'] == 1.0 and c['gate']['c_d_stays_candidate'] is False


def test_frozen_pack_run_and_output_whitelist(tmp_path, monkeypatch):
    _span(monkeypatch)
    monkeypatch.setattr(G, 'LATE_SLOTS', 3)
    monkeypatch.setattr(G, 'LOW_TIER_PPM', 999_999)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    with pytest.raises(G.CdGateError, match='manifest_is_not_the_anchored_one'):
        G.main(['--pools', str(PACK), '--manifest-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    assert G.main(['--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')]) == 0
    text = (tmp_path / 'o' / 'CDGATE.json').read_text()
    doc = json.loads(text)
    c = doc['c_d']
    assert c['n'] > 0 and c['n'] == c['cycles']['closed'] and c['cycles']['eligible'] >= c['n']
    assert set(c['decomposition_mean_share_of_stake']) == {'gross', 'curve_fees', 'tx', 'rent'}
    assert c['decomposition_mean_share_of_stake']['tx'] == pytest.approx(0.0021)
    assert c['mean_net_return_latency_10_slots'] is not None and c['buy_slippage_mean'] is not None
    assert c['min_net_return'] <= c['mean_net_return'] <= c['max_net_return']
    assert doc['trials_added'] == 1 and doc['rule'] == G.RULE and doc['master_reference']['mean_net_return'] == -0.0426
    assert 'placebo_low_tier_descriptive' in doc
    for entry in json.loads((PACK / 'MANIFEST.json').read_text())['pools']:
        assert entry['pool'] not in text
    with pytest.raises(G.CdGateError, match='output_exists'):
        G.main(['--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')])


def test_a_high_rate_makes_nothing_eligible(tmp_path, monkeypatch):
    _span(monkeypatch)
    monkeypatch.setattr(G, 'LATE_SLOTS', 3)
    monkeypatch.setattr(G, 'LOW_TIER_PPM', -1)                    # no causal rate is <= -1
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    assert G.main(['--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')]) == 0
    doc = json.loads((tmp_path / 'o' / 'CDGATE.json').read_text())
    assert doc['c_d']['n'] == 0 and doc['c_d']['cycles']['eligible'] == 0 and doc['c_d']['cycles']['late_pools'] > 0
    assert doc['placebo_low_tier_descriptive']['n'] == 0


def test_outside_the_evaluation_range_nothing_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'LATE_SLOTS', 3)
    monkeypatch.setattr(G, 'LOW_TIER_PPM', 999_999)
    monkeypatch.setattr(LL, 'EVAL_MIN', 10 ** 12)                 # the frozen pools are all before the range
    monkeypatch.setattr(LL, 'CUT_SLOT', 10 ** 12 + 1)
    monkeypatch.setattr(LL, 'EVAL_MAX', 10 ** 12 + 2)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    assert G.main(['--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')]) == 0
    doc = json.loads((tmp_path / 'o' / 'CDGATE.json').read_text())
    assert doc['c_d']['cycles']['late_pools'] == 0 and doc['c_d']['n'] == 0


def test_tier_rule_on_the_real_causal_rate():
    """R02 B-1: a real 2 500 ppm rate on a 123 457 lamport buy gives fee 309 and the interval [2 495 ; 2 502]."""
    Fe = namedtuple('Fe', 'side amount_in amount_out protocol_fee platform_fee creator_fee share_fee')
    event = Fe('buy', 123_457, 1, 309, 0, 0, 0)
    rate, evidence = G.causal_fee_rate([event])
    assert evidence['interval_ppm'] == [2_495, 2_502] and rate == 2_502
    assert G.eligible([event], 0) == (True, 2_502)                  # tier 2 500: eligible, the raw rate kept for costs
    high = Fe('buy', 100_000, 1, 275, 0, 0, 0)                     # 2 750 ppm exactly
    rate, _evidence = G.causal_fee_rate([high])
    assert rate == 2_750 and G.tier(rate) == 3_000 and G.eligible([high], 0) == (False, 2_750)
    assert [G.tier(r) for r in (2_249, 2_250, 2_499, 2_749)] == [2_000, 2_000, 2_500, 2_500]   # as feeage tier_of
