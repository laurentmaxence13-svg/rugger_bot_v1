"""Helius workflow lock (tools/workflow_trigger_guard.py): reader, rules, real files, mutations.

Offline only: nothing here contacts GitHub or Helius. The canary test runs bash
on a temporary directory with a fake key.
"""
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'
_spec = importlib.util.spec_from_file_location('workflow_trigger_guard', ROOT / 'tools' / 'workflow_trigger_guard.py')
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

FAKE_KEY = '0123abcd-4567-89ef-0123-456789abcdef'
GATE_LINES = """    if: >-
      github.event_name == 'workflow_dispatch' &&
      github.ref == 'refs/heads/main' &&
      github.repository == 'laurentmaxence13-svg/rugger_bot_v1' &&
      vars.HELIUS_COLLECTION_ENABLED == 'true' &&
      inputs.confirm == '{phrase}'
"""
CANARY_STEP = ('      - name: Refuse to publish any file that contains the Helius key\n'
               '        id: helius_key_canary\n'
               '        if: always()\n'
               '        env:\n'
               '          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n'
               '        run: |\n'
               + ''.join('          %s\n' % row for row in guard.HELIUS_CANARY_RUN.split('\n')))
NAME = 'helius-demo.yml'
PHRASE = guard.helius_phrase(NAME)
BASE = ("""name: Helius demo
on:
  workflow_dispatch:
    inputs:
      confirm:
        description: 'Type {phrase}'
        required: true
        type: string
permissions:
  contents: read
concurrency:
  group: helius-collection
  cancel-in-progress: false
jobs:
  collect:
""" + GATE_LINES + """    runs-on: ubuntu-latest
    environment: helius-collection
    timeout-minutes: 5
    env:
      RUGGER_NO_DOTENV: '1'
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - name: Observe
        env:
          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
        run: |
          python -B -m bot.live.helius_demo --output paper_artifacts/demo_${{ github.run_id }}.json
""" + CANARY_STEP + """      - name: Archive
        if: always() && steps.helius_key_canary.outcome == 'success'
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: demo
          path: paper_artifacts/demo_*.json
          retention-days: 14
""").replace('{phrase}', PHRASE)


def helius(text, name=NAME):
    return guard.check_workflow(name, text)


def test_locked_workflow_is_accepted():
    assert helius(BASE) == []


def mutate(old, new, count=1):
    assert BASE.count(old) == count, old
    return BASE.replace(old, new)


GATE_EXPR = "inputs.confirm == '%s'" % PHRASE


