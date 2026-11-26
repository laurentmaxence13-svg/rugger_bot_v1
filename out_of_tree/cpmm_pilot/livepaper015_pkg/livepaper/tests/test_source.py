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


class Lag:
    """The n-th getSlot takes `seconds` of the test clock: a slow poll."""
    def __init__(self, inner, clock, n, seconds):
        self.inner, self.clock, self.n, self.seconds, self.k = inner, clock, n, seconds, 0

    def request(self, method, params):
        if method == 'getSlot':
            self.k += 1
            if self.k == self.n:
                self.clock.t += self.seconds
        return self.inner.request(method, params)


def test_the_runner_records_gaps_and_stops(tmp_path):
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + HOUR))
    clock = Clock(START + 300)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    src = S.Source(client(tmp_path, Lag(fake, clock, n=6, seconds=70)), NAMES[:3], mode='gtfa', start=START)
    runner = S.Runner(eng, src, poll_s=30, max_s=900, head_file=tmp_path / 'HEAD.json', wall=clock.wall,
                      mono_ns=clock.mono_ns, sleep=clock.sleep)
    out = runner.run()
    rec = eng.journal.records
    assert out == 'planned_end_of_process'
    assert rec[-1]['kind'] == 'STOP' and json.loads((tmp_path / 'HEAD.json').read_text())['head'] == rec[-1]['sha']
    gaps = [r for r in rec if r['kind'] == 'GAP']
    assert len(gaps) == 1 and gaps[0]['gap_end'] - gaps[0]['gap_start'] == 100      # 30 s poll + a 70-s fetch
    assert not [r for r in rec if r['kind'] == 'ERROR']
    # the credit ceiling stops the run, the ledger is never exceeded
    eng2 = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'k'), store=tmp_path / 't')
    src2 = S.Source(client(tmp_path / 'c', fake, spent=24_460), NAMES[:3], mode='gtfa', start=START)
    assert S.Runner(eng2, src2, poll_s=30, max_s=900, head_file=tmp_path / 'H2.json', wall=clock.wall,
                    mono_ns=clock.mono_ns, sleep=clock.sleep).run() == 'credit_hard_stop_24500'
    assert json.loads((tmp_path / 'c' / 'ledger.json').read_text())['credits'] <= 24_500
    # 0.1.4 (D14): ONE incident -> ERROR then STOP, at once, no sleep and no retry
    for k, (transport, kind, message) in enumerate([(Flaky(fake, fail_at=(3,)), 'RpcError', 'network_error'),
                                                    (FailNth(fake, 'getSignaturesForAddress', 5), 'RpcError',
                                                     'provider_error')]):
        e = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / ('m%d' % k)),
                     store=tmp_path / ('u%d' % k))
        c = Clock(START + 300)
        src3 = S.Source(client(tmp_path / ('d%d' % k), transport), NAMES[:3], mode='gtfa', start=START)
        assert S.Runner(e, src3, poll_s=30, max_s=900, head_file=tmp_path / ('H%d.json' % k), wall=c.wall,
                        mono_ns=c.mono_ns, sleep=c.sleep).run() == 'incident:%s' % kind
        r = e.journal.records
        assert [x['kind'] for x in r[-2:]] == ['ERROR', 'STOP'] and r[-2]['error_type'] == kind
        assert r[-2]['message'] == message and r[-1]['reason'] == 'incident:%s' % kind
        assert r[-2]['wall'] == r[-3]['wall'] + 30 if r[-3]['kind'] == 'STEP' else True
        J.verify_records(r)
    # a SourceError is an incident too
    class BadSlot:
        def request(self, method, params):
            return 'x' if method == 'getSlot' else fake.request(method, params)
    e = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'z'), store=tmp_path / 'zs')
    c = Clock(START + 300)
    assert S.Runner(e, S.Source(client(tmp_path / 'z2', BadSlot()), NAMES[:3], mode='gtfa', start=START), poll_s=30,
                    max_s=900, head_file=tmp_path / 'HZ.json', wall=c.wall, mono_ns=c.mono_ns,
                    sleep=c.sleep).run() == 'incident:SourceError'
    assert e.journal.records[-2]['message'] == 'slot_not_an_integer'


