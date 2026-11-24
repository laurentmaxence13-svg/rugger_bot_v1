"""Offline tests of activity_l2.py (v2, second measure); based on the tests of activity_l.py (R02 18:01Z, point 6). No network: the transport is a fake."""
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('activity_l2', HERE / 'activity_l2.py')
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
LIST_L = HERE / 'TIME1R_20261124T102126Z' / 'LIST_L.json'
U2J = HERE / 'TIME2_20261124T102839Z' / 'U2.json'
GTFA = HERE / 'TIME2_20261124T102839Z' / 'gtfa'


def _real():
    lst = json.loads(LIST_L.read_bytes())['list']
    u2 = json.loads(U2J.read_bytes())
    names = [f.name[len('creation_'):-len('.json.gz')] for f in sorted(GTFA.glob('creation_*.json.gz'))]
    return lst, u2, names


def test_partition_of_the_real_anchored_inputs():
    lst, u2, names = _real()
    valid, invalid, untested = A.partition(lst, u2, names)
    assert (len(valid), len(invalid), len(untested)) == (24, 20, 215)
    assert set(valid) | set(invalid) | set(untested) == {r['pool'] for r in lst}
    assert not (set(valid) & set(invalid)) and not (set(untested) & (set(valid) | set(invalid)))
    with pytest.raises(SystemExit, match='tested_set_mismatch'):
        A.partition(lst, u2, names[:-1] + ['X'])
    bad = dict(u2, selected=u2['selected'][:-1] + [dict(u2['selected'][-1], pool='NOT_TESTED')])
    with pytest.raises(SystemExit, match='valid_not_in_tested'):
        A.partition(lst, bad, names)
    with pytest.raises(SystemExit, match='valid_not_in_tested'):
        A.partition(lst, dict(u2, selected=u2['selected'][:-1]), names)


def test_n_eff_and_bounds_on_a_synthetic_case():
    valid = ['v%d' % i for i in range(24)]
    invalid = ['i%d' % i for i in range(20)]
    untested = ['u%d' % i for i in range(215)]
    per = {p: 0 for p in valid + invalid + untested}
    for p in valid[:6] + invalid[:5] + untested[:100]:
        per[p] = 50                                       # exactly the threshold counts as active
    per[untested[100]] = 49
    r = A.n_eff(per, valid, invalid, untested)
    assert (r['n50_raw'], r['active_valid'], r['active_invalid'], r['active_untested']) == (111, 6, 5, 100)
    assert r['n_eff_point'] == 6 + 100 * 24 // 44 == 60
    assert (r['n_eff_low'], r['n_eff_high']) == (6 + 38, 6 + 69)
    assert r['verdict'] == 'INFAISABLE'                   # high 75 < 80
    for p in untested[100:140]:
        per[p] = 500
    r = A.n_eff(per, valid, invalid, untested)
    assert (r['n_eff_low'], r['n_eff_high'], r['verdict']) == (6 + 54, 6 + 97, 'ZONE_INCERTAINE')
    for p in untested:
        per[p] = 500
    r = A.n_eff(per, valid, invalid, untested)
    assert r['n_eff_low'] == 6 + 83 and r['verdict'] == 'U2BIS_A_PROPOSER'


def _run(tmp_path, monkeypatch, answer):
    from cpmmpilot import rpc
    out = tmp_path / 'out'

    class Resp:
        def __init__(self, raw):
            self.raw = raw

        def read(self, n=-1):
            return self.raw

    def opener(req, timeout):
        body = json.loads(req.data)
        r = answer(body)
        if isinstance(r, BaseException):
            raise r
        return Resp(json.dumps(r).encode())
    real = rpc.LiveRpc.__init__

    def init(self, endpoint=None, **kw):
        kw['opener'] = opener
        kw['sleep'] = lambda s: None
        real(self, endpoint, **kw)
    monkeypatch.setattr(rpc.LiveRpc, '__init__', init)
    argv = ['activity_l.py', '--pkg', str(HERE.parent / 'cpmmpilot_pkg'), '--list-l', str(LIST_L), '--u2', str(U2J),
            '--gtfa-dir', str(GTFA), '--out', str(out),
            '--prior-result', str(HERE / 'T2_20261124T182222Z' / 'ACTIVITY_RESULT.json'),
            '--prior-ledger', str(HERE / 'T2_20261124T182222Z' / 'ledger_t2.json')]
    monkeypatch.setattr(sys, 'argv', argv)
    A.main()
    return out, json.loads((out / A.RESULT).read_text())


def test_stop_on_429_and_no_signature_in_the_output(tmp_path, monkeypatch, capsys):
    n = dict(k=0)

    def answer(b):
        n['k'] += 1
        if n['k'] == 3:
            return urllib.error.HTTPError('https://x', 429, 'Too Many', {}, None)
        now = 2_000_000_000
        return dict(jsonrpc='2.0', id=b['id'], result=[dict(signature='SIG%06d' % n['k'], slot=1, blockTime=now - 10, err=None)])
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'rate_limited_429' and n['k'] == 3
    assert res['budget']['credits'] == 3 and 'per_pool' not in res
    assert res['partial']['pools_done'] == 2 and res['partial']['non_decisionnel'] is True   # 2 pools done, 3rd failed
    assert 'n50' not in res
    text = (out / A.RESULT).read_text() + (out / 'calls_t2.jsonl').read_text() + capsys.readouterr().out
    assert 'SIG0' not in text
    with pytest.raises(SystemExit, match='t2_already_run'):  # the single-run guard
        _run(tmp_path, monkeypatch, answer)


