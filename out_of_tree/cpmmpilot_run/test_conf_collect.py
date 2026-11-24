"""Offline tests of conf_collect.py (confirmation window, R04-8). No network: the transport is a fake opener."""
import hashlib
import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

from cpmmpilot import rpc, step1

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('conf_collect', HERE / 'conf_collect.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
U2J = HERE / 'TIME2_20261124T102839Z' / 'U2.json'
END = C.T1 + 12 * 86_400
SHA = 'b' * 64


def _tx(i, pool):
    return dict(slot=5000 + i, transactionIndex=0, blockTime=C.T1 + 60 * i, version=0,
                meta=dict(err=None, logMessages=[]), transaction=dict(signatures=['%s_c%d' % (pool[:6], i)]))


def _verdicts(tmp_path, **pilots):
    out = []
    for pilot, verdict in pilots.items():
        f = tmp_path / ('verdict_%s.json' % pilot)
        f.write_text(json.dumps(dict(pilot=pilot.replace('_', '-'), verdict=verdict)))
        out += ['--pilot-result', str(f)]
    return out


def _setup(tmp_path, monkeypatch, answer, mode='both', d_days=None, cap=33_000, **pilots):
    pilots = pilots or dict(C_169='GO_PILOTE', C_170='GO_PILOTE')
    auth = tmp_path / 'AUTH_CONF_TEST.txt'
    auth.write_text('test text, not an owner text\n')
    digest = hashlib.sha256(auth.read_bytes()).hexdigest()
    monkeypatch.setattr(C, 'CONF_TEXT_SHA256', digest)
    monkeypatch.setattr(rpc, 'AUTHORIZED_TEXT_SHA256', rpc.AUTHORIZED_TEXT_SHA256 | {digest})
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
    d_days = d_days if d_days is not None else 12
    argv = ['--mode', mode, '--d-days', str(d_days), '--cap', str(cap), '--pkg', str(HERE.parent / 'cpmmpilot_pkg'), '--u2', str(U2J), '--out', str(out),
            '--authorization', str(auth), '--sheet-sha', SHA, '--verdict-code-sha', SHA] + _verdicts(tmp_path, **pilots)
    return argv, out, seen


def _one_page(body, n):
    pool, opts = body['params']
    assert opts['filters'] == dict(blockTime=dict(gte=C.T1, lt=END)) and opts['limit'] == 100
    return dict(data=[_tx(n, pool)], paginationToken=None)


def _result(out):
    return json.loads((out / C.RESULT).read_text())


def test_constants_match_r04_8():
    assert C.T1 == 1796552486 and END == 1797589286 and C.G23_CAP == 32_340 and C.HARD_STOP_PCT == 98
    assert C.RETRY_ON_TRUNCATED == 1 and C.CAP_MAX == 60_000
    assert C.CONF_TEXT_SHA256 is None and '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b' in C.NOT_COVERING
    n1 = json.loads((HERE / 'N1ROT_20261124T215521Z' / 'N1ROT_RESULT.json').read_bytes())
    assert list(C.N1_POOLS) == n1['kept'] and C.N1_LIST_SHA256 == n1['list_sha256']
    g = importlib.util.spec_from_file_location('g23_collect', HERE / 'g23_collect.py')
    G = importlib.util.module_from_spec(g)
    g.loader.exec_module(G)
    assert C.G23_POOLS == G.POOLS and C.G23_POOLS_SHA256 == G.POOLS_SHA256 and C.T1 == G.T0 + G.D_DAYS * 86_400
    assert C.MODES == {'c169': C.G23_POOLS, 'c170': C.N1_POOLS, 'both': C.G23_POOLS}


@pytest.mark.parametrize('mode, pilots, ok', [
    ('c169', dict(C_169='GO_PILOTE'), True), ('c169', dict(C_169='NO_GO'), False),
    ('c169', dict(C_170='GO_PILOTE'), False), ('c170', dict(C_170='GO_PILOTE'), True),
    ('c170', dict(C_169='GO_PILOTE', C_170='NO_GO'), False), ('both', dict(C_169='GO_PILOTE', C_170='GO_PILOTE'), True),
    ('both', dict(C_169='GO_PILOTE', C_170='NO_GO'), False), ('c169', dict(C_169='GO_PILOTE', C_170='GO_PILOTE'), False),
    ('c170', dict(C_169='GO_PILOTE', C_170='GO_PILOTE'), False), ('c169', dict(C_169='GO_PILOTE', C_170='NO_GO'), True),
    ('both', dict(C_169='NO_GO', C_170='NO_GO'), False)])
def test_mode_requires_go_pilote_of_each_confirmed_pilot(tmp_path, monkeypatch, mode, pilots, ok):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page, mode, **pilots)
    if ok:
        C.main(argv, now=END)
        assert _result(out)['verdict_run'] == 'DONE'
    else:
        with pytest.raises(SystemExit, match='mode_needs_a_go_pilote'):
            C.main(argv, now=END)
        assert seen == [] and not out.exists()