def test_no_network_no_key_no_signing(tmp_path):
    with pytest.raises(RPC.RpcError, match='needs_an_anchored_authorization'):
        S.LiveTransport('https://mainnet.helius-rpc.com/')
    text = tmp_path / 'text.txt'
    text.write_text('owner text')
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):
        S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=text)
    assert SIGNED_TEXT_SHA256 not in S.AUTHORIZED_TEXT_SHA256 and SIGNED_TEXT_SHA256 in S.WITHDRAWN_TEXT_SHA256
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
    start = json.loads((tmp_path / 'P.json').read_text())['start']
    late = Clock(start + S.TEST_S)                               # 0.1.5 (c): no collection, no order check past 24 h
    for cmd in (['collect-gsfa', '--pools', str(tmp_path / 'P.json'), '--out', str(tmp_path / 'G')] + common,
                ['ordercheck', '--pools', str(tmp_path / 'P.json'), '--gsfa', str(tmp_path / 'G'), '--gtfa',
                 str(out / 'collect' / 'live_000'), '--out', str(tmp_path / 'OC.json')]):
        rec0 = Record(fake)
        with pytest.raises(S.SourceError, match='test_window_over'):
            C.main(cmd, transport=rec0, clocks=dict(wall=late.wall))
        assert rec0.methods == [] and not (tmp_path / 'L.json').exists() and not (tmp_path / 'OC.json').exists()
    early = dict(wall=lambda: float(now))
    C.main(['collect-gsfa', '--pools', str(tmp_path / 'P.json'), '--out', str(tmp_path / 'G')] + common, transport=fake,
           clocks=early)
    assert seen == [dict(window_start=el['t_start'] - 7 * 86_400)]
    collected = (tmp_path / 'c.jsonl.timing.jsonl').read_text().splitlines()
    assert collected and all(json.loads(x)['method'] == 'getSignaturesForAddress' for x in collected)   # 0.1.3: timed
    assert json.loads(capsys.readouterr().out) == {p: 1 for p in NAMES[:3]}
    C.main(['ordercheck', '--pools', str(tmp_path / 'P.json'), '--gsfa', str(tmp_path / 'G'), '--gtfa',
            str(out / 'collect' / 'live_000'), '--out', str(tmp_path / 'OC.json')], clocks=early)
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
    C.main(base + ['--max-minutes', '5'], transport=Truncating(fake, 'getSlot', 1),      # 0.1.4: one re-read
           clocks=dict(wall=clock.wall, mono_ns=clock.mono_ns, sleep=clock.sleep))
    assert capsys.readouterr().out.strip() == 'planned_end_of_process'
    assert dict(method='getSlot', params_sha256=RPC.sha([dict(commitment='confirmed')]), retry=True,
                after='response_truncated') in [json.loads(x) for x in (tmp_path / 'c.jsonl').read_text().splitlines()]
    rec = J.read(tmp_path / 'J.jsonl')
    assert rec[0]['mode'] == 'gtfa' and rec[0]['poll_s'] == 150
    timing = [json.loads(x) for x in (tmp_path / 'c.jsonl.timing.jsonl').read_text().splitlines()]
    assert {'getSlot', 'getTransactionsForAddress'} <= {t['method'] for t in timing}
    assert [(t['method'], t['error']) for t in timing if not t['ok']] == [('getSlot', 'RpcError:response_truncated')]
    assert all(type(r['fetch_ms']) is float for r in rec if r['kind'] == 'STEP')
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
    # 0.1.5: the command refuses, before any call and without touching the ledger, (c) a run past start + 24 h ...
    ledger_before = (tmp_path / 'L.json').read_bytes()
    rec2 = Record(fake)
    monkeypatch.setattr(E, 'resume', lambda *a, **k: (_ for _ in ()).throw(AssertionError('replayed')))
    late = Clock(json.loads((tmp_path / 'P.json').read_text())['start'] + S.TEST_S)
    with pytest.raises(S.SourceError, match='test_window_over'):
        C.main(base + ['--max-minutes', '5'], transport=rec2,
               clocks=dict(wall=late.wall, mono_ns=late.mono_ns, sleep=late.sleep))
    # ... (b) a journal killed without STOP (it ends on a STEP) ...
    lines = (tmp_path / 'J.jsonl').read_text().splitlines(keepends=True)
    assert json.loads(lines[-1])['reason'] == 'planned_end_of_process' and json.loads(lines[-2])['kind'] == 'STEP'
    (tmp_path / 'K.jsonl').write_text(''.join(lines[:-1]))
    with pytest.raises(S.SourceError, match='journal_ended_without_planned_stop:STEP'):
        C.main([a if a != str(tmp_path / 'J.jsonl') else str(tmp_path / 'K.jsonl') for a in base] + ['--max-minutes', '5'],
               transport=rec2, clocks=dict(wall=clock.wall, mono_ns=clock.mono_ns, sleep=clock.sleep))
    # ... and (b) a journal stopped by an incident
    j = J.Journal(tmp_path / 'J.jsonl', replay=True)
    j.cursor = len(j.records)
    j.append('STOP', reason='incident:RpcError', wall=0.0)
    j.commit()
    with pytest.raises(S.SourceError, match='journal_stopped_for_good:incident:RpcError'):
        C.main(base + ['--max-minutes', '5'], transport=rec2,
               clocks=dict(wall=clock.wall, mono_ns=clock.mono_ns, sleep=clock.sleep))
    assert rec2.methods == [] and (tmp_path / 'L.json').read_bytes() == ledger_before


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


def test_the_former_text_no_longer_opens_and_only_an_inscribed_text_does(tmp_path, monkeypatch):
    """0.1.5 (a): 1366025b (R03's AUTORISATION_LIVEPAPER.txt, the 0.1.2-0.1.4 text) is withdrawn; only a text whose sha
    is inscribed opens LiveTransport. The opener is a fake: no network in the tests."""
    import hashlib
    assert hashlib.sha256(TEXT.read_bytes()).hexdigest() == SIGNED_TEXT_SHA256
    sent = []

    def opener(request, timeout):
        sent.append(json.loads(request.data))
        return Response(dict(jsonrpc='2.0', id=sent[-1]['id'], result=123))
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):
        S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=TEXT, opener=opener)
    signed = tmp_path / 'signed.txt'                                          # a stand-in for the future signed text
    signed.write_bytes(b'owner text v6, signed')
    digest = hashlib.sha256(signed.read_bytes()).hexdigest()
    monkeypatch.setattr(S, 'AUTHORIZED_TEXT_SHA256', frozenset({digest}))
    t = S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=signed, opener=opener, sleep=lambda s: None)
    assert t.authorization_sha256 == digest and t.request('getSlot', [dict(commitment='confirmed')]) == 123
    assert sent == [dict(jsonrpc='2.0', id=1, method='getSlot', params=[dict(commitment='confirmed')])]
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):     # still refused with it inscribed
        S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=TEXT, opener=opener)
    changed = tmp_path / 'changed.txt'
    changed.write_bytes(signed.read_bytes() + b'\n')                          # one byte more: another sha
    with pytest.raises(RPC.RpcError, match='authorization_not_anchored'):
        S.LiveTransport('https://mainnet.helius-rpc.com/', authorization_file=changed, opener=opener)
    with pytest.raises(RPC.RpcError, match='endpoint_must_not_carry_credentials'):
        S.LiveTransport('https://mainnet.helius-rpc.com/?api-key=x', authorization_file=signed, opener=opener)