@pytest.mark.parametrize('mutated, expected', [
    # Trigger and confirmation input.
    (mutate("    inputs:\n      confirm:\n        description: 'Type %s'\n        required: true\n        type: string\n" % PHRASE, ''),
     'helius_dispatch_without_required_confirm_input'),
    (mutate('        required: true\n', '        required: false\n'), 'helius_dispatch_without_required_confirm_input'),
    (mutate('  workflow_dispatch:\n', '  workflow_dispatch:\n  push:\n    branches: [main]\n'), 'automatic_trigger:push'),
    # The gate: every conjunct is required, no || and no other workflow's phrase.
    (mutate("      vars.HELIUS_COLLECTION_ENABLED == 'true' &&\n", ''), 'helius_job_not_gated:collect'),
    (mutate("      github.ref == 'refs/heads/main' &&\n", ''), 'helius_job_not_gated:collect'),
    (mutate("      github.repository == 'laurentmaxence13-svg/rugger_bot_v1' &&\n", ''), 'helius_job_not_gated:collect'),
    (mutate(GATE_EXPR, "inputs.confirm == 'RUN-HELIUS-OTHER'"), 'helius_job_not_gated:collect'),
    (mutate("      github.event_name == 'workflow_dispatch' &&\n",
            "      github.event_name == 'workflow_dispatch' || true &&\n"), 'helius_job_not_gated:collect'),
    (mutate("    if: >-\n", "    if: >-\n      always() || \n"), 'helius_job_not_gated:collect'),
    (mutate(GATE_LINES.format(phrase=PHRASE), ''), 'helius_job_not_gated:collect'),
    # Environment, runner, duration, permissions, concurrency.
    (mutate('    environment: helius-collection\n', ''), 'helius_key_job_without_environment:collect'),
    (mutate('    environment: helius-collection\n', '    environment: production\n'),
     'helius_key_job_without_environment:collect'),
    (mutate('    timeout-minutes: 5\n', '    timeout-minutes: 30\n'), 'helius_job_timeout:collect'),
    (mutate('    timeout-minutes: 5\n', ''), 'helius_job_timeout:collect'),
    (mutate('    runs-on: ubuntu-latest\n', '    runs-on: [self-hosted, linux]\n'), 'helius_runner:collect'),
    (mutate('  contents: read\n', '  contents: write\n'), 'helius_workflow_permissions'),
    (mutate('  contents: read\n', '  contents: read\n  id-token: write\n'), 'helius_workflow_permissions'),
    (mutate('    environment: helius-collection\n', '    environment: helius-collection\n    permissions:\n      contents: read\n'),
     'helius_job_permissions:collect'),
    (mutate('  cancel-in-progress: false\n', '  cancel-in-progress: true\n'), 'helius_concurrency_group'),
    (mutate('  group: helius-collection\n', '  group: demo-${{ github.ref }}\n'), 'helius_concurrency_group'),
    # Secret placement and secret forms.
    (mutate("      RUGGER_NO_DOTENV: '1'\n", "      RUGGER_NO_DOTENV: '1'\n      HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n"),
     'helius_key_in_job_env:collect'),
    (mutate('          python -B -m bot.live.helius_demo', '          KEY=${{ secrets.HELIUS_API_KEY }} python -B -m bot.live.helius_demo'),
     'helius_secret_in_run:collect.steps[1]'),
    (mutate('          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n        run: |\n          python',
            '          HELIUS_API_KEY: ${{ toJSON(secrets) }}\n        run: |\n          python'),
     'secrets_context_not_plain:toJSON(secrets)'),
    (mutate("      RUGGER_NO_DOTENV: '1'\n", "      RUGGER_NO_DOTENV: '1'\n      OTHER: ${{ secrets.BITQUERY_TOKEN }}\n"),
     'secret_not_allowlisted:BITQUERY_TOKEN'),
    (mutate("      RUGGER_NO_DOTENV: '1'\n", "      RUGGER_NO_DOTENV: '1'\n      SOLANA_PRIVATE_KEY: x\n"),
     'helius_wallet_like_env:SOLANA_PRIVATE_KEY'),
    (mutate("      RUGGER_NO_DOTENV: '1'\n", "      RUGGER_NO_DOTENV: '1'\n      RUGGER_LIVE_ENABLED: '1'\n"),
     'helius_live_enabled:collect'),
    (mutate('          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n        run: |\n          python',
            "          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n          RUGGER_LIVE_ENABLED: '1'\n        run: |\n          python"),
     'helius_live_enabled:collect.steps[1]'),
    (mutate('--output paper_artifacts', '--rpc ${{ inputs.confirm }} --output paper_artifacts'),
     'helius_inputs_interpolated_in_run:collect.steps[1]'),
    (mutate('python -B -m bot.live.helius_demo', 'python -B -m bot.live.helius_demo --live'),
     'helius_transaction_or_live_in_run:collect.steps[1]'),
    # Actions and checkout.
    (mutate('actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1', 'actions/checkout@v4'),
     'helius_action_not_allowed:actions/checkout@v4'),
    (mutate('          persist-credentials: false\n', '          persist-credentials: false\n          ref: feature\n'),
     'helius_checkout_must_only_set_persist_credentials_false:collect.steps[0]'),
    # Artifacts: canary first, gated upload, bounded path and retention.
    (mutate(CANARY_STEP, ''), 'helius_upload_without_prior_key_canary:collect.steps[2]'),
    (mutate("        if: always() && steps.helius_key_canary.outcome == 'success'\n", '        if: always()\n'),
     'helius_upload_not_gated_by_canary:collect.steps[3]'),
    (mutate("grep -rqsF", "grep -rqF"), 'helius_canary_run_not_reviewed:collect.steps[2]'),
    (mutate('        id: helius_key_canary\n        if: always()\n', '        id: helius_key_canary\n        if: success()\n'),
     'helius_canary_must_run_always:collect.steps[2]'),
    (mutate('          path: paper_artifacts/demo_*.json\n', '          path: ~/.config\n'),
     'helius_upload_path_outside_paper_artifacts:collect.steps[3]'),
    (mutate('          retention-days: 14\n', '          retention-days: 90\n'),
     'helius_upload_retention_not_bounded:collect.steps[3]'),
    (mutate('          retention-days: 14\n', ''), 'helius_upload_retention_not_bounded:collect.steps[3]'),
])
def test_every_lock_regression_is_reported(mutated, expected):
    violations = helius(mutated)
    assert expected in violations, violations


