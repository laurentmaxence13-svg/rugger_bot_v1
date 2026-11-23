import gzip
import hashlib
import io
import json
import tarfile

import pytest

from cpmmx.events import CPMM_PROGRAM
from cpmmpilot import budget as B
from cpmmpilot import fixtures, layout as L, rpc, step1, store, u2


def test_program_id_is_the_frozen_one():
    assert CPMM_PROGRAM == 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'


def test_filters_are_the_owner_text_ones():
    assert L.config_filters() == [{'dataSize': 236}, {'memcmp': {'offset': 0, 'bytes': 'dd8DvH45THQ'}},
                                  {'memcmp': {'offset': 12, 'bytes': 'Znnd43p7RpT'}}]
    f = L.pool_filters('CFG', 168)
    assert f[0] == {'dataSize': 637} and f[1]['memcmp']['bytes'] == 'iUE1qg7KXeV' and f[3]['memcmp']['bytes'] == L.WSOL
    with pytest.raises(L.LayoutError):
        L.pool_filters('CFG', 40)
    assert L.POOL_SLICE == (0, 413)


def test_b58_any_roundtrip():
    for raw in (L.CONFIG_DISCRIMINATOR, L.POOL_DISCRIMINATOR, (2500).to_bytes(8, 'little'), b'\0\0\x05' + b'x' * 29):
        assert L.b58decode_any(L.b58encode(raw)) == raw


def test_budget_charges_before_and_is_monotone(tmp_path):
    led = tmp_path / 'l.json'
    b = B.PilotBudget(led, stage='step1', max_credits=25)
    b.charge('getTransactionsForAddress', ['p', {'limit': 100}])
    b.charge('getSignaturesForAddress', ['p', {}])
    assert json.loads(led.read_text())['credits'] == 11
    b2 = B.PilotBudget(led, stage='step1', max_credits=25)
    assert b2.credits == 11
    b2.charge('getTransactionsForAddress', ['p', {'limit': 100}])
    with pytest.raises(B.BudgetExhausted):
        b2.charge('getTransactionsForAddress', ['p', {'limit': 100}])
    with pytest.raises(B.BudgetError):
        B.PilotBudget(led, stage='step1', max_credits=30)
    with pytest.raises(B.BudgetError):
        b2.charge('getTransactionsForAddress', ['p', {'limit': 101}])
    with pytest.raises(B.BudgetError):
        b2.charge('getBlock', [])


def test_costs_match_the_w1_grid_on_shared_methods():
    from bot.market.backfill import COST_PRESETS
    grid = COST_PRESETS['helius-documented-20261108']
    for m, c in grid.items():
        assert B.COSTS[m] == c


def test_point2_and_dmax():
    assert B.point2_stop(1692)['stop'] is False and B.point2_stop(1693)['stop'] is True
    assert abs(B.d_max_days(500) - ((32_900 - 400) / 1200 - 7)) < 1e-9
    assert B.STEP1_HARD_STOP == 49_000


def test_live_rpc_refused():
    with pytest.raises(rpc.RpcError, match='needs_an_anchored_authorization'):
        rpc.LiveRpc('https://example.invalid')


# -- 0.2: the live transport (R02 note fb28705b), tested with an injected opener: no socket is ever opened ---------
ENDPOINT = 'https://rpc.example.invalid/v1'


class _Resp:
    def __init__(self, raw):
        self.raw = raw

    def read(self, n=-1):
        return self.raw if n < 0 else self.raw[:n]


class _Opener:
    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def __call__(self, req, timeout):
        self.seen.append((req, timeout))
        body = json.loads(req.data)
        out = self.answer(body) if callable(self.answer) else self.answer
        if isinstance(out, BaseException):
            raise out
        return _Resp(out if isinstance(out, bytes) else json.dumps(out).encode())


