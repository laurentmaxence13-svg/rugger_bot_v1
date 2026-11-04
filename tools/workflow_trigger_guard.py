#!/usr/bin/env python3
"""Offline guard for GitHub Actions triggers (standard library only, no network).

Invariant enforced (decision D3 of the #101 consolidation, P-PRIV correction):

* Only the offline CI workflows listed in ``AUTOMATIC_WORKFLOWS`` may start on
  their own (``pull_request``, ``push``), and only with the events listed for
  each of them.
* Every other workflow (Helius, public RPC, market, trawl.run, Render smoke,
  research probes...) may only be started by hand: its sole trigger is
  ``workflow_dispatch``. A ``pull_request`` trigger of any type (including
  ``labeled``), ``pull_request_target``, ``push``, ``schedule`` or any other
  automatic event is refused.
* An automatic workflow:
  - uses the ``secrets`` context only as ``secrets.GITHUB_TOKEN``: any other use
    in an expression (``${{ ... }}`` or an ``if:`` condition), such as
    ``toJSON(secrets)``, ``secrets[format(...)]`` or ``secrets.NAME``, and any
    ``secrets:`` key (``inherit`` or mapping) is refused;
  - names no host outside GitHub, PyPI and the runner's loopback, whatever the
    URL scheme (``https``, ``wss``, ``ssh``...), and no bare host name with a
    common public suffix (heuristic);
  - runs only allowlisted actions pinned to a full commit SHA (no local,
    Docker or reusable-workflow ``uses:``);
  - runs only reviewed ``run:`` steps: each step's normalized text must have its
    SHA-256 in ``APPROVED_RUN_STEPS``, so a new or changed script invocation is
    refused until it is reviewed and added (``--run-hashes`` prints them);
  - calls no network tool (``curl``, ``wget``, ``Invoke-WebRequest``, ``ssh``,
    ``gh``, ``npm``, ``docker``, ``git clone/fetch/pull/push``...) except on a line
    whose URLs all target the runner's loopback, and gives ``pip`` no package
    source other than PyPI (no ``--index-url``, ``--find-links``, ``git+``...);
  - cannot alter an approved step from outside: no ``vars`` context, no
    ``PIP_INDEX_URL``/proxy/``PYTHONPATH``-style environment key, ``shell:``
    limited to bash, sh, pwsh, powershell, cmd or python, no
    ``working-directory``, ``container``, ``services`` or self-hosted runner, no
    ``actions/checkout`` input that fetches other code (``repository``, ``ref``,
    ``token``, ``ssh-key``...), and ``persist-credentials: false`` on every checkout;
  - declares a top-level ``permissions:`` block and grants no ``write`` scope.

The parser reads only the top-level ``on:`` key. It understands the block
mapping, block sequence, flow sequence, flow mapping and scalar forms, and fails
closed: a file whose triggers it cannot read is a violation. Secret *names* are
reported; no secret value is ever present in a workflow file or read here.

Limits: static analysis cannot prove that repository code started by an
approved step stays offline. Such code still gets no repository secret (the
automatic workflows cannot reference any) and only a read-only ``GITHUB_TOKEN``. Test steps go through ``tools/offline_check.py``,
whose harness refuses external socket connections (checked by
``tests/test_workflow_trigger_guard.py`` inside that harness). The other approved
steps (``pip install`` from PyPI, the PAPER terminal smoke tests on loopback)
were reviewed by hand. The guard checks only the files of the branch it runs on.

Usage::

    python -B tools/workflow_trigger_guard.py [--json | --run-hashes] [WORKFLOW_DIR]

Exit code 0 when no violation is found, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

MANUAL_EVENTS = frozenset({'workflow_dispatch'})

# Offline CI kept automatic. Each entry lists the only events it may use.
AUTOMATIC_WORKFLOWS = {
    'offline-tests.yml': frozenset({'pull_request', 'workflow_dispatch'}),
    'rugger-isolated-ci.yml': frozenset({'push', 'pull_request', 'workflow_dispatch'}),
    'paper-terminal-ci.yml': frozenset({'push', 'pull_request', 'workflow_dispatch'}),
}

ALLOWED_HOSTS = frozenset({
    'github.com', 'api.github.com', 'objects.githubusercontent.com',
    'pypi.org', 'files.pythonhosted.org',
    # Loopback only: local smoke test of the PAPER terminal on the runner itself.
    '127.0.0.1', 'localhost',
})

_ON_KEY = re.compile(r'''^(?:on|"on"|'on')\s*:(?P<rest>.*)$''')
_TOP_KEY = re.compile(r'^[^\s#-]')
# Actions an automatic workflow may run, always pinned to a 40-hex commit SHA.
ALLOWED_ACTIONS = frozenset({
    'actions/checkout', 'actions/setup-python',
    'actions/upload-artifact', 'actions/download-artifact',
})

# Reviewed run: steps of the automatic workflows (SHA-256 of the normalized step
# text, see normalize_run_step). Any other step is refused. Update only after
# review, with: python -B tools/workflow_trigger_guard.py --run-hashes
APPROVED_RUN_STEPS = {
    'offline-tests.yml': {
        '886b7bfc4b59f121ff9474d3846ff6ee44c508973936faee646b2fa59a314e66': 'pip install from PyPI (requirements files)',
        '77b4dac3157b7203b9db4eeb7103a19eab3312a01142e0c9ba4011c77237cfdc': 'print toolchain versions and HEAD',
        'a7de5af82e9cb2a17ed6ec6ca17f1c135076c7c33d59fdaf6bccabe85e665698': 'offline suite in the no-network harness',
    },
    'rugger-isolated-ci.yml': {
        '0bbff73b392134466ddbca28da6e7c927fd4dc69999b52521c03b6073e6a7039': 'pip install from PyPI (requirements files)',
        'ed4ccf43d7bbd7efe9e7a953a42eaefc9bb672e73ff18961dee039c63e985c26': 'print HEAD, tree state and module hashes',
        '8a5339accf7ef73513e7db1d72350c8657a49196f8030c78011492b282553f5e': 'offline suite in the no-network harness',
    },
    'paper-terminal-ci.yml': {
        'd7974e78f63d1c1bf14888c01250bf802d9b7ef08bd4c8af823ffa435dd757ca': 'dashboard unit tests and compileall (no network import)',
        'd61416d7cff366004e508745759f5af7f327c816d15a0b73d9c8495450a45655': 'pip install from PyPI (dashboard requirements)',
        '6586f3c6a24de8ec77254085fbf62c8df6f23f7ac86778cc94ed5d0d76847688': 'Streamlit AppTest render, in process',
        '3c288cf466d13045233dd9c26ef179a8cd2e3845402921f2b6bb2b220661e6a4': 'Streamlit HTTP health on 127.0.0.1 only',
        'd85a63c11ce4a78caed08addd1c3d286d02cfaebc8b6eab007141dca83f41582': 'Windows BAT launcher: pip from PyPI, health on 127.0.0.1',
        'c46ea971d45310142c685aa02d7e205086d44a8946dc69e4c2a968cb3af80a69': 'Windows dashboard smoke unit test',
        'a6a9792b11c9c8cbcb84a357e9ba48aada6daedbd81285a946f4d0186d9c4e42': 'print local launcher logs on failure',
    },
}

_NETWORK_TOOLS = re.compile(
    r'(?<![\w.-])(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|start-bitstransfer|bitsadmin|'
    r'certutil|nc|ncat|netcat|socat|telnet|ssh|scp|sftp|rsync|ftp|gh|npm|npx|yarn|pnpm|docker|podman)'
    r'(?![\w.-])', re.I)
_GIT_NETWORK = re.compile(r'\bgit\b.*?\b(clone|fetch|pull|push|ls-remote|remote|submodule)\b', re.I)
_PIP_SOURCE = re.compile(
    r'(--index-url|--extra-index-url|--find-links|--trusted-host|(?<!\S)-[if](?=\s|$)|\bgit\+|\bhg\+|\bsvn\+|\bbzr\+)')
_PIP_CALL = re.compile(r'\bpip3?\b[^\n]*\b(install|download|wheel)\b', re.I)
_RUN_KEY = re.compile(r'^(?P<indent>[ ]*)(?P<dash>-[ ]+)?run[ ]*:(?P<value>.*)$')
_LOOPBACK = frozenset({'127.0.0.1', 'localhost'})
_ALLOWED_SHELLS = frozenset({'bash', 'sh', 'pwsh', 'powershell', 'cmd', 'python'})
_SHELL_KEY = re.compile(r'^[ ]*(?:-[ ]+)?shell[ ]*:(?P<value>.*)$', re.M)
_FORBIDDEN_KEYS = re.compile(
    r'^[ ]*(?:-[ ]+)?(container|services|working-directory|repository|ref|token|ssh-key|ssh-known-hosts|'
    r'github-server-url)[ ]*:', re.M)
_FORBIDDEN_ENV = re.compile(
    r'^[ ]*(?:-[ ]+)?(pip_index_url|pip_extra_index_url|pip_find_links|pip_trusted_host|pip_config_file|'
    r'uv_index_url|http_proxy|https_proxy|all_proxy|pythonpath|pythonstartup|pythonhome|ld_preload)[ ]*:', re.M | re.I)
_VARS_WORD = re.compile(r'\bvars\b', re.I)
_SELF_HOSTED = re.compile(r'\bself-hosted\b', re.I)
_PERMISSIONS_TOP = re.compile(r'^permissions[ ]*:', re.M)
_WRITE_SCOPE = re.compile(r'''^[ ]*(?:-[ ]+)?[A-Za-z-]+[ ]*:[ ]*['"]?(write|write-all)['"]?[ ]*(?:#.*)?$''', re.M | re.I)
_CHECKOUT = re.compile(r'''^[ ]*(?:-[ ]+)?uses[ ]*:[ ]*['"]?actions/checkout@''', re.M | re.I)
_NO_PERSIST = re.compile(r'''^[ ]*persist-credentials[ ]*:[ ]*['"]?false['"]?[ ]*(?:#.*)?$''', re.M)

_EXPRESSION = re.compile(r'\$\{\{(.*?)\}\}', re.S)
_IF_KEY = re.compile(r'^(?P<indent>[ ]*)(?:-[ ]+)?if[ ]*:(?P<value>.*)$')
_SECRETS_KEY = re.compile(r'^[ ]*(?:-[ ]+)?["\']?secrets["\']?[ ]*:', re.M | re.I)
_SECRETS_WORD = re.compile(r'\bsecrets\b', re.I)
_SECRET_NAME = re.compile(r'\bsecrets\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)', re.I)
_GITHUB_TOKEN = re.compile(r'\bsecrets\s*\.\s*github_token\b', re.I)
_URL = re.compile(r'\b([A-Za-z][A-Za-z0-9+.-]*)://([^\s/\'"`<>(){}\\|;,?#]*)')
_BARE_HOST = re.compile(
    r'(?<![\w./:-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+'
    r'(?:com|net|org|io|run|dev|xyz|co|ai|cloud|tech|network|finance|fi))(?![\w.-])',
    re.I)
_USES = re.compile(r'''^[ ]*(?:-[ ]+)?uses[ ]*:[ ]*['"]?(?P<ref>[^\s'"#]+)''', re.M)
_SHA = re.compile(r'[0-9a-f]{40}')


class TriggerParseError(ValueError):
    """Raised when the top-level ``on:`` key cannot be read with certainty."""


def _strip_comment(line: str) -> str:
    """Remove a trailing ``#`` comment that is outside quotes."""
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '#' and (index == 0 or line[index - 1] in ' \t'):
            return line[:index].rstrip()
    return line.rstrip()


