"""Offline tests of activity_l.py (R02 18:01Z, point 6). No network: the transport is a fake."""
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('activity_l', HERE / 'activity_l.py')
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
            '--gtfa-dir', str(GTFA), '--out', str(out)]
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
    text = (out / A.RESULT).read_text() + (out / 'calls_t2.jsonl').read_text() + capsys.readouterr().out
    assert 'SIG0' not in text
    with pytest.raises(SystemExit, match='t2_already_run'):  # the single-run guard
        _run(tmp_path, monkeypatch, answer)


def test_full_run_counts_only_and_publishes_n50(tmp_path, monkeypatch):
    import time as T
    now = int(T.time())

    def answer(b):
        return dict(jsonrpc='2.0', id=b['id'], result=[
            dict(signature='S%d' % i, slot=1, blockTime=now - 100 - i, err=None) for i in range(60)])
    out, res = _run(tmp_path, monkeypatch, answer)
    assert res['verdict_run'] == 'DONE' and len(res['per_pool']) == 259
    assert all(v == 60 for v in res['per_pool'].values()) and res['n50']['n50_raw'] == 259
    assert res['budget']['credits'] == 259 and res['budget']['stage'] == 't2' and res['budget']['max_credits'] == 1470
    assert '"S1"' not in (out / A.RESULT).read_text()
