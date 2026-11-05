"""Helius P0 getHealth workflow: static guarantees and the exact inline probe, offline.

The probe code is extracted from the workflow file itself, so the tests exercise
the very lines GitHub Actions would run. No network: a fake opener records calls.
"""
import io
import re
import sys
import textwrap
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'helius-p0-gethealth-once.yml'
sys.path.insert(0, str(ROOT / 'tools'))
import workflow_trigger_guard as guard  # noqa: E402

KEY = '0123abcd-4567-89ef-0123-456789abcdef'     # fake, UUID-shaped
TEXT = WORKFLOW.read_text(encoding='utf-8')


def probe_source():
    match = re.search(r"python3 -I -B - <<'PY'\n(.*?)\n\s*PY\n", TEXT, re.S)
    assert match, 'inline probe not found'
    return textwrap.dedent(match.group(1))


def load_probe():
    namespace = {'__name__': 'helius_p0_probe_under_test'}
    exec(compile(probe_source(), 'helius_p0_probe', 'exec'), namespace)
    return namespace


class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body, self.reads = status, body, []

    def read(self, size=-1):
        self.reads.append(size)
        return self._body if size < 0 else self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def run(monkeypatch, tmp_path, capsys, outcome, key=KEY):
    probe = load_probe()
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    if key is None:
        monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    else:
        monkeypatch.setenv('HELIUS_API_KEY', key)
    opener = FakeOpener(outcome)
    ticks = iter([100.0, 100.25])
    code = probe['main'](opener=opener, clock=lambda: next(ticks))
    out = capsys.readouterr()
    written = summary.read_text(encoding='utf-8') if summary.exists() else ''
    for channel in (out.out, out.err, written):
        assert KEY not in channel and 'api-key' not in channel and 'helius-rpc.com' not in channel
    return code, out.out.strip(), opener


# --- static guarantees of the workflow file ---------------------------------------------

def test_manual_only_and_accepted_by_the_trigger_guard():
    assert guard.parse_triggers(TEXT) == ['workflow_dispatch']
    assert guard.check_workflow(WORKFLOW.name, TEXT) == []
    assert guard.is_helius_workflow(TEXT) and guard.helius_violations(WORKFLOW.name, TEXT) == []
    assert WORKFLOW.name not in guard.AUTOMATIC_WORKFLOWS


def test_static_hardening():
    code = '\n'.join(line for line in TEXT.splitlines() if not line.lstrip().startswith('#'))
    # Exactly one secret, only in the probe step env.
    assert re.findall(r'secrets\.[A-Za-z_]+', code) == ['secrets.HELIUS_API_KEY']
    assert code.count('${{') == 1
    # No action at all (no checkout, no artifact upload), no write permission, no install.
    assert not re.search(r'^\s*-?\s*uses:', code, re.M)
    assert 'upload-artifact' not in code and 'pip ' not in code and 'curl' not in code
    assert re.search(r'^permissions: \{\}$', code, re.M)
    # Explicit confirmation, single concurrency group, short time limits.
    assert "inputs.confirm == 'RUN-HELIUS-P0-GETHEALTH-ONCE'" in code
    assert "github.event_name == 'workflow_dispatch'" in code
    assert "vars.HELIUS_COLLECTION_ENABLED == 'true'" in code and "github.ref == 'refs/heads/main'" in code
    assert re.search(r'^    environment: helius-collection$', code, re.M)
    assert re.search(r'^concurrency:\n  group: helius-collection\n  cancel-in-progress: false$', code, re.M)
    assert re.findall(r'timeout-minutes: (\d+)', code) == ['2', '1']
    for event in ('pull_request', 'push:', 'schedule', 'workflow_run', 'repository_dispatch'):
        assert event not in code


def test_probe_sends_only_get_health():
    source = probe_source()
    assert re.findall(r'"method":"(\w+)"', source) == ['getHealth']
    for word in ('sendTransaction', 'Keypair', 'sign', 'subprocess', 'socket', 'while ', 'for '):
        assert word not in source
    assert source.count('opener.open(') == 1


# --- behaviour of the exact inline probe -----------------------------------------------

def test_pass_on_get_health_ok(monkeypatch, tmp_path, capsys):
    response = FakeResponse(200, b'{"jsonrpc":"2.0","result":"ok","id":1}')
    code, out, opener = run(monkeypatch, tmp_path, capsys, response)
    assert code == 0
    assert out == 'HELIUS_P0_GETHEALTH=PASS result=ok http=200 latency_ms=250 requests=1'
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert timeout == 10 and request.get_method() == 'POST'
    assert request.full_url == 'https://mainnet.helius-rpc.com/?api-key=' + KEY
    assert request.data == b'{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
    assert response.reads == [4097]
    assert (tmp_path / 'summary.md').read_text().startswith('### Helius P0 getHealth: PASS')


