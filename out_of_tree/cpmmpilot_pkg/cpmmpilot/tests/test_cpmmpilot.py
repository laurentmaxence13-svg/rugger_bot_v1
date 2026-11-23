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
    bad = {p['pool'] for p in spec['pools'] if p['kind'] != 'valid'}
    assert doc['verdict'] == 'U2_OK' and len(doc['selected']) == 24
    assert not bad & {r['pool'] for r in doc['selected']}
    c = doc['counts']
    assert c['excluded_status'] == c['excluded_lp_zero'] == c['excluded_token2022'] == c['below_100_sol'] == 1


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