def test_the_authorized_text_is_inscribed():
    """0.1.5 (a), R04 03:08Z: FAILS ON PURPOSE while AUTHORIZED_TEXT_SHA256 is pending. It passes only with exactly ONE
    inscribed sha (the owner's signed text, verified by R02) that is not a withdrawn one."""
    assert len(S.AUTHORIZED_TEXT_SHA256) == 1, 'PENDING: the signed text sha is not inscribed yet'
    assert not (S.AUTHORIZED_TEXT_SHA256 & S.WITHDRAWN_TEXT_SHA256)
    assert all(len(x) == 64 and set(x) <= set('0123456789abcdef') for x in S.AUTHORIZED_TEXT_SHA256)


# -- 0.1.3 (R04 20:33Z): timed calls, fetch_ms, GAP at >= 2 x poll_s; edge cases written before the code ---------------
class Slow:
    """A transport that takes `delay` s of the test clock per call and can fail a given method."""
    def __init__(self, inner, clock, delay, fail=None):
        self.inner, self.clock, self.delay, self.fail = inner, clock, delay, fail

    def request(self, method, params):
        self.clock.t += self.delay
        if method == self.fail:
            raise RPC.RpcError('network_error')
        return self.inner.request(method, params)


def test_every_call_is_timed_even_when_it_fails(tmp_path):
    txs = feed(START + HOUR)
    clock = Clock(START + 100)
    base = client(tmp_path, Slow(chain(txs, slot=2 * (START + HOUR)), clock, 0.25, fail='getTransaction'))
    timed = S.TimedClient(base, tmp_path / 'calls.timing.jsonl', wall=clock.wall, mono_ns=clock.mono_ns)
    assert timed.call('getSlot', [dict(commitment='confirmed')]) == 2 * (START + HOUR)
    with pytest.raises(RPC.RpcError, match='network_error'):
        timed.call('getTransaction', ['x', {}])
    rows = [json.loads(x) for x in (tmp_path / 'calls.timing.jsonl').read_text().splitlines()]
    assert [r['method'] for r in rows] == ['getSlot', 'getTransaction'] and [r['ok'] for r in rows] == [True, False]
    assert all(abs(r['duration_ms'] - 250) < 1e-6 and r['end_wall'] - r['start_wall'] == 0.25 for r in rows)
    assert rows[1]['error'] == 'RpcError:network_error' and rows[0]['error'] is None
    assert rows[0]['params_sha256'] == RPC.sha([dict(commitment='confirmed')])
    assert timed.budget is base.budget                                  # the frozen Client is untouched, only wrapped
    plain = [json.loads(x) for x in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert [p['method'] for p in plain] == ['getSlot']                  # the frozen log keeps its own format
    exhausted = S.TimedClient(client(tmp_path / 'x', chain(txs, slot=1), spent=24_500), tmp_path / 'x.timing.jsonl',
                              wall=clock.wall, mono_ns=clock.mono_ns)
    with pytest.raises(B.BudgetExhausted):
        exhausted.call('getSlot', [])
    assert json.loads((tmp_path / 'x.timing.jsonl').read_text())['error'].startswith('BudgetExhausted')


def test_the_fetch_time_is_in_step_and_a_pause_of_exactly_two_polls_is_a_gap(tmp_path):
    txs = feed(START + HOUR)
    clock = Clock(START + 300)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    src = S.Source(client(tmp_path, Slow(chain(txs, slot=2 * (START + HOUR)), clock, 0.5)), NAMES[:3], mode='gtfa',
                   start=START)
    S.Runner(eng, src, poll_s=30, max_s=120, head_file=tmp_path / 'H.json', wall=clock.wall, mono_ns=clock.mono_ns,
             sleep=clock.sleep).run()
    steps = [r for r in eng.journal.records if r['kind'] == 'STEP']
    assert steps and all(r['fetch_ms'] > 0 for r in steps) and 'fetch_ms' in J.VOLATILE
    assert steps[0]['fetch_ms'] == 500.0 * (3 + 1)                       # 3 first-pass GTFA pages + getSlot, 0.5 s each
    # the GAP threshold: >= 2 x poll_s
    eng2 = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'k'), store=tmp_path / 't')
    r = S.Runner(eng2, src, poll_s=30, max_s=0, head_file=tmp_path / 'H2.json', wall=clock.wall, mono_ns=clock.mono_ns,
                 sleep=clock.sleep)
    assert r.gap_of(1_000.0, 1_060.0) == (1_000.0, 1_060.0) and r.gap_of(1_000.0, 1_059.9) is None
    assert r.gap_of(None, 1_060.0) is None


# -- 0.1.4: D13, a failed fetch loses nothing --------------------------------------------------------------------------
class FailNth:
    """Raises RpcError on the n-th request of `method` (for `pool` when given); everything else passes through. Mimics
    D13: GSFA(GaPTvX) and getTransaction(5fP9) succeed, then GSFA(6CQSpR) fails, the fetch raises."""
    def __init__(self, inner, method, n, pool=None):
        self.inner, self.method, self.n, self.pool, self.seen, self.fired = inner, method, n, pool, 0, 0

    def request(self, method, params):
        if method == self.method and (self.pool is None or (params and params[0] == self.pool)):
            self.seen += 1
            if self.seen == self.n:
                self.fired += 1
                raise RPC.RpcError('provider_error')
        return self.inner.request(method, params)


