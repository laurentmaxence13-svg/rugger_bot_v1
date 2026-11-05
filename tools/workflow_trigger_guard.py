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
    ``working-directory``, ``container``, ``services``, ``defaults``,
    ``environment`` or self-hosted runner, no
    ``actions/checkout`` input that fetches other code (``repository``, ``ref``,
    ``token``, ``ssh-key``...), and ``persist-credentials: false`` on every checkout;
  - declares a top-level ``permissions:`` block and grants no ``write`` scope;
  - is written in a form the guard reads exactly (fail closed): outside ``on:``,
    no flow mapping, no flow sequence other than a one-line list of scalars, no
    quoted or complex (``?``) key, no YAML anchor, alias, merge key or tag, no
    second document;
    ``run:`` blocks use the literal ``|`` style only; ``env:`` and ``with:`` are
    block mappings whose keys are in ``ALLOWED_ENV_KEYS`` and
    ``ALLOWED_WITH_KEYS``.

Every manual workflow:

* references the ``secrets`` context only as ``${{ secrets.NAME }}`` with ``NAME``
  in ``ALLOWED_MANUAL_SECRETS`` (today only ``HELIUS_API_KEY``): ``toJSON(secrets)``,
  ``secrets[...]``, a ``secrets:`` key or any other secret name is refused.

A *Helius workflow* is any workflow that names ``HELIUS_API_KEY``. On top of the
manual-only trigger it must satisfy the Helius lock (``helius_violations``), read
with a strict block-YAML reader that fails closed:

* ``workflow_dispatch`` declares a required string input ``confirm``; every job is
  gated by exactly ``HELIUS_GATE``: manual event, ``refs/heads/main``, this
  repository, the repository variable ``HELIUS_COLLECTION_ENABLED == 'true'`` and
  ``inputs.confirm == 'RUN-<WORKFLOW STEM>'`` (only ``always()`` and
  ``needs.<job>.result == ...`` may precede it, never ``||``). A job whose condition
  starts with ``github.event_name == 'pull_request'`` and has no ``||`` can never run
  (no ``pull_request`` trigger) and is exempt, unless it names the key;
* every job that names the key declares ``environment: helius-collection`` (the
  owner holds the key only in that environment, with required reviewers and a
  ``main``-only branch policy: see docs/ops/HELIUS_WORKFLOW_LOCK.md), runs on
  ``ubuntu-latest`` for at most ``HELIUS_MAX_JOB_MINUTES`` minutes, with only
  allowlisted actions pinned to a commit SHA and checkouts without ``ref`` or
  credentials;
* the key appears only as ``HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}`` in a
  step ``env:`` mapping; no ``inputs`` expression is interpolated anywhere;
* artifacts: an ``upload-artifact`` step is allowed only in a key job, after the
  reviewed key canary step (``HELIUS_CANARY_RUN``, id ``helius_key_canary``, run
  after every other step that names the key) and only when that canary succeeded;
  paths stay under ``paper_artifacts/`` and end in ``.json``; the canary matches the key
  in any letter case; retention at most
  ``HELIUS_MAX_RETENTION_DAYS`` days;
* one workflow-level concurrency group ``helius-collection`` without cancellation,
  workflow permissions limited to ``read``/``none`` on ``contents`` and
  ``actions``, no job-level permissions, no wallet-like secret or environment
  name, ``RUGGER_LIVE_ENABLED`` only ``'0'``, no ``sendTransaction`` or ``--live`` in a
  ``run:`` step.

The repository's ``requirements*.txt`` files, installed by the approved
``pip install`` steps, may only list PyPI requirements by name: no pip option other
than ``--hash`` and ``-r``/``-c`` naming another root ``requirements*.txt`` (so every
included file is scanned too), no URL, VCS or direct reference, no local path,
directory or archive.

The parser reads only the top-level ``on:`` key. It understands the block
mapping, block sequence, flow sequence, flow mapping and scalar forms, and fails
closed: a file whose triggers it cannot read is a violation. Secret *names* are
reported; no secret value is ever present in a workflow file or read here.

Limits: static analysis cannot prove that repository code started by an
approved step stays offline. Such code still gets no repository secret (the
automatic workflows cannot reference any) and only a read-only ``GITHUB_TOKEN``.
Files read or executed by approved steps without being hashed here: the tests
and ``bot/`` code run through the harness, ``bot/dashboard/app.py`` and the
dashboard tests, ``LANCER_TERMINAL_PAPER.bat`` and ``LANCER_TERMINAL_PAPER.ps1``
(Windows launcher: pip from PyPI, health check on 127.0.0.1). Test steps go through ``tools/offline_check.py``,
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

