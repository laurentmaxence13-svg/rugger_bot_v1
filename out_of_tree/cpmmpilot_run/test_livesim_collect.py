"""Offline tests of livesim_collect.py (R04-10). No network: the transport is a fake opener."""
import hashlib
import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

from cpmmpilot import budget as B
from cpmmpilot import rpc, u2

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('livesim_collect', HERE / 'livesim_collect.py')
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
UNI = HERE / 'LIVESIM_UNIVERSE.json'
ROWS = sorted(json.loads(UNI.read_bytes())['ordered'], key=lambda r: r['rank'])
NOW = 1_800_000_000
T_START = NOW - 600


def _creation(pool, ok=True, young=False):
    logs = ['Program %s invoke [1]' % u2.CPMM_PROGRAM, 'Program log: Instruction: Initialize',
            'Program %s success' % u2.CPMM_PROGRAM]
    if not ok:
        logs.insert(0, 'Program %s invoke [1]' % u2.LAUNCHLAB_PROGRAM)
    bt = T_START - (3 if young else 30) * 86_400
    return dict(slot=1, transactionIndex=0, blockTime=bt, meta=dict(err=None, logMessages=logs),
                transaction=dict(signatures=['cre_' + pool[:6]]))


def _tx(pool, t, i):
    return dict(slot=10 + i, transactionIndex=0, blockTime=t, version=1, meta=dict(err=None, logMessages=[]),
                transaction=dict(signatures=['%s_%d_%d' % (pool[:6], t, i)]))


class Chain:
    def __init__(self, bad=(), young=(), fail_at=None, truncate_at=()):
        self.bad, self.young, self.fail_at, self.truncate_at, self.n, self.seen = bad, young, fail_at, truncate_at, 0, []

    def __call__(self, body):
        self.n += 1
        self.seen.append(body)
        if self.n == self.fail_at:
            return OSError('x')
        if self.n in self.truncate_at:
            return b'{"tr'
        pool, opts = body['params']
        if opts['sortOrder'] == 'asc' and opts['limit'] == 1 and 'filters' not in opts:
            return dict(data=[_creation(pool, pool[:6] not in self.bad, pool[:6] in self.young)], paginationToken=None)
        f = opts['filters']['blockTime']
        return dict(data=[_tx(pool, f['gte'], self.n)], paginationToken=None)


def _setup(tmp_path, monkeypatch, chain, cap=15_000):
    auth = tmp_path / 'AUTH_LIVESIM_TEST.txt'
    auth.write_text('test text, not an owner text\n')
    digest = hashlib.sha256(auth.read_bytes()).hexdigest()
    monkeypatch.setattr(L, 'LIVESIM_TEXT_SHA256', digest)
    monkeypatch.setattr(rpc, 'AUTHORIZED_TEXT_SHA256', rpc.AUTHORIZED_TEXT_SHA256 | {digest})

    class Resp:
        def __init__(self, raw):
            self.raw = raw

        def read(self, n=-1):
            return self.raw

    def opener(req, timeout):
        body = json.loads(req.data)
        r = chain(body)
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

    def argv(phase, t_start=T_START, cap_=cap, universe=UNI, authorization=auth):
        return ['--phase', phase, '--pkg', str(HERE.parent / 'cpmmpilot_pkg'), '--universe', str(universe),
                '--out', str(out), '--t-start', str(t_start), '--cap', str(cap_), '--authorization', str(authorization)]
    return argv, out


def test_constants_and_universe():
    assert L.K == 8 and L.HISTORY_S == 7 * 86_400 and L.LIVE_S == 86_400 and L.HARD_STOP_PCT == 98
    assert L.CAP_MAX == 20_000 and L.RETRY_ON_TRUNCATED == 1 and L.LIVESIM_TEXT_SHA256 is None and L.MARGIN_S == 120
    assert '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b' in L.NOT_COVERING
    assert len(L.FORBIDDEN) == 5 and not L.FORBIDDEN & {r['pool'] for r in ROWS}
    assert L.list_sha([r['pool'] for r in ROWS]) == L.UNIVERSE_LIST_SHA256 and len(ROWS) == 10
    assert 'livesim' in B.STAGES