def live_sigs(txs, pool, slot):
    return sorted(r['transaction']['signatures'][0] for r in txs[pool].values()
                  if r['blockTime'] >= START and r['slot'] <= slot)


def state(src):
    return json.dumps([src.last_sig, src.rank, src.since, {p: sorted(s) for p, s in src.seen.items()}], sort_keys=True)


FAILURES = [('gsfa_rank', 'getSignaturesForAddress', NAMES[1]), ('gsfa_rank', 'getSlot', None),
            ('gtfa', 'getTransactionsForAddress', NAMES[1]), ('gtfa', 'getSlot', None)]


@pytest.mark.parametrize('mode,method,pool', FAILURES)
def test_a_fetch_that_fails_after_a_pool_was_read_restores_the_source_and_loses_nothing(tmp_path, mode, method, pool):
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + 1_800))
    fail = FailNth(Quiet(fake), method, n=2, pool=pool)            # the 2nd such request: inside the 2nd fetch
    src = S.Source(client(tmp_path, fail), NAMES[:3], mode=mode, start=START)
    got1, slot1 = src.fetch()
    fake.slot = 2 * (START + HOUR)
    before = state(src)
    ledger = lambda: json.loads((tmp_path / 'ledger.json').read_text())['by_method']
    read_before = ledger().get('getTransaction', 0) + ledger().get('getTransactionsForAddress', 0)
    with pytest.raises(RPC.RpcError):
        src.fetch()
    assert fail.fired == 1
    # the D13 precondition: NAMES[0] WAS read (transactions bought) inside the failed fetch ...
    assert ledger().get('getTransaction', 0) + ledger().get('getTransactionsForAddress', 0) > read_before
    # ... and the source is back where it was, so the retry asks again from the last DELIVERED signature
    assert state(src) == before
    got3, slot3 = src.fetch()
    for p in NAMES[:3]:
        seen = [r['transaction']['signatures'][0] for r in got1[p] + got3[p]]
        assert sorted(seen) == live_sigs(txs, p, slot3) and len(seen) == len(set(seen))


class Advancing:
    """The chain grows with the test clock: slot = 2 x t, as the fixtures."""
    def __init__(self, inner, clock):
        self.inner, self.clock = inner, clock

    def request(self, method, params):
        self.inner.slot = 2 * int(self.clock.t)
        return self.inner.request(method, params)


def test_one_failed_poll_stops_and_the_journal_is_never_resumed(tmp_path):
    """D13 + D14 + 0.1.5 (b): the incident stops the process (ERROR, STOP); the timing log has the failed call with its
    error type; the replay still reproduces the journal, but no run resumes it -- no call is made."""
    txs = feed(START + HOUR)
    clock = Clock(START + 300)
    fake = chain(txs, slot=2 * (START + 300))
    fail = FailNth(Quiet(Advancing(fake, clock)), 'getSignaturesForAddress', n=4, pool=NAMES[1])
    ledger = S.Budget(tmp_path / 'ledger.json')
    timed = S.TimedClient(RPC.Client(fail, ledger, tmp_path / 'calls.jsonl'), tmp_path / 'timing.jsonl',
                          wall=clock.wall, mono_ns=clock.mono_ns)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    src = S.Source(S.RetryOnce(timed, tmp_path / 'calls.jsonl'), NAMES[:3], mode='gsfa_rank', start=START)
    assert S.Runner(eng, src, poll_s=30, max_s=1_200, head_file=tmp_path / 'HEAD.json', wall=clock.wall,
                    mono_ns=clock.mono_ns, sleep=clock.sleep).run() == 'incident:RpcError'
    rows = [json.loads(x) for x in (tmp_path / 'timing.jsonl').read_text().split('\n') if x]
    bad = [x for x in rows if not x['ok']]
    assert len(bad) == 1 and bad[0]['method'] == 'getSignaturesForAddress' and bad[0]['error'] == 'RpcError:provider_error'
    clock.t += 120
    again = E.resume(pools(), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'j', store=tmp_path / 's')
    assert not again.journal.replaying and again.journal.head == eng.journal.head
    src2 = S.Source(S.RetryOnce(timed, tmp_path / 'calls.jsonl'), NAMES[:3], mode='gsfa_rank', start=START)
    src2.restore(again.journal.records)
    calls = (tmp_path / 'calls.jsonl').read_text()
    with pytest.raises(S.SourceError, match='journal_stopped_for_good:ERROR'):     # its ERROR comes before its STOP
        S.Runner(again, src2, poll_s=30, max_s=900, head_file=tmp_path / 'HEAD.json', wall=clock.wall,
                 mono_ns=clock.mono_ns, sleep=clock.sleep).run()
    assert (tmp_path / 'calls.jsonl').read_text() == calls and fail.fired == 1        # nothing was called
    assert J.read(tmp_path / 'j')[-1]['reason'] == 'incident:RpcError'                # nothing was written


