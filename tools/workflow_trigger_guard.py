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
* An automatic workflow references no repository secret other than
  ``GITHUB_TOKEN`` and no URL outside GitHub, PyPI and the runner's loopback.

The parser reads only the top-level ``on:`` key. It understands the block
mapping, block sequence, flow sequence, flow mapping and scalar forms, and fails
closed: a file whose triggers it cannot read is a violation. Secret *names* are
reported; no secret value is ever present in a workflow file or read here.

Usage::

    python -B tools/workflow_trigger_guard.py [--json] [WORKFLOW_DIR]

Exit code 0 when no violation is found, 1 otherwise.
"""
from __future__ import annotations

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
_SECRET_DOT = re.compile(r'\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)')
_SECRET_INDEX = re.compile(r'''\bsecrets\[\s*['"]([^'"]+)['"]\s*\]''')
_SECRET_INHERIT = re.compile(r'^\s*secrets\s*:\s*inherit\s*(?:#.*)?$', re.M)
_URL_HOST = re.compile(r'https?://([A-Za-z0-9.-]+)', re.I)


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


def referenced_secrets(text: str) -> list[str]:
    code = _code_lines(text)
    names = set(_SECRET_DOT.findall(code)) | set(_SECRET_INDEX.findall(code))
    if _SECRET_INHERIT.search(code):
        names.add('inherit')
    return sorted(names)


def external_hosts(text: str) -> list[str]:
    hosts = {host.lower().rstrip('.') for host in _URL_HOST.findall(_code_lines(text))}
    return sorted(host for host in hosts if host not in ALLOWED_HOSTS)


def check_workflow(name: str, text: str) -> list[str]:
    """Return the violations of one workflow file (empty list when compliant)."""
    try:
        events = parse_triggers(text)
    except TriggerParseError as error:
        return ['unparseable_on:%s' % error]
    allowed = AUTOMATIC_WORKFLOWS.get(name, MANUAL_EVENTS)
    violations = ['automatic_trigger:%s' % event for event in events if event not in allowed]
    if name in AUTOMATIC_WORKFLOWS:
        violations += ['secret_in_automatic_workflow:%s' % secret
                       for secret in referenced_secrets(text) if secret != 'GITHUB_TOKEN']
        violations += ['external_host_in_automatic_workflow:%s' % host for host in external_hosts(text)]
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
    args = [arg for arg in argv if arg != '--json']
    directory = Path(args[0]) if args else Path(__file__).resolve().parents[1] / '.github' / 'workflows'
    if not directory.is_dir():
        print('workflow directory not found: %s' % directory, file=sys.stderr)
        return 2
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
