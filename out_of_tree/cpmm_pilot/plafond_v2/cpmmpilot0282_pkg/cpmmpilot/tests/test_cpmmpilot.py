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


def test_live_rpc_release_authorizes_only_the_owner_text_b_c_and_unanchored_text_is_refused(tmp_path):
    from pathlib import Path
    owner = Path(__file__).resolve().parents[2] / 'AUTORISATION_B_C_v1_3.txt'
    raw = owner.read_bytes()
    assert len(raw) == 2175 and not raw.endswith(b'\n')                    # R02: exact bytes, no final newline
    t2 = (Path(__file__).resolve().parents[2] / 'AUTORISATION_T1_T2.txt').read_bytes()
    assert len(t2) == 1183 and not t2.endswith(b'\n') and 'J\'autorise T2' in t2.decode('utf-8')
    t2b = (Path(__file__).resolve().parents[2] / 'AUTORISATION_T2_BIS.txt').read_bytes()
    assert len(t2b) == 533 and not t2b.endswith(b'\n') and 'relue une seule fois' in t2b.decode('utf-8')
    g23 = (Path(__file__).resolve().parents[2] / 'AUTORISATION_G23.txt').read_bytes()     # 0.2.8.1 (R02 a5e8f770)
    assert len(g23) == 1257 and not g23.endswith(b'\n') and 'au plus 33 000 crédits' in g23.decode('utf-8')
    extra = {rpc.ADDENDUM_TEXT_SHA256} if rpc.ADDENDUM_TEXT_SHA256 else set()        # 0.2.8.2: the addendum, once inscribed
    assert rpc.AUTHORIZED_TEXT_SHA256 == frozenset({hashlib.sha256(x).hexdigest() for x in (raw, t2, t2b, g23)} | extra)
    assert rpc.AUTHORIZED_TEXT_SHA256 - extra == frozenset(
        {'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1',
         'b75e657a60a0de335906e091936c93ba707b639a3b9ca5fc56c7623142a063f9',
         'cae25a3c1f07c3daafef18131d6ace13c8604b6d847f00fbaed69fe451c0967d',
         '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b'})
    text = raw.decode('utf-8')
    for clause in ('au plus 5 000 crédits', 'au plus 50 000 crédits', 'arrêt dur à 49 000 crédits',
                   'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C', 'hachée et ancrée par R02 ; puis'):
        assert clause in text, clause
    live = rpc.LiveRpc(ENDPOINT, authorization_file=owner, opener=_Opener({}))
    assert live.authorization_sha256 == hashlib.sha256(raw).hexdigest()
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


