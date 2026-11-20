"""latesel: filters from trade amounts only, causal, firewall; quantiles without any return; anchored screen."""
import hashlib
import inspect
import json
from collections import namedtuple
from pathlib import Path

import pytest

import bot
from latelab import study as LL
from latesel import select as S

E = namedtuple('E', 'side fee_payer amount_in amount_out')
PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'


def test_unique_buyers_excludes_the_creator_and_sellers():
    history = [E('buy', 'cr', 5, 50), E('buy', 'a', 1, 10), E('buy', 'a', 1, 10), E('buy', 'b', 1, 10),
               E('sell', 'c', 10, 1)]
    assert S.unique_buyers(history, 'cr') == 2
    assert S.unique_buyers(history, None) == 3


def test_top5_holder_share_from_amounts_only():
    history = [E('buy', 'cr', 1, 1000)] + [E('buy', p, 1, 10 * (i + 1)) for i, p in enumerate('abcdef')]
    # positions a..f = 10..60, creator excluded; top 5 = 20..60 = 200 of 210
    assert S.top5_holder_share(history, 'cr') == pytest.approx(200 / 210)
    history.append(E('sell', 'f', 60, 1))                       # f sells all: position 0, no longer held
    assert S.top5_holder_share(history, 'cr') == pytest.approx(1.0)
    assert S.top5_holder_share([E('buy', 'cr', 1, 5)], 'cr') is None
    assert S.top5_holder_share([E('buy', 'a', 1, 5), E('sell', 'a', 5, 1)], None) is None


def test_keeps_direction_and_missing_values():
    t1, t3 = S.HYPOTHESES['T1'], S.HYPOTHESES['T3p']
    assert S.keeps(t1, 7, 7) and S.keeps(t1, 8, 7) and not S.keeps(t1, 6, 7)
    assert S.keeps(t3, 0.5, 0.5) and S.keeps(t3, 0.4, 0.5) and not S.keeps(t3, 0.6, 0.5)
    assert not S.keeps(t1, None, 7) and not S.keeps(t3, 0.4, None)


def test_hypotheses_frozen_and_firewall_in_the_code():
    assert S.HYPOTHESES == {'T1': dict(age=120, feature='unique_buyers', q=2 / 3, keep='>='),
                            'T3p': dict(age=300, feature='top5_holder_share', q=1 / 2, keep='<=')}
    assert max(h['age'] for h in S.HYPOTHESES.values()) < 600 and 'T2' not in S.HYPOTHESES
    code = inspect.getsource(S).split('"""', 2)[2]
    for name in ('state_after', 'state_before', 'real_base', 'real_quote', 'native_features', 'master_v2',
                 'progress', 'signer', 'signed', "'sell'", 'fee_rate', 'tier', 'peak', 'maximum', 'drawdown',
                 'price', 'top5_token_share', 'reserve', 'age:600', 'take_profit', 'stop_loss'):
        assert name not in code, name
    assert S.LL.RULE == dict(id='CLOCK60', clock_s=60)


def _fake_points(monkeypatch):
    from statelab import points as P

    def fake(events, created, pool):
        whole = [k for k in range(len(events)) if P.whole(events, k)]
        wanted = ((3, [['age', 120]]), (5, [['progress', 650_000]]), (7, [['age', 120], ['age', 300]]))
        return [(whole[i], labels) for i, labels in wanted if i < len(whole)]        # short pools: fewer points
    monkeypatch.setattr(S, 'decision_points', fake)


def test_feature_points_are_causal(monkeypatch):
    from w1aux.lazy import clear_cache, load_fixtures_lazy
    _fake_points(monkeypatch)
    monkeypatch.setattr(LL, 'EVAL_MIN', 1)
    monkeypatch.setattr(LL, 'CUT_SLOT', 10 ** 12)
    monkeypatch.setattr(LL, 'EVAL_MAX', 10 ** 12 + 1)
    try:
        archive = next(a for e, a in load_fixtures_lazy(PACK)[2] if e['pool'].startswith('C7F9'))
        facts, half, timeline = S._timeline(archive)
    finally:
        clear_cache()
    events = timeline.events
    points = S.feature_points(events, facts, archive.pool)
    assert half == 'discovery' and [p[0] for p in points] == ['T1', 'T1', 'T3p']      # the progress label is dropped
    for name, k, value in points:
        feature = S.FEATURES[S.HYPOTHESES[name]['feature']]
        assert value == feature(events[:k + 1], facts.get('creator'))              # the prefix up to event k only
    assert S.feature_points(events[:points[-1][1] + 1], facts, archive.pool) == points   # the future is not read


def test_feature_points_ignore_the_future(monkeypatch):
    """Appending events after the decision event must not change the value at that event."""
    _fake_points(monkeypatch)
    from w1aux.lazy import clear_cache, load_fixtures_lazy
    try:
        archive = next(a for e, a in load_fixtures_lazy(PACK)[2] if e['pool'].startswith('C7F9'))
        monkeypatch.setattr(LL, 'EVAL_MIN', 1)
        monkeypatch.setattr(LL, 'CUT_SLOT', 10 ** 12)
        monkeypatch.setattr(LL, 'EVAL_MAX', 10 ** 12 + 1)
        facts, _half, timeline = S._timeline(archive)
    finally:
        clear_cache()
    events = timeline.events
    first = S.feature_points(events, facts, archive.pool)[0]
    seen = []
    real = S.FEATURES['unique_buyers']

    def spy(history, creator):
        seen.append(len(history))
        return real(history, creator)
    monkeypatch.setitem(S.FEATURES, 'unique_buyers', spy)
    S.feature_points(events, facts, archive.pool)
    assert seen[0] == first[1] + 1 and all(n <= len(events) for n in seen)