def test_full_cycle_qualify_history_polls(tmp_path, monkeypatch):
    chain = Chain()
    argv, out = _setup(tmp_path, monkeypatch, chain)
    r = L.main(argv('qualify'), now=NOW)
    q = json.loads((out / 'QUALIFIED.json').read_text())
    assert r['verdict_run'] == 'DONE' and q['pools'] == [x['pool'] for x in ROWS[:8]] and q['complete']
    assert chain.n == 7                                  # CXgcuE is already 'valid': no call for it
    L.main(argv('history'), now=NOW)
    hist = [b for b in chain.seen[7:]]
    assert len(hist) == 8 and {tuple(b['params'][1]['filters']['blockTime'].values()) for b in hist} == \
        {(T_START - 7 * 86_400, T_START)}
    L.main(argv('poll'), now=NOW + 3_600)
    L.main(argv('poll'), now=NOW + 7_200)
    polls = json.loads((out / 'POLLS.json').read_text())
    assert [p['window'] for p in polls] == [[T_START, NOW + 3_600 - 120], [NOW + 3_600 - 120, NOW + 7_200 - 120]]
    assert all(p['done'] for p in polls)
    L.main(argv('poll'), now=T_START + 30 * 3_600)
    polls = json.loads((out / 'POLLS.json').read_text())
    assert polls[-1]['window'][1] == T_START + 86_400
    r = L.main(argv('poll'), now=T_START + 31 * 3_600)
    assert r['result'] == dict(nothing_to_collect=True, edge=T_START + 86_400)
    ledger = json.loads((out / 'ledger_livesim.json').read_text())
    assert ledger['stage'] == 'livesim' and ledger['max_credits'] == 14_700
    assert len((out / 'PASSES.jsonl').read_text().splitlines()) == 6


def test_replacements_taken_in_order(tmp_path, monkeypatch):
    chain = Chain(bad=('GaPTvX',), young=('6CQSpR',))
    argv, out = _setup(tmp_path, monkeypatch, chain)
    L.main(argv('qualify'), now=NOW)
    q = json.loads((out / 'QUALIFIED.json').read_text())
    want = [x['pool'] for x in ROWS if x['pool'][:6] not in ('GaPTvX', '6CQSpR')][:8]
    assert q['pools'] == want and q['complete'] and q['list_sha256'] == L.list_sha(want)
    assert {t['reason'] for t in q['tested'] if not t['valid']} == {'launchlab_in_creation_transaction', 'younger_than_7_days'}


def test_too_few_valid_is_published_incomplete(tmp_path, monkeypatch):
    chain = Chain(bad=('GaPTvX', 'CqvMZm', '6CQSpR'))
    argv, out = _setup(tmp_path, monkeypatch, chain)
    L.main(argv('qualify'), now=NOW)
    q = json.loads((out / 'QUALIFIED.json').read_text())
    assert q['k'] == 7 and not q['complete'] and chain.n == 9


def test_order_of_phases_and_single_use(tmp_path, monkeypatch):
    argv, out = _setup(tmp_path, monkeypatch, Chain())
    with pytest.raises(SystemExit, match='qualify_first'):
        L.main(argv('history'), now=NOW)
    L.main(argv('qualify'), now=NOW)
    with pytest.raises(SystemExit, match='already_qualified'):
        L.main(argv('qualify'), now=NOW)
    with pytest.raises(SystemExit, match='history_first'):
        L.main(argv('poll'), now=NOW)
    L.main(argv('history'), now=NOW)
    with pytest.raises(SystemExit, match='history_already_done'):
        L.main(argv('history'), now=NOW)


def test_config_cannot_change_between_passes(tmp_path, monkeypatch):
    argv, out = _setup(tmp_path, monkeypatch, Chain())
    L.main(argv('qualify'), now=NOW)
    with pytest.raises(SystemExit, match='config_differs'):
        L.main(argv('history', t_start=T_START - 1), now=NOW)
    with pytest.raises(SystemExit, match='config_differs'):
        L.main(argv('history', cap_=16_000), now=NOW)


@pytest.mark.parametrize('t_start, ok', [(NOW, True), (NOW - 3_600, True), (NOW - 3_601, False), (NOW + 1, False)])
def test_t_start_at_qualify(tmp_path, monkeypatch, t_start, ok):
    argv, out = _setup(tmp_path, monkeypatch, Chain())
    if ok:
        assert L.main(argv('qualify', t_start=t_start), now=NOW)['verdict_run'] == 'DONE'
    else:
        with pytest.raises(SystemExit, match='t_start_must_be'):
            L.main(argv('qualify', t_start=t_start), now=NOW)
        assert not out.exists()


@pytest.mark.parametrize('cap, ok', [(20_000, True), (20_001, False), (999, False), (1_000, True)])
def test_cap_bounds(tmp_path, monkeypatch, cap, ok):
    argv, out = _setup(tmp_path, monkeypatch, Chain(), cap=cap)
    if ok:
        L.main(argv('qualify'), now=NOW)
        assert json.loads((out / 'ledger_livesim.json').read_text())['max_credits'] == cap * 98 // 100
    else:
        with pytest.raises(SystemExit, match='cap_out_of_range'):
            L.main(argv('qualify'), now=NOW)


def test_texts_guard(tmp_path, monkeypatch):
    chain = Chain()
    argv, out = _setup(tmp_path, monkeypatch, chain)
    monkeypatch.setattr(L, 'LIVESIM_TEXT_SHA256', None)
    with pytest.raises(SystemExit, match='livesim_owner_text_not_anchored'):
        L.main(argv('qualify'), now=NOW)
    g23 = HERE / 'AUTORISATION_G23.txt'
    monkeypatch.setattr(L, 'LIVESIM_TEXT_SHA256', hashlib.sha256(g23.read_bytes()).hexdigest())
    with pytest.raises(SystemExit, match='livesim_owner_text_not_anchored'):
        L.main(argv('qualify', authorization=g23), now=NOW)
    monkeypatch.setattr(L, 'LIVESIM_TEXT_SHA256', '0' * 64)
    with pytest.raises(SystemExit, match='livesim_owner_text_not_anchored'):
        L.main(argv('qualify'), now=NOW)
    assert chain.n == 0 and not out.exists()