def _authorized(tmp_path, monkeypatch, text=b'texte A ancre (synthetique)'):
    f = tmp_path / 'AUTORISATION.txt'
    f.write_bytes(text)
    monkeypatch.setattr(rpc, 'AUTHORIZED_TEXT_SHA256', frozenset({hashlib.sha256(text).hexdigest()}))
    return f


def test_live_rpc_release_authorizes_nothing_and_unanchored_text_is_refused(tmp_path):
    assert rpc.AUTHORIZED_TEXT_SHA256 == frozenset()                     # 0.2: no network call is possible
    f = tmp_path / 'a.txt'
    f.write_bytes(b'any text')
    with pytest.raises(rpc.RpcError, match='authorization_not_anchored'):
        rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=_Opener({}))
    with pytest.raises(rpc.RpcError, match='authorization_file_unreadable'):
        rpc.LiveRpc(ENDPOINT, authorization_file=tmp_path / 'missing.txt', opener=_Opener({}))


def test_live_rpc_reads_no_host_and_no_key_and_refuses_credentials_in_the_endpoint(tmp_path, monkeypatch):
    import ast
    import inspect
    f = _authorized(tmp_path, monkeypatch)
    tree = ast.parse(inspect.getsource(rpc))
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    code = set()
    for n in ast.walk(tree):                              # every name, attribute, import and string of the CODE
        if isinstance(n, ast.Name):
            code.add(n.id)
        elif isinstance(n, ast.Attribute):
            code.add(n.attr)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            code.update(a.name for a in n.names)
            code.add(getattr(n, 'module', None) or '')
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            code.add(n.value)
    text = ' '.join(code).lower()
    for forbidden in ('environ', 'getenv', 'dotenv', '.env', 'helius', 'api-key', 'api_key', 'open('):
        assert forbidden not in text, forbidden
    assert 'os' not in code and 'environ' not in code
    for bad in ('http://rpc.example.invalid', 'https://rpc.example.invalid/?api-key=SECRET',
                'https://u:p@rpc.example.invalid', 'https://rpc.example.invalid/key/SECRET', 'https://x/#f', None):
        with pytest.raises(rpc.RpcError):
            rpc.LiveRpc(bad, authorization_file=f, opener=_Opener({}))
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=_Opener({}))
    assert 'example' not in repr(live)


def test_live_rpc_json_rpc_round_trip_and_charge_before_send(tmp_path, monkeypatch):
    f = _authorized(tmp_path, monkeypatch)
    op = _Opener(lambda b: dict(jsonrpc='2.0', id=b['id'], result=dict(context=dict(slot=7), value=[b['method']])))
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=op, timeout_s=30)
    client = _client(live, tmp_path, 'step0', B.STEP0_CAP)
    assert client.call('getSlot', [{'commitment': 'finalized'}])['value'] == ['getSlot']
    req, timeout = op.seen[0]
    assert req.full_url == ENDPOINT and req.get_method() == 'POST' and timeout == 30
    assert req.get_header('Content-type') == 'application/json'
    assert json.loads(req.data) == dict(jsonrpc='2.0', id=1, method='getSlot', params=[{'commitment': 'finalized'}])
    assert client.budget.credits == 1
    with pytest.raises(rpc.RpcError, match='method_not_in_pilot'):
        live.request('sendTransaction', [])
    assert set(rpc.PILOT_METHODS) == set(B.COSTS)


