"""Grouped chronological holdouts and exact label availability, without market data."""
import csv
import random
from unittest.mock import patch

import pytest

from bot.analyser import research_pipeline as research, behavior_pipeline as behavior
from bot.analyser.temporal_split import temporal_partition


def sample(tmp_path, count=50, spacing=10000, paired=False, tied=False,
           hold=3600, delayed_index=None, missing_index=None):
    events = [(1000 + (0 if tied else (i // 2 if paired else i) * spacing),
               'shared' if tied else f'sig{i // 2 if paired else i:03}',
               'creator', f'mint{i:03}', f'pool{i:03}') for i in range(count)]
    path = tmp_path / 'synthetic-prices.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['mint', 'timestamp', 'price_usd'])
        for i, (when, _, _, mint, _) in enumerate(events):
            if i == missing_index:
                continue
            values = [(when + 60, 1), (when + 300, 1.1), (when + 900, 1.3),
                      (when + 60 + hold + (100 if i == delayed_index else 0), 1.5)]
            for timestamp, price in sorted(set(values)):
                writer.writerow([mint, timestamp, price])
    return events, path


def run_path(name, events, path, **kwargs):
    with patch.object(research, 'verified_launches', return_value=events), \
            patch.object(behavior, 'verified_launches', return_value=events), \
            patch.object(behavior, 'load_cached_transactions', return_value=[]):
        function = {'basic': research.backtest, 'momentum': research.momentum_backtest,
                    'behavior': behavior.behavior_backtest}[name]
        return function(':memory:', path, **kwargs)


@pytest.mark.parametrize('name', ['basic', 'momentum', 'behavior'])
@pytest.mark.parametrize('paired,expected', [(False, (35, 15)), (True, (34, 16))])
def test_real_backtest_paths_preserve_groups_and_minima(tmp_path, name, paired, expected):
    events, path = sample(tmp_path, paired=paired)
    result = run_path(name, events, path)
    assert (result['train'], result['test']) == expected
    info = result['temporal_split']
    assert info['max_train_label_time'] < info['test_period_started_at']
    assert info['purged_train_observations'] == 0
    assert result['train'] >= 30 and result['test'] >= 15


@pytest.mark.parametrize('name', ['basic', 'momentum', 'behavior'])
def test_one_timestamp_never_becomes_two_eligible_periods(tmp_path, name):
    events, path = sample(tmp_path, tied=True)
    if name == 'behavior':
        result = run_path(name, events, path)
        assert result['status'] == 'insufficient_data' and result['train'] == 0
    else:
        with pytest.raises(ValueError, match='insuffisant'):
            run_path(name, events, path)


@pytest.mark.parametrize('name', ['basic', 'momentum', 'behavior'])
def test_dense_training_labels_are_purged_not_moved_to_test(tmp_path, name):
    events, path = sample(tmp_path, count=60, spacing=10)
    if name == 'behavior':
        result = run_path(name, events, path)
        assert result['status'] == 'insufficient_data'
        assert result['train'] == 0 and result['test'] == 18
        assert result['temporal_split']['purged_train_observations'] == 42
    else:
        with pytest.raises(ValueError, match='insuffisant'):
            run_path(name, events, path)


@pytest.mark.parametrize('missing_first_test', [False, True])
def test_actual_delayed_quote_and_raw_test_boundary_control_purge(tmp_path, missing_first_test):
    count = 60 if missing_first_test else 50
    cut = int(count * .7)
    events, path = sample(tmp_path, count=count, spacing=1000, hold=880,
        delayed_index=cut - 1, missing_index=cut if missing_first_test else None)
    result = run_path('basic', events, path, hold_seconds=880)
    assert result['train'] == cut - 1
    assert result['test'] == count - cut - int(missing_first_test)
    info = result['temporal_split']
    assert info['test_period_started_at'] == events[cut][0]
    assert info['purged_train_observations'] == 1
    # Configured exit target is before the boundary; its actual quote is after.
    assert events[cut - 1][0] + 60 + 880 < events[cut][0]
    assert info['max_train_label_time'] < events[cut][0]


def test_label_at_boundary_is_not_assumed_known_before_it():
    events = [(i * 100, f's{i}', 'c', f'm{i}', 'p') for i in range(10)]
    ends = {e[3]: e[0] + 100 for e in events}
    train, test, info = temporal_partition(events, ends)
    assert len(train) == 6 and len(test) == 3
    assert info['purged_train_observations'] == 1
    assert max(ends[e[3]] for e in train) < info['test_period_started_at']


@pytest.mark.parametrize('seed', range(20))
def test_partition_is_deterministic_and_never_splits_transitive_groups(seed):
    generator = random.Random(seed)
    events = [(1000 + (i // 2) * 100, f's{i // 2}', 'c', f'm{i}', 'p') for i in range(20)]
    # A signature with inconsistent times bridges otherwise separate groups.
    events[8] = (*events[8][:1], events[4][1], *events[8][2:])
    ends = {e[3]: e[0] + generator.randrange(0, 500) for e in events}
    expected = temporal_partition(events, ends)
    generator.shuffle(events)
    assert temporal_partition(events, ends) == expected
    train, test, info = expected
    assert not ({e[1] for e in train} & {e[1] for e in test})
    assert not ({e[0] for e in train} & {e[0] for e in test})
    assert all(ends[e[3]] < info['test_period_started_at'] for e in train)
    assert not ({e[3] for e in train} & {e[3] for e in test})


@pytest.mark.parametrize('fraction', [0, 1, -1, 2, float('nan'), float('inf'), True, None])
def test_invalid_fractions_cannot_bypass_partition(fraction):
    with pytest.raises(ValueError):
        temporal_partition([], {}, fraction)


@pytest.mark.parametrize('end', [True, 1.5, -1, float('nan')])
def test_invalid_label_dates_are_not_imputed(end):
    with pytest.raises(ValueError):
        temporal_partition([(0, 's0', 'c', 'm0', 'p'), (10, 's1', 'c', 'm1', 'p')], {'m0': end})


def test_minimum_training_size_is_checked_after_purge(tmp_path):
    events, path = sample(tmp_path, count=47, spacing=1000, hold=3000)
    with pytest.raises(ValueError, match='29 entraînement'):
        run_path('basic', events, path, hold_seconds=3000)


def test_creator_returns_require_exit_strictly_before_observation():
    rows = [dict(creator='a', gross_return=.2, exit_time=100),
            dict(creator='a', gross_return=.4, exit_time=200),
            dict(creator='b', gross_return=99, exit_time=1)]
    assert behavior._causal_creator_mean(rows, 'a', 100) is None
    assert behavior._causal_creator_mean(rows, 'a', 200) == pytest.approx(.2)
    assert behavior._causal_creator_mean(rows, 'a', 201) == pytest.approx(.3)


def test_noncausal_price_windows_are_rejected():
    event = (1000, 's', 'c', 'm', 'p')
    prices = {'m': [(1060, 1), (1300, 1.1), (1900, 1.2)]}
    assert research.momentum_observation(event, prices, entry_delay=900, exit_delay=300) is None
    assert behavior.behavior_observation(event, prices, [], entry_delay=900, exit_delay=300) is None



def test_duplicate_mint_cannot_share_one_outcome_between_periods():
    with pytest.raises(ValueError, match='Duplicate temporal mint'):
        temporal_partition([(100, 's1', 'c', 'same', 'p'), (200, 's2', 'c', 'same', 'p')],
                           {'same': 150})
