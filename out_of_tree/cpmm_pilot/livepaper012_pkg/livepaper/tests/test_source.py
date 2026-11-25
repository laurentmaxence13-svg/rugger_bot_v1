"""livepaper 0.1 source, budget, runner, transport and commands, offline (cpmmpilot.rpc.FakeChain or fakes)."""
import json
import sys
from pathlib import Path

import pytest

from cpmmpilot import budget as B, rpc as RPC
from livepaper import cli as C, engine as E, journal as J, source as S
from livepaper.tests.test_livepaper import CFG, NAMES, SEED, START, feed, pools

HOUR = 3_600
SIGNED_TEXT_SHA256 = '1366025b6290c0a748c2190eebc5e3ee078a25868ef005591710b23658ebface'   # owner, event a60ed568
TEXT = Path(__file__).parent / 'data' / 'AUTORISATION_LIVEPAPER.txt'


def chain(txs, slot):
    hist = {p: list(d.values()) for p, d in txs.items()}
    return RPC.FakeChain({}, hist, slot=slot, block_time=slot // 2)


def client(tmp_path, transport, spent=0):
    if spent:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / 'ledger.json').write_text(json.dumps(dict(ceiling=S.CEILING, costs=dict(sorted(B.COSTS.items())),
                                                              requests=1, credits=spent, by_method={'getSlot': spent})))
    return RPC.Client(transport, S.Budget(tmp_path / 'ledger.json'), tmp_path / 'calls.jsonl')


def same_slot(txs, pool, n=3):
    """Put n consecutive live transactions of `pool` in one slot, indices 0 .. n-1, keeping their order."""
    rows = sorted([r for r in txs[pool].values() if r['blockTime'] >= START],
                  key=lambda r: (r['slot'], r['transactionIndex']))
    base = rows[10]['slot']
    for k, r in enumerate(rows[10:10 + n]):
        r['slot'], r['transactionIndex'] = base, k
    return [r['transaction']['signatures'][0] for r in rows[10:10 + n]]


def test_both_modes_return_each_new_transaction_once_with_its_order_in_the_slot(tmp_path):
    txs = feed(START + HOUR)
    sigs = same_slot(txs, NAMES[0])
    for mode in S.MODES:
        fake = chain(txs, slot=2 * (START + 1_800))
        src = S.Source(client(tmp_path / mode, fake), NAMES[:3], mode=mode, start=START)
        got1, slot1 = src.fetch()
        fake.slot = 2 * (START + HOUR)
        got2, slot2 = src.fetch()
        assert (slot1, slot2) == (2 * (START + 1_800), 2 * (START + HOUR))
        for p in NAMES[:3]:
            seen = [r['transaction']['signatures'][0] for r in got1[p] + got2[p]]
            want = [r['transaction']['signatures'][0] for r in sorted(txs[p].values(),
                    key=lambda r: (r['slot'], r['transactionIndex'])) if r['blockTime'] >= START]
            assert sorted(seen) == sorted(want) and len(seen) == len(set(seen))
            assert all(r['slot'] <= slot1 for r in got1[p])
        ranked = {r['transaction']['signatures'][0]: r for r in got1[NAMES[0]] + got2[NAMES[0]]}
        assert [ranked[s]['transactionIndex'] for s in sigs] == [0, 1, 2]
        if mode == 'gsfa_rank':
            assert all(r['livepaper_index_source'] == 'gsfa_rank' for r in ranked.values())
        else:
            assert all('livepaper_index_source' not in r for r in ranked.values())
    gs = json.loads((tmp_path / 'gsfa_rank' / 'ledger.json').read_text())['by_method']
    gt = json.loads((tmp_path / 'gtfa' / 'ledger.json').read_text())['by_method']
    assert set(gs) == {'getSlot', 'getSignaturesForAddress', 'getTransaction'} and gs['getSlot'] == 2
    assert set(gt) == {'getSlot', 'getSignaturesForAddress', 'getTransactionsForAddress'}
    assert gt['getTransactionsForAddress'] % 10 == 0 and gt['getSignaturesForAddress'] == 3      # 2nd poll, 3 pools