def test_live_rpc_failures_stop_without_retry_and_never_echo_endpoint_or_message(tmp_path, monkeypatch):
    import urllib.error
    f = _authorized(tmp_path, monkeypatch)
    secret_msg = 'quota for https://rpc.example.invalid/v1 exceeded'
    cases = [
        (urllib.error.HTTPError(ENDPOINT, 429, 'Too Many', {}, None), rpc.RpcError, 'rate_limited_429'),
        (urllib.error.HTTPError(ENDPOINT, 401, 'no', {}, None), rpc.RpcError, 'unauthorized_401'),
        (urllib.error.HTTPError(ENDPOINT, 500, 'x', {}, None), rpc.RpcError, 'http_500'),
        (urllib.error.URLError('dns rpc.example.invalid'), rpc.RpcError, 'network_error'),
        (b'{"jsonrpc":"2.0","id":1,"res', rpc.RpcError, 'response_truncated'),
        (dict(jsonrpc='2.0', id=99, result=1), rpc.RpcError, 'response_id_mismatch'),
        (dict(jsonrpc='2.0', id=1), rpc.RpcError, 'response_without_result'),
        (dict(jsonrpc='2.0', id=1, error=dict(code=-32601, message='Method not found')), rpc.MethodRefused, 'method_refused'),
        (dict(jsonrpc='2.0', id=1, error=dict(code=-32603, message='not available on your plan, upgrade')),
         rpc.MethodRefused, 'method_refused'),
        (dict(jsonrpc='2.0', id=1, error=dict(code=-32000, message=secret_msg)), rpc.RpcError, 'rpc_error'),
    ]
    for answer, exc, tag in cases:
        op = _Opener(answer)
        live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=op)
        with pytest.raises(exc, match=tag) as info:
            live.request('getTransactionsForAddress', ['P', dict(limit=1)])
        assert len(op.seen) == 1, tag                                        # no retry inside the transport
        assert 'example' not in str(info.value) and 'quota' not in str(info.value), tag
        assert info.value.__cause__ is None, tag


def test_live_rpc_response_size_is_bounded(tmp_path, monkeypatch):
    f = _authorized(tmp_path, monkeypatch)
    monkeypatch.setattr(rpc, 'MAX_RESPONSE_BYTES', 10)
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=_Opener(dict(jsonrpc='2.0', id=1, result='x' * 50)))
    with pytest.raises(rpc.RpcError, match='response_too_large'):
        live.request('getSlot', [])


def test_live_rpc_gtfa_refusal_stops_u2_without_fallback(tmp_path, monkeypatch):
    f = _authorized(tmp_path, monkeypatch)
    chain, spec = fixtures.build(n_pools=24)
    chain.slot = spec['t0_slot']

    def answer(b):
        if b['method'] == 'getTransactionsForAddress':
            return dict(jsonrpc='2.0', id=b['id'], error=dict(code=-32603, message='requires a paid plan'))
        return dict(jsonrpc='2.0', id=b['id'], result=json.loads(json.dumps(chain.request(b['method'], b['params']))))
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=_Opener(answer))
    with pytest.raises(u2.U2Stop, match='gtfa_refused_no_fallback'):
        u2.run(_client(live, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=spec['t0_time'])


def test_permutation_is_deterministic_and_seeded_by_sha_l():
    lst = [dict(pool='P%02d' % k) for k in range(30)]
    s = rpc.sha(lst)
    assert u2.permutation(lst, s) == u2.permutation(lst, s)
    assert sorted(u2.permutation(lst, s)) == [r['pool'] for r in lst]
    assert u2.permutation(lst, s) != u2.permutation(lst, '0' * 64)


def _logs(*programs_depth_init):
    return programs_depth_init


def test_creation_check_cases():
    ok = dict(blockTime=1000, meta=dict(logMessages=['Program %s invoke [1]' % CPMM_PROGRAM,
                                                    'Program log: Instruction: Initialize',
                                                    'Program %s success' % CPMM_PROGRAM]))
    t0 = 1000 + 8 * 86_400
    assert u2.creation_check(ok, t0_time=t0) == (True, 'ok')
    assert u2.creation_check(ok, t0_time=1000 + 6 * 86_400)[1] == 'younger_than_7_days'
    ll = dict(ok, meta=dict(logMessages=['Program %s invoke [1]' % u2.LAUNCHLAB_PROGRAM,
                                         'Program %s invoke [2]' % CPMM_PROGRAM, 'Program log: Instruction: Initialize',
                                         'Program %s success' % CPMM_PROGRAM, 'Program %s success' % u2.LAUNCHLAB_PROGRAM]))
    assert u2.creation_check(ll, t0_time=t0)[1] == 'launchlab_in_creation_transaction'
    other = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
    deep = dict(ok, meta=dict(logMessages=['Program %s invoke [1]' % other, 'Program %s invoke [2]' % CPMM_PROGRAM,
                                           'Program log: Instruction: Initialize', 'Program %s success' % CPMM_PROGRAM,
                                           'Program %s success' % other]))
    assert u2.creation_check(deep, t0_time=t0)[1] == 'initialize_not_at_depth_1'
    assert u2.creation_check(None, t0_time=t0)[1] == 'no_transaction'


def _client(chain, tmp_path, stage, cap):
    return rpc.Client(chain, B.PilotBudget(tmp_path / ('l_%s.json' % stage), stage=stage, max_credits=cap),
                      tmp_path / 'calls.jsonl')


def test_u2_on_fixtures_excludes_the_special_pools(tmp_path):
    chain, spec = fixtures.build(n_pools=36)   # 6 special + 1 on another config -> 29 valid
    chain.slot = spec['t0_slot']
    doc = u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=spec['t0_time'])
    bad = {p['pool'] for p in spec['pools'] if p['kind'] not in ('valid', 'token2022')}
    assert doc['verdict'] == 'U2_OK' and len(doc['selected']) == 24
    assert not bad & {r['pool'] for r in doc['selected']}
    c = doc['counts']
    assert c['excluded_status'] == c['excluded_lp_zero'] == c['below_100_sol'] == 1
    assert 'excluded_token2022' not in c


