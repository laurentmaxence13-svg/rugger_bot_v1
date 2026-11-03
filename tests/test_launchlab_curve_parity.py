"""Offline tests for tools/launchlab_curve_parity.py (committed SOL fixtures only)."""
import dataclasses
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'launchlab_curve_parity.py'
spec = importlib.util.spec_from_file_location('launchlab_curve_parity', TOOL)
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

from bot.market.collector import load_archive, summarize  # noqa: E402


def _events(entry):
    _, timeline = summarize(load_archive(parity.PACK, entry['pool']))
    return timeline.events


def test_every_supported_fixture_trade_is_reproduced_exactly():
    report = parity.run()
    totals = report['totals']
    assert totals['events'] == 113
    assert totals['supported'] + totals['unsupported'] == totals['events']
    assert totals['matched'] == totals['supported']
    assert totals['mismatches'] == 0 and totals['not_recomputable'] == 0


def test_per_pool_counts_and_fee_schedule():
    expected = {'5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2': (11, 10000),
                'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC': (100, 12500),
                'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r': (2, 18000)}
    for pool in parity.run()['pools']:
        count, rate = expected[pool['pool']]
        assert pool['events'] == count
        assert pool['fee_rate_interval_ppm'] == [rate, rate] == [pool['fee_rate_ppm']] * 2


def test_exact_out_and_bad_pool_status_are_unsupported_not_approximated():
    event = _events(parity.json.loads((parity.PACK / 'MANIFEST.json').read_text())['pools'][0])[0]
    assert parity.classify(event) is None
    assert parity.classify(dataclasses.replace(event, exact_in=False)) == 'exact_out_not_modelled'
    assert parity.classify(dataclasses.replace(event, pool_status=1)) == 'pool_not_in_curve_phase'
    assert parity.classify(dataclasses.replace(event, violations=('x',))).startswith('event_has_violations')


def test_wrong_fee_rate_is_reported_as_mismatch():
    manifest = parity.json.loads((parity.PACK / 'MANIFEST.json').read_text())
    entry = dict(manifest['pools'][1], fee_rate_ppm=12501)
    result = parity.check_pool(entry)
    assert result['mismatches'] or result['not_recomputable']
    assert result['matched'] < result['supported']


def test_cli_exit_code_zero_on_clean_fixtures():
    assert parity.main([]) == 0