class Quiet:
    """getSignaturesForAddress honours `until` (FakeChain does not): an empty probe when nothing is new."""
    def __init__(self, inner):
        self.inner = inner

    def request(self, method, params):
        if method == 'getSignaturesForAddress' and params[1].get('until'):
            out = self.inner.request(method, [params[0], dict(params[1], until=None)])
            sigs = [x['signature'] for x in out]
            return out[:sigs.index(params[1]['until'])] if params[1]['until'] in sigs else out
        return self.inner.request(method, params)


def test_gtfa_pages_are_bought_only_when_the_probe_sees_something_new(tmp_path):
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + 1_800))
    src = S.Source(client(tmp_path, Quiet(fake)), NAMES[:3], mode='gtfa', start=START)
    src.fetch()
    before = json.loads((tmp_path / 'ledger.json').read_text())['by_method']
    got, _ = src.fetch()                                     # nothing new: probes only
    after = json.loads((tmp_path / 'ledger.json').read_text())['by_method']
    assert all(v == [] for v in got.values())
    assert after['getTransactionsForAddress'] == before['getTransactionsForAddress']
    assert after['getSignaturesForAddress'] == before.get('getSignaturesForAddress', 0) + 3
    fake.slot = 2 * (START + HOUR)
    got, _ = src.fetch()
    assert all(got[p] for p in NAMES[:3])
    assert json.loads((tmp_path / 'ledger.json').read_text())['by_method']['getTransactionsForAddress'] > \
        after['getTransactionsForAddress']


def test_the_source_state_is_restored_from_the_journal(tmp_path):
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + 1_800))
    src = S.Source(client(tmp_path, fake), NAMES[:3], mode='gsfa_rank', start=START)
    batch, slot = src.fetch()
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    eng.step(receipt_slot=slot, receipt_time=START + 1_800, batch=batch, wall=1.0, mono_ns=1)
    again = S.Source(client(tmp_path / 'b', fake), NAMES[:3], mode='gsfa_rank', start=START)
    again.restore(eng.journal.records)
    assert again.last_sig == src.last_sig and again.rank == src.rank and again.seen == src.seen
    fake.slot = 2 * (START + HOUR)
    a, _ = src.fetch()
    b, _ = again.fetch()
    assert a == b


def test_one_ledger_25000_with_a_hard_stop_at_24500(tmp_path):
    assert (S.CEILING, S.HARD_STOP) == (25_000, 24_500)
    with pytest.raises(B.BudgetError, match='owner_text'):
        S.Budget(tmp_path / 'x.json', 30_000)
    c = client(tmp_path, None, spent=24_490)
    bud = c.budget
    for _ in range(10):
        bud.charge('getSlot')
    assert bud.credits == 24_500
    with pytest.raises(B.BudgetExhausted, match='24500'):
        bud.charge('getSlot')
    with pytest.raises(B.BudgetExhausted):
        bud.charge('getTransactionsForAddress', ['p', dict(limit=100)])
    assert json.loads((tmp_path / 'ledger.json').read_text())['credits'] == 24_500
    with pytest.raises(B.BudgetError, match='not_in_livepaper'):
        bud.charge('getProgramAccounts')
    with pytest.raises(B.BudgetError, match='gtfa_limit'):
        bud.charge('getTransactionsForAddress', ['p', dict(limit=1_000)])
    assert S.Budget(tmp_path / 'ledger.json').credits == 24_500                       # never goes back


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def wall(self):
        return self.t

    def mono_ns(self):
        return int(self.t * 1e9)

    def sleep(self, s):
        self.t += s


class Flaky:
    """Fails the getSlot calls whose rank (1, 2, ...) is in `fail_at`."""
    def __init__(self, inner, fail_at):
        self.inner, self.fail_at, self.n = inner, set(fail_at), 0

    def request(self, method, params):
        if method == 'getSlot':
            self.n += 1
            if self.n in self.fail_at:
                raise RPC.RpcError('network_error')
        return self.inner.request(method, params)