def test_u2_stops(tmp_path):
    chain, spec = fixtures.build(gtfa_refused=True, n_pools=26)
    chain.slot = spec['t0_slot']
    with pytest.raises(u2.U2Stop):
        u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'a', t0_time=spec['t0_time'])
    chain, spec = fixtures.build(n_pools=18)
    chain.slot = spec['t0_slot']
    assert u2.run(_client(chain, tmp_path / 'b', 'u2', B.U2_CAP), tmp_path / 'b', t0_time=spec['t0_time'])['verdict'] \
        == 'INCONCLUSIF'


def test_collect_resumes_without_duplicates(tmp_path):
    chain, spec = fixtures.build(n_pools=8, specials=False)
    pool = spec['pools'][0]['pool']
    t0 = spec['t0_time']

    class Dies:
        def __init__(self, n):
            self.n = n

        def request(self, m, p):
            if self.n == 0:
                raise RuntimeError('cut')
            self.n -= 1
            return chain.request(m, p)
    with pytest.raises(RuntimeError):
        step1.collect(_client(Dies(2), tmp_path, 'step1', 1000), tmp_path / 'o', [pool], start_time=t0 - 7 * 86_400,
                      end_time=t0, phase='pre')
    st = step1.collect(_client(chain, tmp_path, 'step1', 1000), tmp_path / 'o', [pool], start_time=t0 - 7 * 86_400,
                       end_time=t0, phase='pre')[pool]
    txs = step1.transactions_of(tmp_path / 'o', 'pre', pool)
    expected = [t for t in chain.history[pool] if t0 - 7 * 86_400 <= t['blockTime'] < t0]
    assert st['done'] and len(txs) == len(expected) == st['transactions']


def test_anchor_check(tmp_path):
    (tmp_path / 'FICHE_GEL_RCP1.json').write_text('{}')
    (tmp_path / 'FICHE_GEL_B1.json').write_text('{}')
    good = {n: store.file_sha(tmp_path / ('FICHE_GEL_%s.json' % n)) for n in ('RCP1', 'B1')}
    step1.check_anchor(tmp_path, good)
    with pytest.raises(step1.Step1Stop):
        step1.check_anchor(tmp_path, dict(good, B1='0' * 64))