# -- 0.1.5 (b) and (c) ---------------------------------------------------------------------------------------------------
def test_only_a_planned_stop_can_be_resumed(tmp_path):
    """0.1.5 (b), ONE rule (R04 04:32Z): the last record read from disk must be STOP planned_end_of_process."""
    start, step = dict(kind='START'), dict(kind='STEP')
    def rec(reason):
        return [start, step, dict(kind='STOP', reason=reason)]
    S.check_resumable(rec('planned_end_of_process'))
    S.check_resumable([])                                                     # no journal yet
    for bad in ('incident:RpcError', 'incident:SourceError', 'credit_hard_stop_24500', 'end_of_test_86400'):
        with pytest.raises(S.SourceError, match='journal_stopped_for_good:' + bad):
            S.check_resumable(rec(bad))
    with pytest.raises(S.SourceError, match='journal_ended_without_planned_stop:manual_stop'):
        S.check_resumable(rec('manual_stop'))                                 # an unknown reason: a white list
    for records, kind in (([start], 'START'), ([start, step], 'STEP')):
        with pytest.raises(S.SourceError, match='journal_ended_without_planned_stop:' + kind):
            S.check_resumable(records)                                        # a process killed without STOP
    error = dict(kind='ERROR', error_type='RpcError', message='m')
    with pytest.raises(S.SourceError, match='journal_stopped_for_good:ERROR'):
        S.check_resumable([start, step, error])                               # killed between ERROR and STOP
    S.check_resumable([start], loaded=0)                                      # this process wrote START: a new run
    with pytest.raises(S.SourceError, match='journal_ended_without_planned_stop:START'):
        S.check_resumable([start, step], loaded=1)                            # START read from disk: killed after it
    # R04 04:39Z: a final record ANYWHERE refuses, even followed by a planned stop (a case livepaper cannot write)
    for final in (error, dict(kind='STOP', reason='incident:RpcError'), dict(kind='STOP', reason='credit_hard_stop_24500'),
                  dict(kind='STOP', reason='end_of_test_86400')):
        with pytest.raises(S.SourceError, match='journal_stopped_for_good:' + final.get('reason', 'ERROR')):
            S.check_resumable([start, step, final, step, dict(kind='STOP', reason='planned_end_of_process')])
    S.check_resumable([start, step, dict(kind='STOP', reason='planned_end_of_process'), step,
                       dict(kind='STOP', reason='planned_end_of_process')])   # planned stops in the middle are fine
    # the credit hard stop: the next process, resuming the journal from disk, is refused before any call
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + HOUR))
    clock = Clock(START + 300)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'k'), store=tmp_path / 't')
    assert eng.journal.loaded == 0 and J.Journal(tmp_path / 'k', replay=True).loaded == 1
    src = S.Source(client(tmp_path / 'c', fake, spent=24_460), NAMES[:3], mode='gtfa', start=START)
    assert S.Runner(eng, src, poll_s=30, max_s=900, head_file=tmp_path / 'H.json', wall=clock.wall,
                    mono_ns=clock.mono_ns, sleep=clock.sleep).run() == 'credit_hard_stop_24500'
    again = E.resume(pools(), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'k', store=tmp_path / 't')
    rec2 = Record(fake)
    with pytest.raises(S.SourceError, match='journal_stopped_for_good:credit_hard_stop_24500'):
        S.Runner(again, S.Source(client(tmp_path / 'd', rec2), NAMES[:3], mode='gtfa', start=START), poll_s=30,
                 max_s=900, head_file=tmp_path / 'H.json', wall=clock.wall, mono_ns=clock.mono_ns,
                 sleep=clock.sleep).run()
    assert rec2.methods == []


def test_a_process_killed_without_stop_is_never_resumed(tmp_path):
    """0.1.5 (b): SIGKILL / lost container -- the journal ends on a STEP; replay identical, the Runner refuses, the same
    journal with its planned STOP resumes."""
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + HOUR))
    clock = Clock(START + 300)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    S.Runner(eng, S.Source(client(tmp_path / 'a', fake), NAMES[:3], mode='gtfa', start=START), poll_s=30, max_s=120,
             head_file=tmp_path / 'H.json', wall=clock.wall, mono_ns=clock.mono_ns, sleep=clock.sleep).run()
    lines = (tmp_path / 'j').read_text().splitlines(keepends=True)
    assert json.loads(lines[-1])['reason'] == 'planned_end_of_process'
    (tmp_path / 'j').write_text(''.join(lines[:-1]))                          # the STOP was never written
    again = E.resume(pools(), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'j', store=tmp_path / 's')
    assert again.journal.loaded == len(lines) - 1 and again.journal.records[-1]['kind'] == 'STEP'
    rec2 = Record(fake)
    src = S.Source(client(tmp_path / 'b', rec2), NAMES[:3], mode='gtfa', start=START)
    src.restore(again.journal.records)
    with pytest.raises(S.SourceError, match='journal_ended_without_planned_stop:STEP'):
        S.Runner(again, src, poll_s=30, max_s=120, head_file=tmp_path / 'H.json', wall=clock.wall,
                 mono_ns=clock.mono_ns, sleep=clock.sleep).run()
    assert rec2.methods == [] and (tmp_path / 'j').read_text() == ''.join(lines[:-1])
    (tmp_path / 'k').write_text(''.join(lines))
    k = E.resume(pools(), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'k', store=tmp_path / 's')
    src3 = S.Source(client(tmp_path / 'c', fake), NAMES[:3], mode='gtfa', start=START)
    src3.restore(k.journal.records)
    assert S.Runner(k, src3, poll_s=30, max_s=60, head_file=tmp_path / 'H2.json', wall=clock.wall,
                    mono_ns=clock.mono_ns, sleep=clock.sleep).run() == 'planned_end_of_process'