def test_the_runner_records_gaps_and_stops(tmp_path):
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + HOUR))
    clock = Clock(START + 300)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    flaky = Flaky(fake, fail_at=(6, 7))                           # two failing polls in a row: a 90-s pause
    src = S.Source(client(tmp_path, flaky), NAMES[:3], mode='gtfa', start=START)
    runner = S.Runner(eng, src, poll_s=30, max_s=900, head_file=tmp_path / 'HEAD.json', wall=clock.wall,
                      mono_ns=clock.mono_ns, sleep=clock.sleep)
    out = runner.run()
    rec = eng.journal.records
    assert out == 'planned_end_of_process'
    assert rec[-1]['kind'] == 'STOP' and json.loads((tmp_path / 'HEAD.json').read_text())['head'] == rec[-1]['sha']
    gaps = [r for r in rec if r['kind'] == 'GAP']
    assert len(gaps) == 1 and gaps[0]['gap_end'] - gaps[0]['gap_start'] == 90
    # the credit ceiling stops the run, the ledger is never exceeded
    eng2 = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'k'), store=tmp_path / 't')
    src2 = S.Source(client(tmp_path / 'c', fake, spent=24_460), NAMES[:3], mode='gtfa', start=START)
    assert S.Runner(eng2, src2, poll_s=30, max_s=900, head_file=tmp_path / 'H2.json', wall=clock.wall,
                    mono_ns=clock.mono_ns, sleep=clock.sleep).run() == 'credit_hard_stop_24500'
    assert json.loads((tmp_path / 'c' / 'ledger.json').read_text())['credits'] <= 24_500
    # three errors in a row stop it
    eng3 = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'm'), store=tmp_path / 'u')
    src3 = S.Source(client(tmp_path / 'd', Flaky(fake, fail_at=range(0, 10 ** 6))), NAMES[:3], mode='gtfa', start=START)
    assert S.Runner(eng3, src3, poll_s=30, max_s=900, head_file=tmp_path / 'H3.json', wall=clock.wall,
                    mono_ns=clock.mono_ns, sleep=clock.sleep).run().startswith('consecutive_errors')


def test_no_network_no_key_no_signing(tmp_path):
    with pytest.raises(RPC.RpcError, match='needs_an_anchored_authorization'):
        S.LiveTransport('https://mainnet.helius-rpc.com/')
    text = tmp_path / 'text.txt'
    text.write_text('owner text')
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):
        S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=text)
    assert S.AUTHORIZED_TEXT_SHA256 == frozenset({SIGNED_TEXT_SHA256})
    t = object.__new__(S.LiveTransport)
    with pytest.raises(RPC.RpcError, match='method_not_in_livepaper'):
        t.request('sendTransaction', [])
    with pytest.raises(RPC.RpcError, match='method_not_in_livepaper'):
        t.request('getProgramAccounts', [])
    assert S.check_no_signing_modules(sys.modules) is True
    with pytest.raises(S.SourceError, match='signing_module_loaded'):
        S.check_no_signing_modules(['json', 'solders.keypair'])
    root = Path(S.__file__).parent
    code = ''.join((root / n).read_text() for n in ('engine.py', 'fill.py', 'journal.py', 'source.py', 'cli.py'))
    for word in ('sendTransaction', 'sign(', 'Keypair', 'os.environ[', 'getenv', 'api-key', 'api_key'):
        assert word not in code
    assert S.env_has_no_key() is True
    import os
    os.environ['HELIUS_API_KEY'] = 'placeholder-not-a-key'
    try:
        assert S.env_has_no_key() is False
    finally:
        del os.environ['HELIUS_API_KEY']


def gsfa_root(tmp_path, txs):
    fake = chain(txs, slot=2 * (START + 10 * HOUR))
    c = client(tmp_path / 'oc', fake)
    S.collect_gsfa(c, list(txs), tmp_path / 'GSFA', window_start=START - 8 * 86_400)
    return tmp_path / 'GSFA', c


