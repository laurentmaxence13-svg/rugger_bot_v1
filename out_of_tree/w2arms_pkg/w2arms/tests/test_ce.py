"""w2arms.ce: window range, rows without returns, the paired placebo, the section 5 verdict, guards."""
import hashlib
import json
from pathlib import Path

import pytest

import bot
from cdgate import gate as CG
from closedacct import model as CA
from w2arms import ce as W

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
PACK_S0 = 464_661_843 - 402_800 - 10          # the frozen pools are created from slot 464 661 843 (dayj _FIRST_SLOT)
ANCHOR = 'ab' * 32
STAKE = 100_000_000


def test_window_range_and_constants():
    assert W.evaluation_range(467_275_745) == (467_678_545, 469_291_345)              # W1, as w1_run.plan
    assert W.evaluation_range(467_275_745 + W.WINDOW_SLOTS)[0] == 469_291_345          # consecutive windows meet
    assert W.WINDOW_SLOTS == 1_612_800 and W.N_MIN == 414 and W.DRAWS == 10_000
    assert W.ALPHA_ONE_SIDED == pytest.approx(0.05 / 3)


def _pack_rows(tmp_path, monkeypatch, *, low=999_999):
    monkeypatch.setattr(CG, 'LOW_TIER_PPM', low)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    assert W.main(['rows', '--pools', str(PACK), '--manifest-sha256', sha, '--s0', str(PACK_S0),
                   '--out', str(tmp_path / 'r')]) == 0
    raw = (tmp_path / 'r' / 'W2_CE_ROWS.json').read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest(), sha


def test_rows_hold_no_return_and_flag_the_tier(tmp_path, monkeypatch, capsys):
    doc, _sha, msha = _pack_rows(tmp_path, monkeypatch)
    printed = json.loads(capsys.readouterr().out)
    kept = [r for r in doc['rows'] if not r['refused']]
    assert kept and printed['counts']['placebo_positions'] == len(kept) == printed['counts']['c_e_positions']
    text = json.dumps(doc)
    for word in ('net', 'return', 'mean'):
        assert f'"{word}' not in text, word                                          # raw outcomes only
    for r in kept:
        assert r['outcome']['cost'] == STAKE + 210_000 and r['rate'] > 0 and r['buy_fee'] == CG.fee_for(STAKE, r['rate'])
        assert r['outcome_latency10'] is not None and W.evaluation_range(PACK_S0)[0] <= r['creation_slot']
    with pytest.raises(W.W2ArmsError, match='manifest_is_not_the_anchored_one'):
        W.main(['rows', '--pools', str(PACK), '--manifest-sha256', '0' * 64, '--s0', str(PACK_S0), '--out', str(tmp_path / 'x')])
    with pytest.raises(W.W2ArmsError, match='output_exists'):
        W.main(['rows', '--pools', str(PACK), '--manifest-sha256', msha, '--s0', str(PACK_S0), '--out', str(tmp_path / 'r')])


def test_rows_are_the_cdgate_placebo_positions(tmp_path, monkeypatch):
    """The same frozen placebo decisions and outcomes as cdgate's low-tier placebo, on the same pools."""
    from latelab import study as LL
    doc, _sha, msha = _pack_rows(tmp_path, monkeypatch)
    low, high = W.evaluation_range(PACK_S0)
    monkeypatch.setattr(LL, 'EVAL_MIN', low)
    monkeypatch.setattr(LL, 'CUT_SLOT', high)
    monkeypatch.setattr(LL, 'EVAL_MAX', high + 1)
    assert CG.main(['--pools', str(PACK), '--manifest-sha256', msha, '--out', str(tmp_path / 'g')]) == 0
    gate = json.loads((tmp_path / 'g' / 'CDGATE.json').read_text())
    kept = [r for r in doc['rows'] if not r['refused']]
    assert gate['placebo_low_tier_descriptive']['n'] == len(kept)
    nets = sorted(LL.net_return(r['outcome']) for r in kept)
    assert gate['placebo_low_tier_descriptive']['mean_net_return'] == pytest.approx(sum(nets) / len(nets))


def test_a_window_outside_the_pools_reads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(CG, 'LOW_TIER_PPM', 999_999)
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    assert W.main(['rows', '--pools', str(PACK), '--manifest-sha256', sha, '--s0', str(PACK_S0 + 3 * W.WINDOW_SLOTS),
                   '--out', str(tmp_path / 'r')]) == 0
    assert json.loads((tmp_path / 'r' / 'W2_CE_ROWS.json').read_text())['rows'] == []