# -- 0.2.1: U-2 in TWO times (owner text B + R02 07:01Z): L hashed and anchored by R02, THEN the permutation ----------
def test_u2_first_time_sends_no_gtfa_and_stops_with_list_l(tmp_path):
    chain, spec = fixtures.build(n_pools=26)
    chain.slot = spec['t0_slot']
    seen = []

    class Spy:
        def request(self, m, p):
            seen.append(m)
            return chain.request(m, p)
    first = u2.run_list(_client(Spy(), tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=spec['t0_time'])
    assert first['verdict'] == 'LIST_L_AWAITS_R02_ANCHOR'
    assert set(seen) <= {'getSlot', 'getProgramAccounts', 'getMultipleAccounts'} and 'getSlot' in seen
    assert not (tmp_path / 'u2' / 'U2.json').exists()
    doc = json.loads((tmp_path / 'u2' / 'LIST_L.json').read_text())
    assert doc['sha256'] == first['sha_l'] == rpc.sha(doc['list'])
    assert first['list_l_file_sha256'] == hashlib.sha256((tmp_path / 'u2' / 'LIST_L.json').read_bytes()).hexdigest()


def test_u2_second_time_needs_the_anchored_sha_and_equals_the_one_shot_run(tmp_path):
    chain, spec = fixtures.build(n_pools=26)
    chain.slot = spec['t0_slot']
    first = u2.run_list(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'a', t0_time=spec['t0_time'])
    before = chain.requests
    with pytest.raises(u2.U2Stop, match='list_l_not_anchored'):
        u2.run_qualify(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'a', anchored_sha_l='0' * 64)
    assert chain.requests == before                                       # refused BEFORE any call
    path = tmp_path / 'a' / 'LIST_L.json'
    doc = json.loads(path.read_text())
    doc['list'] = doc['list'][1:]                                         # an edited L, even with its sha anchored
    path.write_text(json.dumps(doc))
    with pytest.raises(u2.U2Stop, match='list_l_not_anchored'):
        u2.run_qualify(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'a', anchored_sha_l=first['sha_l'])
    assert chain.requests == before
    (tmp_path / 'b').mkdir()
    (tmp_path / 'c').mkdir()
    second = u2.run_list(_client(chain, tmp_path / 'b', 'u2', B.U2_CAP), tmp_path / 'b', t0_time=spec['t0_time'])
    two = u2.run_qualify(_client(chain, tmp_path / 'b', 'u2', B.U2_CAP), tmp_path / 'b', anchored_sha_l=second['sha_l'])
    chain2, spec2 = fixtures.build(n_pools=26)
    chain2.slot = spec2['t0_slot']
    one = u2.run(_client(chain2, tmp_path / 'c', 'u2', B.U2_CAP), tmp_path / 'c', t0_time=spec2['t0_time'])
    assert two['verdict'] == one['verdict'] == 'U2_OK' and two['selected'] == one['selected']
    assert two['anchored_sha_l'] == second['sha_l'] == one['sha_l']
    ledger = json.loads((tmp_path / 'b' / 'l_u2.json').read_text())        # both times on ONE ledger, resumed
    assert ledger['credits'] == two['budget']['credits'] > second['budget']['credits']


# -- 0.2.2: spacing of the live transport (R02 note 41c20a16), simulated clock -----------------------------------------
class _Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def test_live_rpc_spaces_every_send_by_at_least_0_2_s(tmp_path, monkeypatch):
    f = _authorized(tmp_path, monkeypatch)
    clock = _Clock()
    sent = []

    def answer(b):
        sent.append(clock.now)
        return dict(jsonrpc='2.0', id=b['id'], result=1)
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=_Opener(answer), clock=clock, sleep=clock.sleep)
    assert rpc.MIN_INTERVAL_S == 0.2
    live.request('getSlot', [])                                          # first send: no wait
    assert clock.slept == []
    for _ in range(5):                                                   # back-to-back calls are spaced
        live.request('getMultipleAccounts', [[], {}])
    clock.now += 1.0                                                     # a slow caller is not slowed further
    live.request('getSlot', [])
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    assert all(g >= 0.2 - 1e-9 for g in gaps) and len(sent) == 7
    assert len(clock.slept) == 5 and all(abs(s - 0.2) < 1e-9 for s in clock.slept)
    assert gaps[-1] >= 1.0


def test_live_rpc_429_is_a_stop_without_retry_even_with_spacing(tmp_path, monkeypatch):
    import urllib.error
    f = _authorized(tmp_path, monkeypatch)
    clock = _Clock()
    op = _Opener(urllib.error.HTTPError(ENDPOINT, 429, 'Too Many', {}, None))
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=op, clock=clock, sleep=clock.sleep)
    client = _client(live, tmp_path, 'u2', B.U2_CAP)
    with pytest.raises(rpc.RpcError, match='rate_limited_429'):
        client.call('getMultipleAccounts', [[], {}])
    assert len(op.seen) == 1 and client.budget.credits == 1             # charged once, sent once, never resent
    chain, spec = fixtures.build(n_pools=24)
    chain.slot = spec['t0_slot']
    n = dict(k=0)

    def answer(b):
        n['k'] += 1
        if b['method'] == 'getMultipleAccounts':
            raise urllib.error.HTTPError(ENDPOINT, 429, 'Too Many', {}, None)
        return dict(jsonrpc='2.0', id=b['id'], result=json.loads(json.dumps(chain.request(b['method'], b['params']))))
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=_Opener(answer), clock=clock, sleep=clock.sleep)
    (tmp_path / 'x').mkdir()
    with pytest.raises(rpc.RpcError, match='rate_limited_429'):
        u2.run_list(_client(live, tmp_path / 'x', 'u2', B.U2_CAP), tmp_path / 'x' / 'u2', t0_time=spec['t0_time'])
    assert not (tmp_path / 'x' / 'u2' / 'LIST_L.json').exists()