def test_the_test_lasts_at_most_24_hours_from_start(tmp_path):
    assert S.TEST_S == 86_400
    S.check_window(START, START + S.TEST_S - 1)
    with pytest.raises(S.SourceError, match='test_window_over'):
        S.check_window(START, START + S.TEST_S)                                 # at the boundary: refused
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + HOUR))
    # a process started 70 s before the end stops at the end, by the clock, without an incident
    clock = Clock(START + S.TEST_S - 70)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    src = S.Source(client(tmp_path / 'a', fake), NAMES[:3], mode='gtfa', start=START)
    runner = S.Runner(eng, src, poll_s=30, max_s=900, head_file=tmp_path / 'H.json', wall=clock.wall,
                      mono_ns=clock.mono_ns, sleep=clock.sleep)
    assert runner.run() == 'end_of_test_86400'
    steps = [r for r in eng.journal.records if r['kind'] == 'STEP']
    assert len(steps) == 3 and all(r['receipt_time'] < START + S.TEST_S for r in steps)
    # a poll that would begin EXACTLY at start + 86 400 s does not happen
    on = Clock(START + S.TEST_S - 60)
    eng3 = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'e'), store=tmp_path / 'es')
    assert S.Runner(eng3, S.Source(client(tmp_path / 'e2', fake), NAMES[:3], mode='gtfa', start=START), poll_s=30,
                    max_s=900, head_file=tmp_path / 'H3.json', wall=on.wall, mono_ns=on.mono_ns,
                    sleep=on.sleep).run() == 'end_of_test_86400'
    assert [r['receipt_time'] for r in eng3.journal.records if r['kind'] == 'STEP'] == [START + S.TEST_S - 60,
                                                                                        START + S.TEST_S - 30]
    # a run at or after the end is refused before any call, and the end of test may be resumed by nothing
    rec = Record(fake)
    eng2 = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'k'), store=tmp_path / 't')
    late = Clock(START + S.TEST_S)
    with pytest.raises(S.SourceError, match='test_window_over'):
        S.Runner(eng2, S.Source(client(tmp_path / 'b', rec), NAMES[:3], mode='gtfa', start=START), poll_s=30,
                 max_s=900, head_file=tmp_path / 'H2.json', wall=late.wall, mono_ns=late.mono_ns,
                 sleep=late.sleep).run()
    assert rec.methods == []


class Truncating:
    """Answers 'response_truncated' to the first `times` requests of `method`."""
    def __init__(self, inner, method, times):
        self.inner, self.method, self.times, self.k = inner, method, times, 0

    def request(self, method, params):
        if method == self.method and self.k < self.times:
            self.k += 1
            raise RPC.RpcError('response_truncated')
        return self.inner.request(method, params)


def test_a_truncated_response_is_re_read_once_charged_and_logged_and_a_second_one_is_an_incident(tmp_path):
    txs = feed(START + HOUR)
    fake = chain(txs, slot=2 * (START + HOUR))
    for times, retry, expect in ((1, 1, 'ok'), (2, 1, 'raise'), (1, 0, 'raise')):
        d = tmp_path / ('%d_%d' % (times, retry))
        inner = client(d, Truncating(fake, 'getSlot', times))
        rc = S.RetryOnce(inner, d / 'calls.jsonl', retry=retry)
        if expect == 'ok':
            assert rc.call('getSlot', [dict(commitment='confirmed')]) == fake.slot and rc.retries == 1
            assert json.loads((d / 'ledger.json').read_text())['by_method']['getSlot'] == 2      # the re-read is charged
            lines = [json.loads(x) for x in (d / 'calls.jsonl').read_text().split('\n') if x]
            assert lines[0] == dict(method='getSlot', params_sha256=RPC.sha([dict(commitment='confirmed')]), retry=True,
                                    after='response_truncated') and lines[1]['method'] == 'getSlot'
        else:
            with pytest.raises(RPC.RpcError, match='response_truncated'):
                rc.call('getSlot', [dict(commitment='confirmed')])
    other = S.RetryOnce(client(tmp_path / 'o', Flaky(fake, fail_at=(1,))), tmp_path / 'o' / 'calls.jsonl')
    with pytest.raises(RPC.RpcError, match='network_error'):
        other.call('getSlot', [dict(commitment='confirmed')])
    assert other.retries == 0
    with pytest.raises(S.SourceError, match='retry_on_truncated_is_0_or_1'):
        S.RetryOnce(other.client, tmp_path / 'x', retry=2)
    assert S.RETRY_ON_TRUNCATED == 1 and S.RetryOnce(other.client, tmp_path / 'x').budget is other.client.budget
    # in a run: one truncation does not stop it
    clock = Clock(START + 300)
    e = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    src = S.Source(S.RetryOnce(client(tmp_path / 'r', Truncating(fake, 'getSignaturesForAddress', 1)),
                               tmp_path / 'r' / 'calls.jsonl'), NAMES[:3], mode='gtfa', start=START)
    assert S.Runner(e, src, poll_s=30, max_s=300, head_file=tmp_path / 'H.json', wall=clock.wall, mono_ns=clock.mono_ns,
                    sleep=clock.sleep).run() == 'planned_end_of_process'
    assert not [r for r in e.journal.records if r['kind'] == 'ERROR']


def test_the_incident_message_is_redacted():
    assert S.redact(RPC.RpcError('http_503')) == 'http_503'
    got = S.redact(RuntimeError('https://beta.example/?api-key=SECRET é ' + 'x' * 200))
    assert len(got) == 80 and '/' not in got and '=' not in got and ' ' not in got and 'é' not in got
    assert got.startswith('https:??beta.example??api-key?SECRET???')


# -- 0.1.4: the bounded catch-up before any G-0 exclusion (D13, second net) ---------------------------------------------
class Hide:
    """Provider index lag: the polls (GSFA limit 1000) never list `sigs`; the catch-up GSFA (limit 100) does."""
    def __init__(self, inner, sigs):
        self.inner, self.sigs = inner, set(sigs)

    def request(self, method, params):
        out = self.inner.request(method, params)
        if method == 'getSignaturesForAddress' and params[1].get('limit') == S.GSFA_LIMIT:
            out = [x for x in out if x['signature'] not in self.sigs]
        return out