def _unquote(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    return token


def _split_top_level(text: str) -> list[str]:
    """Split a flow collection body on commas at nesting depth 0."""
    parts, depth, quote, current = [], 0, None, []
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char in '[{':
            depth += 1
        elif char in ']}':
            depth -= 1
            if depth < 0:
                raise TriggerParseError('unbalanced flow collection')
        elif char == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
            continue
        current.append(char)
    if depth != 0 or quote:
        raise TriggerParseError('unbalanced flow collection')
    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part]


def _event_name(token: str) -> str:
    name = _unquote(token)
    if not re.fullmatch(r'[a-z_]+', name):
        raise TriggerParseError('unexpected event name %r' % name)
    return name


def _flow_value(rest: str) -> list[str]:
    if rest.startswith('['):
        if not rest.endswith(']'):
            raise TriggerParseError('flow sequence must end on the same line')
        return [_event_name(item) for item in _split_top_level(rest[1:-1])]
    if rest.startswith('{'):
        if not rest.endswith('}'):
            raise TriggerParseError('flow mapping must end on the same line')
        names = []
        for item in _split_top_level(rest[1:-1]):
            key = item.split(':', 1)[0]
            names.append(_event_name(key))
        return names
    return [_event_name(rest)]


def parse_triggers(text: str) -> list[str]:
    """Return the event names of the top-level ``on:`` key, in file order."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    found = [index for index, line in enumerate(lines) if _ON_KEY.match(line)]
    if not found:
        raise TriggerParseError('no top-level on: key')
    if len(found) > 1:
        raise TriggerParseError('several top-level on: keys')
    start = found[0]
    rest = _strip_comment(_ON_KEY.match(lines[start]).group('rest')).strip()
    if rest:
        names = _flow_value(rest)
    else:
        names, child_indent = [], None
        for line in lines[start + 1:]:
            body = _strip_comment(line)
            if not body.strip():
                continue
            if _TOP_KEY.match(body) or body.startswith('---') or body.startswith('...'):
                break
            indent = len(body) - len(body.lstrip(' '))
            if '\t' in body[:indent + 1]:
                raise TriggerParseError('tab indentation')
            if child_indent is None:
                child_indent = indent
            if indent < child_indent:
                raise TriggerParseError('inconsistent indentation under on:')
            if indent > child_indent:
                continue
            entry = body.strip()
            if entry.startswith('- '):
                names.append(_event_name(entry[2:]))
            elif ':' in entry:
                key, value = entry.split(':', 1)
                names.append(_event_name(key))
                value = value.strip()
                if value and value not in ('null', '~', '{}', '[]') and not value.startswith(('{', '[')):
                    raise TriggerParseError('unexpected scalar value for %s' % key.strip())
            else:
                raise TriggerParseError('cannot read entry %r' % entry)
    if not names:
        raise TriggerParseError('on: has no event')
    if len(set(names)) != len(names):
        raise TriggerParseError('duplicate event under on:')
    return names


def _code_lines(text: str) -> str:
    """Workflow text without full-line comments (comments may describe secrets)."""
    return '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))


def _expressions(code: str) -> list[str]:
    """Texts evaluated as GitHub expressions: ``${{ ... }}`` bodies and ``if:`` values."""
    if code.count('${{') != len(_EXPRESSION.findall(code)):
        return ['${{ unclosed']
    found = _EXPRESSION.findall(code)
    lines = code.splitlines()
    for index, line in enumerate(lines):
        match = _IF_KEY.match(line)
        if not match:
            continue
        value = _strip_comment(match.group('value')).strip()
        if value[:1] in ('|', '>'):
            indent = len(match.group('indent'))
            block = []
            for follow in lines[index + 1:]:
                if follow.strip() and len(follow) - len(follow.lstrip(' ')) <= indent:
                    break
                block.append(follow)
            value = '\n'.join(block)
        found.append(value)
    return found


def referenced_secrets(text: str) -> list[str]:
    """Uses of the ``secrets`` context other than ``secrets.GITHUB_TOKEN``."""
    code = _code_lines(text)
    found = set()
    for expression in _expressions(code):
        if expression == '${{ unclosed':
            found.add('unclosed_expression')
            continue
        rest = _GITHUB_TOKEN.sub('', expression)
        if _SECRETS_WORD.search(rest):
            names = _SECRET_NAME.findall(rest)
            found.update(names or ['secrets_context'])
    if _SECRETS_KEY.search(code):
        found.add('secrets_key')
    return sorted(found)


def external_hosts(text: str) -> list[str]:
    """Hosts outside ``ALLOWED_HOSTS``: any URL scheme, plus bare public host names."""
    code = _code_lines(text)
    hosts = set()
    for scheme, authority in _URL.findall(code):
        host = authority.rsplit('@', 1)[-1]
        host = re.sub(r':[0-9]*$', '', host).lower().rstrip('.')
        hosts.add(host or '%s://<unreadable>' % scheme.lower())
    for host in _BARE_HOST.findall(_URL.sub(' ', code)):
        hosts.add(host.lower())
    return sorted(host for host in hosts if host not in ALLOWED_HOSTS)


def disallowed_actions(text: str) -> list[str]:
    """``uses:`` references that are not an allowlisted action pinned to a commit SHA."""
    bad = []
    for ref in _USES.findall(_code_lines(text)):
        name, _, version = ref.partition('@')
        if name.lower() not in ALLOWED_ACTIONS:
            bad.append('action_not_allowed:%s' % ref)
        elif not _SHA.fullmatch(version):
            bad.append('action_not_pinned:%s' % ref)
    return bad


def run_steps(text: str) -> list[str]:
    """Normalized text of every ``run:`` step (block or inline scalar)."""
    lines = _code_lines(text).splitlines()
    steps = []
    for index, line in enumerate(lines):
        match = _RUN_KEY.match(line)
        if not match:
            continue
        key_column = len(match.group('indent')) + len(match.group('dash') or '')
        value = match.group('value').strip()
        body = []
        for follow in lines[index + 1:]:
            if follow.strip() and len(follow) - len(follow.lstrip(' ')) <= key_column:
                break
            body.append(follow)
        if value and value[0] not in ('|', '>'):
            body.insert(0, ' ' * (key_column + 2) + value)
        steps.append(normalize_run_step(body))
    return steps


def normalize_run_step(lines: list[str]) -> str:
    stripped = [line.rstrip() for line in lines]
    while stripped and not stripped[0]:
        stripped.pop(0)
    while stripped and not stripped[-1]:
        stripped.pop()
    indent = min((len(line) - len(line.lstrip(' ')) for line in stripped if line), default=0)
    return '\n'.join(line[indent:] for line in stripped)


def run_step_hash(step: str) -> str:
    return hashlib.sha256(step.encode('utf-8')).hexdigest()


def network_commands(text: str) -> list[str]:
    """Network tools and non-PyPI pip sources used by run: steps (loopback-only lines allowed)."""
    found = []
    for step in run_steps(text):
        for line in step.splitlines():
            tools = [tool.lower() for tool in _NETWORK_TOOLS.findall(line)]
            tools += ['git ' + sub.lower() for sub in _GIT_NETWORK.findall(line)]
            if tools:
                hosts = [re.sub(r':[0-9]*$', '', authority.rsplit('@', 1)[-1]).lower()
                         for _, authority in _URL.findall(line)]
                if not hosts or any(host not in _LOOPBACK for host in hosts):
                    found += ['network_command_in_automatic_workflow:%s' % tool for tool in tools]
            if _PIP_CALL.search(line):
                found += ['pip_source_in_automatic_workflow:%s' % option.strip()
                          for option in _PIP_SOURCE.findall(line)]
    return found


def unapproved_run_steps(name: str, text: str) -> list[str]:
    approved = APPROVED_RUN_STEPS.get(name, {})
    return ['unapproved_run_step:%s' % run_step_hash(step)[:16]
            for step in run_steps(text) if run_step_hash(step) not in approved]


def hardening_violations(text: str) -> list[str]:
    """Ways to change what an approved step does without changing its text."""
    code = _code_lines(text)
    found = []
    if any(_VARS_WORD.search(expr) for expr in _expressions(code)):
        found.append('vars_context_in_automatic_workflow')
    found += ['forbidden_env_in_automatic_workflow:%s' % key.upper() for key in _FORBIDDEN_ENV.findall(code)]
    found += ['forbidden_key_in_automatic_workflow:%s' % key for key in _FORBIDDEN_KEYS.findall(code)]
    for value in _SHELL_KEY.findall(code):
        shell = _unquote(_strip_comment(value).strip())
        if shell.lower() not in _ALLOWED_SHELLS:
            found.append('shell_not_allowed:%s' % shell)
    if _SELF_HOSTED.search(code):
        found.append('self_hosted_runner_in_automatic_workflow')
    if not _PERMISSIONS_TOP.search(code):
        found.append('missing_top_level_permissions')
    found += ['write_permission_in_automatic_workflow:%s' % scope.lower() for scope in _WRITE_SCOPE.findall(code)]
    if len(_NO_PERSIST.findall(code)) < len(_CHECKOUT.findall(code)):
        found.append('checkout_without_persist_credentials_false')
    return found


def check_workflow(name: str, text: str) -> list[str]:
    """Return the violations of one workflow file (empty list when compliant)."""
    try:
        events = parse_triggers(text)
    except TriggerParseError as error:
        return ['unparseable_on:%s' % error]
    allowed = AUTOMATIC_WORKFLOWS.get(name, MANUAL_EVENTS)
    violations = ['automatic_trigger:%s' % event for event in events if event not in allowed]
    if name in AUTOMATIC_WORKFLOWS:
        violations += ['secret_in_automatic_workflow:%s' % secret for secret in referenced_secrets(text)]
        violations += ['external_host_in_automatic_workflow:%s' % host for host in external_hosts(text)]
        violations += disallowed_actions(text)
        violations += network_commands(text)
        violations += unapproved_run_steps(name, text)
        violations += hardening_violations(text)
    return violations


def scan_directory(directory: Path) -> dict:
    files = sorted(path for path in directory.iterdir()
                   if path.is_file() and path.suffix in ('.yml', '.yaml'))
    report = {}
    for path in files:
        text = path.read_text(encoding='utf-8')
        try:
            events = parse_triggers(text)
        except TriggerParseError:
            events = None
        report[path.name] = {
            'events': events,
            'automatic': path.name in AUTOMATIC_WORKFLOWS,
            'violations': check_workflow(path.name, text),
        }
    return report


def main(argv: list[str]) -> int:
    as_json = '--json' in argv
    show_hashes = '--run-hashes' in argv
    args = [arg for arg in argv if arg not in ('--json', '--run-hashes')]
    directory = Path(args[0]) if args else Path(__file__).resolve().parents[1] / '.github' / 'workflows'
    if not directory.is_dir():
        print('workflow directory not found: %s' % directory, file=sys.stderr)
        return 2
    if show_hashes:
        for name in sorted(AUTOMATIC_WORKFLOWS):
            path = directory / name
            if path.is_file():
                for step in run_steps(path.read_text(encoding='utf-8')):
                    first = step.splitlines()[0] if step else ''
                    print('%s %s %s' % (name, run_step_hash(step), first[:70]))
        return 0
    report = scan_directory(directory)
    bad = {name: entry['violations'] for name, entry in report.items() if entry['violations']}
    if as_json:
        print(json.dumps({'workflows': report, 'violations': bad}, indent=1, sort_keys=True))
    else:
        automatic = sorted(name for name, entry in report.items() if entry['automatic'])
        print('workflows=%d automatic=%s manual_only=%d violations=%d'
              % (len(report), ','.join(automatic) or '-',
                 sum(1 for entry in report.values()
                     if entry['events'] is not None and set(entry['events']) <= MANUAL_EVENTS),
                 sum(len(v) for v in bad.values())))
        for name, violations in sorted(bad.items()):
            print('VIOLATION %s: %s' % (name, ', '.join(violations)))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
