"""Legacy profit diagnostics must never qualify as independent OOS evidence."""
import importlib
import json

import pytest

from bot.analyser.paper_trader import eligible_model


ROUTES = [
    ('creator_backtest_v25', 'run_v25_decision_engine'),
    ('creator_backtest_v26', 'run_v25_decision_engine'),
    ('creator_backtest_v26', 'run_v26_launch_selector'),
]


def profitable_rows(*, grouped=False):
    rows = []
    for index in range(30):
        launch = 1000 if grouped else 1000 + index * 1000
        rows.append({
            'n': index + 1, 'mint': f'synthetic-mint-{index}',
            'launch_signature': 'shared-transaction' if grouped else f'sig-{index}',
            'launch_time': launch, 'sale_time': launch + 300,
            'relay': 'synthetic-relay', 'transfer_time': launch + 2,
            'status': 'Vente détectée', 'sale_delay': 300,
            'market_series': [
                {'time': launch + delay, 'price': price}
                for delay, price in [(5, 1), (15, 1.05), (35, 1.1),
                                     (65, 1.2), (100, 1.4), (300, 1.6)]
            ],
        })
    return rows


@pytest.mark.parametrize('module_name,function_name', ROUTES)
@pytest.mark.parametrize('grouped', [False, True])
def test_profitable_legacy_routes_are_excluded_even_with_enough_test_trades(
        module_name, function_name, grouped, capsys, tmp_path):
    module = importlib.import_module('bot.analyser.' + module_name)
    report = getattr(module, function_name)(profitable_rows(grouped=grouped))
    text = capsys.readouterr().out
    assert isinstance(report, dict)
    assert report['validation_status'] == 'excluded_legacy_temporal_integrity'
    assert report['model_eligible'] is False
    assert report['eligible_for_p2'] is False
    assert report['validated'] is False
    assert report['status'] != 'paper_candidate'
    assert report['selected'] >= 5
    assert report['mean_return'] > 0
    assert 'VALIDATION HORS ECHANTILLON' not in text
    assert 'VALIDATION CHRONOLOGIQUE HORS ECHANTILLON' not in text
    assert 'Signal positif hors échantillon' not in text
    assert 'signal hors échantillon positif' not in text
    assert 'DIAGNOSTIC HERITE NON VALIDE' in text
    # Profitability/sample-size alone cannot promote these reports to a model.
    artifact = tmp_path / 'legacy-report.json'
    artifact.write_text(json.dumps(dict(report, train=100, test=100,
                                       selected=100, mean_return=1)), encoding='utf-8')
    with pytest.raises(ValueError):
        eligible_model(artifact)


@pytest.mark.parametrize('module_name,function_name', ROUTES)
def test_insufficient_legacy_data_keeps_explicit_exclusion(
        module_name, function_name, capsys):
    module = importlib.import_module('bot.analyser.' + module_name)
    report = getattr(module, function_name)([])
    capsys.readouterr()
    assert report['status'] == 'insufficient_data'
    assert report['selected'] == 0
    assert report['model_eligible'] is False
    assert report['eligible_for_p2'] is False
    assert report['validated'] is False
    assert report['exclusion_reasons']