def test_archive_parts_reassemble(tmp_path):
    root = tmp_path / 'data'
    root.mkdir()
    for k in range(5):
        (root / ('f%d.bin' % k)).write_bytes(hashlib.sha256(b'%d' % k).digest() * 5000)
    doc = store.archive_parts(root, tmp_path / 'arc', part_bytes=50_000)
    whole = b''.join((tmp_path / 'arc' / p['name']).read_bytes() for p in doc['parts'])
    assert hashlib.sha256(whole).hexdigest() == doc['archive_sha256'] and all(p['bytes'] <= 50_000 for p in doc['parts'])
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(whole))) as tar:
        assert len(tar.getnames()) == 5
    doc2 = store.archive_parts(root, tmp_path / 'arc2', part_bytes=50_000)
    assert doc2['archive_sha256'] == doc['archive_sha256']


# -- 0.1.1: tests asked by R02 (K-1 survivors, K-2, K-3) ---------------------------------------------------------------
def test_charge_is_written_before_the_request_leaves(tmp_path):
    class Boom:
        def request(self, m, p):
            raise RuntimeError('network_down')
    c = _client(Boom(), tmp_path, 'u2', 100)
    with pytest.raises(RuntimeError):
        c.call('getSlot', [{}])
    assert json.loads((tmp_path / 'l_u2.json').read_text())['credits'] == 1 and c.budget.credits == 1


def test_permutation_seed_is_exactly_int_sha_l_first_8_hex():
    import random as R
    lst = [dict(pool='P%02d' % k) for k in range(40)]
    s = rpc.sha(lst)
    expected = [r['pool'] for r in lst]
    R.Random(int(s[:8], 16)).shuffle(expected)
    assert u2.permutation(lst, s) == expected


def _chain_with_reserve(tmp_path, lamports):
    chain, spec = fixtures.build(n_pools=26, specials=False)
    chain.slot = spec['t0_slot']
    target = spec['pools'][0]['pool']
    vault = L.vault_pda(target, L.WSOL)
    chain.accounts[vault] = dict(chain.accounts[vault], data=fixtures.token_account(L.WSOL, lamports))
    lst, counts, _, _ = u2.snapshot(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'o')
    return target in {r['pool'] for r in lst}, counts


def test_reserve_boundary_is_100_sol_inclusive(tmp_path):
    assert _chain_with_reserve(tmp_path / 'a', 100 * 10 ** 9)[0] is True
    kept, counts = _chain_with_reserve(tmp_path / 'b', 100 * 10 ** 9 - 1)
    assert kept is False and counts['below_100_sol'] == 1


def test_inconclusive_when_fewer_than_20_valid_after_exhausting_l(tmp_path):
    chain, spec = fixtures.build(n_pools=24, specials=False)     # 23 pools on the 0.25 % config -> |L| = 23 >= 20
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    for p in spec['pools'][:6]:                                # 6 created 3 days before T0 -> 17 valid
        first = chain.history[p['pool']][0]
        first['blockTime'] = t0 - 3 * 86_400
    doc = u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=t0)
    assert doc['verdict'] == 'INCONCLUSIF' and doc['tested'] == doc['counts']['list_l'] == 23


def test_token2022_pools_stay_in_l(tmp_path):
    chain, spec = fixtures.build(n_pools=26)
    chain.slot = spec['t0_slot']
    lst, counts, _, _ = u2.snapshot(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'o')
    t22 = next(p['pool'] for p in spec['pools'] if p['kind'] == 'token2022')
    assert t22 in {r['pool'] for r in lst}


def _window(tmp_path, n_pools=26):
    chain, spec = fixtures.build(n_pools=n_pools, window_days=1)
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    doc = u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=t0)
    sel = doc['selected']
    chain.slot = 10 ** 12
    step1.collect(_client(chain, tmp_path, 'step1', B.STEP1_HARD_STOP), tmp_path / 's', [r['pool'] for r in sel],
                  start_time=t0, end_time=t0 + 86_400, phase='window')
    return doc, sel, t0