# -- 0.2.3: the D rule of R02 (note e294655a) and the count that never writes a signature ---------------------------
def _count(t):
    return dict(triggers=t, days=7, outcomes_computed=False)


def test_d_rule_of_r02():
    r = step1.d_rule(_count(70), 30.5)                 # D_155 = 16 (floor(70 x 16 / 7) = 160 >= 155; 15 -> 150)
    assert (r['d_155'], r['d_days'], r['expected_entries']) == (16, 16, 160)
    assert r['power_stop'] == 'POWERED'
    assert step1.d_rule(_count(70), 12.9)['d_days'] == 12                 # floor(D_max)
    assert step1.d_rule(_count(1000), 30)['d_days'] == 7                  # at least 7 days
    assert step1.d_rule(_count(5), 100)['d_days'] == 60                   # capped at 60
    z = step1.d_rule(_count(0), 20.2)
    assert z['d_155'] == 'inf' and z['d_days'] == 20 and z['expected_entries'] == 0
    assert z['power_stop'] == 'UNDERPOWERED_DECLARED_OWNER_DECIDES'
    low = step1.d_rule(_count(20), 40)                 # 20 x 40 / 7 = 114 -> below 155, still >= 30
    assert low['d_days'] == 40 and low['power_stop'] == 'BELOW_POWER_TARGET_PUBLISHED_AS_SUCH'
    for t in (1, 3, 22, 31, 155, 156, 1085):
        d = step1.d_rule(_count(t), 1000)['d_155']
        assert (t * d) // 7 >= 155 and (d == 1 or (t * (d - 1)) // 7 < 155)
    with pytest.raises(step1.Step1Stop, match='d_below_one_day'):
        step1.d_rule(_count(70), 0.9)


def test_freeze_sheets_carry_the_d_rule(tmp_path):
    u2_doc = dict(t0_slot=5, t0_time=1_000_000, sha_l='c' * 64, selected=[dict(pool='P')])
    rule = step1.d_rule(_count(70), 30.5)
    step1.freeze_sheets(tmp_path, u2_doc=u2_doc, count_doc=dict(r_hat=3.0), triggers=dict(rcp1=_count(70), b1=_count(9)),
                        d_days=rule['d_days'], code_sha={}, d_rule=rule)
    for name in ('RCP1', 'B1'):
        sheet = json.loads((tmp_path / ('FICHE_GEL_%s.json' % name)).read_text())
        assert sheet['d_rule'] == rule and sheet['d_days'] == 16
        assert sheet['cut_time'] == 1_000_000 + 16 * 86_400 // 2
    with pytest.raises(step1.Step1Stop, match='d_rule_differs'):
        step1.freeze_sheets(tmp_path / 'x', u2_doc=u2_doc, count_doc=dict(r_hat=3.0),
                            triggers=dict(rcp1=_count(70), b1=_count(9)), d_days=15, code_sha={}, d_rule=rule)


def test_count_24h_ignores_and_never_writes_signatures_after_t0(tmp_path):
    chain, spec = fixtures.build(n_pools=3, specials=False)
    t0 = spec['t0_time']
    chain.slot = 10 ** 12                              # the chain goes on after T0 (paginated, then ignored)
    pools = [p['pool'] for p in spec['pools']]
    after = [t for p in pools for t in chain.history[p] if t['blockTime'] >= t0]
    assert after
    doc = step1.count_24h(_client(chain, tmp_path, 'step1', 10_000), pools, t0_time=t0)
    for pool in pools:
        assert doc['per_pool'][pool] == sum(1 for t in chain.history[pool] if t0 - 86_400 <= t['blockTime'] < t0)
    text = json.dumps(doc)
    assert not any(t['transaction']['signatures'][0] in text for p in pools for t in chain.history[p])
    assert set(doc) == {'per_pool', 'r_hat', 'statistic', 'point2', 'd_max_days'}