def test_the_order_check(tmp_path):
    from cpmmpilot.store import write_gz_page
    from livepaper import ordercheck as OC
    txs = feed(START + HOUR)
    for p in NAMES[:3]:
        same_slot(txs, p, n=4)
    root, c = gsfa_root(tmp_path, txs)
    pages = sum(int((root / p / 'DONE').read_text()) for p in NAMES[:3])
    assert json.loads((tmp_path / 'oc' / 'ledger.json').read_text())['by_method'] == {'getSignaturesForAddress': pages}
    assert pages > 3                                       # paged back to the window start, 1 000 per call
    for p, d in txs.items():
        write_gz_page(tmp_path / 'GTFA' / p / 'page_00000.json.gz', dict(data=list(d.values())))
    doc = OC.check(root, tmp_path / 'GTFA', NAMES[:3])
    assert doc['verdict'] == 'a-ok' and doc['pairs'] == 3 * 6 and doc['discrepancies'] == 0
    # one swapped index -> b; a slot that differs -> b; nothing comparable -> b
    p0 = NAMES[0]
    rows = [dict(r) for r in sorted(txs[p0].values(), key=lambda r: (r['slot'], r['transactionIndex']))]
    multi = [r for r in rows if sum(1 for x in rows if x['slot'] == r['slot']) > 1]
    multi[0]['transactionIndex'], multi[1]['transactionIndex'] = multi[1]['transactionIndex'], multi[0]['transactionIndex']
    write_gz_page(tmp_path / 'GTFA2' / p0 / 'page_00000.json.gz', dict(data=rows))
    bad = OC.check(root, tmp_path / 'GTFA2', [p0])
    assert bad['verdict'] == 'b' and bad['pools'][p0]['discrepancies'] == 1
    good = sorted(txs[p0].values(), key=lambda r: (r['slot'], r['transactionIndex']))
    shifted = [dict(r, slot=r['slot'] + 1) if r['transaction'] == multi[2]['transaction'] else r for r in good]
    write_gz_page(tmp_path / 'GTFA3' / p0 / 'page_00000.json.gz', dict(data=shifted))
    mis = OC.check(root, tmp_path / 'GTFA3', [p0])
    assert mis['verdict'] == 'b' and mis['pools'][p0]['slot_mismatches'] == 1
    assert mis['pairs'] > 0 and mis['pools'][p0]['discrepancies'] == 0                 # only the slot differs
    assert OC.check(root, tmp_path / 'EMPTY', [p0])['verdict'] == 'b'                   # no pair compared
    assert OC.compare_pool([dict(signature='a', slot=5), dict(signature='b', slot=5)],
                           dict(a=(5, 1), b=(5, 0)))['discrepancies'] == 0           # newest first = later index
    assert OC.compare_pool([dict(signature='a', slot=5), dict(signature='b', slot=5)],
                           dict(a=(5, 0), b=(5, 1)))['discrepancies'] == 1