def lagged(txs, pool, lo, hi, n=1):
    """n live transactions of `pool` with block time in [lo, hi], each alone in its slot."""
    rows = sorted(txs[pool].values(), key=lambda r: (r['slot'], r['transactionIndex']))
    slots = {}
    for r in rows:
        slots[r['slot']] = slots.get(r['slot'], 0) + 1
    picked = [r for r in rows if lo <= r['blockTime'] <= hi and slots[r['slot']] == 1][:n]
    assert len(picked) == n
    return [r['transaction']['signatures'][0] for r in picked]


def catchup_run(tmp_path, txs, hidden, *, mode='gsfa_rank', catchup=True, monkeypatch=None, transport=None):
    clock = Clock(START + 300)
    fake = chain(txs, slot=2 * (START + 300))
    inner = transport(Quiet(Advancing(fake, clock))) if transport else Quiet(Advancing(fake, clock))
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'j'), store=tmp_path / 's')
    src = S.Source(client(tmp_path, Hide(inner, hidden)), NAMES[:3], mode=mode, start=START)
    runner = S.Runner(eng, src, poll_s=30, max_s=900, head_file=tmp_path / 'HEAD.json', wall=clock.wall,
                      mono_ns=clock.mono_ns, sleep=clock.sleep)
    if not catchup:
        monkeypatch.setattr(runner, '_catchup', lambda *a: None)
    return runner.run(), eng.journal.records


def broken(rec, pool):
    return [r for r in rec if r['kind'] == 'G0' and r['pool'] == pool and E.BROKEN in r['reasons']]


def test_a_transaction_the_polls_never_list_is_caught_up_once_and_g0_stays_admitted(tmp_path, monkeypatch):
    txs = feed(START + HOUR)
    hidden = lagged(txs, NAMES[0], START + 400, START + 900)
    # the precondition: without the catch-up, the pool is excluded for a broken reserves chain
    out, rec = catchup_run(tmp_path / 'off', txs, hidden, catchup=False, monkeypatch=monkeypatch)
    assert out == 'planned_end_of_process' and broken(rec, NAMES[0])
    assert hidden[0] not in {r['signature'] for r in rec if r['kind'] == 'RECEIVED'}
    # with it: one CATCHUP, the transaction joins the journal (catch-up index source), G-0 never refuses
    out, rec = catchup_run(tmp_path / 'on', txs, hidden)
    assert out == 'planned_end_of_process' and not broken(rec, NAMES[0])
    cu = [r for r in rec if r['kind'] == 'CATCHUP']
    assert [(r['pool'], r['outcome'], r['signatures']) for r in cu] == [(NAMES[0], 'found', hidden)]
    got = [r for r in rec if r['kind'] == 'RECEIVED' and r['signature'] == hidden[0]]
    assert len(got) == 1 and got[0]['index_source'] == 'gsfa_rank_catchup' and got[0]['transaction_index'] == 0
    assert got[0]['step'] == [r for r in rec if r['kind'] == 'STEP' and r['seq'] > cu[0]['seq']][0]['step']
    calls = [json.loads(x) for x in (tmp_path / 'on' / 'calls.jsonl').read_text().splitlines()]
    probe = RPC.sha([NAMES[0], dict(limit=S.CATCHUP_GSFA_LIMIT, commitment='confirmed')])
    assert [c['params_sha256'] for c in calls].count(probe) == 1              # ONE catch-up GSFA (1 credit)
    # the replay steps over CATCHUP and reproduces every record
    again = E.resume(pools(), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'on' / 'j',
                     store=tmp_path / 'on' / 's')
    assert not again.journal.replaying and again.n == len([r for r in rec if r['kind'] == 'STEP'])


def test_the_catch_up_refuses_when_the_rank_is_uncertain_too_many_are_missed_or_the_mode_is_gtfa(tmp_path):
    txs = feed(START + HOUR)
    # a hidden transaction in a slot that already holds a delivered one: rank uncertain, the refusal stands
    sigs = same_slot(txs, NAMES[0], n=2)
    rows = {r['transaction']['signatures'][0]: r for r in txs[NAMES[0]].values()}
    assert rows[sigs[0]]['slot'] == rows[sigs[1]]['slot']
    out, rec = catchup_run(tmp_path / 'rank', txs, [sigs[1]])
    cu = [r for r in rec if r['kind'] == 'CATCHUP']
    assert [r['outcome'] for r in cu] == ['rank_uncertain'] and broken(rec, NAMES[0])
    assert sigs[1] not in {r['signature'] for r in rec if r['kind'] == 'RECEIVED'}
    # more than 10 missed: nothing added
    many = lagged(txs, NAMES[0], START + 1, START + 1_150, n=S.CATCHUP_MAX_TX + 1)
    out, rec = catchup_run(tmp_path / 'many', txs, many)
    assert [r['outcome'] for r in rec if r['kind'] == 'CATCHUP'][0] == 'too_many_missed:%d' % (S.CATCHUP_MAX_TX + 1)
    # gtfa mode: no catch-up call at all
    src = S.Source(client(tmp_path / 'g', chain(txs, slot=2 * START)), NAMES[:3], mode='gtfa', start=START)
    assert src.catchup(NAMES[0], 10 ** 9) == ([], 'not_in_gtfa_mode')
    assert not (tmp_path / 'g' / 'calls.jsonl').exists()


