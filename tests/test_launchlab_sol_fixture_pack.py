"""Committed SOL-quoted pool archives: digests, completeness and exact fee schedules.

Runs fully offline from git alone, so a cloud checkout (which never receives the
git-ignored data/ directory) exercises the same evidence as the local machine.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

from bot.market.collector import load_archive, summarize
from bot.market.launchlab_events import WSOL_MINT

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
MANIFEST = json.loads((PACK / 'MANIFEST.json').read_text(encoding='utf-8'))
REPORT_TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'launchlab_baseline_report.py'


def _fee_rate_interval(events):
    spec = importlib.util.spec_from_file_location('launchlab_baseline_report', REPORT_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fee_rate_interval(events)


def test_every_archive_matches_its_recorded_digest():
    assert len(MANIFEST['pools']) == 3
    for entry in MANIFEST['pools']:
        digest = hashlib.sha256((PACK / entry['file']).read_bytes()).hexdigest()
        assert digest == entry['sha256'], entry['pool']


def test_every_pool_is_complete_sol_quoted_and_matches_the_manifest():
    for entry in MANIFEST['pools']:
        archive = load_archive(PACK, entry['pool'])
        summary, timeline = summarize(archive)
        assert archive.account['mint_quote'] == WSOL_MINT == entry['quote_mint']
        assert summary['complete'] is True, entry['pool']
        assert summary['gaps'] == [] and summary['rejected'] == 0
        assert summary['transactions_missing'] == 0 and summary['undecodable'] == 0
        assert summary['signatures'] == entry['signatures']
        assert summary['trades'] == entry['trades']


def test_each_pool_keeps_one_exact_fee_schedule():
    for entry in MANIFEST['pools']:
        _, timeline = summarize(load_archive(PACK, entry['pool']))
        low, high = _fee_rate_interval(timeline.events)
        assert low == high == entry['fee_rate_ppm'], entry['pool']
