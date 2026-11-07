"""Owner decision of 2026-11-07: Python 3.12 reference interpreter; duplicate MASTER arm out of the comparison.

The historical MASTER arm keeps its code and stays in every bundle, whose fingerprints
do not change; it is only left out of the economic comparison while it duplicates the
reference arm. Reproducible bundles are written under Python 3.12.
"""
from copy import deepcopy
from functools import lru_cache
import importlib.util
import json
from pathlib import Path

import pytest

from bot.p4 import historical_research_replay as hrr

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
DECLARED = dict(sol_usd=150.0, sol_usd_provenance='ASSUMED_DECLARED')
DEFAULT_BUNDLE_SHA = 'fa86f314f015277fc7a84f0124e5a04c4beaef00ab7caec05f91e3d255985270'


@lru_cache(maxsize=None)
def _bundle(**kwargs):
    return hrr.run_replay(PACK, hrr.ReplayParams(**kwargs))


def _cli():
    spec = importlib.util.spec_from_file_location('hrr_cli_dedup', ROOT / 'tools' / 'historical_research_replay.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


@pytest.mark.parametrize('kwargs', [{}, DECLARED, dict(exclude_launchlab_vault=True, **DECLARED)])
def test_duplicate_master_arm_is_excluded_from_the_comparison_only(kwargs):
    doc = _bundle(**kwargs)
    before = json.dumps(doc, sort_keys=True)
    comparison = hrr.economic_comparison(doc)
    assert comparison['arms'] == ['reference']
    assert comparison['excluded'] == [dict(arm='master', duplicate_of='reference', rule=hrr.DUPLICATE_ARM_RULE)]
    assert comparison['totals'] == {'reference': doc['totals']['reference']}
    assert comparison['bundle_sha256'] == doc['bundle_sha256']
    # The bundle keeps both arms and is not modified (historical results unchanged).
    assert set(doc['totals']) == set(hrr.ARMS) and json.dumps(doc, sort_keys=True) == before
    assert all(set(pool['arms']) == set(hrr.ARMS) for pool in doc['pools'])


def test_default_fingerprint_is_unchanged():
    assert _bundle()['bundle_sha256'] == DEFAULT_BUNDLE_SHA


def _diverge(doc, change):
    doc = deepcopy(doc)
    change(doc)
    return hrr.economic_comparison(doc)


def test_an_arm_that_differs_is_compared():
    doc = _bundle(**DECLARED)

    def trade(d):
        d['pools'][0]['arms']['master'] = dict(d['pools'][0]['arms']['master'], outcome='closed')

    def intent(d):
        row = next(r for r in d['pools'][0]['journal'] if r['arm'] == 'master')
        row['intent'] = 'ENTER'

    for change in (trade, intent):
        comparison = _diverge(doc, change)
        assert comparison['arms'] == ['reference', 'master'] and comparison['excluded'] == []
        assert set(comparison['totals']) == {'reference', 'master'}


def test_cli_reports_only_the_compared_arm_and_names_the_excluded_one(capsys, monkeypatch):
    cli = _cli()
    monkeypatch.setattr(cli, 'python_version', lambda: (3, 12, 3))
    cli.main(['--fixtures', str(PACK), '--sol-usd', '150', '--sol-usd-provenance', 'ASSUMED_DECLARED'])
    out = capsys.readouterr().out
    assert 'python 3.12.3 reference=3.12 reproducible=True' in out
    assert '  [reference] decisions=113' in out and '  [master] decisions=' not in out
    assert '  [master] excluded from the economic comparison: duplicate of [reference] (kept in the bundle)' in out
    assert 'master=' not in out.split('bundle_sha256')[0].split('\n', 1)[1]


@pytest.mark.parametrize('version', [(3, 11, 18), (3, 13, 18)])
def test_bundle_files_are_written_under_the_reference_python_only(tmp_path, capsys, monkeypatch, version):
    cli = _cli()
    monkeypatch.setattr(cli, 'python_version', lambda: version)
    out = tmp_path / 'bundle.json'
    with pytest.raises(SystemExit) as excinfo:
        cli.main(['--fixtures', str(PACK), '--out', str(out)])
    assert excinfo.value.code == 2 and not out.exists()
    assert 'non_reference_python:%d.%d.%d' % version in capsys.readouterr().err
    cli.main(['--fixtures', str(PACK)])                     # no file written: allowed, labelled
    assert 'reproducible=False' in capsys.readouterr().out
    cli.main(['--fixtures', str(PACK), '--out', str(out), '--allow-non-reference-python'])
    assert out.exists() and 'reproducible=False' in capsys.readouterr().out


def test_bundle_file_under_the_reference_python(tmp_path, capsys, monkeypatch):
    cli = _cli()
    monkeypatch.setattr(cli, 'python_version', lambda: (3, 12, 12))
    out = tmp_path / 'bundle.json'
    cli.main(['--fixtures', str(PACK), '--out', str(out)])
    assert json.loads(out.read_text('utf-8'))['bundle_sha256'] == DEFAULT_BUNDLE_SHA
    assert 'reproducible=True' in capsys.readouterr().out


def test_reference_interpreter_is_pinned_in_both_offline_ci_suites():
    assert hrr.REFERENCE_PYTHON == (3, 12)
    workflows = ROOT / '.github' / 'workflows'
    isolated = (workflows / 'rugger-isolated-ci.yml').read_text('utf-8')
    offline = (workflows / 'offline-tests.yml').read_text('utf-8')
    assert "python-version: '3.12'" in isolated and "python-version: '3.11'" not in isolated
    assert 'python-version: "3.12"' in offline and 'python-version: "3.13"' not in offline