def test_g1_uses_the_frozen_pilot_verdict_through_g1ind(tmp_path):
    from cpmmcost import model as CC
    from g1ind import report as G
    doc, sel, t0 = _window(tmp_path)
    sheets = dict(RCP1='a' * 64, B1='b' * 64)
    cut = t0 + 43_200
    stop = step1.g1(tmp_path / 's', sel, t0_slot=doc['t0_slot'], sheets=sheets, g0_passed=False, cut_time=cut)
    assert stop['RCP1']['g1']['decision'] == 'STOP' and stop['B1']['g1']['decision'] == 'STOP'
    assert stop['RCP1']['descriptive'] == G.NM and 'robustness' not in stop['RCP1']
    go = step1.g1(tmp_path / 's', sel, t0_slot=doc['t0_slot'], sheets=sheets, g0_passed=True, cut_time=cut)
    r = go['RCP1']
    assert r['schema'] == G.SCHEMA and r['g1']['decision'] in ('INCONCLUSIF', 'NO-GO', 'GO_PILOTE')
    assert r['g1']['seed'] == int('a' * 8, 16) and go['B1']['g1']['seed'] == int('b' * 8, 16)
    assert r['g1']['meaning'] == G.SHEET_MEANING and not hasattr(step1, 'SHEET_SENTENCE')
    assert r['robustness']['half_1_half_2']['cut_time'] == cut
    for key in step1.SENSITIVITIES:                      # all four supplied, none left NON MESURÉ
        assert isinstance(r['robustness'][key], dict) and r['robustness'][key]['positions'] == r['g1']['n']
    assert set(step1.SENSITIVITIES) == set(G.SUPPLIED)
    assert r['metrics_b31a3c47'] is not None and r['paired_gap']['status'].startswith('DESCRIPTIF')
    assert CC.pilot_verdict is not None


def test_freeze_sheet_holds_the_cut_time_in_the_middle_of_the_window(tmp_path):
    u2_doc = dict(t0_slot=5, t0_time=1_000_000, sha_l='c' * 64, selected=[dict(pool='P')])
    step1.freeze_sheets(tmp_path, u2_doc=u2_doc, count_doc=dict(r_hat=3.0), triggers=dict(rcp1=1, b1=2), d_days=7,
                        code_sha={})
    sheet = json.loads((tmp_path / 'FICHE_GEL_RCP1.json').read_text())
    assert sheet['cut_time'] == 1_000_000 + 7 * 86_400 // 2 and type(sheet['cut_time']) is int
    assert sheet['window'] == [1_000_000, 1_000_000 + 7 * 86_400]