def test_a_key_step_after_the_canary_is_refused():
    extra = ('      - name: Late observation\n        env:\n          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n'
             '        run: python -B -m bot.live.helius_demo\n')
    text = BASE.replace('      - name: Archive\n', extra + '      - name: Archive\n')
    assert 'helius_upload_without_prior_key_canary:collect.steps[4]' in helius(text)


def test_inert_job_is_exempt_only_without_the_key():
    inert = ("  vendor:\n    if: >-\n      github.event_name == 'pull_request' &&\n      github.event.action == 'labeled'\n"
             "    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n"
             "        with:\n          path: x.json\n")
    assert helius(BASE + inert) == []
    with_key = inert + "        env:\n          HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}\n"
    violations = helius(BASE + with_key)
    assert 'helius_job_not_gated:vendor' in violations
    assert 'helius_key_job_without_environment:vendor' in violations
    loose = inert.replace("github.event.action == 'labeled'", "github.event.action == 'labeled' || true")
    assert 'helius_job_not_gated:vendor' in helius(BASE + loose)


def test_offline_job_in_a_helius_workflow_is_gated_and_cannot_upload():
    offline = ('  offline:\n' + GATE_LINES.format(phrase=PHRASE) + '    runs-on: ubuntu-latest\n    timeout-minutes: 3\n    steps:\n'
               '      - run: python -m pytest -q\n')
    assert helius(BASE + offline) == []
    ungated = offline.replace("      vars.HELIUS_COLLECTION_ENABLED == 'true' &&\n", '')
    assert 'helius_job_not_gated:offline' in helius(BASE + ungated)
    uploading = offline + ('      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n'
                           '        if: always() && steps.helius_key_canary.outcome == \'success\'\n'
                           '        with:\n          path: paper_artifacts/x.json\n          retention-days: 7\n')
    assert 'helius_upload_outside_key_job:offline.steps[1]' in helius(BASE + uploading)


def test_needs_prefix_is_allowed_but_nothing_else():
    prefixed = BASE.replace("    if: >-\n", "    if: >-\n      always() && needs.offline.result == 'success' &&\n")
    assert 'helius_job_not_gated:collect' not in helius(prefixed)
    other = BASE.replace("    if: >-\n", "    if: >-\n      github.actor == 'someone' &&\n")
    assert 'helius_job_not_gated:collect' in helius(other)


@pytest.mark.parametrize('text, reason', [
    ('a: &x 1\nb: *x\n', 'unsupported YAML form'),
    ('a: !!str 1\n', 'unsupported YAML form'),
    ('a: {b: 1}\n', 'unsupported YAML form'),
    ('"a": 1\n', 'unreadable mapping entry'),
    ('a: 1\na: 2\n', 'duplicate key'),
    ('a: one\n  two\n', 'multi-line plain scalar'),
    ('a:\n\tb: 1\n', 'tab indentation'),
    ('a: 1\n---\nb: 2\n', 'multiple documents'),
    ('a: [b, [c]]\n', 'nested flow collection'),
    ('? a\n: 1\n', 'unreadable mapping entry'),
])
def test_strict_reader_fails_closed(text, reason):
    with pytest.raises(guard.WorkflowParseError, match=reason):
        guard.parse_workflow(text)