def test_unknown_pilot_in_result_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page, 'c169', C_169='GO_PILOTE')
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps(dict(pilot='C-171', verdict='GO_PILOTE')))
    with pytest.raises(SystemExit, match='pilot_result_unknown_pilot'):
        C.main(argv + ['--pilot-result', str(bad)], now=END)
    assert seen == []


def test_window_bounds_exact_and_refused_before_close(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page)
    with pytest.raises(SystemExit, match='window_not_closed'):
        C.main(argv, now=END - 1)
    assert seen == [] and not out.exists()
    C.main(argv, now=END)
    assert {tuple(b['params'][1]['filters']['blockTime'].items()) for b in seen} == {(('gte', C.T1), ('lt', END))}


def test_c170_collects_only_the_3_n1_pools(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page, 'c170', C_170='GO_PILOTE')
    C.main(argv, now=END)
    res = _result(out)
    assert [b['params'][0] for b in seen] == list(C.N1_POOLS) and set(res['states']) == set(C.N1_POOLS)
    assert res['budget']['requests'] == 3 and res['mode'] == 'c170' and res['window'] == [C.T1, END]
    ledger = json.loads((out / 'ledger_conf.json').read_text())
    assert ledger['stage'] == 'g23' and ledger['max_credits'] == 32_340 == 33_000 * 98 // 100


def test_both_collects_the_4_pools_once(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page, 'both')
    C.main(argv, now=END)
    res = _result(out)
    assert [b['params'][0] for b in seen] == list(C.G23_POOLS) and res['budget']['requests'] == 4
    assert res['tx_format']['transactions_by_version'] == {'0': 4}


def test_texts_guard(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page)
    monkeypatch.setattr(C, 'CONF_TEXT_SHA256', None)
    with pytest.raises(SystemExit, match='conf_owner_text_not_anchored'):
        C.main(argv, now=END)
    g23 = HERE / 'AUTORISATION_G23.txt'
    monkeypatch.setattr(C, 'CONF_TEXT_SHA256', hashlib.sha256(g23.read_bytes()).hexdigest())
    a = list(argv)
    a[a.index('--authorization') + 1] = str(g23)
    with pytest.raises(SystemExit, match='conf_owner_text_not_anchored'):
        C.main(a, now=END)
    other = tmp_path / 'OTHER.txt'
    other.write_text('x')
    a[a.index('--authorization') + 1] = str(other)
    monkeypatch.setattr(C, 'CONF_TEXT_SHA256', '0' * 64)
    with pytest.raises(SystemExit, match='conf_owner_text_not_anchored'):
        C.main(a, now=END)
    assert seen == [] and not out.exists()


def test_pool_lists_pinned(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page)
    monkeypatch.setattr(C, 'N1_POOLS', C.N1_POOLS + ('Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr',))
    with pytest.raises(SystemExit, match='pools_mismatch'):
        C.main(argv, now=END)
    monkeypatch.undo()
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page)
    monkeypatch.setattr(C, 'G23_POOLS', C.G23_POOLS[:3])
    with pytest.raises(SystemExit, match='pools_mismatch'):
        C.main(argv, now=END)
    assert seen == []


def test_bad_inputs_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page)
    a = list(argv)
    a[a.index('--verdict-code-sha') + 1] = 'nothex'
    with pytest.raises(SystemExit, match='anchor_sha_must_be_64_hex'):
        C.main(a, now=END)
    bad = tmp_path / 'U2_bad.json'
    bad.write_bytes(U2J.read_bytes() + b' ')
    a = list(argv)
    a[a.index('--u2') + 1] = str(bad)
    with pytest.raises(SystemExit, match='u2_not_anchored'):
        C.main(a, now=END)
    monkeypatch.setattr(step1.B, 'G23_CAP', 33_000)
    with pytest.raises(SystemExit, match='package_without_g23_stage'):
        C.main(argv, now=END)
    monkeypatch.setattr(step1.B, 'G23_CAP', 32_340)
    out.mkdir()
    with pytest.raises(SystemExit, match='out_exists'):
        C.main(argv, now=END)
    assert seen == []


