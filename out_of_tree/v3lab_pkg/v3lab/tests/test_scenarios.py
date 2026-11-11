"""v3lab.scenarios: token-class filters and rent on hand-made rows."""
import pytest

from v3lab import scenarios
from v3lab.tests.test_tables import bundle, pool

RENT_SPL, RENT_T22 = 2_039_280, 2_074_080


def census(**classes):
    rent = dict(executable_now=RENT_SPL, token2022_allowlisted=RENT_T22, refused=RENT_T22)
    return dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[],
                rows=[dict(pool=p, class_=c, our_account_rent_lamports=rent[c]) for p, c in classes.items()])


ROWS = [pool('p1', 'validation', 'closed', 30_000_000, 30), pool('p2', 'validation', 'closed', -50_000_000, 10),
        pool('p3', 'validation', 'closed', -20_000_000, 20), pool('p4', 'validation', 'closed', 1_000_000, 40),
        pool('p6', 'validation', 'no_entry', None, None, entered=False)]
CLASSES = census(p1='executable_now', p2='token2022_allowlisted', p3='refused', p4='executable_now',
                 p6='executable_now')


def test_executable_now_keeps_spl_entries_only_and_counts_rent():
    out = scenarios.scenarios({'V3-01': bundle(ROWS)}, CLASSES)
    now = out['scenarios']['executable_now']['V3-01']['segments']['validation']
    assert (now['trades'], now['closed']) == (2, 2)
    assert now['pnl_sol'] == 0.031 and now['rent_sol'] == 2 * RENT_SPL / 1e9
    assert now['pnl_with_rent_sol'] == (31_000_000 - 2 * RENT_SPL) / 1e9
    assert now['pnl_with_rent_pct'] == pytest.approx(100 * (31_000_000 - 2 * RENT_SPL) / (2 * 100_210_000 + 2 * RENT_SPL))
    # the small winner (+1,000,000) turns into a loss once the rent is counted
    assert now['win_rate_with_rent_pct'] == 50.0
    assert out['excluded_entries']['V3-01'] == {'refused': 1}


def test_experimental_adds_allowlisted_token2022_entries_with_their_rent():
    out = scenarios.scenarios({'V3-01': bundle(ROWS)}, CLASSES)
    exp = out['scenarios']['experimental']['V3-01']['segments']['validation']
    assert (exp['trades'], exp['closed']) == (3, 3)
    assert exp['rent_sol'] == (2 * RENT_SPL + RENT_T22) / 1e9
    assert exp['pnl_with_rent_sol'] == (-19_000_000 - 2 * RENT_SPL - RENT_T22) / 1e9


def test_unknown_pools_are_excluded_and_a_bad_census_is_refused():
    out = scenarios.scenarios({'V3-01': bundle(ROWS)}, census(p1='executable_now'))
    assert out['excluded_entries']['V3-01'] == {'unknown': 3}
    with pytest.raises(ValueError):
        scenarios.scenarios({'V3-01': bundle(ROWS)}, dict(CLASSES, disagreements_with_frozen_reader=['p2']))
    assert '### executable_now' in scenarios.markdown(out)


def test_difference_is_experimental_minus_executable_and_exclusions_carry_reasons():
    census = CLASSES
    census['rows'][2]['reasons'] = ['extension_refused:TransferFeeConfig']
    out = scenarios.scenarios({'V3-01': bundle(ROWS)}, census)
    d = out['difference_experimental_minus_executable']['V3-01']['validation']
    assert (d['trades'], d['closed']) == (1, 1)
    assert d['pnl_with_rent_sol'] == pytest.approx((-50_000_000 - RENT_T22) / 1e9)
    assert out['excluded_reasons']['V3-01'] == {'extension_refused:TransferFeeConfig': 1}
    assert 'Différence expérimentale' in scenarios.markdown(out)


def test_cleanup_variant_costs_only_the_cleanup_fee():
    out = scenarios.scenarios({'V3-01': bundle(ROWS)}, CLASSES)
    now = out['scenarios']['executable_now']['V3-01']['segments']['validation']
    assert now['pnl_with_cleanup_sol'] == (31_000_000 - 2 * scenarios.CLEANUP_FEE_LAMPORTS) / 1e9
    assert now['pnl_with_cleanup_sol'] > now['pnl_with_rent_sol']
    assert now['win_rate_with_cleanup_pct'] == 100.0          # the small winner stays a winner
    d = out['difference_experimental_minus_executable']['V3-01']['validation']
    assert d['pnl_with_cleanup_sol'] == pytest.approx((-50_000_000 - scenarios.CLEANUP_FEE_LAMPORTS) / 1e9)


def test_labels_required_by_r02_h3_h4_h5():
    out = scenarios.scenarios({'V3-01': bundle(ROWS)}, CLASSES)
    seg = out['scenarios']['executable_now']['V3-01']['segments']['validation']
    assert seg['conclusive_sample'] is False and 'NOT executable today' in seg['with_cleanup_label']
    notes = ' '.join(out['notes'])
    assert 'NON CONCLUSIVE' in notes and 'NC-1' in notes and 'E-2' in notes and '34 trials' in notes
    text = scenarios.markdown(out)
    assert 'NON exécutable aujourd’hui' in text and '| NON |' in text