# Secrets a manual workflow may name. Adding one needs a review of this guard.
ALLOWED_MANUAL_SECRETS = frozenset({'HELIUS_API_KEY'})

# Helius lock (see helius_violations and docs/ops/HELIUS_WORKFLOW_LOCK.md).
HELIUS_SECRET = 'HELIUS_API_KEY'
HELIUS_ENVIRONMENT = 'helius-collection'
HELIUS_CONCURRENCY_GROUP = 'helius-collection'
HELIUS_REPOSITORY = 'laurentmaxence13-svg/rugger_bot_v1'
HELIUS_MAX_JOB_MINUTES = 10
HELIUS_MAX_RETENTION_DAYS = 30
HELIUS_CANARY_ID = 'helius_key_canary'
HELIUS_SECRET_VALUE = '${{ secrets.HELIUS_API_KEY }}'
HELIUS_UPLOAD_IF = "always() && steps.helius_key_canary.outcome == 'success'"
# Reviewed canary: refuses to publish any artifact file whose content or name holds the key,
# in any letter case (T-0037 O1). Uploads are limited to .json files (helius_violations).
HELIUS_CANARY_RUN = (
    'if [ -z "${HELIUS_API_KEY}" ]; then echo \'HELIUS_KEY_CANARY=FAIL empty_key\'; exit 1; fi\n'
    'if grep -rqsiF -- "${HELIUS_API_KEY}" paper_artifacts; then echo \'HELIUS_KEY_CANARY=FAIL key_found\'; exit 1; fi\n'
    'if [ -n "$(find paper_artifacts -iname "*${HELIUS_API_KEY}*" 2>/dev/null | head -n 1)" ]; then '
    'echo \'HELIUS_KEY_CANARY=FAIL key_in_file_name\'; exit 1; fi\n'
    "echo 'HELIUS_KEY_CANARY=PASS'")
_HELIUS_PREFIX = re.compile(
    r"^(?:always\(\) && )?(?:needs\.[A-Za-z0-9_-]+\.result == '(?:success|failure|skipped|cancelled)' && )*$")
_WALLET_NAME = re.compile(r'PRIVATE|KEYPAIR|SECRET_KEY|SEED|MNEMONIC|WALLET', re.I)
_HELIUS_PERMISSION_SCOPES = frozenset({'contents', 'actions'})

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
    r'^[ ]*(?:-[ ]+)?(container|services|working-directory|defaults|environment|repository|ref|token|ssh-key|'
    r'ssh-known-hosts|github-server-url)[ ]*:', re.M)
ALLOWED_ENV_KEYS = frozenset({
    'PYTHONDONTWRITEBYTECODE', 'PYTHONUTF8', 'RUGGER_NO_DOTENV', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD',
})
ALLOWED_WITH_KEYS = frozenset({
    'persist-credentials', 'python-version',            # checkout, setup-python
    'name', 'path', 'retention-days', 'if-no-files-found',  # upload/download-artifact
})
_BLOCK_KEY = re.compile(r'^(?P<indent>[ ]*)(?P<dash>-[ ]+)?(?P<key>[A-Za-z0-9_.-]+)[ ]*:(?P<value>.*)$')
_QUOTED_KEY = re.compile(r'''^(?:-[ ]+)?(["'])(?:(?!\1).)*\1[ ]*:''')
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"' + r"|'[^']*'")
# A tag, anchor or alias starts a YAML node: at line start, after "key: ", "- " or in a flow list.
_ANCHOR_OR_TAG = re.compile(r'(?:^|:[ ]+|-[ ]+|[\[,][ ]*)(?:[&*][A-Za-z0-9_-]|![^\s=])|<<[ ]*:')
_REQ_INCLUDE = re.compile(r'^(?:-r|--requirement|-c|--constraint)[ =]+(?P<file>\S+)$')
# Includes may only name another root requirements file: no directory part.
_ROOT_REQUIREMENTS = re.compile(r'requirements[A-Za-z0-9_.-]*\.txt')
# PEP 508 requirement by name only (PyPI): name, extras, version clauses, environment marker.
_VERSION_CLAUSE = r'(?:===|==|~=|!=|<=|>=|<|>)[ ]*[A-Za-z0-9.*+!_-]+'
_PYPI_REQUIREMENT = re.compile(
    r'[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?'
    r'(?:[ ]*\[[ ]*[A-Za-z0-9._-]+(?:[ ]*,[ ]*[A-Za-z0-9._-]+)*[ ]*\])?'
    r'(?:[ ]*' + _VERSION_CLAUSE + r'(?:[ ]*,[ ]*' + _VERSION_CLAUSE + r')*)?'
    r'(?:[ ]*;[^@]*)?')
