"""statelab.signals: rank correlation, thirds, declared K and the screening on hand-made rows."""
import pytest

from statelab import points, signals
from statelab.tests.test_statelab import COST, RENT, _document, _row


def _rows(n=60, *, signal=lambda i: i, value=lambda i: 90_000_000 + 400_000 * i, creators=None):
    rows = []
    for i in range(n):
        row = _row('p%03d' % i, [['age', 5]], value(i))
        row['features'] = {name: 1 for name in signals.FEATURES}
        row['features']['trades'] = signal(i)
        row['features']['sells'] = None if i % 2 else 5                 # half missing, constant otherwise
        if creators:
            row['creator'] = creators(i)
        rows.append(row)
    rows.append(dict(_row('other', [['age', 15]], 10 ** 9), features={name: 9 for name in signals.FEATURES}))
    return rows


def test_ranks_and_spearman():
    assert signals.ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0]
    assert signals.spearman([1, 2, 3, 4], [10, 20, 25, 99]) == pytest.approx(1.0)
    assert signals.spearman([1, 2, 3, 4], [9, 7, 5, 1]) == pytest.approx(-1.0)
    assert signals.spearman([1, 1, 1], [1, 2, 3]) is None and signals.spearman([1, 2], [1, 2]) is None
    assert signals.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == pytest.approx(0.8)


def test_a_monotone_signal_is_ranked_first_and_retained_with_exact_thirds():
    out = signals.signals(_document(_rows()), declared_k=34, n_boot=2_000)
    assert (out['k'], out['trials_added_to_n'], out['pools'], out['entries'], out['horizon_s']) == (34, 34, 60, 'age:5', 25)
    first = out['signals'][0]
    assert first['signal'] == 'trades' and first['rho'] == pytest.approx(1.0) and first['retained'] is True
    r = lambda i: (90_000_000 + 400_000 * i - COST - RENT) / (COST + RENT)                  # noqa: E731
    thirds = first['thirds']
    assert [thirds[k]['pools'] for k in ('bottom', 'middle', 'top')] == [20, 20, 20]
    assert thirds['bottom']['mean_r'] == pytest.approx(sum(r(i) for i in range(20)) / 20)
    assert thirds['top']['mean_r'] == pytest.approx(sum(r(i) for i in range(40, 60)) / 20)
    assert first['top_minus_bottom'] == pytest.approx(thirds['top']['mean_r'] - thirds['bottom']['mean_r'])
    assert first['top_minus_bottom_ci95'][0] > 0 and thirds['top']['signal_range'] == [40, 59]
    assert out['retained'] == ['trades'] and out['mean_r'] == pytest.approx(sum(r(i) for i in range(60)) / 60)
    by_name = {row['signal']: row for row in out['signals']}
    assert by_name['age_s']['rho'] is None and by_name['age_s']['retained'] is False        # constant signal
    assert by_name['sells']['pools'] == 30 and by_name['sells']['rho'] is None              # missing values dropped
    assert '| 1 | trades | 60 | +1.00 |' in signals.markdown(out) and 'OUI' in signals.markdown(out)


def test_noise_is_not_retained_and_clusters_widen_the_interval():
    noise = lambda i: (i * 37) % 60                                                         # noqa: E731
    out = signals.signals(_document(_rows(signal=noise)), declared_k=34, n_boot=400)
    assert out['retained'] == [] and abs(out['signals'][0]['rho']) < 0.3
    free = signals.signals(_document(_rows()), declared_k=34, n_boot=400)['signals'][0]
    # the same monotone link carried by only three creators: far fewer independent units
    few = signals.signals(_document(_rows(value=lambda i: 90_000_000 + 400_000 * ((i * 7) % 60), creators=lambda i: 'c%d' % (i % 3))),
                          declared_k=34, n_boot=400)['signals'][0]
    wide = signals.signals(_document(_rows(value=lambda i: 90_000_000 + 400_000 * ((i * 7) % 60))), declared_k=34,
                           n_boot=400)['signals'][0]
    assert free['rho_ci95'][1] - free['rho_ci95'][0] < 0.05
    assert few['rho'] == pytest.approx(wide['rho']) and few['rho_ci95'] != wide['rho_ci95']


def test_k_must_be_declared_and_migrated_or_unknown_classes_are_handled():
    document = _document(_rows())
    for bad in (33, None, '34'):
        with pytest.raises(ValueError, match='declared_k_is_not_the_number_of_signals:34'):
            signals.signals(document, declared_k=bad)
    assert signals.K == len(set(signals.FEATURES)) == 34 and points.REFERENCE_CELL == 'age:5'
    rows = _rows()
    rows[0]['horizons']['25'].update(value=None, migrated=True)
    out = signals.signals(_document(rows), declared_k=34, n_boot=0)
    assert out['signals'][0]['thirds']['bottom']['mean_r'] < -0.05                          # the migrated probe counts -1
    census = dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[], rows=[])
    with pytest.raises(ValueError, match='token_class_unknown'):
        signals.signals(_document(_rows()), census, declared_k=34, n_boot=0)
    with pytest.raises(ValueError, match='not_a_statelab_rows_document'):
        signals.signals(dict(document, schema='x'), declared_k=34)


def test_too_few_bootstrap_draws_cannot_retain_anything():
    """With 400 draws the smallest p-value (2 / 401) is above the first BH step (0.10 / 34): nothing passes."""
    out = signals.signals(_document(_rows()), declared_k=34, n_boot=400)
    assert out['signals'][0]['rho'] == pytest.approx(1.0) and out['retained'] == []
    assert signals.N_BOOT >= 2_000