def test_resume_does_not_refetch_finished_pages(tmp_path):
    chain, spec = fixtures.build(n_pools=4, specials=False)
    pool = spec['pools'][0]['pool']
    t0 = spec['t0_time']
    n = sum(1 for t in chain.history[pool] if t0 - 7 * 86_400 <= t['blockTime'] < t0)
    pages = -(-n // 100)
    assert pages >= 4

    class Dies:
        def __init__(self, k):
            self.k = k

        def request(self, m, p):
            if self.k == 0:
                raise RuntimeError('cut')
            self.k -= 1
            return chain.request(m, p)
    with pytest.raises(RuntimeError):
        step1.collect(_client(Dies(3), tmp_path, 'step1', 10_000), tmp_path / 'o', [pool],
                      start_time=t0 - 7 * 86_400, end_time=t0, phase='pre')
    before = chain.requests
    c = _client(chain, tmp_path, 'step1', 10_000)
    step1.collect(c, tmp_path / 'o', [pool], start_time=t0 - 7 * 86_400, end_time=t0, phase='pre')
    assert chain.requests - before == pages - 3                 # only the missing pages are fetched
    assert c.budget.credits == 10 * (pages + 1)                 # 3 done + 1 charged and cut + the rest


def test_count_24h_counts_exactly_the_24_hours_before_t0(tmp_path):
    chain, spec = fixtures.build(n_pools=3, specials=False)
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    pools = [p['pool'] for p in spec['pools']]
    doc = step1.count_24h(_client(chain, tmp_path, 'step1', 10_000), pools, t0_time=t0)
    for pool in pools:
        assert doc['per_pool'][pool] == sum(1 for t in chain.history[pool]
                                            if t0 - 86_400 <= t['blockTime'] < t0 and t['slot'] <= chain.slot)


# -- 0.1.2: K01 / K02 of R02 (f41c6cb0) -------------------------------------------------------------------------------
def test_zero_sale_conversion_k01():
    from cpmmcost import model as CC
    row = dict(pool='P', decision_index=3, unpriced='data_ends_before_exit', decision_time=1)
    z = step1.zero_sale(row)
    assert z['entered'] is True and z['received'] == 0 and z['unpriced_reason'] == 'data_ends_before_exit'
    assert z['net_lamports'] == -(CC.STAKE_LAMPORTS + 4 * CC.TX_FEE_LAMPORTS) == -100_420_000
    assert z['net_return'] == -1.0042


def test_closed_vocabulary_k02_and_parity_with_plbench():
    import ast
    import os
    src = None
    for d in os.environ.get('PYTHONPATH', '').split(':'):
        if d.endswith('plbench_pkg') and os.path.exists(os.path.join(d, 'plbench', 'bench.py')):
            with open(os.path.join(d, 'plbench', 'bench.py')) as handle:
                src = handle.read()
    if src is not None:
        node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], 'id', '') == 'FORBIDDEN_WORDS')
        assert tuple(ast.literal_eval(node.value)) == step1.FORBIDDEN_WORDS
    step1.assert_closed_vocabulary(dict(a='NO-GO'))
    with pytest.raises(step1.Step1Stop):
        step1.assert_closed_vocabulary(dict(meaning='it never means profitable'))


def test_g1_k01_every_series_is_converted_by_zero_sale_with_its_failures(tmp_path, monkeypatch):
    from cpmmcost import model as CC
    doc, sel, t0 = _window(tmp_path)
    real = CC.position
    calls = dict(n=0)

    def flaky_position(*a, **k):
        calls['n'] += 1
        if calls['n'] % 5 == 0:
            raise CC.CostError('synthetic_unpriced')
        return real(*a, **k)
    monkeypatch.setattr(CC, 'position', flaky_position)
    seen = {}
    real_verdict = CC.pilot_verdict

    def spy(positions, **k):
        seen.setdefault('n', []).append(len(positions))
        seen.setdefault('zero', []).append(sum(p.get('status') == 'unpriced_zero_sale' for p in positions))
        return real_verdict(positions, **k)
    monkeypatch.setattr(CC, 'pilot_verdict', spy)
    out = step1.g1(tmp_path / 's', sel, t0_slot=doc['t0_slot'], sheets=dict(RCP1='a' * 64, B1='b' * 64),
                   g0_passed=True, cut_time=t0 + 43_200)
    r = out['RCP1']
    for h in ('RCP1', 'B1'):                             # end to end: g1ind accepted every converted series
        assert out[h]['g1']['decision'] in ('STOP', 'INCONCLUSIF', 'NO-GO', 'GO_PILOTE')
    assert r['robustness']['half_1_half_2']['cut_time'] == t0 + 43_200
    assert r['robustness']['one_failure_per_tx']['zero_sale']['count'] > 0
    assert r['placebo']['zero_sale']['count'] > 0
    assert r['unpriced']['count'] > 0 and r['unpriced']['reasons'] == {'synthetic_unpriced': r['unpriced']['count']}
    inputs = json.loads((tmp_path / 's' / 'G1_INPUTS_RCP1.json').read_text())
    assert seen['n'][0] == r['g1']['n'] == len(inputs['primary']) and seen['zero'][0] == r['unpriced']['count']
    assert set(inputs) == {'primary', 'placebo', 'sensitivities'} and set(inputs['sensitivities']) == set(step1.SENSITIVITIES)
    series = dict(inputs['sensitivities'], primary=inputs['primary'], placebo=inputs['placebo'])
    assert any(p.get('status') == 'unpriced_zero_sale' for p in inputs['placebo'])
    for name, rows in series.items():
        assert all('net_return' in p for p in rows), name           # no raw unpriced row is ever written
        f = step1.SENSITIVITIES.get(name, {}).get('failures', CC.FROZEN_FAILURES)
        for p in rows:
            if p.get('status') == 'unpriced_zero_sale':
                assert p['net_lamports'] == step1.zero_sale_net_lamports(f), name
                assert p['failures'] == dict(buy=f.buy, sell=f.sell, cleanup=f.cleanup), name
                assert type(p['decision_slot']) is int and 'unpriced_reason' in p, name
    zs = [p for p in inputs['sensitivities']['one_failure_per_tx'] if p.get('status') == 'unpriced_zero_sale']
    assert zs and all(p['net_lamports'] == -100_735_000 for p in zs)
    zr = [p for p in inputs['sensitivities']['rent_lost_vs_closed_account'] if p.get('status') == 'unpriced_zero_sale']
    assert zr and all(p['net_lamports'] == -102_669_280 for p in zr)
    keys = sorted((p['pool'], p['decision_index']) for p in inputs['primary'])
    for name, rows in inputs['sensitivities'].items():
        assert sorted((p['pool'], p['decision_index']) for p in rows) == keys, name