_HASH_OPTION = re.compile(r'[ ]+--hash[ =]+sha(?:256|384|512):[0-9a-f]+')
# pip installs a line ending in an archive extension from a local file, not from PyPI.
_ARCHIVE_NAME = re.compile(r'^[^ \[;<>=!~,]*\.(?:whl|zip|tar|tar\.gz|tgz|tar\.bz2|tbz|tar\.xz|txz|tlz|tar\.lz|tar\.lzma)'
                           r'(?=$|[ \[;<>=!~,])', re.I)
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


def _structure_lines(code: str) -> list[tuple[int, str]]:
    """(index, line) of YAML structure lines: block-scalar contents are skipped."""
    lines = code.splitlines()
    out, skip_column = [], None
    for index, line in enumerate(lines):
        indent = len(line) - len(line.lstrip(' '))
        if skip_column is not None:
            if not line.strip() or indent > skip_column:
                continue
            skip_column = None
        if not line.strip():
            continue
        out.append((index, line))
        match = _BLOCK_KEY.match(_strip_comment(line))
        if match and match.group('value').strip()[:1] in ('|', '>'):
            skip_column = len(match.group('indent')) + len(match.group('dash') or '')
    return out


def _outside_on(structure: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Structure lines outside the top-level on: block (parsed by parse_triggers)."""
    out, in_on = [], False
    for index, line in structure:
        if not line.startswith((' ', '-')):
            in_on = bool(_ON_KEY.match(line))
        if not in_on:
            out.append((index, line))
    return out


def syntax_violations(text: str) -> list[str]:
    """YAML forms the line-based checks could misread: refused in automatic workflows."""
    found = []
    for _, line in _outside_on(_structure_lines(_code_lines(text))):
        body = _strip_comment(line).strip()
        if body in ('---', '...'):
            found.append('multiple_documents_in_automatic_workflow')
            continue
        if re.match(r'^(?:-[ ]+)?[?:](?:[ ]|$)', body):
            found.append('complex_key_in_automatic_workflow:%s' % body[:60])
        if _QUOTED_KEY.match(body):
            found.append('quoted_key_in_automatic_workflow:%s' % re.sub(r'^-[ ]+', '', body).split(':', 1)[0])
        bare = _QUOTED.sub('""', _EXPRESSION.sub('E', body))
        if '{' in bare or '}' in bare:
            found.append('flow_mapping_in_automatic_workflow:%s' % body[:60])
        if '[' in bare or ']' in bare:
            match = re.fullmatch(r'(?:-[ ]+)?[A-Za-z0-9_.-]+[ ]*:[ ]*\[(?P<items>[^\[\]:{}]*)\]', bare)
            if not match:
                found.append('flow_sequence_in_automatic_workflow:%s' % body[:60])
        if _ANCHOR_OR_TAG.search(bare):
            found.append('yaml_anchor_or_tag_in_automatic_workflow:%s' % body[:60])
    for value in _run_indicators(text):
        if value != '|':
            found.append('run_block_not_literal:%s' % value)
    return found


def _run_indicators(text: str) -> list[str]:
    indicators = []
    for line in _code_lines(text).splitlines():
        match = _RUN_KEY.match(line)
        if match:
            value = _strip_comment(match.group('value')).strip()
            if value[:1] in ('|', '>'):
                indicators.append(value)
    return indicators


def _block_children(structure: list[tuple[int, str]], key: str) -> tuple[list[str], list[str]]:
    """Child keys of every ``key:`` block mapping, and keys given an inline value."""
    children, inline = [], []
    for position, (_, line) in enumerate(structure):
        match = _BLOCK_KEY.match(_strip_comment(line))
        if not match or match.group('key') != key:
            continue
        if match.group('value').strip():
            inline.append(match.group('value').strip())
            continue
        column = len(match.group('indent')) + len(match.group('dash') or '')
        child_indent = None
        for _, follow in structure[position + 1:]:
            indent = len(follow) - len(follow.lstrip(' '))
            if indent <= column:
                break
            child_indent = indent if child_indent is None else child_indent
            if indent == child_indent:
                child = _BLOCK_KEY.match(_strip_comment(follow))
                children.append(child.group('key') if child and not child.group('dash') else follow.strip())
    return children, inline


def mapping_key_violations(text: str) -> list[str]:
    """env: and with: must be block mappings with allowlisted keys."""
    structure = _outside_on(_structure_lines(_code_lines(text)))
    found = []
    for key, allowed, label in (('env', ALLOWED_ENV_KEYS, 'forbidden_env_in_automatic_workflow'),
                                ('with', ALLOWED_WITH_KEYS, 'forbidden_with_input_in_automatic_workflow')):
        children, inline = _block_children(structure, key)
        found += ['%s:%s' % (label, child.upper() if key == 'env' else child)
                  for child in children if child not in allowed]
        found += ['%s_not_block_mapping:%s' % (key, value[:60]) for value in inline]
    return found


def requirements_violations(text: str) -> list[str]:
    """A requirements file installed by an automatic workflow may only name PyPI packages.

    Accepted lines: a PEP 508 requirement by name (extras, version clauses, environment
    marker, optional ``--hash``), or ``-r``/``-c`` naming another *root*
    ``requirements*.txt`` file (itself scanned). Everything else is refused: other pip
    options, URLs, VCS or direct references, and local paths, directories or archives.
    """
    found = []
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith('-'):
            include = _REQ_INCLUDE.match(line)
            if not include:
                found.append('pip_option_in_requirements:%s' % line.split()[0])
            elif not _ROOT_REQUIREMENTS.fullmatch(include.group('file')):
                found.append('pip_include_not_root_requirements:%s' % include.group('file'))
            continue
        if '://' in line or re.search(r'\b(?:git|hg|svn|bzr)\+', line) or '@' in line.split(';', 1)[0]:
            found.append('url_in_requirements:%s' % line[:60])
            continue
        for option in re.findall(r'(?<!\S)(--?[A-Za-z][A-Za-z-]*)', line):
            if option != '--hash':
                found.append('pip_option_in_requirements:%s' % option)
        requirement = _HASH_OPTION.sub('', line).strip()
        if not _PYPI_REQUIREMENT.fullmatch(requirement) or _ARCHIVE_NAME.match(requirement):
            found.append('not_a_pypi_requirement:%s' % line[:60])
    return found


def scan_requirements(root: Path) -> dict:
    return {path.name: requirements_violations(path.read_text(encoding='utf-8'))
            for path in sorted(root.glob('requirements*.txt')) if path.is_file()}


def hardening_violations(text: str) -> list[str]:
    """Ways to change what an approved step does without changing its text."""
    code = _code_lines(text)
    found = []
    if any(_VARS_WORD.search(expr) for expr in _expressions(code)):
        found.append('vars_context_in_automatic_workflow')
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


class WorkflowParseError(ValueError):
    """The strict block-YAML reader cannot read the file with certainty."""


_MAP_ITEM = re.compile(r'^(?P<key>[A-Za-z0-9_.-]+)[ ]*:(?:[ ]+(?P<value>.*)|$)')
_BLOCK_SCALAR = re.compile(r'^[|>][+-]?$')


def _yaml_scalar(raw: str):
    raw = _strip_comment(raw).strip()
    if raw == '':
        return None
    if raw[0] == '"':
        if len(raw) < 2 or not raw.endswith('"'):
            raise WorkflowParseError('unterminated double-quoted scalar')
        try:
            return json.loads(raw)
        except ValueError:
            raise WorkflowParseError('unsupported double-quoted escape') from None
    if raw[0] == "'":
        if len(raw) < 2 or not raw.endswith("'"):
            raise WorkflowParseError('unterminated single-quoted scalar')
        return raw[1:-1].replace("''", "'")
    if raw in ('{}', '[]'):
        return {} if raw == '{}' else []
    if raw[0] == '[':
        if not raw.endswith(']'):
            raise WorkflowParseError('flow sequence must end on its line')
        try:
            items = _split_top_level(raw[1:-1])
        except TriggerParseError as error:
            raise WorkflowParseError(str(error)) from None
        if any(item[:1] in ('[', '{') for item in items):
            raise WorkflowParseError('nested flow collection')
        return [_yaml_scalar(item) for item in items]
    if raw[0] in '{&*!%@`|>' or raw.startswith(('<<', '? ')):
        raise WorkflowParseError('unsupported YAML form: %s' % raw[:30])
    return raw


class _Lines:
    def __init__(self, text: str):
        self.lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    def significant(self, index: int) -> int:
        while index < len(self.lines):
            stripped = self.lines[index].strip()
            if stripped and not stripped.startswith('#'):
                if stripped in ('---', '...'):
                    raise WorkflowParseError('multiple documents')
                return index
            index += 1
        return index

    def indent(self, index: int) -> int:
        line = self.lines[index]
        indent = len(line) - len(line.lstrip(' '))
        if line[indent:indent + 1] == '\t':
            raise WorkflowParseError('tab indentation')
        return indent


def _block_scalar(src: _Lines, index: int, key_indent: int, indicator: str):
    body, position = [], index
    while position < len(src.lines):
        line = src.lines[position]
        if line.strip() and len(line) - len(line.lstrip(' ')) <= key_indent:
            break
        body.append(line)
        position += 1
    while body and not body[-1].strip():
        body.pop()
    content = [line for line in body if line.strip()]
    if not content:
        return '', position
    indent = min(len(line) - len(line.lstrip(' ')) for line in content)
    rows = [line[indent:] if line.strip() else '' for line in body]
    if indicator[0] == '|':
        text = '\n'.join(rows)
    else:
        # YAML folding: a break between two normal lines becomes a space; breaks next
        # to more-indented lines are kept; each empty line keeps one newline.
        text, previous, empty = '', None, 0
        for row in rows:
            if not row:
                empty += 1
                continue
            kind = 'more' if row.startswith(' ') else 'normal'
            if previous is None:
                text += '\n' * empty
            elif previous == kind == 'normal':
                text += '\n' * empty if empty else ' '
            else:
                text += '\n' * (empty + 1)
            text += row
            previous, empty = kind, 0
    if not indicator.endswith('-'):
        text += '\n'
    return text, position


def _parse_node(src: _Lines, index: int, indent: int):
    index = src.significant(index)
    if index >= len(src.lines) or src.indent(index) != indent:
        raise WorkflowParseError('unexpected indentation at line %d' % (index + 1))
    if src.lines[index][indent:].startswith('-'):
        return _parse_sequence(src, index, indent)
    return _parse_mapping(src, index, indent)


def _mapping_value(src: _Lines, index: int, key_indent: int, value, allow_same_indent_sequence=True):
    """Value of a mapping key given its inline text; returns (value, next_index)."""
    if value is not None and _BLOCK_SCALAR.match(_strip_comment(value).strip()):
        return _block_scalar(src, index + 1, key_indent, _strip_comment(value).strip())
    following = src.significant(index + 1)
    deeper = following < len(src.lines) and src.indent(following) > key_indent
    same_seq = (allow_same_indent_sequence and following < len(src.lines)
                and src.indent(following) == key_indent
                and src.lines[following][key_indent:].startswith('- '))
    if value is None or not _strip_comment(value).strip():
        if deeper:
            return _parse_node(src, following, src.indent(following))
        if same_seq:
            return _parse_sequence(src, following, key_indent)
        return None, index + 1
    if deeper:
        raise WorkflowParseError('multi-line plain scalar at line %d' % (index + 1))
    return _yaml_scalar(value), index + 1


def _parse_mapping(src: _Lines, index: int, indent: int, first_line=None):
    result = {}
    while True:
        index = src.significant(index)
        if index >= len(src.lines):
            return result, index
        if first_line is None:
            if src.indent(index) < indent:
                return result, index
            if src.indent(index) > indent:
                raise WorkflowParseError('unexpected indentation at line %d' % (index + 1))
            body = src.lines[index][indent:]
        else:
            body, first_line = first_line, None
        if body.startswith('-'):
            return result, index
        match = _MAP_ITEM.match(body)
        if not match:
            raise WorkflowParseError('unreadable mapping entry at line %d' % (index + 1))
        key = match.group('key')
        if key in result:
            raise WorkflowParseError('duplicate key %s' % key)
        result[key], index = _mapping_value(src, index, indent, match.group('value'))


def _parse_sequence(src: _Lines, index: int, indent: int):
    result = []
    while True:
        index = src.significant(index)
        if index >= len(src.lines) or src.indent(index) != indent or not src.lines[index][indent:].startswith('-'):
            if index < len(src.lines) and src.indent(index) > indent:
                raise WorkflowParseError('unexpected indentation at line %d' % (index + 1))
            return result, index
        body = src.lines[index][indent:]
        if body.strip() == '-':
            following = src.significant(index + 1)
            if following >= len(src.lines) or src.indent(following) <= indent:
                result.append(None)
                index += 1
                continue
            node, index = _parse_node(src, following, src.indent(following))
            result.append(node)
            continue
        if not body.startswith('- '):
            raise WorkflowParseError('unreadable sequence entry at line %d' % (index + 1))
        rest = body[2:].lstrip(' ')
        item_indent = indent + (len(body) - len(rest))
        if _MAP_ITEM.match(rest):
            node, index = _parse_mapping(src, index, item_indent, first_line=rest)
            result.append(node)
        else:
            if src.significant(index + 1) < len(src.lines) and src.indent(src.significant(index + 1)) > indent \
                    and not src.lines[src.significant(index + 1)][src.indent(src.significant(index + 1)):].startswith('-'):
                raise WorkflowParseError('multi-line sequence scalar at line %d' % (index + 1))
            result.append(_yaml_scalar(rest))
            index += 1


def parse_workflow(text: str) -> dict:
    """Read a workflow written in the block-YAML subset; raise WorkflowParseError otherwise.

    Supported: block mappings and sequences, plain and quoted scalars, ``|``/``>``
    block scalars, ``{}``/``[]`` and one-line flow sequences of scalars. Scalars stay
    strings (``true``, ``5``...). Anchors, aliases, tags, flow mappings, complex or
    quoted keys, duplicate keys and multi-line plain scalars are refused.
    """
    src = _Lines(text)
    start = src.significant(0)
    if start >= len(src.lines):
        raise WorkflowParseError('empty document')
    node, end = _parse_node(src, start, 0)
    if src.significant(end) < len(src.lines):
        raise WorkflowParseError('trailing content at line %d' % (src.significant(end) + 1))
    if not isinstance(node, dict):
        raise WorkflowParseError('document is not a mapping')
    return node


def helius_phrase(name: str) -> str:
    """Per-workflow confirmation phrase: RUN- and the file stem in upper case."""
    return 'RUN-' + re.sub(r'\.ya?ml$', '', name).upper()


def helius_gate(name: str) -> str:
    return ("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && "
            "github.repository == '%s' && vars.HELIUS_COLLECTION_ENABLED == 'true' && "
            "inputs.confirm == '%s'" % (HELIUS_REPOSITORY, helius_phrase(name)))


def _normal(expression) -> str:
    return ' '.join(str(expression or '').split())


def is_helius_workflow(text: str) -> bool:
    return HELIUS_SECRET in _code_lines(text)


def manual_secret_violations(text: str) -> list[str]:
    """Secrets in a manual workflow: plain ``secrets.NAME`` forms of allowlisted names only."""
    code = _code_lines(text)
    found = []
    for expression in _expressions(code):
        if expression == '${{ unclosed':
            found.append('unclosed_expression')
            continue
        if not _SECRETS_WORD.search(expression):
            continue
        rest = _SECRET_NAME.sub('', expression)
        if _SECRETS_WORD.search(rest):
            found.append('secrets_context_not_plain:%s' % _normal(expression)[:60])
        found += ['secret_not_allowlisted:%s' % name for name in _SECRET_NAME.findall(expression)
                  if name not in ALLOWED_MANUAL_SECRETS and name.upper() != 'GITHUB_TOKEN']
    if _SECRETS_KEY.search(code):
        found.append('secrets_key_in_manual_workflow')
    return found


def _walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, path + (key,))
    elif isinstance(node, list):
        for position, value in enumerate(node):
            yield from _walk(value, path + (position,))
    else:
        yield path, node


def _names_key(node) -> bool:
    return any(HELIUS_SECRET in str(value) or HELIUS_SECRET in [str(p) for p in path]
               for path, value in _walk(node))


def _int_at_most(value, limit) -> bool:
    return isinstance(value, str) and value.isdigit() and 0 < int(value) <= limit


def _helius_step(job_name, position, step, key_job, canary_seen, later_key_steps):
    found = []
    label = '%s.steps[%d]' % (job_name, position)
    if not isinstance(step, dict):
        return ['helius_step_not_mapping:%s' % label]
    uses = step.get('uses')
    if uses is not None:
        action, _, version = str(uses).partition('@')
        if action.lower() not in ALLOWED_ACTIONS or not _SHA.fullmatch(version):
            found.append('helius_action_not_allowed:%s' % uses)
        if action.lower() == 'actions/checkout':
            with_ = step.get('with') or {}
            if not isinstance(with_, dict) or with_.get('persist-credentials') != 'false' \
                    or set(with_) - {'persist-credentials'}:
                found.append('helius_checkout_must_only_set_persist_credentials_false:%s' % label)
        if action.lower() == 'actions/upload-artifact':
            if not key_job:
                found.append('helius_upload_outside_key_job:%s' % label)
            if not canary_seen or later_key_steps:
                found.append('helius_upload_without_prior_key_canary:%s' % label)
            if _normal(step.get('if')) != HELIUS_UPLOAD_IF:
                found.append('helius_upload_not_gated_by_canary:%s' % label)
            with_ = step.get('with') or {}
            paths = [line.strip() for line in str(with_.get('path') or '').splitlines() if line.strip()]
            if not paths or any(not p.startswith('paper_artifacts/') or '..' in p for p in paths):
                found.append('helius_upload_path_outside_paper_artifacts:%s' % label)
            if any(not p.endswith('.json') for p in paths):
                found.append('helius_upload_not_json:%s' % label)
            if not _int_at_most(with_.get('retention-days'), HELIUS_MAX_RETENTION_DAYS):
                found.append('helius_upload_retention_not_bounded:%s' % label)
    env = step.get('env')
    if env is not None and not isinstance(env, dict):
        found.append('helius_step_env_not_mapping:%s' % label)
        env = {}
    for env_name, value in (env or {}).items():
        if _WALLET_NAME.search(env_name):
            found.append('helius_wallet_like_env:%s' % env_name)
        if env_name == HELIUS_SECRET:
            if str(value) != HELIUS_SECRET_VALUE:
                found.append('helius_key_env_value:%s' % label)
            if not key_job:
                found.append('helius_key_outside_key_job:%s' % label)
        elif 'secrets' in str(value):
            found.append('helius_secret_in_other_env:%s' % env_name)
        if env_name == 'RUGGER_LIVE_ENABLED' and str(value) != '0':
            found.append('helius_live_enabled:%s' % label)
    run = step.get('run')
    if run is not None:
        text = str(run)
        if 'secrets' in text or HELIUS_SECRET_VALUE in text:
            found.append('helius_secret_in_run:%s' % label)
        if re.search(r'\$\{\{[^}]*\binputs\b', text) or 'github.event.inputs' in text:
            found.append('helius_inputs_interpolated_in_run:%s' % label)
        if re.search(r'sendTransaction|--live\b', text):
            found.append('helius_transaction_or_live_in_run:%s' % label)
    for key in ('with',):
        for path, value in _walk(step.get(key)):
            if 'secrets' in str(value):
                found.append('helius_secret_in_with:%s' % label)
    if step.get('id') == HELIUS_CANARY_ID:
        if normalize_run_step(str(run or '').splitlines()) != HELIUS_CANARY_RUN:
            found.append('helius_canary_run_not_reviewed:%s' % label)
        if _normal(step.get('if')) != 'always()':
            found.append('helius_canary_must_run_always:%s' % label)
        if set(env or {}) != {HELIUS_SECRET} or uses is not None:
            found.append('helius_canary_shape:%s' % label)
    return found


def helius_violations(name: str, text: str) -> list[str]:
    """Helius lock rules for a workflow that names HELIUS_API_KEY (see module docstring)."""
    try:
        doc = parse_workflow(text)
    except WorkflowParseError as error:
        return ['helius_unparseable:%s' % error]
    found = []
    on = doc.get('on')
    dispatch = on.get('workflow_dispatch') if isinstance(on, dict) else None
    confirm = ((dispatch or {}).get('inputs') or {}).get('confirm') if isinstance(dispatch, dict) else None
    if not isinstance(on, dict) or set(on) != {'workflow_dispatch'} or not isinstance(confirm, dict) \
            or confirm.get('required') != 'true' or confirm.get('type') != 'string':
        found.append('helius_dispatch_without_required_confirm_input')
    permissions = doc.get('permissions')
    if not isinstance(permissions, dict) or set(permissions) - _HELIUS_PERMISSION_SCOPES \
            or any(value not in ('read', 'none') for value in permissions.values()):
        found.append('helius_workflow_permissions')
    if doc.get('concurrency') != {'group': HELIUS_CONCURRENCY_GROUP, 'cancel-in-progress': 'false'}:
        found.append('helius_concurrency_group')
    if _names_key(doc.get('env')) or 'secrets' in str(doc.get('env') or ''):
        found.append('helius_key_in_workflow_env')
    for path, value in _walk(doc):
        if path and isinstance(path[-1], str) and path[-1] in ('secrets',):
            found.append('helius_secrets_key')
    jobs = doc.get('jobs')
    if not isinstance(jobs, dict) or not jobs:
        return found + ['helius_no_jobs']
    gate = helius_gate(name)
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            found.append('helius_job_not_mapping:%s' % job_name)
            continue
        key_job = _names_key(job)
        condition = _normal(job.get('if'))
        inert = (condition.startswith("github.event_name == 'pull_request' &&") and '||' not in condition
                 and not key_job)
        if not inert:
            if '||' in condition or not condition.endswith(gate) \
                    or not _HELIUS_PREFIX.match(condition[:len(condition) - len(gate)]):
                found.append('helius_job_not_gated:%s' % job_name)
        if 'permissions' in job:
            found.append('helius_job_permissions:%s' % job_name)
        if _names_key(job.get('env')) or 'secrets' in str(job.get('env') or ''):
            found.append('helius_key_in_job_env:%s' % job_name)
        for env_name in (job.get('env') or {}) if isinstance(job.get('env'), dict) else ():
            if _WALLET_NAME.search(env_name):
                found.append('helius_wallet_like_env:%s' % env_name)
            if env_name == 'RUGGER_LIVE_ENABLED' and str(job['env'][env_name]) != '0':
                found.append('helius_live_enabled:%s' % job_name)
        if key_job and job.get('environment') != HELIUS_ENVIRONMENT:
            found.append('helius_key_job_without_environment:%s' % job_name)
        if not inert:
            if not _int_at_most(job.get('timeout-minutes'), HELIUS_MAX_JOB_MINUTES):
                found.append('helius_job_timeout:%s' % job_name)
            if job.get('runs-on') != 'ubuntu-latest':
                found.append('helius_runner:%s' % job_name)
            for forbidden in ('container', 'services', 'defaults', 'uses', 'secrets'):
                if forbidden in job:
                    found.append('helius_job_key_%s:%s' % (forbidden, job_name))
        if inert:
            continue        # can never run (no pull_request trigger) and does not name the key
        steps = job.get('steps') or []
        if not isinstance(steps, list):
            found.append('helius_steps_not_list:%s' % job_name)
            continue
        key_positions = [i for i, step in enumerate(steps)
                         if isinstance(step, dict) and step.get('id') != HELIUS_CANARY_ID and _names_key(step)]
        canary_positions = [i for i, step in enumerate(steps)
                            if isinstance(step, dict) and step.get('id') == HELIUS_CANARY_ID]
        for position, step in enumerate(steps):
            canary_seen = any(c < position for c in canary_positions)
            later = [k for k in key_positions if canary_positions and k > canary_positions[0]]
            found += _helius_step(job_name, position, step, key_job, canary_seen, later)
        if len(canary_positions) > 1:
            found.append('helius_several_canaries:%s' % job_name)
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
        violations += syntax_violations(text)
        violations += mapping_key_violations(text)
    else:
        violations += manual_secret_violations(text)
    if is_helius_workflow(text):
        violations += helius_violations(name, text)
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
    root = directory.parent.parent if (directory.name, directory.parent.name) == ('workflows', '.github') else None
    requirements = scan_requirements(root) if root else {}
    bad.update({name: violations for name, violations in requirements.items() if violations})
    if as_json:
        print(json.dumps({'workflows': report, 'requirements': requirements, 'violations': bad},
                         indent=1, sort_keys=True))
    else:
        automatic = sorted(name for name, entry in report.items() if entry['automatic'])
        print('workflows=%d automatic=%s manual_only=%d requirements=%d violations=%d'
              % (len(report), ','.join(automatic) or '-',
                 sum(1 for entry in report.values()
                     if entry['events'] is not None and set(entry['events']) <= MANUAL_EVENTS),
                 len(requirements), sum(len(v) for v in bad.values())))
        for name, violations in sorted(bad.items()):
            print('VIOLATION %s: %s' % (name, ', '.join(violations)))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
