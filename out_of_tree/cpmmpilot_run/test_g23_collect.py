"""Offline tests of g23_collect.py (G2-3 window collection, R04-1). No network: the transport is a fake opener."""
import hashlib
import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

from cpmmpilot import rpc, step1

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('g23_collect', HERE / 'g23_collect.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
U2J = HERE / 'TIME2_20261124T102839Z' / 'U2.json'
END = G.T0 + 12 * 86_400
SHA = 'a' * 64


def _tx(i, pool):
    return dict(slot=1000 + i, transactionIndex=0, blockTime=G.T0 + 60 * i, version=1,
                meta=dict(err=None, logMessages=[]), transaction=dict(signatures=['%s_sig%d' % (pool[:6], i)]))


def _setup(tmp_path, monkeypatch, answer):
    auth = tmp_path / 'AUTH_G23_TEST.txt'
    auth.write_text('test text, not an owner text\n')
    digest = hashlib.sha256(auth.read_bytes()).hexdigest()
    monkeypatch.setattr(G, 'G23_TEXT_SHA256', digest)
    monkeypatch.setattr(rpc, 'AUTHORIZED_TEXT_SHA256', frozenset({digest}))
    seen = []

    class Resp:
        def __init__(self, raw):
            self.raw = raw

        def read(self, n=-1):
            return self.raw

    def opener(req, timeout):
        body = json.loads(req.data)
        seen.append(body)
        r = answer(body, len(seen))
        if isinstance(r, BaseException):
            raise r
        if isinstance(r, bytes):
            return Resp(r)
        return Resp(json.dumps(dict(jsonrpc='2.0', id=body['id'], result=r)).encode())
    real = rpc.LiveRpc.__init__

    def init(self, endpoint=None, **kw):
        kw['opener'], kw['sleep'] = opener, (lambda s: None)
        real(self, endpoint, **kw)
    monkeypatch.setattr(rpc.LiveRpc, '__init__', init)
    out = tmp_path / 'out'
    argv = ['--pkg', str(HERE.parent / 'cpmmpilot_pkg'), '--u2', str(U2J), '--out', str(out), '--authorization',
            str(auth), '--sheet-sha', SHA, '--verdict-code-sha', SHA]
    return argv, out, seen


def _two_pages(body, n):
    pool, opts = body['params']
    assert body['method'] == 'getTransactionsForAddress'
    assert opts['filters'] == dict(blockTime=dict(gte=G.T0, lt=END)) and opts['limit'] == 100
    assert opts['maxSupportedTransactionVersion'] == 1
    if opts.get('paginationToken') is None:
        return dict(data=[_tx(0, pool)], paginationToken='t1')
    return dict(data=[_tx(1, pool)], paginationToken=None)


def _result(out):
    return json.loads((out / G.RESULT).read_text())


def test_constants_match_r04_1_and_r02():
    assert G.T0 == 1795515686 and G.D_DAYS == 12 and G.CAP == 32_340 == int(33_000 * 0.98)
    assert G.RETRY_ON_TRUNCATED == 1 and G.G23_TEXT_SHA256 is None
    assert len(G.POOLS) == 4 and len(set(G.POOLS)) == 4
    assert {p[:6] for p in G.POOLS} == {'AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc'}
    assert hashlib.sha256(U2J.read_bytes()).hexdigest() == G.U2_SHA256


def test_refused_before_window_close_without_any_call(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    with pytest.raises(SystemExit, match='window_not_closed'):
        G.main(argv, now=END - 1)
    assert not out.exists() and seen == []


def test_unset_owner_text_refuses_everything(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    monkeypatch.setattr(G, 'G23_TEXT_SHA256', None)
    with pytest.raises(SystemExit, match='g23_owner_text_not_anchored'):
        G.main(argv, now=END)
    assert not out.exists() and seen == []


def test_existing_texts_never_cover_g23(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    for name in ('AUTORISATION_T1_T2.txt', 'AUTORISATION_T2_BIS.txt'):
        f = HERE / name
        monkeypatch.setattr(G, 'G23_TEXT_SHA256', hashlib.sha256(f.read_bytes()).hexdigest())
        a = list(argv)
        a[a.index('--authorization') + 1] = str(f)
        with pytest.raises(SystemExit, match='g23_owner_text_not_anchored'):
            G.main(a, now=END)
    assert not out.exists() and seen == []


def test_bad_anchor_sha_u2_and_out_exists(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    a = list(argv)
    a[a.index('--sheet-sha') + 1] = 'xyz'
    with pytest.raises(SystemExit, match='anchor_sha_must_be_64_hex'):
        G.main(a, now=END)
    bad = tmp_path / 'U2_bad.json'
    bad.write_bytes(U2J.read_bytes() + b' ')
    a = list(argv)
    a[a.index('--u2') + 1] = str(bad)
    with pytest.raises(SystemExit, match='u2_not_anchored'):
        G.main(a, now=END)
    out.mkdir()
    with pytest.raises(SystemExit, match='out_exists'):
        G.main(argv, now=END)
    assert seen == []


def test_pool_absent_from_u2_selection_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    monkeypatch.setattr(G, 'POOLS', G.POOLS[:3] + ('NOT_A_SELECTED_POOL',))
    with pytest.raises(SystemExit, match='pools_or_t0_mismatch'):
        G.main(argv, now=END)
    assert not out.exists() and seen == []


def test_full_run_collects_the_4_pools_and_checks_format(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'DONE' and res['window'] == [G.T0, END] and res['cap'] == 32_340
    assert {p: (s['pages'], s['transactions'], s['done']) for p, s in res['states'].items()} == \
        {p: (2, 2, True) for p in G.POOLS}
    assert res['budget']['requests'] == 8 and res['budget']['max_credits'] == 32_340 and res['retries'] == 0
    assert res['tx_format']['transactions_by_version'] == {'1': 8}
    assert [b['params'][0] for b in seen[::2]] == list(G.POOLS)
    assert res['sheet_sha256'] == res['verdict_code_sha256'] == SHA
    ledger = json.loads((out / 'ledger_g23.json').read_text())
    assert ledger['max_credits'] == 32_340 and ledger['stage'] == 'g23'


def test_one_truncation_is_reread_once_and_charged(tmp_path, monkeypatch):
    def answer(body, n):
        return b'{"jsonrpc": "2.0", "id"' if n == 3 else _two_pages(body, n)
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'DONE' and res['retries'] == 1 and res['budget']['requests'] == 9
    assert sum('"retry":true' in line for line in (out / 'calls_g23.jsonl').read_text().splitlines()) == 1


def test_second_truncation_of_the_same_call_stops_and_keeps_pages(tmp_path, monkeypatch):
    def answer(body, n):
        return b'{"trunc' if n in (3, 4) else _two_pages(body, n)
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'response_truncated' and res['retries'] == 1
    assert res['states'][G.POOLS[0]] == dict(pages=2, transactions=2, done=True)
    assert res['states'][G.POOLS[1]] == dict(pages=0, transactions=0, done=False)
    assert len(seen) == 4 and 'tx_format' not in res


@pytest.mark.parametrize('exc, tag', [(urllib.error.HTTPError('u', 429, 'x', {}, None), 'rate_limited_429'),
                                      (OSError('boom'), 'network_error')])
def test_any_other_incident_stops_without_retry(tmp_path, monkeypatch, exc, tag):
    def answer(body, n):
        return exc if n == 2 else _two_pages(body, n)
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'] == tag and res['retries'] == 0 and len(seen) == 2
    assert res['states'][G.POOLS[0]] == dict(pages=1, transactions=1, done=False)


def test_rpc_error_message_is_not_echoed(tmp_path, monkeypatch, capsys):
    def answer(body, n):
        return b'{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"secret-key=ABC host"}}'
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'].startswith('rpc_error:-32000:')
    assert 'ABC' not in (out / G.RESULT).read_text() and 'ABC' not in capsys.readouterr().out


def test_cap_reached_stops_at_98_percent(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'CAP', 3 * step1.B.COSTS['getTransactionsForAddress'])
    monkeypatch.setattr(step1.B, 'G23_CAP', G.CAP)
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'].startswith('credit_cap_reached') and len(seen) == 3


def test_bad_tx_format_stops_after_collection(tmp_path, monkeypatch):
    def answer(body, n):
        r = _two_pages(body, n)
        if n == 1:
            del r['data'][0]['blockTime']
        return r
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    G.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'STOP_TX_FORMAT:blockTime' and len(seen) == 8


def test_window_bounds_are_exact_to_the_second(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    with pytest.raises(SystemExit, match='window_not_closed'):
        G.main(argv, now=G.T0 + 12 * 86_400 - 1)
    G.main(argv, now=G.T0 + 12 * 86_400)
    assert {tuple(b['params'][1]['filters']['blockTime'].items()) for b in seen} == {(('gte', G.T0), ('lt', END))}


def test_package_without_g23_cap_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    monkeypatch.setattr(step1.B, 'G23_CAP', 33_000)
    with pytest.raises(SystemExit, match='package_without_g23_stage'):
        G.main(argv, now=END)
    assert seen == [] and not out.exists()


def test_extra_pool_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    monkeypatch.setattr(G, 'POOLS', G.POOLS + ('4NX5P7V8gEJydHias47cjUv173FA9pzfDfJNNo2AigJv',))
    with pytest.raises(SystemExit, match='pools_or_t0_mismatch'):
        G.main(argv, now=END)
    assert seen == []


def test_partial_is_published_for_every_pool(tmp_path, monkeypatch):
    def answer(body, n):
        return OSError('x') if n == 1 else _two_pages(body, n)
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    G.main(argv, now=END)
    res = _result(out)
    assert set(res['states']) == set(G.POOLS) and res['verdict_run'] == 'STOP'
    assert all(s == dict(pages=0, transactions=0, done=False) for s in res['states'].values())
    assert res['budget']['requests'] == 1


def test_other_text_than_the_anchored_g23_one_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    other = tmp_path / 'OTHER.txt'
    other.write_text('another text\n')
    od = hashlib.sha256(other.read_bytes()).hexdigest()
    monkeypatch.setattr(rpc, 'AUTHORIZED_TEXT_SHA256', rpc.AUTHORIZED_TEXT_SHA256 | {od})
    a = list(argv)
    a[a.index('--authorization') + 1] = str(other)
    with pytest.raises(SystemExit, match='g23_owner_text_not_anchored'):
        G.main(a, now=END)
    assert seen == [] and not out.exists()


def test_u2_without_one_of_the_pools_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _two_pages)
    doc = json.loads(U2J.read_bytes())
    doc['selected'] = [r for r in doc['selected'] if r['pool'] != G.POOLS[3]]
    bad = tmp_path / 'U2_minus_one.json'
    bad.write_text(json.dumps(doc))
    monkeypatch.setattr(G, 'U2_SHA256', hashlib.sha256(bad.read_bytes()).hexdigest())
    a = list(argv)
    a[a.index('--u2') + 1] = str(bad)
    with pytest.raises(SystemExit, match='pools_or_t0_mismatch'):
        G.main(a, now=END)
    assert seen == [] and not out.exists()