def test_unreadable_helius_workflow_is_a_violation():
    text = BASE.replace('  contents: read\n', '  contents: &perm read\n')
    assert helius(text) == ['helius_unparseable:unsupported YAML form: &perm read']


def test_strict_reader_matches_pyyaml_on_every_repository_workflow():
    yaml = pytest.importorskip('yaml')

    def norm(value):
        if isinstance(value, dict):
            return {('on' if key is True else str(key)): norm(item) for key, item in value.items()}
        if isinstance(value, list):
            return [norm(item) for item in value]
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return None if value is None else str(value)

    files = sorted(WORKFLOWS.glob('*.yml'))
    assert len(files) >= 50
    for path in files:
        text = path.read_text(encoding='utf-8')
        assert norm(guard.parse_workflow(text)) == norm(yaml.safe_load(text)), path.name


# --- the repository's own Helius workflows ------------------------------------------------

HELIUS_FILES = sorted(p for p in WORKFLOWS.glob('*.yml') if guard.is_helius_workflow(p.read_text(encoding='utf-8')))


def test_every_repository_helius_workflow_is_locked():
    assert len(HELIUS_FILES) == 24             # 23 collection workflows + the P0 getHealth probe
    phrases = set()
    for path in HELIUS_FILES:
        text = path.read_text(encoding='utf-8')
        assert guard.helius_violations(path.name, text) == [], path.name
        doc = guard.parse_workflow(text)
        assert set(doc['on']) == {'workflow_dispatch'}
        phrases.add(guard.helius_phrase(path.name))
        for job_name, job in doc['jobs'].items():
            if guard._names_key(job):
                assert job['environment'] == 'helius-collection', (path.name, job_name)
                assert int(job['timeout-minutes']) <= guard.HELIUS_MAX_JOB_MINUTES
    assert len(phrases) == len(HELIUS_FILES)


def test_no_workflow_outside_the_lock_names_a_secret():
    for path in sorted(WORKFLOWS.glob('*.yml')):
        text = path.read_text(encoding='utf-8')
        names = set(re.findall(r'secrets\.([A-Za-z0-9_]+)', guard._code_lines(text)))
        assert names <= {'HELIUS_API_KEY', 'GITHUB_TOKEN'}, path.name
        if 'HELIUS_API_KEY' in names:
            assert path in HELIUS_FILES


MUTATIONS = [
    ('environment removed', lambda t: t.replace('    environment: helius-collection\n', '', 1),
     'helius_key_job_without_environment'),
    ('kill switch removed', lambda t: t.replace("      vars.HELIUS_COLLECTION_ENABLED == 'true' &&\n", '', 1),
     'helius_job_not_gated'),
    ('main branch condition removed', lambda t: t.replace("      github.ref == 'refs/heads/main' &&\n", '', 1),
     'helius_job_not_gated'),
    ('confirmation phrase of another workflow',
     lambda t: re.sub(r"inputs\.confirm == 'RUN-[A-Z0-9-]+'", "inputs.confirm == 'RUN-SOMETHING-ELSE'", t, count=1),
     'helius_job_not_gated'),
    ('confirmation input removed', lambda t: t.replace('        required: true\n', '        required: false\n', 1),
     'helius_dispatch_without_required_confirm_input'),
    ('concurrency cancelled', lambda t: t.replace('  cancel-in-progress: false\n', '  cancel-in-progress: true\n', 1),
     'helius_concurrency_group'),
    ('timeout raised', lambda t: re.sub(r'(\n    timeout-minutes: )\d+', r'\g<1>45', t, count=1),
     'helius_job_timeout'),
    ('push trigger added', lambda t: t.replace('  workflow_dispatch:\n', '  push:\n  workflow_dispatch:\n', 1),
     'automatic_trigger:push'),
]