def test_truncated_response_stops_and_publishes_the_partial(tmp_path, monkeypatch):
    import http.client
    n = dict(k=0)

    def answer(b):
        n['k'] += 1
        if n['k'] == 5:
            return http.client.IncompleteRead(b'x' * 10, 99)
        return dict(jsonrpc='2.0', id=b['id'], result=[dict(signature='Q%d' % n['k'], slot=1, blockTime=2_000_000_000 - 10, err=None)])
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'response_truncated'
    assert res['partial']['pools_done'] == 4 and len(res['partial']['per_pool']) == 4 and 'Q1' not in (out / A.RESULT).read_text()


def test_full_run_counts_only_and_publishes_n50(tmp_path, monkeypatch):
    import time as T
    now = int(T.time())

    def answer(b):
        return dict(jsonrpc='2.0', id=b['id'], result=[
            dict(signature='S%d' % i, slot=1, blockTime=now - 100 - i, err=None) for i in range(60)])
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'DONE' and len(res['per_pool']) == 259
    assert all(v == 60 for v in res['per_pool'].values()) and res['n50']['n50_raw'] == 259
    assert res['budget']['credits'] == 259 and res['budget']['stage'] == 't2' and res['budget']['max_credits'] == 1470 - 186
    assert res['prior_credits'] == 186 and res['cap_this_run'] == 1284
    assert json.loads((out / A.PARTIAL).read_text())['pools_done'] == 259
    assert '"S1"' not in (out / A.RESULT).read_text()
    assert res['n50']['threshold'] == 50 and res['n50']['verdict'] == 'U2BIS_A_PROPOSER'   # 259 active at 50
    for t in ('180', '360', '1000'):                          # DESCRIPTIVE: no verdict, 0 active at 60 signatures
        d = res['descriptive_thresholds'][t]
        assert 'verdict' not in d and d['non_decisionnel'] is True and d['n50_raw'] == 0 and d['threshold'] == int(t)


def test_verdict_comes_from_the_threshold_50_only():
    valid = ['v%d' % i for i in range(24)]
    invalid = ['i%d' % i for i in range(20)]
    untested = ['u%d' % i for i in range(215)]
    per = {p: 100 for p in valid + invalid + untested}       # all active at 50, none at 180
    d = A.descriptive_thresholds(per, valid, invalid, untested)
    assert set(d) == {'180', '360', '1000'} and all('verdict' not in v for v in d.values())
    assert A.n_eff(per, valid, invalid, untested)['verdict'] == 'U2BIS_A_PROPOSER'
    assert d['180']['n_eff_high'] == 0


def test_prior_stop_must_be_the_anchored_one(tmp_path, monkeypatch):
    bad = tmp_path / 'fake_prior.json'
    bad.write_text('{}')
    argv = ['activity_l2.py', '--pkg', str(HERE.parent / 'cpmmpilot_pkg'), '--list-l', str(LIST_L), '--u2', str(U2J),
            '--gtfa-dir', str(GTFA), '--out', str(tmp_path / 'o'), '--prior-result', str(bad),
            '--prior-ledger', str(HERE / 'T2_20261124T182222Z' / 'ledger_t2.json')]
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(SystemExit, match='prior_t2_not_the_anchored_stop'):
        A.main()
    assert not (tmp_path / 'o').exists()


# -- option (b): at most one re-read after a truncated response (R02 1d903d5a) --------------------------------------
def _seq(script):
    """answer() following a script per call number: 'T' truncated, '429', or a page of 1 signature."""
    import http.client
    n = dict(k=0)

    def answer(b):
        n['k'] += 1
        step = script.get(n['k'])
        if step == 'T':
            return http.client.IncompleteRead(b'x', 9)
        if step == '429':
            return urllib.error.HTTPError('https://x', 429, 'Too Many', {}, None)
        return dict(jsonrpc='2.0', id=b['id'], result=[dict(signature='Z', slot=1, blockTime=2_000_000_000 - 10, err=None)])
    return answer, n


def test_retry_one_truncation_then_success_counts_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'RETRY_ON_TRUNCATED', 1)
    answer, n = _seq({3: 'T'})
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'DONE' and res['retries'] == 1 and n['k'] == 260
    assert res['budget']['credits'] == 260                   # the re-read is charged: 259 + 1
    calls = [json.loads(l) for l in (out / 'calls_t2.jsonl').read_text().splitlines()]
    assert sum(1 for c in calls if c.get('retry')) == 1 and len(res['per_pool']) == 259


def test_retry_two_truncations_of_the_same_call_stop_with_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'RETRY_ON_TRUNCATED', 1)
    answer, n = _seq({3: 'T', 4: 'T'})
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'response_truncated' and n['k'] == 4
    assert res['partial']['pools_done'] == 2 and res['retries'] == 1


def test_retry_never_on_429(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'RETRY_ON_TRUNCATED', 1)
    answer, n = _seq({3: '429'})
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'STOP' and res['tag'] == 'rate_limited_429' and n['k'] == 3 and res['retries'] == 0


def test_retry_0_stops_at_the_first_truncation(tmp_path, monkeypatch):
    assert A.RETRY_ON_TRUNCATED == 0                          # the shipped default, fixed by the signed text
    answer, n = _seq({3: 'T'})
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'STOP' and n['k'] == 3 and res['retries'] == 0 and res['partial']['pools_done'] == 2