def test_one_truncation_reread_then_second_stops_with_partial(tmp_path, monkeypatch):
    def answer(body, n):
        return b'{"x' if n in (2, 4, 5) else _one_page(body, n)
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    C.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'response_truncated' and res['retries'] == 2
    assert [res['states'][p]['done'] for p in C.G23_POOLS] == [True, True, False, False]
    assert res['budget']['requests'] == 5 and 'tx_format' not in res


@pytest.mark.parametrize('exc, tag', [(urllib.error.HTTPError('u', 429, 'x', {}, None), 'rate_limited_429'),
                                      (OSError('boom'), 'network_error')])
def test_other_incident_stops_without_retry(tmp_path, monkeypatch, exc, tag):
    def answer(body, n):
        return exc if n == 1 else _one_page(body, n)
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    C.main(argv, now=END)
    res = _result(out)
    assert res['verdict_run'] == 'STOP' and res['tag'] == tag and res['retries'] == 0 and len(seen) == 1
    assert set(res['states']) == set(C.G23_POOLS)


def test_cap_reached_stops(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, lambda b, n: dict(data=[_tx(n, b['params'][0])], paginationToken='t%d' % n),
                             cap=1_000)
    C.main(argv, now=END)
    res = _result(out)
    assert res['cap'] == 980 and res['owner_cap'] == 1_000 and res['budget']['max_credits'] == 980
    assert res['verdict_run'] == 'STOP' and res['tag'].startswith('credit_cap_reached') and len(seen) == 98


def test_bad_tx_format_stops(tmp_path, monkeypatch):
    def answer(body, n):
        r = _one_page(body, n)
        if n == 3:
            del r['data'][0]['slot']
        return r
    argv, out, seen = _setup(tmp_path, monkeypatch, answer)
    C.main(argv, now=END)
    assert _result(out)['tag'] == 'STOP_TX_FORMAT:slot'


@pytest.mark.parametrize('mode, d, ok', [('c170', 12, True), ('c170', 13, False), ('c169', 11, False), ('c169', 12, True),
                                         ('c169', 30, True), ('c169', 31, False), ('both', 20, True), ('both', 31, False)])
def test_duration_rules(tmp_path, monkeypatch, mode, d, ok):
    end = C.T1 + d * 86_400

    def answer(body, n):
        assert body['params'][1]['filters'] == dict(blockTime=dict(gte=C.T1, lt=end))
        return dict(data=[], paginationToken=None)
    pilots = {'c169': dict(C_169='GO_PILOTE'), 'c170': dict(C_170='GO_PILOTE'),
              'both': dict(C_169='GO_PILOTE', C_170='GO_PILOTE')}[mode]
    argv, out, seen = _setup(tmp_path, monkeypatch, answer, mode, d, **pilots)
    if ok:
        with pytest.raises(SystemExit, match='window_not_closed'):
            C.main(argv, now=end - 1)
        C.main(argv, now=end)
        res = _result(out)
        assert res['d_days'] == d and res['window'] == [C.T1, end] and res['verdict_run'] == 'DONE'
    else:
        with pytest.raises(SystemExit, match='c170_window_is_12_days|d_c_out_of_12_30'):
            C.main(argv, now=C.T1 + 40 * 86_400)
        assert seen == [] and not out.exists()


@pytest.mark.parametrize('cap, stop', [(53_190, 52_126), (41_001, 40_180), (60_000, 58_800), (1_000, 980)])
def test_owner_cap_p_drives_the_hard_stop(tmp_path, monkeypatch, cap, stop):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page, cap=cap)
    C.main(argv, now=END)
    assert _result(out)['cap'] == stop == cap * 98 // 100
    assert json.loads((out / 'ledger_conf.json').read_text())['max_credits'] == stop


@pytest.mark.parametrize('cap', [999, 60_001, 1_000_000, 0])
def test_cap_out_of_range_refused(tmp_path, monkeypatch, cap):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page, cap=cap)
    with pytest.raises(SystemExit, match='cap_out_of_range'):
        C.main(argv, now=END)
    assert seen == [] and not out.exists()


def test_g23_list_swapped_outside_n1_is_refused(tmp_path, monkeypatch):
    argv, out, seen = _setup(tmp_path, monkeypatch, _one_page)
    swapped = tuple('4NX5P7V8gEJydHias47cjUv173FA9pzfDfJNNo2AigJv' if p.startswith('Gms3Ma') else p for p in C.G23_POOLS)
    monkeypatch.setattr(C, 'G23_POOLS', swapped)
    with pytest.raises(SystemExit, match='pools_mismatch'):
        C.main(argv, now=END)
    assert seen == [] and not out.exists()