def test_commands(tmp_path, monkeypatch, capsys):
    from cpmmpilot.store import read_gz_page
    from livesim import sim as LS
    from livesim.tests.test_sim import three
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    el = LS.eligibility(out, LS.list_l_doc(list_l))
    variant = {'livesim-v0.3.1': 'A', 'livesim-v0.3.2': 'B'}[LS.SCHEMA]               # R02 reserve 5: any livesim
    other_variant = 'B' if variant == 'A' else 'A'
    (tmp_path / 'E.json').write_text(json.dumps(el))
    sha = LS.file_sha(tmp_path / 'E.json')
    prep = ['prepare', '--eligible', str(tmp_path / 'E.json'), '--eligible-sha', sha, '--list-l', str(list_l),
            '--variant', variant, '--start', str(START + 600), '--out', str(tmp_path / 'P.json')]
    with pytest.raises(C.CliError, match='eligible_not_the_anchored_file'):
        C.main(prep[:4] + ['0' * 64] + prep[5:])
    with pytest.raises(C.CliError, match='eligible_not_of_the_variant'):
        C.main(prep[:8] + [other_variant] + prep[9:])
    with pytest.raises(C.CliError, match='start_before'):
        C.main(prep[:10] + [str(START - 1)] + prep[11:])
    C.main(prep)
    doc = json.loads((tmp_path / 'P.json').read_text())
    capsys.readouterr()
    assert doc['variant'] == variant and doc['start'] == START + 600 and doc['eligible'] == NAMES[:3]
    assert [r['b3'] for r in doc['rows']] == [r['b3'] for r in el['rows']] and doc['eligible_sha256'] == sha
    with pytest.raises(C.CliError, match='output_exists'):
        C.main(prep)
    other = dict(el, rows=[dict(el['rows'][0], b3=3.0)] + el['rows'][1:])
    (tmp_path / 'E3.json').write_text(json.dumps(other))
    C.main(['prepare', '--eligible', str(tmp_path / 'E3.json'), '--eligible-sha', LS.file_sha(tmp_path / 'E3.json'),
            '--list-l', str(list_l), '--variant', variant, '--start', str(START + 600), '--out', str(tmp_path / 'P3.json')])
    capsys.readouterr()
    assert json.loads((tmp_path / 'P3.json').read_text())['rows'][0]['b3'] == 3.0       # b3 taken from ELIGIBLE
    tampered = dict(el, rows=[dict(el['rows'][0], amm_config_sha256='0' * 64)] + el['rows'][1:])
    (tmp_path / 'E2.json').write_text(json.dumps(tampered))
    with pytest.raises(C.CliError, match='amm_config_differs'):
        C.main(['prepare', '--eligible', str(tmp_path / 'E2.json'), '--eligible-sha', LS.file_sha(tmp_path / 'E2.json'),
                '--list-l', str(list_l), '--variant', variant, '--start', str(START + 600), '--out', str(tmp_path / 'Q.json')])
    # order check: collect-gsfa (transport injected by the test only) then ordercheck, on the one ledger
    txs = {}
    for c in sorted((out / 'collect').glob('live_*')):
        for p in NAMES[:3]:
            for f in sorted((c / p).glob('page_*.json.gz')):
                for t in read_gz_page(f).get('data') or []:
                    txs.setdefault(p, {})[t['transaction']['signatures'][0]] = t
    fake = chain(txs, slot=2 * now)
    common = ['--ledger', str(tmp_path / 'L.json'), '--calls', str(tmp_path / 'c.jsonl'), '--authorization',
              str(tmp_path / 'P.json'), '--endpoint', 'https://x.example/']
    seen = []
    real_collect = S.collect_gsfa
    monkeypatch.setattr(S, 'collect_gsfa', lambda *a, **k: seen.append(k) or real_collect(*a, **k))
    C.main(['collect-gsfa', '--pools', str(tmp_path / 'P.json'), '--out', str(tmp_path / 'G')] + common, transport=fake)
    assert seen == [dict(window_start=el['t_start'] - 7 * 86_400)]
    assert json.loads(capsys.readouterr().out) == {p: 1 for p in NAMES[:3]}
    C.main(['ordercheck', '--pools', str(tmp_path / 'P.json'), '--gsfa', str(tmp_path / 'G'), '--gtfa',
            str(out / 'collect' / 'live_000'), '--out', str(tmp_path / 'OC.json')])
    capsys.readouterr()
    oc = json.loads((tmp_path / 'OC.json').read_text())
    assert oc['verdict'] == 'b' and oc['pairs'] == 0                     # one transaction per slot: nothing to compare
    oc_sha = LS.file_sha(tmp_path / 'OC.json')
    base = ['run', '--pools', str(tmp_path / 'P.json'), '--ordercheck', str(tmp_path / 'OC.json'), '--journal',
            str(tmp_path / 'J.jsonl'), '--store', str(tmp_path / 'S'), '--seed-sha', SEED, '--ordercheck-sha',
            oc_sha] + common
    with pytest.raises(C.CliError, match='ordercheck_not_the_anchored_file'):
        C.main([a if a != oc_sha else '0' * 64 for a in base])
    with pytest.raises(C.CliError, match='ordercheck_not_the_anchored_file'):
        C.main([a if a != oc_sha else 'abc' for a in base])
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):
        C.main(base)
    monkeypatch.setenv('HELIUS_API_KEY', 'placeholder-not-a-key')
    with pytest.raises(C.CliError, match='provider_key_visible'):
        C.main(base)
    monkeypatch.delenv('HELIUS_API_KEY')
    with pytest.raises(C.CliError, match='process_above'):
        C.main(base + ['--max-minutes', '120'])
    assert not (tmp_path / 'J.jsonl').exists()                                          # nothing started
    assert C.way(tmp_path / 'OC.json', oc_sha) == ('gtfa', 150)
    a_ok = dict(oc, verdict='a-ok')
    (tmp_path / 'OK.json').write_text(json.dumps(a_ok))
    assert C.way(tmp_path / 'OK.json', LS.file_sha(tmp_path / 'OK.json')) == ('gsfa_rank', 30)
    clock = Clock(now)
    C.main(base + ['--max-minutes', '5'], transport=fake,
           clocks=dict(wall=clock.wall, mono_ns=clock.mono_ns, sleep=clock.sleep))
    assert capsys.readouterr().out.strip() == 'planned_end_of_process'
    rec = J.read(tmp_path / 'J.jsonl')
    assert rec[0]['mode'] == 'gtfa' and rec[0]['poll_s'] == 150
    led = json.loads((tmp_path / 'L.json').read_text())
    assert led['by_method']['getSignaturesForAddress'] >= 3 and led['ceiling'] == 25_000      # one ledger
    C.main(['verify', '--journal', str(tmp_path / 'J.jsonl')])
    v = json.loads(capsys.readouterr().out)
    assert v['head'] == rec[-1]['sha']
    C.main(['replay', '--pools', str(tmp_path / 'P.json'), '--journal', str(tmp_path / 'J.jsonl'), '--store',
            str(tmp_path / 'S'), '--seed-sha', SEED])
    assert json.loads(capsys.readouterr().out)['head'] == v['head']
    C.main(['compare', '--pools', str(tmp_path / 'P.json'), '--journal', str(tmp_path / 'J.jsonl'), '--store',
            str(tmp_path / 'S'), '--now', str(now), '--out', str(tmp_path / 'CMP.json')])
    cmp = json.loads((tmp_path / 'CMP.json').read_text())
    assert cmp['verdict'] is None and cmp['counts_for_operational_master'] is False and cmp['label'] == 'PAPER_LIVE_DEMO'
    assert cmp['journal_head'] == v['head'] and cmp['processing_ms']['steps'] >= 1