# -- 0.2.5: v1 transactions (R02 erratum f2e62c72) -------------------------------------------------------------------
def test_every_full_data_call_asks_for_version_1(tmp_path):
    import inspect
    from cpmmpilot import step0
    assert rpc.MAX_TX_VERSION == 1
    for mod in (step0, u2, step1):
        src = inspect.getsource(mod)
        assert 'maxSupportedTransactionVersion=MAX_TX_VERSION' in src and 'maxSupportedTransactionVersion=0' not in src
    chain, spec = fixtures.build(n_pools=3, specials=False)
    chain.slot = 10 ** 12
    t0 = spec['t0_time']
    sent = []

    class Spy:
        def request(self, m, p):
            sent.append(p[-1])
            return chain.request(m, p)
    step1.collect(_client(Spy(), tmp_path, 'step1', 10_000), tmp_path / 'o', [spec['pools'][0]['pool']],
                  start_time=t0 - 7 * 86_400, end_time=t0, phase='pre')
    assert sent and all(o['maxSupportedTransactionVersion'] == 1 for o in sent)


def test_a_v1_transaction_goes_through_collect_timeline_and_trigger_count(tmp_path):
    from cpmmprereg import rule as R
    results = []
    for version in (0, 1):
        chain, spec = fixtures.build(n_pools=26, window_days=1)
        if version == 1:                                      # same chain, every transaction turned into a v1 one
            for txs in chain.history.values():
                for t in txs:
                    t['version'] = 1
                    t['transaction']['message'] = dict(t['transaction'].get('message') or {},
                                                       transactionConfig=dict(computeUnitPrice=5000, computeUnitLimit=200000))
        chain.slot = spec['t0_slot']
        t0 = spec['t0_time']
        d = tmp_path / ('v%d' % version)
        doc = u2.run(_client(chain, d, 'u2', B.U2_CAP), d / 'u2', t0_time=t0)
        sel = doc['selected']
        chain.slot = 10 ** 12
        step1.collect(_client(chain, d, 'step1', B.STEP1_HARD_STOP), d / 's', [r['pool'] for r in sel],
                      start_time=t0 - 7 * 86_400, end_time=t0, phase='pre')
        lines = step1.timelines(d / 's', 'pre', sel)
        trig = step1.trigger_counts(d / 's', sel, t0_time=t0, t0_slot=doc['t0_slot'])
        results.append((doc['selected'], [len(l.swaps) for l in lines], sum(len(l.skipped) for l in lines),
                        trig['rcp1']['triggers'], trig['b1']['triggers']))
    assert results[1] == results[0]                           # v1 is neither dropped nor decoded differently
    assert sum(results[1][1]) > 0 and results[1][2] == results[0][2]


def test_tx_version_error_is_not_a_method_refusal_and_its_text_is_redacted(tmp_path, monkeypatch):
    f = _authorized(tmp_path, monkeypatch)
    msg = ('Transaction version (1) is not supported by the requesting client. Please try the request again with '
           'the following configuration parameter: "maxSupportedTransactionVersion": 1')
    live = rpc.LiveRpc(ENDPOINT, authorization_file=f,
                       opener=_Opener(dict(jsonrpc='2.0', id=1, error=dict(code=-32015, message=msg))))
    with pytest.raises(rpc.RpcError) as info:
        live.request('getTransactionsForAddress', ['P', dict(limit=1)])
    assert not isinstance(info.value, rpc.MethodRefused)
    assert str(info.value) == 'tx_version_unsupported:-32015:61294f25e789'
    assert info.value.error_text.startswith('transaction version (1) is not supported by the requesting client.')
    assert '[masque]' in info.value.error_text                             # "maxsupportedtransactionversion": is > 32


