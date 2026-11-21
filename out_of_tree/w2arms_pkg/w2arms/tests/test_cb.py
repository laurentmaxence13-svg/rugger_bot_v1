"""w2arms.cb: C-B verdict on the frozen statelab rows (rent lost, paired placebo of the same pool, halves by creation slot)."""
import hashlib
import json
from pathlib import Path

import pytest

import bot
from statelab import hypotheses as H
from w2arms import cb as C
from w2arms import ce as W

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
PACK_S0 = 464_661_843 - 402_800 - 10
ANCHOR = 'cd' * 32
STAKE, COST, RENT = 100_000_000, 100_210_000, 2_039_280
S0 = 1_000_000_000


@pytest.fixture
def few_draws(monkeypatch):
    monkeypatch.setattr(W, 'DRAWS', 300)


def _row(pool, hyp, value, creator, migrated=False, h='10'):
    return dict(pool=pool, hypothesis=hyp, creator=creator, cost=COST, tokens=1_000, fee_rate_ppm=10_000,
                horizons={h: dict(value=None if migrated else value, migrated=migrated)})


def _docs(n, value, *, placebo_value=95_000_000, k=2, bad_half=False, hyp='HW1-5'):
    docs, slots = [], []
    for w in range(k):
        s0 = S0 + w * W.WINDOW_SLOTS
        low, high = W.evaluation_range(s0)
        rows_, created = [], {}
        for i in range(n // k):
            pool = f'p{w}-{i}'
            v = 99_000_000 if (bad_half and w == 0) else value
            rows_ += [_row(pool, hyp, v, f'k{i % 50}'), _row(pool, H.PLACEBO, placebo_value, f'k{i % 50}')]
            created[pool] = low + i
        docs.append(dict(schema=H.SCHEMA, hypotheses_sha256=C.FROZEN_HYPOTHESES_SHA256, latency_slots=4, source='export',
                         evaluation=[low, high], rows=rows_))
        slots.append(dict(schema=C.SCHEMA_SLOTS, s0=s0, evaluation=[low, high], slots=created))
    return docs, slots


def _lat10(docs, value=None):
    out = json.loads(json.dumps(docs))
    for d in out:
        d['latency_slots'] = 10
        if value is not None:
            for r in d['rows']:
                for cell in r['horizons'].values():
                    cell['value'] = value
    return out


def _v(hyp, docs, slots, **kw):
    if hyp == 'HW1-5':
        kw.setdefault('latency10_docs', _lat10(docs))
    return C.verdict(hyp, docs, slots, **kw)


def test_net_rent_lost_on_the_stake_and_the_strict_migrated_convention():
    r = _row('a', 'HW1-5', 105_000_000, 'k')
    assert C.net(r, '10', None) == pytest.approx((105_000_000 - COST - RENT) / STAKE)
    assert C.net(r, '10', None, 'closed') == pytest.approx((105_000_000 - COST - 105_000) / STAKE)
    m = _row('b', 'HW1-5', None, 'k', migrated=True)
    assert C.net(m, '10', None) == C.net(m, '10', None, 'closed') == pytest.approx((-COST - RENT) / STAKE)
    with pytest.raises(C.CbError, match='token_class_unknown_for_a_position'):
        C.net(r, '10', {})                                                       # census without this pool
    g, curve, tx, rent, n = C.decomposition_lamports(r, '10', None)
    assert g - curve - tx - rent == n and rent == RENT and tx == 210_000


def test_horizon_is_the_frozen_one():
    assert C._horizon('HW1-5') == '10' and C._horizon('HW1-4') == '120' and C._horizon('HW1-1') == '25'
    with pytest.raises(C.CbError, match='unknown_hypothesis'):
        C._horizon('HW1-9')


def test_verdict_go_and_decisions(few_draws):
    docs, slots = _docs(440, 106_000_000)
    out = _v('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR)
    assert out['decision'] == 'GO' and all(out['conditions'].values()) and out['frozen_mode'] == 'rent_lost'
    assert out['paired_placebo']['pairs'] == 440 and out['horizon_s'] == 10 and out['seed'] == int('cdcdcdcd', 16)
    assert out['mean_net_return'] == pytest.approx((106_000_000 - COST - RENT) / STAKE)
    assert out['published_apart']['closed_account_mode'] > out['mean_net_return']
    assert out['halves']['cut_slot'] == W.evaluation_range(S0)[0] + W.WINDOW_SLOTS
    assert _v('HW1-5', *_docs(400, 106_000_000), freeze_anchor_sha256=ANCHOR)['decision'] == 'INCONCLUSIVE'
    bad = _v('HW1-5', *_docs(440, 106_000_000, bad_half=True), freeze_anchor_sha256=ANCHOR)
    assert bad['decision'] == 'NO-GO' and bad['conditions']['c3_both_halves_positive'] is False
    same = _v('HW1-5', *_docs(440, 106_000_000, placebo_value=106_000_000), freeze_anchor_sha256=ANCHOR)
    assert same['conditions']['c2_superiority_to_paired_placebo'] is False and same['decision'] == 'NO-GO'
    loss = _v('HW1-5', *_docs(440, 100_000_000), freeze_anchor_sha256=ANCHOR)
    assert loss['conditions']['c1_profitability'] is False


def test_halves_use_the_creation_slot_not_the_window(few_draws):
    docs, slots = _docs(440, 106_000_000)
    for pool in list(slots[1]['slots']):                       # every pool of window 2 created in its first half
        slots[1]['slots'][pool] = slots[0]['evaluation'][0] + 5
    out = _v('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR)
    assert out['halves']['means'][1] is None and out['conditions']['c3_both_halves_positive'] is False


def test_guards(few_draws):
    kw = dict(freeze_anchor_sha256=ANCHOR)
    docs, slots = _docs(40, 106_000_000)
    docs[0]['hypotheses_sha256'] = '0' * 64
    with pytest.raises(C.CbError, match='rows_not_from_the_frozen_hypotheses'):
        _v('HW1-5', docs, slots, **kw)
    docs, slots = _docs(40, 106_000_000)
    docs[1]['latency_slots'] = 10
    with pytest.raises(C.CbError, match='rows_not_the_4_slot_export_run'):
        _v('HW1-5', docs, slots, **kw)
    docs, slots = _docs(40, 106_000_000)
    slots[1]['s0'] += W.WINDOW_SLOTS
    with pytest.raises(C.CbError, match='creation_slots_of_another_window|windows_not_consecutive'):
        _v('HW1-5', docs, slots, **kw)
    docs, slots = _docs(40, 106_000_000)
    slots[1]['slots']['p0-0'] = 1
    with pytest.raises(C.CbError, match='a_pool_in_two_windows'):
        _v('HW1-5', docs, slots, **kw)
    docs, slots = _docs(40, 106_000_000)
    del slots[0]['slots']['p0-0']
    with pytest.raises(C.CbError, match='a_position_without_creation_slot'):
        _v('HW1-5', docs, slots, **kw)
    with pytest.raises(C.CbError, match='one_creation_slots_file_per_rows_file'):
        C.verdict('HW1-5', *(lambda d, s: (d, s[:1]))(*_docs(40, 106_000_000)), latency10_docs=[], **kw)
    with pytest.raises(C.CbError, match='freeze_anchor_sha256_required'):
        _v('HW1-5', *_docs(40, 106_000_000), freeze_anchor_sha256='x')


def test_real_statelab_rows_and_creation_slots_on_the_frozen_pack(tmp_path, monkeypatch, capsys):
    """The frozen statelab export of the pack, plus creation-slots, through the CLI verdict (INCONCLUSIVE, n tiny)."""
    monkeypatch.setattr(W, 'DRAWS', 50)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    low, high = W.evaluation_range(PACK_S0)
    doc = H.run_export(PACK, sha, evaluation=(low, high))
    assert doc['hypotheses_sha256'] == C.FROZEN_HYPOTHESES_SHA256 and doc['counts']['HW1-5']['positions'] == 1
    rows = tmp_path / 'rows.json'
    rows.write_text(json.dumps(doc))
    slow = tmp_path / 'rows10.json'
    slow.write_text(json.dumps(H.run_export(PACK, sha, evaluation=(low, high), latency_slots=10)))
    assert C.main(['creation-slots', '--pools', str(PACK), '--manifest-sha256', sha, '--s0', str(PACK_S0),
                   '--out', str(tmp_path / 's')]) == 0
    printed = json.loads(capsys.readouterr().out)
    slots_file = tmp_path / 's' / 'W2_CB_CREATION_SLOTS.json'
    slots = json.loads(slots_file.read_text())
    assert printed['pools'] == 3 and 'value' not in slots_file.read_text()
    args = ['verdict', '--hypothesis', 'HW1-5', '--rows', str(rows), '--rows-sha256', hashlib.sha256(rows.read_bytes()).hexdigest(),
            '--creation-slots', str(slots_file), '--freeze-anchor-sha256', ANCHOR,
            '--latency10', str(slow), '--latency10-sha256', hashlib.sha256(slow.read_bytes()).hexdigest()]
    with pytest.raises(C.CbError, match='creation_slots_are_not_the_anchored_ones'):
        C.main([*args, '--creation-slots-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    assert C.main([*args, '--creation-slots-sha256', hashlib.sha256(slots_file.read_bytes()).hexdigest(),
                   '--out', str(tmp_path / 'v')]) == 0
    out = json.loads((tmp_path / 'v' / 'W2_CB_VERDICT.json').read_text())
    hw15 = [r for r in doc['rows'] if r['hypothesis'] == 'HW1-5'][0]
    assert out['n'] == 1 and out['decision'] == 'INCONCLUSIVE' and out['paired_placebo']['pairs'] == (
        1 if any(r['hypothesis'] == H.PLACEBO and r['pool'] == hw15['pool'] for r in doc['rows']) else 0)
    assert out['mean_net_return'] == pytest.approx(C.net(hw15, '10', None)) and '"pool' not in json.dumps(out)
    assert slots['slots'][hw15['pool']] >= low


def test_the_placebo_is_paired_by_pool(few_draws):
    """Values that vary across pools, a constant paired gap: the paired lower bound is exactly that gap."""
    docs, slots = _docs(440, 106_000_000)
    for d in docs:
        by_pool = {}
        for r in d['rows']:
            by_pool.setdefault(r['pool'], []).append(r)
        for i, (pool, pair) in enumerate(sorted(by_pool.items())):
            base = 90_000_000 + (i * 7_919) % 30_000_000
            for r in pair:
                r['horizons']['10']['value'] = base + (500_000 if r['hypothesis'] == 'HW1-5' else 0)
    out = _v('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR)
    assert out['lower_bound_minus_paired_placebo'] == pytest.approx(500_000 / STAKE)


def test_creation_slots_keep_the_window_only(tmp_path):
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    doc = C.creation_slots(PACK, sha, PACK_S0 + 3 * W.WINDOW_SLOTS)
    assert doc['slots'] == {} and doc['evaluation'] == list(W.evaluation_range(PACK_S0 + 3 * W.WINDOW_SLOTS))
    with pytest.raises(C.CbError, match='manifest_is_not_the_anchored_one'):
        C.creation_slots(PACK, '0' * 64, PACK_S0)



def test_condition_5_of_hw1_5(few_draws):
    docs, slots = _docs(440, 106_000_000)
    with pytest.raises(C.CbError, match='hw1_5_needs_the_latency10_rows'):
        C.verdict('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR)
    ok = _v('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR)
    assert ok['conditions']['c5_section_3'] is True and ok['decision'] == 'GO'
    slow_loss = _v('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR, latency10_docs=_lat10(docs, 100_000_000))
    assert slow_loss['conditions']['c5_section_3'] is False and slow_loss['decision'] == 'NO-GO'
    assert slow_loss['published_apart']['latency_10_slots'] < 0
    bad10 = _lat10(docs)
    bad10[0]['latency_slots'] = 4
    with pytest.raises(C.CbError, match='latency10_rows_are_not_the_10_slot_run_of_the_same_windows'):
        C.verdict('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR, latency10_docs=bad10)


def test_condition_5_without_the_5_best_pools(few_draws):
    docs, slots = _docs(440, 102_200_000)            # each position barely negative ...
    for d in docs[:1]:
        for r in [r for r in d['rows'] if r['hypothesis'] == 'HW1-5'][:5]:
            r['horizons']['10']['value'] = 400_000_000   # ... and 5 huge winners carry the mean
    out = _v('HW1-5', docs, slots, freeze_anchor_sha256=ANCHOR, latency10_docs=_lat10(docs, 106_000_000))
    assert out['mean_net_return'] > 0 and out['published_apart']['without_best_5_pools'] < 0
    assert out['conditions']['c5_section_3'] is False and out['decision'] == 'NO-GO'


def test_condition_5_passes_for_another_hypothesis(few_draws):
    docs, slots = _docs(440, 106_000_000, hyp='HW1-4')
    for d in docs:
        for r in d['rows']:
            r['horizons'] = {'120': r['horizons']['10']}
    out = C.verdict('HW1-4', docs, slots, freeze_anchor_sha256=ANCHOR)
    assert out['conditions']['c5_section_3'] is True and out['horizon_s'] == 120 and out['decision'] == 'GO'