def test_the_replay_module_outside_the_manifests_is_checked_at_start(tmp_path, monkeypatch):
    assert S.check_imports() == S.HRR_SHA256
    with pytest.raises(S.SourceError, match='historical_research_replay_differs'):
        S.check_imports('0' * 64)
    monkeypatch.setattr(S, 'HRR_SHA256', '0' * 64)
    args = ['run', '--pools', 'P', '--ordercheck', 'O', '--journal', str(tmp_path / 'J'), '--store', 'S', '--seed-sha',
            SEED, '--ledger', 'L', '--calls', 'C', '--authorization', 'A', '--endpoint', 'https://x.example/',
            '--ordercheck-sha', '0' * 64]
    with pytest.raises(S.SourceError, match='historical_research_replay_differs'):
        C.run(C.argparse.Namespace(**{k.lstrip('-').replace('-', '_'): v for k, v in zip(args[1::2], args[2::2])},
                                   max_minutes=5), {})
    with pytest.raises(S.SourceError, match='historical_research_replay_differs'):
        C.main(['collect-gsfa', '--pools', 'P', '--out', 'G', '--ledger', 'L', '--calls', 'C', '--authorization', 'A',
                '--endpoint', 'https://x.example/'])


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self, n):
        return json.dumps(self.payload).encode()


def test_the_signed_text_opens_the_transport_and_nothing_else_does(tmp_path):
    """0.1.2: the owner's signed text (R03's AUTORISATION_LIVEPAPER.txt) has the authorized sha; only that file opens
    LiveTransport. The opener is a fake: no network in the tests."""
    import hashlib
    assert hashlib.sha256(TEXT.read_bytes()).hexdigest() == SIGNED_TEXT_SHA256
    sent = []

    def opener(request, timeout):
        sent.append(json.loads(request.data))
        return Response(dict(jsonrpc='2.0', id=sent[-1]['id'], result=123))
    t = S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=TEXT, opener=opener, sleep=lambda s: None)
    assert t.authorization_sha256 == SIGNED_TEXT_SHA256 and t.request('getSlot', [dict(commitment='confirmed')]) == 123
    assert sent == [dict(jsonrpc='2.0', id=1, method='getSlot', params=[dict(commitment='confirmed')])]
    changed = tmp_path / 'changed.txt'
    changed.write_bytes(TEXT.read_bytes() + b'\n')                         # one byte more: another sha
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):
        S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=changed, opener=opener)
    with pytest.raises(RPC.RpcError, match='endpoint_must_not_carry_credentials'):
        S.LiveTransport('https://mainnet.helius-rpc.com/?api-key=x', authorization_file=TEXT, opener=opener)