def test_redaction_masks_urls_keys_and_long_segments():
    secretish = 'a' * 40
    t = rpc.redact_error_text('Quota for https://x.example/v1 exceeded, api-key=' + secretish + ' token ' + secretish
                              + ' see KeyVault and RapidAPI ' + 'word ' * 80)
    assert 'http' not in t and 'api' not in t and 'key' not in t and secretish not in t
    assert t.startswith('quota for [masque] exceeded, [masque] token [masque] see [masque] and [masque] word')
    assert len(t) <= 200
    assert rpc.redact_error_text('Method not found') == 'method not found'
    live_refusal = rpc.redact_error_text('requires a paid plan')
    assert live_refusal == 'requires a paid plan'


def _pre_collected(tmp_path, n_pools=26, mutate=None):
    chain, spec = fixtures.build(n_pools=n_pools, window_days=1)
    if mutate:
        for txs in chain.history.values():
            for t in txs:
                mutate(t)
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    doc = u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=t0)
    sel = doc['selected']
    chain.slot = 10 ** 12
    step1.collect(_client(chain, tmp_path, 'step1', B.STEP1_HARD_STOP), tmp_path / 's', [r['pool'] for r in sel],
                  start_time=t0 - 7 * 86_400, end_time=t0, phase='pre')
    return sel


def test_format_guard_counts_versions_and_skipped(tmp_path):
    def mixed(t):
        h = int(t['transaction']['signatures'][0][:2], 16) % 3
        t['version'] = ('legacy', 0, 1)[h]
    sel = _pre_collected(tmp_path, mutate=mixed)
    fc = step1.require_tx_format(tmp_path / 's', 'pre', sel)
    by = fc['transactions_by_version']
    assert set(by) == {'legacy', '0', '1'} and all(n > 0 for n in by.values())
    lines = step1.timelines(tmp_path / 's', 'pre', sel)
    assert sum(fc['skipped_by_version_and_reason'].values()) == sum(len(l.skipped) for l in lines)
    assert all(k.split('|')[0] in ('legacy', '0', '1') for k in fc['skipped_by_version_and_reason'])


@pytest.mark.parametrize('field', ['signatures', 'slot', 'transactionIndex', 'blockTime', 'meta'])
def test_format_guard_stops_on_any_missing_field(tmp_path, field):
    sel = _pre_collected(tmp_path)
    pool = sel[0]['pool']
    page = sorted((tmp_path / 's' / 'collect' / 'pre' / pool).glob('page_*.json.gz'))[0]
    doc = step1.read_gz_page(page)
    tx = doc['data'][0]
    if field == 'signatures':
        tx['transaction']['signatures'] = []
    elif field == 'meta':
        tx['meta'] = dict(err=None)                          # neither logMessages nor a non-null err
    else:
        tx.pop(field)
    page.unlink()
    step1.write_gz_page(page, doc)
    with pytest.raises(step1.TxFormatStop, match='STOP_TX_FORMAT'):
        step1.require_tx_format(tmp_path / 's', 'pre', sel)


def test_format_guard_accepts_a_failed_tx_without_logs(tmp_path):
    sel = _pre_collected(tmp_path)
    pool = sel[0]['pool']
    page = sorted((tmp_path / 's' / 'collect' / 'pre' / pool).glob('page_*.json.gz'))[0]
    doc = step1.read_gz_page(page)
    doc['data'][0]['meta'] = dict(err={'InstructionError': [0, 'Custom']}, logMessages=None)
    page.unlink()
    step1.write_gz_page(page, doc)
    assert step1.require_tx_format(tmp_path / 's', 'pre', sel)['transactions_by_version']


# -- 0.2.6: T2 (owner 24/11 18:00:36Z) ----------------------------------------------------------------------------------
def test_t2_ledger_stage_and_cap(tmp_path):
    assert B.T2_CAP == 1_470
    b = B.PilotBudget(tmp_path / 'l.json', stage='t2', max_credits=B.T2_CAP)
    b.credits = B.T2_CAP - 1
    b.charge('getSignaturesForAddress', ['P', dict(limit=1000)])
    with pytest.raises(B.BudgetExhausted):
        b.charge('getSignaturesForAddress', ['P', dict(limit=1000)])