def test_forbidden_or_unanchored_universe_refused(tmp_path, monkeypatch):
    chain = Chain()
    argv, out = _setup(tmp_path, monkeypatch, chain)
    doc = json.loads(UNI.read_bytes())
    doc['ordered'][0]['pool'] = 'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh'
    bad = tmp_path / 'U.json'
    bad.write_text(json.dumps(doc))
    with pytest.raises(SystemExit, match='universe_not_anchored'):
        L.main(argv('qualify', universe=bad), now=NOW)
    pools = [r['pool'] for r in sorted(doc['ordered'], key=lambda r: r['rank'])]
    monkeypatch.setattr(L, 'UNIVERSE_LIST_SHA256', L.list_sha(pools))
    doc['ordered_list_sha256'] = L.list_sha(pools)
    bad.write_text(json.dumps(doc))
    with pytest.raises(SystemExit, match='forbidden_or_duplicate_pool'):
        L.main(argv('qualify', universe=bad), now=NOW)
    assert chain.n == 0 and not out.exists()


def test_package_without_livesim_stage(tmp_path, monkeypatch):
    argv, out = _setup(tmp_path, monkeypatch, Chain())
    monkeypatch.setattr(B, 'STAGES', ('g23',))
    with pytest.raises(SystemExit, match='package_without_livesim_stage'):
        L.main(argv('qualify'), now=NOW)


def test_incident_stops_and_blocks_later_passes(tmp_path, monkeypatch):
    chain = Chain(fail_at=9)
    argv, out = _setup(tmp_path, monkeypatch, chain)
    L.main(argv('qualify'), now=NOW)
    r = L.main(argv('history'), now=NOW)
    assert r['verdict_run'] == 'STOP' and r['tag'] == 'network_error' and r['retries'] == 0
    assert (out / 'STOP.json').exists() and not (out / 'HISTORY_DONE.json').exists()
    n = chain.n
    with pytest.raises(SystemExit, match='stopped_earlier'):
        L.main(argv('history'), now=NOW)
    assert chain.n == n


def test_one_truncation_reread_second_stops(tmp_path, monkeypatch):
    chain = Chain(truncate_at=(8,))
    argv, out = _setup(tmp_path, monkeypatch, chain)
    L.main(argv('qualify'), now=NOW)
    r = L.main(argv('history'), now=NOW)
    assert r['verdict_run'] == 'DONE' and r['retries'] == 1
    chain2 = Chain(truncate_at=(8, 9))
    monkeypatch.undo()
    (tmp_path / 'b').mkdir()
    argv2, out2 = _setup(tmp_path / 'b', monkeypatch, chain2)
    L.main(argv2('qualify'), now=NOW)
    r = L.main(argv2('history'), now=NOW)
    assert r['verdict_run'] == 'STOP' and r['tag'] == 'response_truncated'


def test_429_never_reread(tmp_path, monkeypatch):
    class C429(Chain):
        def __call__(self, body):
            self.n += 1
            if self.n == 2:
                return urllib.error.HTTPError('u', 429, 'x', {}, None)
            self.n -= 1
            return Chain.__call__(self, body)
    chain = C429()
    argv, out = _setup(tmp_path, monkeypatch, chain)
    r = L.main(argv('qualify'), now=NOW)
    assert r['verdict_run'] == 'STOP' and r['tag'] == 'rate_limited_429' and r['retries'] == 0


def test_unfinished_chunk_is_resumed_not_recut(tmp_path, monkeypatch):
    chain = Chain()
    argv, out = _setup(tmp_path, monkeypatch, chain)
    L.main(argv('qualify'), now=NOW)
    L.main(argv('history'), now=NOW)
    (out / 'POLLS.json').write_text(json.dumps([dict(name='live_000', window=[T_START, T_START + 500], done=False)]))
    L.main(argv('poll'), now=NOW + 3_600)
    polls = json.loads((out / 'POLLS.json').read_text())
    assert polls == [dict(name='live_000', window=[T_START, T_START + 500], done=True)]


def test_cap_reached_stops(tmp_path, monkeypatch):
    chain = Chain()
    argv, out = _setup(tmp_path, monkeypatch, chain, cap=1_000)
    L.main(argv('qualify'), now=NOW)
    r = L.main(argv('history'), now=NOW)
    assert r['verdict_run'] == 'DONE'
    for h in range(1, 200):
        r = L.main(argv('poll'), now=NOW + h * 600)
        if r['verdict_run'] == 'STOP':
            break
    assert r['tag'].startswith('credit_cap_reached') and r['budget']['credits'] <= 980