def test_a_failed_catch_up_restores_the_source_and_is_an_incident(tmp_path):
    txs = feed(START + HOUR)
    hidden = lagged(txs, NAMES[0], START + 400, START + 900)
    out, rec = catchup_run(tmp_path, txs, hidden,
                           transport=lambda t: FailNth(t, 'getTransaction', 1, pool=hidden[0]))
    assert out == 'incident:RpcError' and [r['kind'] for r in rec[-2:]] == ['ERROR', 'STOP']
    assert not [r for r in rec if r['kind'] == 'CATCHUP']
    # the source itself: state restored on failure, and a nothing-found catch-up adds nothing
    fake = chain(txs, slot=2 * (START + HOUR))
    src = S.Source(client(tmp_path / 'x', FailNth(Quiet(fake), 'getTransaction', 2, pool=hidden[0])), NAMES[:3],
                   mode='gsfa_rank', start=START)
    src.fetch()
    slot = next(r['slot'] for r in txs[NAMES[0]].values() if r['transaction']['signatures'][0] == hidden[0])
    src.seen[NAMES[0]].discard(hidden[0])                    # as if never delivered
    src.rank[NAMES[0]].pop(slot)
    before = state(src)
    with pytest.raises(RPC.RpcError):
        src.catchup(NAMES[0], 2 * (START + HOUR))
    assert state(src) == before
    got, outcome = src.catchup(NAMES[0], 2 * (START + HOUR))            # the 3rd getTransaction is served
    assert outcome == 'found' and [r['transaction']['signatures'][0] for r in got] == hidden
    assert src.rank[NAMES[0]][slot] == 1 and hidden[0] in src.seen[NAMES[0]]
    assert src.catchup(NAMES[0], 2 * (START + HOUR)) == ([], 'nothing_found')
    src.seen[NAMES[0]].discard(hidden[0])
    src.rank[NAMES[0]].pop(slot)
    assert src.catchup(NAMES[0], slot - 1) == ([], 'nothing_found')       # after the receipt slot: never
    assert src.catchup(NAMES[0], slot)[1] == 'found'                       # at the receipt slot: yes


# -- 0.1.4: D15, the exhaustive list of called methods (R02 01:36Z / R04 01:34Z) ----------------------------------------
METHODS_FILE = Path(__file__).resolve().parents[2] / 'METHODS_livepaper_v0_1_4.txt'


def test_the_methods_are_exactly_the_published_list():
    published = METHODS_FILE.read_text().split('\n')
    assert published[-1] == '' and published[:-1] == sorted(published[:-1])      # one per line, sorted, final newline
    assert tuple(sorted(S.METHODS)) == tuple(published[:-1])
    assert len(set(S.METHODS)) == len(S.METHODS)


def test_the_code_calls_no_method_outside_the_list():
    """Static: every literal method of a .call(...) / .request(...) / charge(...) in livepaper is in the list, and every
    method of the list is called somewhere. Dynamic: the refusals of the budget and of the transport."""
    import ast
    called = set()
    for f in sorted(Path(S.__file__).parent.glob('*.py')):
        for node in ast.walk(ast.parse(f.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('call', 'request', 'charge') and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                called.add(node.args[0].value)
    assert called == set(S.METHODS)
    with pytest.raises(B.BudgetError, match='method_not_in_livepaper'):
        S.Budget(Path(__import__('tempfile').mkdtemp()) / 'l.json').charge('getMultipleAccounts')
    t = S.LiveTransport.__new__(S.LiveTransport)
    with pytest.raises(RPC.RpcError, match='method_not_in_livepaper'):
        t.request('sendTransaction', [])


class Record:
    def __init__(self, inner):
        self.inner, self.methods = inner, []

    def request(self, method, params):
        self.methods.append(method)
        return self.inner.request(method, params)


def test_both_modes_with_catch_up_call_only_listed_methods(tmp_path):
    txs = feed(START + HOUR)
    hidden = lagged(txs, NAMES[0], START + 400, START + 900)
    seen = set()
    for mode in S.MODES:
        rec = Record(None)
        out, _ = catchup_run(tmp_path / mode, txs, hidden, mode=mode,
                             transport=lambda t, r=rec: (setattr(r, 'inner', t), r)[1])
        assert out == 'planned_end_of_process' and rec.methods and set(rec.methods) <= set(S.METHODS)
        seen |= set(rec.methods)
    assert seen == set(S.METHODS)                     # the two modes and the catch-up use every listed method


class NoneFor:
    """getTransaction answers None (not served yet) for `sig` after its first `after` requests."""
    def __init__(self, inner, sig, after):
        self.inner, self.sig, self.after, self.k = inner, sig, after, 0

    def request(self, method, params):
        if method == 'getTransaction' and params[0] == self.sig:
            self.k += 1
            if self.k > self.after:
                return None
        return self.inner.request(method, params)


def test_a_catch_up_that_fails_after_its_first_transaction_rolls_everything_back(tmp_path):
    txs = feed(START + HOUR)
    two = lagged(txs, NAMES[0], START + 400, START + 1_500, n=2)
    slots = {r['transaction']['signatures'][0]: r['slot'] for r in txs[NAMES[0]].values()}
    for k, wrap in enumerate((lambda f: FailNth(f, 'getTransaction', 2, pool=two[1]),     # 2nd: inside the catch-up
                              lambda f: NoneFor(f, two[1], 1))):
        fake = chain(txs, slot=2 * (START + HOUR))
        src = S.Source(client(tmp_path / str(k), wrap(Quiet(fake))), NAMES[:3], mode='gsfa_rank', start=START)
        src.fetch()
        for s in two:                                          # as if neither had been delivered
            src.seen[NAMES[0]].discard(s)
            src.rank[NAMES[0]].pop(slots[s])
        before = state(src)
        if k == 0:
            with pytest.raises(RPC.RpcError):
                src.catchup(NAMES[0], 2 * (START + HOUR))
        else:
            assert src.catchup(NAMES[0], 2 * (START + HOUR)) == ([], 'not_served')
        assert state(src) == before                            # the FIRST caught-up transaction is rolled back too