def test_zero_sale_with_sensitivity_failures_and_no_placebo_difference():
    from cpmmcost import model as CC
    row = dict(pool='P', decision_index=1, unpriced='x', decision_time=1)
    assert step1.zero_sale(row, CC.Failures(1, 1, 1))['net_lamports'] == -100_735_000
    assert step1.zero_sale(row)['net_lamports'] == -100_420_000
    assert step1.zero_sale_net_lamports(CC.Failures(1, 1, 0)) == -100_630_000
    assert not hasattr(step1, 'paired_difference')


def test_zero_sale_is_the_frozen_composition_with_received_zero_erratum_r02():
    from closedacct import model as CA
    from cpmmcost import model as CC
    assert step1.zero_sale_net_lamports(CC.FROZEN_FAILURES) == step1.ZERO_SALE_NET_LAMPORTS == -100_420_000
    assert step1.zero_sale_net_lamports(CC.SENSITIVITY_FAILURES) == -100_735_000
    rent = CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS)
    assert step1.zero_sale_net_lamports(rent) == -102_669_280                 # 6 transactions + rent lost 2 039 280
    assert step1.zero_sale_net_lamports(CC.Failures(0, 0, 2)) == -100_630_000  # 2 failed cleanups, closed: no rent
    row = dict(pool='P', decision_index=1, unpriced='x', decision_time=1, decision_slot=5)
    z = step1.zero_sale(row, rent)
    assert z['net_lamports'] == -102_669_280 and z['net_return'] == -102_669_280 / CC.STAKE_LAMPORTS
    # the closed-account module of the frozen chain gives the same value for a sale that received nothing
    for f in (CC.FROZEN_FAILURES, CC.SENSITIVITY_FAILURES, rent):
        outcome = dict(migrated=False, value=0, tokens=1, cost=CC.STAKE_LAMPORTS + (2 + f.buy + f.sell + 1) * CC.TX_FEE_LAMPORTS)
        assert abs(CA.net_return_closed(outcome, failed_attempts=f.cleanup) - step1.zero_sale_net_lamports(f) / CC.STAKE_LAMPORTS) < 1e-12
