"""v3lab.tables: sums of the owner's profitability table on hand-made rows."""
from v3lab import tables


def pool(name, segment, outcome, pnl, exit_slot, *, entered=True, cost=100_210_000, immediate=96_000_000):
    trade = dict(entry_index=0 if entered else None, outcome=outcome, spent=100_000_000, tx_costs=210_000,
                 failed_attempt_costs=0, pnl_lamports=pnl if outcome == 'closed' else None, exit_slot=exit_slot)
    return dict(pool=name, creator='c' + name[-1], segment=segment, trade=trade,
                v3=dict(cost_lamports=cost, immediate_mark=immediate) if entered else {})


def bundle(rows, trial='V3-01'):
    return dict(trial=trial, role='reference', policy='p', bundle_sha256='x', pools=rows)


ROWS = [pool('p1', 'validation', 'closed', 30_000_000, 30), pool('p2', 'validation', 'closed', -50_000_000, 10),
        pool('p3', 'validation', 'closed', -20_000_000, 20), pool('p4', 'validation', 'closed', 10_000_000, 40),
        pool('p5', 'validation', 'counterfactual_divergence', None, None),
        pool('p6', 'validation', 'no_entry', None, None, entered=False),
        pool('p7', 'train', 'closed', 5_000_000, 5)]


def test_sums_of_one_segment():
    r = tables.row(bundle(ROWS), 'validation')
    assert (r['trades'], r['closed'], r['non_closed']) == (5, 4, {'counterfactual_divergence': 1})
    assert r['pnl_sol'] == -0.03 and abs(r['capital_sol'] - 0.40084) < 1e-12
    assert abs(r['pnl_pct'] - 100 * -30_000_000 / 400_840_000) < 1e-12
    assert r['win_rate_pct'] == 50.0 and r['profit_factor'] == 40 / 70
    # realised in the order of the exit slots: -50, -70, -40, -30 (millions): the fall from 0 to -70 is the drawdown
    assert r['max_drawdown_sol'] == 0.07 and r['max_drawdown_stakes'] == 0.7
    assert abs(r['tx_costs_sol'] - 5 * 210_000 / 1e9) < 1e-15
    assert abs(r['round_trip_cost_pct'] - 100 * 4_210_000 / 100_210_000) < 1e-12
    assert abs(r['pnl_if_non_closed_lost_sol'] - (-0.03 - 0.10021)) < 1e-12


def test_a_row_outside_the_visible_segments_is_refused():
    import pytest
    for segment in ('holdout', None, 'embargoed'):
        with pytest.raises(ValueError):
            tables.row(bundle(ROWS + [pool('p9', segment, 'closed', 1, 1)]), 'validation')


def test_drawdown_after_a_peak_and_empty_segment():
    rows = [pool('a1', 'train', 'closed', 40_000_000, 1), pool('a2', 'train', 'closed', -10_000_000, 2),
            pool('a3', 'train', 'closed', -25_000_000, 3), pool('a4', 'train', 'closed', 50_000_000, 4)]
    r = tables.row(bundle(rows), 'train')
    assert r['max_drawdown_sol'] == 0.035 and r['profit_factor'] == 90 / 35
    empty = tables.row(bundle(rows), 'exploration')
    assert empty['trades'] == 0 and empty['pnl_pct'] is None and empty['profit_factor'] is None


def test_document_compares_with_the_reference_and_renders():
    candidate = [dict(p, trade=dict(p['trade'], pnl_lamports=(p['trade']['pnl_lamports'] or 0) + 10_000_000
                                    if p['trade']['outcome'] == 'closed' else None)) for p in ROWS]
    document = tables.tables({'V3-01': bundle(ROWS), 'V3-03': bundle(candidate, 'V3-03')})
    seg = document['trials']['V3-03']['segments']['validation']
    assert abs(seg['vs_reference']['pnl_sol'] - 0.04) < 1e-12
    assert document['trials']['V3-01']['segments']['all_visible']['trades'] == 6
    text = tables.markdown(document)
    assert text.count('\n') == 2 + 2 * 4 and '| V3-03 | validation | 5 | 4 |' in text