def test_quantiles_then_anchored_screen_on_the_frozen_pack(tmp_path, monkeypatch):
    _fake_points(monkeypatch)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    names = [p['pool'] for p in json.loads((PACK / 'MANIFEST.json').read_text())['pools']]
    monkeypatch.setattr(LL, 'EVAL_MIN', 1)
    monkeypatch.setattr(LL, 'CUT_SLOT', 10 ** 12)                  # every frozen pool in half 1
    monkeypatch.setattr(LL, 'EVAL_MAX', 10 ** 12 + 1)
    with pytest.raises(S.LateSelError, match='manifest_is_not_the_anchored_one'):
        S.main(['quantiles', '--pools', str(PACK), '--manifest-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    assert S.main(['quantiles', '--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'q')]) == 0
    qfile = tmp_path / 'q' / 'LATESEL.json'
    text = qfile.read_text()
    q = json.loads(text)
    assert q['trials_added'] == 0 and q['half'] == 'discovery'
    assert 'mean_net_return' not in text and 'cells' not in q and not any(n in text for n in names)
    t1, t3 = q['thresholds']['T1'], q['thresholds']['T3p']
    assert t1['n_points'] > 0 and t3['n_points'] > 0 and t1['threshold'] >= 1 and 0 < t3['threshold'] <= 1
    qsha = hashlib.sha256(qfile.read_bytes()).hexdigest()
    with pytest.raises(S.LateSelError, match='anchored_quantiles_required'):
        S.main(['screen', '--pools', str(PACK), '--manifest-sha256', sha, '--out', str(tmp_path / 'x')])
    with pytest.raises(S.LateSelError, match='quantiles_are_not_the_anchored_ones'):
        S.main(['screen', '--pools', str(PACK), '--manifest-sha256', sha, '--quantiles', str(qfile),
                '--quantiles-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    other = json.loads(text)
    other['hypotheses']['T1']['q'] = 0.5
    ofile = tmp_path / 'other.json'
    ofile.write_text(json.dumps(other))
    with pytest.raises(S.LateSelError, match='quantiles_of_other_hypotheses'):
        S.main(['screen', '--pools', str(PACK), '--manifest-sha256', sha, '--quantiles', str(ofile),
                '--quantiles-sha256', hashlib.sha256(ofile.read_bytes()).hexdigest(), '--out', str(tmp_path / 'x')])
    assert not (tmp_path / 'x').exists()
    monkeypatch.setattr(LL, 'CUT_SLOT', 2)                         # now every frozen pool in half 2
    assert S.main(['screen', '--pools', str(PACK), '--manifest-sha256', sha, '--quantiles', str(qfile),
                   '--quantiles-sha256', qsha, '--out', str(tmp_path / 's')]) == 0
    stext = (tmp_path / 's' / 'LATESEL.json').read_text()
    doc = json.loads(stext)
    assert doc['half'] == 'screen' and doc['trials_added'] == 2 and set(doc['cells']) == {'T1', 'T3p'}
    assert doc['input']['quantiles_sha256'] == qsha and doc['rule'] == LL.RULE
    assert sum(c['n'] for c in doc['cells'].values()) > 0 and not any(n in stext for n in names)
    for cell in doc['cells'].values():
        assert cell['passes'] is False                             # 4 frozen pools: below the floors
    with pytest.raises(S.LateSelError, match='output_exists'):
        S.main(['screen', '--pools', str(PACK), '--manifest-sha256', sha, '--quantiles', str(qfile),
                '--quantiles-sha256', qsha, '--out', str(tmp_path / 's')])
    monkeypatch.setattr(LL, 'CUT_SLOT', 10 ** 12)                  # back to half 1 only: the screen sees nothing
    assert S.main(['screen', '--pools', str(PACK), '--manifest-sha256', sha, '--quantiles', str(qfile),
                   '--quantiles-sha256', qsha, '--out', str(tmp_path / 's1')]) == 0
    assert all(c['n'] == 0 for c in json.loads((tmp_path / 's1' / 'LATESEL.json').read_text())['cells'].values())


def _pos(value, cluster):
    return (cluster, dict(migrated=False, value=value, reason='clock', cost=100_210_000))


def test_verdict_pass_rule_uses_the_floors_and_the_sign():
    good = [_pos(110_000_000, f'c{i % 25}') for i in range(40)]
    assert S.verdict(good)['passes'] is True
    assert S.verdict(good[:29])['passes'] is False                                   # n < 30
    assert S.verdict([_pos(110_000_000, f'c{i % 10}') for i in range(40)])['passes'] is False   # < 20 clusters
    assert S.verdict([_pos(90_000_000, f'c{i % 25}') for i in range(40)])['passes'] is False    # mean < 0
    assert S.verdict([])['passes'] is False