@pytest.mark.parametrize('path', HELIUS_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize('label, change, expected', MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutating_a_real_helius_workflow_is_caught(path, label, change, expected):
    text = path.read_text(encoding='utf-8')
    mutated = change(text)
    if mutated == text:
        pytest.skip('mutation not applicable to %s' % path.name)
    assert any(v.startswith(expected) for v in guard.check_workflow(path.name, mutated)), (path.name, label)


UPLOADING = [p for p in HELIUS_FILES if 'actions/upload-artifact@' in p.read_text(encoding='utf-8')]


@pytest.mark.parametrize('path', UPLOADING, ids=lambda p: p.name)
def test_removing_the_canary_or_its_gate_is_caught(path):
    text = path.read_text(encoding='utf-8')
    no_gate = text.replace("if: always() && steps.helius_key_canary.outcome == 'success'", 'if: always()', 1)
    assert any(v.startswith('helius_upload_not_gated_by_canary') for v in guard.check_workflow(path.name, no_gate))
    start = text.index('      - name: Refuse to publish any file that contains the Helius key\n')
    end = text.index("echo 'HELIUS_KEY_CANARY=PASS'\n", start) + len("echo 'HELIUS_KEY_CANARY=PASS'\n")
    no_canary = text[:start] + text[end:]
    assert any(v.startswith('helius_upload_without_prior_key_canary') for v in guard.check_workflow(path.name, no_canary))


def test_uploading_workflows_all_carry_the_canary():
    assert len(UPLOADING) == 14                 # 16 uploading key jobs in 14 workflows
    jobs = 0
    for path in UPLOADING:
        doc = guard.parse_workflow(path.read_text(encoding='utf-8'))
        for job in doc['jobs'].values():
            steps = job.get('steps') or []
            if any(str(s.get('uses', '')).startswith('actions/upload-artifact@') for s in steps) and guard._names_key(job):
                jobs += 1
                assert sum(s.get('id') == guard.HELIUS_CANARY_ID for s in steps) == 1
    assert jobs == 16


# --- the canary itself, run by bash on a temporary directory ---------------------------

@pytest.mark.skipif(shutil.which('bash') is None, reason='bash not available')
@pytest.mark.parametrize('files, key, expected, code', [
    ({'a.json': '{"ok": true}'}, FAKE_KEY, 'HELIUS_KEY_CANARY=PASS', 0),
    ({}, FAKE_KEY, 'HELIUS_KEY_CANARY=PASS', 0),
    (None, FAKE_KEY, 'HELIUS_KEY_CANARY=PASS', 0),
    ({'a.json': '{"url": "https://mainnet.helius-rpc.com/?api-key=%s"}' % FAKE_KEY}, FAKE_KEY,
     'HELIUS_KEY_CANARY=FAIL key_found', 1),
    ({'sub/deep.bin': 'xx%syy' % FAKE_KEY}, FAKE_KEY, 'HELIUS_KEY_CANARY=FAIL key_found', 1),
    ({'%s.json' % FAKE_KEY: '{}'}, FAKE_KEY, 'HELIUS_KEY_CANARY=FAIL key_in_file_name', 1),
    ({'a.json': '{}'}, '', 'HELIUS_KEY_CANARY=FAIL empty_key', 1),
])
def test_canary_refuses_any_artifact_holding_the_key(tmp_path, files, key, expected, code):
    if files is not None:
        for relative, content in files.items():
            target = tmp_path / 'paper_artifacts' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    result = subprocess.run(['bash', '-e', '-c', guard.HELIUS_CANARY_RUN], cwd=tmp_path, capture_output=True,
                            text=True, env={'PATH': '/usr/bin:/bin', 'HELIUS_API_KEY': key}, timeout=30)
    assert (result.returncode, result.stdout.strip()) == (code, expected)
    assert FAKE_KEY not in result.stdout + result.stderr