def _http_error(code):
    return urllib.error.HTTPError('https://mainnet.helius-rpc.com/?api-key=' + KEY, code,
                                  'denied for https://mainnet.helius-rpc.com/?api-key=' + KEY,
                                  Message(), io.BytesIO(b'{"key":"%s"}' % KEY.encode()))


@pytest.mark.parametrize('outcome, expected', [
    (FakeResponse(200, b'{"jsonrpc":"2.0","error":{"code":-32005,"message":"behind ' + KEY.encode()
                  + b'"},"id":1}'), 'reason=rpc_error code=-32005 requests=1'),
    (FakeResponse(200, b'{"jsonrpc":"2.0","result":"behind","id":1}'), 'reason=unexpected_result requests=1'),
    (FakeResponse(200, b'{"jsonrpc":"2.0","result":"ok","id":2}'), 'reason=bad_envelope requests=1'),
    (FakeResponse(200, b'["ok"]'), 'reason=bad_envelope requests=1'),
    (FakeResponse(200, b'<html>' + KEY.encode()), 'reason=not_json requests=1'),
    (FakeResponse(200, b' ' * 4097), 'reason=response_too_large requests=1'),
    (FakeResponse(204, b''), 'reason=http_status status=204 requests=1'),
    (_http_error(401), 'reason=http_status status=401 requests=1'),
    (_http_error(429), 'reason=http_status status=429 requests=1'),
    (urllib.error.URLError('connect https://mainnet.helius-rpc.com/?api-key=' + KEY), 'reason=transport_error type=URLError requests=1'),
    (TimeoutError('timed out ' + KEY), 'reason=transport_error type=TimeoutError requests=1'),
])
def test_every_failure_is_fail_with_one_request_and_no_leak(monkeypatch, tmp_path, capsys, outcome, expected):
    code, out, opener = run(monkeypatch, tmp_path, capsys, outcome)
    assert code == 1 and out == 'HELIUS_P0_GETHEALTH=FAIL ' + expected
    assert len(opener.calls) == 1


@pytest.mark.parametrize('key', [None, '', 'short', KEY + '&x=1', KEY + '#', ' ' + KEY, 'a' * 65, 'clé-' + 'a' * 20])
def test_missing_or_malformed_key_sends_nothing(monkeypatch, tmp_path, capsys, key):
    probe = load_probe()
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 's.md'))
    if key is None:
        monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    else:
        monkeypatch.setenv('HELIUS_API_KEY', key)
    opener = FakeOpener(FakeResponse(200, b'{"jsonrpc":"2.0","result":"ok","id":1}'))
    assert probe['main'](opener=opener, clock=lambda: 0.0) == 1
    assert capsys.readouterr().out.strip() == 'HELIUS_P0_GETHEALTH=FAIL reason=key_missing_or_malformed requests=0'
    assert opener.calls == []


def test_unexpected_exception_is_a_fail_without_traceback(monkeypatch, tmp_path, capsys):
    class Exploding(FakeResponse):
        @property
        def status(self):
            raise RuntimeError('boom ' + KEY)

        @status.setter
        def status(self, value):
            pass
    code, out, _opener = run(monkeypatch, tmp_path, capsys, Exploding(200, b''))
    assert code == 1 and out == 'HELIUS_P0_GETHEALTH=FAIL reason=transport_error type=RuntimeError requests=1'


def test_default_opener_has_no_proxy_and_never_follows_redirects(monkeypatch):
    # Even with proxy variables in the environment, the explicit empty ProxyHandler
    # replaces the default one: no proxy handler is installed at all.
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.example:3128')
    monkeypatch.setenv('https_proxy', 'http://proxy.example:3128')
    probe = load_probe()
    opener = probe['build_opener']()
    assert not any(isinstance(h, urllib.request.ProxyHandler) and h.proxies for h in opener.handlers)
    assert not any('proxy_open' in dir(h) for h in opener.handlers)
    redirects = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert redirects and all(isinstance(h, probe['NoRedirect']) for h in redirects)
    assert probe['NoRedirect']().redirect_request(None, None, 302, 'Found', {}, 'https://elsewhere.example/') is None