# -- 0.2.7: truncated HTTP responses and per-pool checkpoints (R02 822d5edf) --------------------------------------------
def test_incomplete_read_is_a_truncated_response(tmp_path, monkeypatch):
    import http.client
    f = _authorized(tmp_path, monkeypatch)
    for exc in (http.client.IncompleteRead(b'x' * 10, 99), http.client.RemoteDisconnected('closed'),
                http.client.BadStatusLine('x')):
        op = _Opener(exc)
        live = rpc.LiveRpc(ENDPOINT, authorization_file=f, opener=op)
        with pytest.raises(rpc.RpcError) as info:
            live.request('getSignaturesForAddress', ['P', dict(limit=1000)])
        assert str(info.value) == 'response_truncated'
        assert 'bytes read' not in str(info.value) and info.value.__cause__ is None


def test_count_24h_checkpoints_after_each_pool_and_keeps_them_on_a_stop(tmp_path):
    chain, spec = fixtures.build(n_pools=4, specials=False)
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    pools = [p['pool'] for p in spec['pools']]
    ck = tmp_path / 'PARTIAL.json'
    full = step1.count_24h(_client(chain, tmp_path / 'a', 'step1', 10_000), pools, t0_time=t0, checkpoint=ck)
    part = json.loads(ck.read_text())
    assert part['per_pool'] == full['per_pool'] and part['pools_done'] == part['pools_total'] == 4
    seen = []

    class DiesOnThird:
        def request(self, m, p):
            if p[0] == pools[2]:
                raise rpc.RpcError('response_truncated')
            seen.append(p[0])
            return chain.request(m, p)
    ck2 = tmp_path / 'PARTIAL2.json'
    (tmp_path / 'b').mkdir()
    with pytest.raises(rpc.RpcError, match='response_truncated'):
        step1.count_24h(_client(DiesOnThird(), tmp_path / 'b', 'step1', 10_000), pools, t0_time=t0, checkpoint=ck2)
    part2 = json.loads(ck2.read_text())
    assert part2['pools_done'] == 2 and part2['per_pool'] == {p: full['per_pool'][p] for p in pools[:2]}
    text = ck.read_text() + ck2.read_text()
    assert not any(t['transaction']['signatures'][0] in text for p in pools for t in chain.history[p])


def test_g23_stage_and_cap_0_2_8_2(tmp_path):
    assert B.G23_CAP == 88_200 == 90_000 * 98 // 100                           # 0.2.8.2: cap v2 (R02 plan e886578c)
    b = B.PilotBudget(tmp_path / 'h.json', stage='g23', max_credits=B.G23_CAP)
    b.credits = 88_191                                                          # 88 191 + 10 > 88 200: refused BEFORE the call
    with pytest.raises(B.BudgetExhausted, match='credit_cap_reached:88200'):
        b.charge('getTransactionsForAddress', [None, dict(limit=100)])
    assert b.credits == 88_191 and b.requests == 0
    b = B.PilotBudget(tmp_path / 'g.json', stage='g23', max_credits=B.G23_CAP)
    b.credits = B.G23_CAP - B.COSTS['getTransactionsForAddress']
    b.charge('getTransactionsForAddress', [None, dict(limit=100)])
    assert b.credits == B.G23_CAP
    with pytest.raises(B.BudgetExhausted):
        b.charge('getTransactionsForAddress', [None, dict(limit=100)])
    with pytest.raises(B.BudgetError, match='ledger_of_another_stage'):
        B.PilotBudget(tmp_path / 'g.json', stage='step1', max_credits=B.G23_CAP)


def test_the_addendum_is_inscribed():
    """0.2.8.2: FAILS ON PURPOSE while the owner's addendum is not signed and verified by R02 (PENDING)."""
    from pathlib import Path
    f = Path(__file__).resolve().parents[2] / 'AUTORISATION_G23_ADDENDUM.txt'
    assert rpc.ADDENDUM_TEXT_SHA256 is not None and f.exists()
    raw = f.read_bytes()
    assert not raw.endswith(b'\n') and hashlib.sha256(raw).hexdigest() == rpc.ADDENDUM_TEXT_SHA256
    assert rpc.ADDENDUM_TEXT_SHA256 in rpc.AUTHORIZED_TEXT_SHA256
    assert rpc.ADDENDUM_TEXT_SHA256 != '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b'
