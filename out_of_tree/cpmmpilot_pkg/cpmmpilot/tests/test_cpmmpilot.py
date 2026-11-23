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
    with pytest.raises(rpc.RpcError):
        rpc.LiveRpc('https://example.invalid')


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


def test_g1_uses_the_frozen_pilot_verdict(tmp_path):
    from cpmmcost import model as CC
    chain, spec = fixtures.build(n_pools=26, window_days=1)
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    doc = u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=t0)
    sel = doc['selected']
    chain.slot = 10 ** 12
    step1.collect(_client(chain, tmp_path, 'step1', B.STEP1_HARD_STOP), tmp_path / 's', [r['pool'] for r in sel],
                  start_time=t0, end_time=t0 + 86_400, phase='window')
    sheets = dict(RCP1='a' * 64, B1='b' * 64)
    stop = step1.g1(tmp_path / 's', sel, t0_slot=doc['t0_slot'], sheets=sheets, g0_passed=False)
    assert stop['RCP1']['verdict']['decision'] == 'STOP' and stop['B1']['verdict']['decision'] == 'STOP'
    go = step1.g1(tmp_path / 's', sel, t0_slot=doc['t0_slot'], sheets=sheets, g0_passed=True)
    assert go['RCP1']['verdict']['decision'] in ('INCONCLUSIF', 'NO-GO', 'GO_PILOTE')
    assert go['RCP1']['verdict']['seed'] == int('a' * 8, 16)
    assert set(go['RCP1']['verdict']) >= {'n_entered', 'pools_entered', 'upper_bound_95_one_sided'}
    assert CC.pilot_verdict is not None


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


def test_g1_k01_counts_unpriced_and_k02_removes_meaning(tmp_path, monkeypatch):
    from cpmmcost import model as CC
    chain, spec = fixtures.build(n_pools=26, window_days=1)
    chain.slot = spec['t0_slot']
    t0 = spec['t0_time']
    doc = u2.run(_client(chain, tmp_path, 'u2', B.U2_CAP), tmp_path / 'u2', t0_time=t0)
    sel = doc['selected']
    chain.slot = 10 ** 12
    step1.collect(_client(chain, tmp_path, 'step1', B.STEP1_HARD_STOP), tmp_path / 's', [r['pool'] for r in sel],
                  start_time=t0, end_time=t0 + 86_400, phase='window')
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
    out = step1.g1(tmp_path / 's', sel, t0_slot=doc['t0_slot'], sheets=dict(RCP1='a' * 64, B1='b' * 64), g0_passed=True)
    r = out['RCP1']
    assert r['unpriced_counted_at_zero_sale'] > 0 and r['unpriced_reasons'] == {'synthetic_unpriced': r['unpriced_counted_at_zero_sale']}
    assert seen['n'][0] == r['positions'] and seen['zero'][0] == r['unpriced_counted_at_zero_sale']
    assert 'meaning' not in r['verdict'] and r['verdict']['sheet_sentence'].startswith('GO_PILOTE autorise seulement')
