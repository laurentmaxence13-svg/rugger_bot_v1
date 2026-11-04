"""GitHub Actions trigger guard (pure parsing, no network, no secret)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'workflow_trigger_guard.py'
WORKFLOWS = ROOT / '.github' / 'workflows'


def _load_tool():
    spec = importlib.util.spec_from_file_location('workflow_trigger_guard', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_tool()

PROVIDER_PR = """name: Helius probe
on:
  pull_request:
    paths:
      - "bot/live/helius_probe.py"
  workflow_dispatch:
jobs:
  probe:
    runs-on: ubuntu-latest
    env:
      HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
    steps:
      - run: python -m bot.live.helius_probe
"""

MANUAL_ONLY = """name: Helius probe (manual)
# Manual only; uses secrets.HELIUS_API_KEY when an owner dispatches it.
on:
  workflow_dispatch:
jobs:
  probe:
    runs-on: ubuntu-latest
    env:
      HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
    steps:
      - run: python -m bot.live.helius_probe
"""

OFFLINE_CI = """name: Offline test suite
on:
  pull_request:
    paths:
      - "bot/**"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  offline-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - run: python -B tools/offline_check.py -q tests
"""


@pytest.mark.parametrize('text, expected', [
    (PROVIDER_PR, ['pull_request', 'workflow_dispatch']),
    (MANUAL_ONLY, ['workflow_dispatch']),
    ('on: workflow_dispatch\njobs: {}\n', ['workflow_dispatch']),
    ('on: [push, "pull_request"]  # flow sequence\njobs: {}\n', ['push', 'pull_request']),
    ("on: {pull_request: {paths: ['a', 'b']}, workflow_dispatch: {}}\njobs: {}\n",
     ['pull_request', 'workflow_dispatch']),
    ('"on":\n  - push\n  - pull_request\njobs: {}\n', ['push', 'pull_request']),
    ("'on':\n- schedule\njobs: {}\n", ['schedule']),
    ('name: x\n\non:   # triggers\n  # a comment line\n\n  pull_request_target:\n'
     '    types: [labeled]\n  workflow_dispatch: {}\njobs: {}\n',
     ['pull_request_target', 'workflow_dispatch']),
    ('on:\r\n  pull_request:\r\n    types: [labeled]\r\njobs: {}\r\n', ['pull_request']),
])
def test_parse_triggers_reads_every_yaml_form(text, expected):
    assert guard.parse_triggers(text) == expected


@pytest.mark.parametrize('text, reason', [
    ('name: x\njobs:\n  a:\n    with:\n      on: push\n', 'no top-level on'),
    ('on: push\non: pull_request\n', 'several top-level on'),
    ('on: [push, pull_request\n  ]\n', 'flow sequence must end'),
    ('on:\n  push:\n  push:\n', 'duplicate event'),
    ('on:\n  schedule: "0 * * * *"\n', 'unexpected scalar value'),
    ('on:\njobs: {}\n', 'has no event'),
    ('on: ${{ evil }}\n', 'unexpected event name'),
])
def test_unreadable_triggers_fail_closed(text, reason):
    with pytest.raises(guard.TriggerParseError, match=reason):
        guard.parse_triggers(text)
    assert guard.check_workflow('anything.yml', text)[0].startswith('unparseable_on:')


def test_provider_workflow_with_pull_request_is_refused():
    assert guard.check_workflow('helius-probe.yml', PROVIDER_PR) == ['automatic_trigger:pull_request']


def test_manual_only_provider_workflow_is_accepted_even_with_secrets():
    assert guard.check_workflow('helius-probe.yml', MANUAL_ONLY) == []


@pytest.mark.parametrize('trigger', [
    'pull_request:\n    types: [labeled]',
    'pull_request_target:',
    'push:\n    branches: ["review/*"]',
    'schedule:\n    - cron: "43 */6 * * *"',
    'workflow_run:\n    workflows: ["x"]',
    'issue_comment:',
])
def test_any_automatic_event_is_refused_outside_the_ci_allowlist(trigger):
    text = 'on:\n  %s\n  workflow_dispatch:\njobs: {}\n' % trigger
    event = trigger.split(':', 1)[0]
    assert guard.check_workflow('trawl-no-payment-quotes.yml', text) == ['automatic_trigger:%s' % event]


def test_allowlisted_ci_is_accepted_and_cannot_widen_its_events():
    assert guard.check_workflow('offline-tests.yml', OFFLINE_CI) == []
    widened = OFFLINE_CI.replace('  workflow_dispatch:\n', '  workflow_dispatch:\n  pull_request_target:\n')
    assert guard.check_workflow('offline-tests.yml', widened) == ['automatic_trigger:pull_request_target']
    scheduled = OFFLINE_CI.replace('  workflow_dispatch:\n', '  workflow_dispatch:\n  schedule:\n    - cron: "0 0 * * *"\n')
    assert guard.check_workflow('rugger-isolated-ci.yml', scheduled) == ['automatic_trigger:schedule']


@pytest.mark.parametrize('snippet, violation', [
    ('    env:\n      KEY: ${{ secrets.HELIUS_API_KEY }}\n', 'secret_in_automatic_workflow:HELIUS_API_KEY'),
    ("    env:\n      KEY: ${{ secrets['BITQUERY_TOKEN'] }}\n", 'secret_in_automatic_workflow:BITQUERY_TOKEN'),
    ('    secrets: inherit\n', 'secret_in_automatic_workflow:inherit'),
    ('    env:\n      RPC_URL: https://api.mainnet-beta.solana.com\n',
     'external_host_in_automatic_workflow:api.mainnet-beta.solana.com'),
    ('    env:\n      QUOTE_URL: https://trawl.run/api/quote\n', 'external_host_in_automatic_workflow:trawl.run'),
])
def test_automatic_ci_may_not_use_secrets_or_external_hosts(snippet, violation):
    text = OFFLINE_CI.replace('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n' + snippet, 1)
    assert guard.check_workflow('offline-tests.yml', text) == [violation]


def test_github_token_github_or_loopback_urls_and_commented_secrets_are_allowed_in_ci():
    text = OFFLINE_CI.replace(
        '    runs-on: ubuntu-latest\n',
        '    runs-on: ubuntu-latest\n'
        '    # never add secrets.HELIUS_API_KEY or https://mainnet.helius-rpc.com here\n'
        '    env:\n      GH: ${{ secrets.GITHUB_TOKEN }}\n'
        '      DOC: https://github.com/actions/checkout\n'
        '      SMOKE: http://127.0.0.1:8501/healthz\n', 1)
    assert guard.check_workflow('offline-tests.yml', text) == []


def test_scan_directory_and_cli_exit_codes(tmp_path, capsys):
    (tmp_path / 'offline-tests.yml').write_text(OFFLINE_CI, encoding='utf-8')
    (tmp_path / 'helius-manual.yml').write_text(MANUAL_ONLY, encoding='utf-8')
    (tmp_path / 'notes.txt').write_text('on: push\n', encoding='utf-8')
    assert guard.main([str(tmp_path)]) == 0
    assert 'workflows=2 automatic=offline-tests.yml manual_only=1 violations=0' in capsys.readouterr().out
    (tmp_path / 'helius-probe.yaml').write_text(PROVIDER_PR, encoding='utf-8')
    assert guard.main([str(tmp_path)]) == 1
    assert 'VIOLATION helius-probe.yaml: automatic_trigger:pull_request' in capsys.readouterr().out
    assert guard.main([str(tmp_path / 'missing')]) == 2


def test_repository_workflows_respect_the_trigger_invariant():
    """Regression lock for D3: every network/provider workflow stays manual-only."""
    assert WORKFLOWS.is_dir(), 'workflow files must be copied into the offline harness'
    report = guard.scan_directory(WORKFLOWS)
    assert len(report) >= 3
    violations = {name: entry['violations'] for name, entry in report.items() if entry['violations']}
    assert violations == {}
    automatic = {name for name, entry in report.items() if set(entry['events']) - guard.MANUAL_EVENTS}
    assert automatic <= set(guard.AUTOMATIC_WORKFLOWS)