def _row(pool, cluster, slot, value, low_tier=True, migrated=False):
    outcome = dict(migrated=migrated, value=None if migrated else value, cost=STAKE + 210_000,
                   tokens=None if migrated else 1_000, reason=None if migrated else 'clock')
    buy, sell = (CG.fee_for(STAKE, 2_500), 0) if migrated else W.curve_fees(outcome, 2_500)
    return dict(pool=pool, refused=False, cluster=cluster, creation_slot=slot, low_tier=low_tier, rate=2_500,
                outcome=outcome, buy_fee=buy, sell_fee=sell, outcome_latency10=outcome, slippage=0.0)


def _docs(n_c, value_c, *, value_p=90_000_000, n_p=200, k=2, s0=1_000_000_000, bad_half=False):
    low = W.evaluation_range(s0)[0]
    docs = []
    for w in range(k):
        rows_ = []
        for i in range(n_c // k):
            slot = low + w * W.WINDOW_SLOTS + i
            v = value_c if not (bad_half and w == 0) else 95_000_000
            rows_.append(_row(f'c{w}-{i}', f'k{i % 60}', slot, v))
        for i in range(n_p // k):
            rows_.append(_row(f'p{w}-{i}', f'k{i % 60}', low + w * W.WINDOW_SLOTS + i, value_p, low_tier=False))
        docs.append(dict(schema=W.SCHEMA_ROWS, s0=s0 + w * W.WINDOW_SLOTS, evaluation=list(W.evaluation_range(s0 + w * W.WINDOW_SLOTS)),
                         rule=CG.RULE, tier_ppm=CG.LOW_TIER_PPM, latency_slots=4, input={}, rows=rows_))
    return docs


@pytest.fixture
def few_draws(monkeypatch):
    monkeypatch.setattr(W, 'DRAWS', 300)


def test_verdict_go_and_its_published_parts(few_draws):
    out = W.verdict(_docs(440, 104_000_000), freeze_anchor_sha256=ANCHOR, section_6_4_fired=False, section_3_pass=True)
    assert out['decision'] == 'GO' and all(out['conditions'].values()) and out['n'] == 440
    assert out['seed'] == int('abababab', 16) and out['frozen_mode'] == 'closed'
    assert out['mean_net_return'] == pytest.approx(CA.net_return_closed(_row('x', 'k', 0, 104_000_000)['outcome']))
    assert out['published_apart']['rent_lost_mode'] == pytest.approx(CA.net_return_open(_row('x', 'k', 0, 104_000_000)['outcome']))
    assert out['published_apart']['failed_attempts_1'] < out['mean_net_return']
    d = out['decomposition_mean_share_of_stake']
    assert d['gross'] - d['curve_fees'] - d['tx'] - d['rent_or_cleanup'] == pytest.approx(d['net'])
    assert out['halves']['cut_slot'] == W.evaluation_range(1_000_000_000)[0] + 2 * W.WINDOW_SLOTS // 2
    assert out['paired_placebo']['n'] == 440 + 200


def test_verdict_decisions(few_draws):
    kw = dict(freeze_anchor_sha256=ANCHOR, section_3_pass=True)
    assert W.verdict(_docs(440, 104_000_000), section_6_4_fired=True, **kw)['decision'] == 'DESCRIPTIVE'
    assert W.verdict(_docs(400, 104_000_000), section_6_4_fired=False, **kw)['decision'] == 'INCONCLUSIVE'
    bad = W.verdict(_docs(440, 104_000_000, bad_half=True), section_6_4_fired=False, **kw)
    assert bad['decision'] == 'NO-GO' and bad['conditions']['c3_both_halves_positive'] is False
    loss = W.verdict(_docs(440, 99_000_000), section_6_4_fired=False, **kw)
    assert loss['decision'] == 'NO-GO' and loss['conditions']['c1_profitability'] is False
    same = W.verdict(_docs(440, 104_000_000, value_p=104_000_000), section_6_4_fired=False, **kw)
    assert same['conditions']['c2_superiority_to_paired_placebo'] is False and same['decision'] == 'NO-GO'
    s3 = W.verdict(_docs(440, 104_000_000), freeze_anchor_sha256=ANCHOR, section_6_4_fired=False, section_3_pass=False)
    assert s3['decision'] == 'NO-GO' and s3['conditions']['c5_section_3'] is False


def test_verdict_guards(few_draws):
    kw = dict(freeze_anchor_sha256=ANCHOR, section_6_4_fired=False, section_3_pass=True)
    docs = _docs(40, 104_000_000)
    docs[1]['s0'] += 1
    with pytest.raises(W.W2ArmsError, match='windows_not_consecutive'):
        W.verdict(docs, **kw)
    docs = _docs(40, 104_000_000)
    docs[1]['rows'].append(dict(docs[0]['rows'][0]))
    with pytest.raises(W.W2ArmsError, match='a_pool_in_two_windows'):
        W.verdict(docs, **kw)
    docs = _docs(40, 104_000_000)
    docs[0]['rule'] = dict(CG.RULE, clock_s=60)
    with pytest.raises(W.W2ArmsError, match='rows_of_another_rule'):
        W.verdict(docs, **kw)
    with pytest.raises(W.W2ArmsError, match='freeze_anchor_sha256_required'):
        W.verdict(_docs(40, 104_000_000), freeze_anchor_sha256='x', section_6_4_fired=False, section_3_pass=True)


def test_migrated_rows_use_the_strict_convention(few_draws):
    docs = _docs(40, 104_000_000)
    docs[0]['rows'][0] = _row('m', 'k0', docs[0]['rows'][0]['creation_slot'], None, migrated=True)
    m = docs[0]['rows'][0]
    assert W.net(m, 'closed') == pytest.approx((-(STAKE + 210_000) - 2_039_280) / STAKE)
    gross, curve, tx, rent, net_l = W.decomposition_lamports(m, 'closed')
    assert rent == 2_039_280 and gross - curve - tx - rent == net_l                 # no cleanup without a sale


def test_cli_verdict_reads_only_anchored_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(W, 'DRAWS', 50)
    docs = _docs(40, 104_000_000)
    paths, shas = [], []
    for i, d in enumerate(docs):
        p = tmp_path / f'rows{i}.json'
        p.write_text(json.dumps(d))
        paths.append(str(p))
        shas.append(hashlib.sha256(p.read_bytes()).hexdigest())
    s64 = tmp_path / 's64.json'
    s64.write_text(json.dumps(dict(descriptive=False)))
    base = ['verdict', '--rows', *paths, '--freeze-anchor-sha256', ANCHOR, '--section-6-4', str(s64), '--section-3', 'PASS']
    with pytest.raises(W.W2ArmsError, match='rows_are_not_the_anchored_ones'):
        W.main([*base, '--rows-sha256', shas[0], '0' * 64, '--out', str(tmp_path / 'x')])
    with pytest.raises(W.W2ArmsError, match='one_sha256_per_rows_file'):
        W.main([*base, '--rows-sha256', shas[0], '--out', str(tmp_path / 'x')])
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps(dict(fired=True)))
    with pytest.raises(W.W2ArmsError, match='section_6_4_input_must_state_descriptive'):
        W.main(['verdict', '--rows', *paths, '--rows-sha256', *shas, '--freeze-anchor-sha256', ANCHOR,
                '--section-6-4', str(bad), '--section-3', 'PASS', '--out', str(tmp_path / 'x')])
    assert W.main([*base, '--rows-sha256', *shas, '--out', str(tmp_path / 'v')]) == 0
    out = json.loads((tmp_path / 'v' / 'W2_CE_VERDICT.json').read_text())
    assert out['decision'] == 'INCONCLUSIVE' and out['rows_sha256'] == shas and '"pool' not in json.dumps(out)


def test_lower_bound_is_the_one_sided_alpha_quantile():
    import random as R
    groups = {f'g{i}': [i] for i in range(50)}
    stat = (lambda rows_: sum(rows_) / len(rows_))
    got = W.lower_bound(groups, stat, seed=7, draws=1_000)
    rng, values = R.Random(7), []
    keys = sorted(groups)
    for _ in range(1_000):
        picked = [groups[keys[rng.randrange(len(keys))]] for _k in keys]
        values.append(stat([x for g in picked for x in g]))
    values.sort()
    assert got == values[int(W.ALPHA_ONE_SIDED * 1_000) - 1]                    # quantile 1/60, one-sided
    assert W.lower_bound({}, stat, seed=1) is None


def test_rows_replay_at_4_and_at_10_slots(tmp_path, monkeypatch):
    seen = []
    real = W.run_rule

    def spy(timeline, k, actors, model, rule):
        seen.append((model.latency_slots, rule['id']))
        return real(timeline, k, actors, model, rule)
    monkeypatch.setattr(W, 'run_rule', spy)
    _pack_rows(tmp_path, monkeypatch)
    assert seen and set(seen) == {(4, CG.RULE['id']), (10, CG.RULE['id'])} and len(seen) % 2 == 0
