"""plbench 0.2: the economic verdict of R02's frozen rules (section 3.2) and the closed vocabulary (R-0.1, R-0.2)."""
import json

import pytest

from bot.p4 import sol_usd_series as sus
from paperstream.tests.test_engine import PACK
from plbench import bench as B
from w1aux import dayj
from w2arms import ce as W

SHEET = '1234abcd' + 'e' * 56


def cycles(n, creators, value=lambda i: 0.05 + 0.001 * (i % 7), one=None, receipt=True):
    return [dict(pool='p%03d' % i, creator='c%02d' % (i % creators), net_return=value(i),
                 net_return_1_failure=(one(i) if one else value(i) - 0.002), cycle_receipt=receipt) for i in range(n)]


def test_negative_when_the_upper_bound_is_below_zero():
    out = B.economic_verdict(cycles(60, 25, value=lambda i: -0.05 + 0.001 * (i % 5)), SHEET, draws=500)
    assert out['verdict'] == 'NÉGATIF' and out['upper_bound_95'] < 0 and out['population'] == 60


def test_positive_in_paper_needs_every_condition():
    good = B.economic_verdict(cycles(60, 25), SHEET, draws=500)
    assert good['verdict'] == 'POSITIF EN PAPER' and good['lower_bound_95'] > 0 and good['creators'] == 25
    assert B.economic_verdict(cycles(49, 25), SHEET, draws=500)['verdict'] == 'INCONCLUSIF'        # < 50 cycles
    assert B.economic_verdict(cycles(60, 19), SHEET, draws=500)['verdict'] == 'INCONCLUSIF'        # < 20 creators
    assert B.economic_verdict(cycles(60, 25, one=lambda i: -0.01), SHEET, draws=500)['verdict'] == 'INCONCLUSIF'
    mixed = cycles(60, 25, value=lambda i: 0.3 if i % 2 else -0.29)                               # bound straddles 0
    assert B.economic_verdict(mixed, SHEET, draws=500)['verdict'] == 'INCONCLUSIF'
    slightly_negative = cycles(60, 25, value=lambda i: 0.29 if i % 2 else -0.3)                 # mean < 0, upper >= 0
    out = B.economic_verdict(slightly_negative, SHEET, draws=500)
    assert out['mean_net_return'] < 0 <= out['upper_bound_95'] and out['verdict'] == 'INCONCLUSIF'


def test_only_cycles_with_a_receipt_count():
    rows = cycles(60, 25) + cycles(40, 10, value=lambda i: -0.9, receipt=False)
    out = B.economic_verdict(rows, SHEET, draws=500)
    assert out['population'] == 60 and out['excluded_without_receipt'] == 40 and out['verdict'] == 'POSITIF EN PAPER'
    none = B.economic_verdict(cycles(60, 25, receipt=False), SHEET, draws=500)
    assert none['verdict'] == 'INCONCLUSIF' and none['population'] == 0 and none['lower_bound_95'] is None


def test_the_bootstrap_is_the_audited_one_grouped_by_creator_with_the_sheet_seed():
    rows = cycles(60, 25, value=lambda i: ((i * 37) % 23 - 9) / 1000)
    out = B.economic_verdict(rows, SHEET, draws=400)
    groups = {}
    for r in rows:
        groups.setdefault(r['creator'], []).append(r)
    mean = lambda rs: sum(r['net_return'] for r in rs) / len(rs)                 # noqa: E731
    assert out['seed'] == 0x1234abcd
    assert out['lower_bound_95'] == W.lower_bound(groups, mean, seed=0x1234abcd, draws=400, alpha=0.05)
    assert B.ECONOMIC_DRAWS == 10_000 and (B.MIN_QUALIFIED_CYCLES, B.MIN_CREATORS) == (50, 20)
    for bad in ('x', 'AB' * 32, None):
        with pytest.raises(B.BenchError, match='freeze_sheet_sha256_required'):
            B.economic_verdict(rows, bad)


def test_the_closed_vocabulary(tmp_path):
    for word in ('rentable', 'Profitable', 'GAGNANT'):
        with pytest.raises(B.BenchError, match='forbidden_word_in_output'):
            B.assert_closed_vocabulary(dict(note='stratégie %s' % word))
    path = tmp_path / 'series.json'
    dayj._selfcheck_series(path)
    report = B.run_bench(PACK, sus.load_series(path), latency_slots=[2] * 20, freeze_sheet_sha256=SHEET)
    assert report['economic_verdict']['verdict'] == 'INCONCLUSIF' and report['economic_verdict']['population'] == 0
    assert report['economic_claim'] is None and report['cycle_receipts'] == 0
    text = json.dumps(report, ensure_ascii=False).lower()
    assert not any(w in text for w in B.FORBIDDEN_WORDS)
    assert set(B.VERDICTS) == {'NÉGATIF', 'POSITIF EN PAPER', 'INCONCLUSIF'}
