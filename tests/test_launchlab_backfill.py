"""Offline tests of the bounded window backfill (fake HTTP opener, no network).

The fake chain replays the three certified SOL pool archives of T-0007
(tests/fixtures/launchlab_sol_pools, 173 signatures, 59 failed) through the real
JsonRpc client, so request building, metering and parsing are all exercised.
"""
import gzip
import io
import json
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import backfill_cli as cli
from bot.market.collector import MAX_TX_VERSION

FIXTURES = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
ADDRESS = bf.LAUNCHLAB_PROGRAM
SECRET = 'SECRET-KEY-must-never-appear-7f3a'
URL = f'https://rpc.example.test/v1/?api-key={SECRET}'
ENV = {'RUGGER_BACKFILL_RPC_URL': URL}


def _chain():
    rows, bodies = {}, {}
    for path in sorted(FIXTURES.glob('*.json.gz')):
        archive = json.loads(gzip.decompress(path.read_bytes()))
        for row in archive['signatures']:
            sig = row['signature']
            rows[sig] = {'signature': sig, 'slot': row['slot'], 'err': row.get('err'),
                         'blockTime': row.get('blockTime')}
            if sig in archive['transactions']:
                bodies[sig] = archive['transactions'][sig]
            else:   # failed: fixtures keep no body; a minimal one naming the pool account
                bodies[sig] = {'slot': row['slot'], 'blockTime': row.get('blockTime'),
                               'transactionIndex': row.get('transactionIndex'),
                               'transaction': {'signatures': [sig],
                                               'message': {'accountKeys': [archive['pool']]}},
                               'meta': {'err': row['err']}}
    return rows, bodies


ROWS, BODIES = _chain()
SLOT_MIN = min(r['slot'] for r in ROWS.values())
SLOT_MAX = max(r['slot'] for r in ROWS.values())


class FakeChain:
    """Plays the JSON-RPC server behind JsonRpc's ``opener``."""

    def __init__(self, *, drop_from_gsfa=()):
        self.calls, self.urls = [], set()
        self.drop = set(drop_from_gsfa)

    def __call__(self, request, timeout):
        self.urls.add(request.full_url)
        body = json.loads(request.data)
        method, params = body['method'], body['params']
        self.calls.append((method, params))
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1,
                                      'result': getattr(self, method)(*params)}).encode())

    def getSignaturesForAddress(self, address, options):
        assert address == ADDRESS and options['commitment'] == 'finalized'
        order = sorted((r for r in ROWS.values() if r['signature'] not in self.drop),
                       key=lambda r: (r['slot'], r['signature']), reverse=True)
        sigs = [r['signature'] for r in order]
        start = sigs.index(options['before']) + 1 if 'before' in options else 0
        return order[start:start + options['limit']]

    def getTransaction(self, signature, options):
        assert options['maxSupportedTransactionVersion'] == MAX_TX_VERSION
        assert options['commitment'] == 'finalized'
        return BODIES[signature]

    def getTransactionsForAddress(self, address, options):
        assert address == ADDRESS and options['sortOrder'] == 'asc'
        assert options['maxSupportedTransactionVersion'] == MAX_TX_VERSION
        assert options['filters']['status'] == 'any'
        slot = options['filters']['slot']
        order = sorted((r for r in ROWS.values() if slot['gte'] <= r['slot'] <= slot['lte']),
                       key=lambda r: (r['slot'], r['signature']))
        start = int(options.get('paginationToken') or 0)
        page = order[start:start + options['limit']]
        token = str(start + len(page)) if start + len(page) < len(order) else None
        if options['transactionDetails'] == 'full':
            data = [BODIES[r['signature']] for r in page]
        else:
            data = [dict(r, transactionIndex=0, memo=None, confirmationStatus='finalized')
                    for r in page]
        return {'data': data, 'paginationToken': token}


def _run(tmp_path, chain, *extra, caps=('100000', '100000000'), out='w', costs='public'):
    buf = io.StringIO()
    code = cli.main(['run', '--network', '--slot-min', str(SLOT_MIN), '--slot-max', str(SLOT_MAX),
                     '--max-requests', caps[0], '--max-credits', caps[1], '--costs', costs,
                     '--out', str(tmp_path / out), *extra],
                    environ=ENV, opener=chain, out=buf)
    return code, json.loads(buf.getvalue())


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(bf, 'GSFA_PAGE', 25)
    monkeypatch.setattr(bf, 'GTFA_FULL_PAGE', 10)
    monkeypatch.setattr(bf, 'GTFA_SIG_PAGE', 40)


def test_fixture_chain_is_the_certified_pack():
    assert len(ROWS) == 173 and sum(r['err'] is not None for r in ROWS.values()) == 59


def test_dry_run_and_plan_send_nothing(tmp_path):
    def forbidden(*_a, **_k):
        raise AssertionError('network used')
    buf = io.StringIO()
    code = cli.main(['run', '--slot-min', '1', '--slot-max', '9', '--max-requests', '5',
                     '--max-credits', '5', '--out', str(tmp_path / 'w')],
                    environ=ENV, opener=forbidden, out=buf)
    assert code == 0 and json.loads(buf.getvalue())['requests_sent'] == 0
    assert not (tmp_path / 'w').exists()
    buf = io.StringIO()
    assert cli.main(['plan', '--slot-min', '0', '--slot-max', '999', '--expected-tx-per-slot',
                     '2.0', '--costs', 'helius-conservative'], out=buf) == 0
    estimate = json.loads(buf.getvalue())
    assert estimate['expected_transactions'] == 2000
    # Pages shrunk by the autouse fixture: 25 signatures and 10 full transactions per page.
    assert estimate['requests'] == {'getSignaturesForAddress': 80, 'getTransactionsForAddress': 200}
    assert estimate['credits'] == 80 * 10 + 200 * 100


def test_gtfa_window_is_complete_reconciled_and_verifiable(tmp_path):
    chain = FakeChain()
    code, report = _run(tmp_path, chain)
    assert code == 0 and report['complete'] and report['stopped_by'] is None
    assert report['totals'] == {'transactions': 173, 'failed_transactions': 59,
                                'duplicate_signatures': 0, 'bodies_missing': 0}
    assert report['reconciliation']['equal'] and report['reconciliation']['second_method'] == 173
    assert report['budget']['requests'] == len(chain.calls)
    assert {m for m, _ in chain.calls} == {'getTransactionsForAddress', 'getSignaturesForAddress'}
    checked = bf.verify(tmp_path / 'w')
    assert checked['ok'] and checked['complete'] and checked['transactions'] == 173
    stored = {r['signature'] for p in (tmp_path / 'w').glob('tx-*.jsonl.gz')
              for r in bf.read_segment(p)}
    assert stored == set(ROWS)


def test_rpc_bodies_path_fetches_failed_bodies_and_reconciles(tmp_path):
    chain = FakeChain()
    code, report = _run(tmp_path, chain, '--bodies', 'rpc')
    assert code == 0 and report['complete']
    assert report['totals']['transactions'] == 173 and report['totals']['failed_transactions'] == 59
    assert sum(1 for m, _ in chain.calls if m == 'getTransaction') == 173
    assert report['reconciliation']['equal']


def test_window_bounds_are_inclusive_and_respected(tmp_path):
    inner = sorted({r['slot'] for r in ROWS.values()})[1:-1]
    expected = {s for s, r in ROWS.items() if inner[0] <= r['slot'] <= inner[-1]}
    rpc = bf.open_rpc(URL, bf.CreditBudget(10**6, 10**9, bf.COST_PRESETS['public']),
                      opener=FakeChain())
    manifest = bf.Backfill(rpc, bf.Window(ADDRESS, inner[0], inner[-1]), tmp_path / 'w',
                           endpoint='https://rpc.example.test').run()
    assert manifest['complete'] and manifest['totals']['transactions'] == len(expected)
    stored = {r['signature'] for p in (tmp_path / 'w').glob('tx-*.jsonl.gz')
              for r in bf.read_segment(p)}
    assert stored == expected


def test_credit_cap_stops_before_sending_and_resume_completes_without_duplicates(tmp_path):
    chain = FakeChain()
    # helius-conservative: 100 credits per gtfa page; 18 pages needed, cap allows 7.
    code, report = _run(tmp_path, chain, '--segment-pages', '2', caps=('1000', '700'),
                        costs='helius-conservative')
    assert code == 3 and not report['complete']
    assert report['stopped_by'] == 'credit_cap_reached:700'
    assert len(chain.calls) == report['budget']['requests'] == 7      # nothing sent past the cap
    assert report['budget']['credits'] == 700
    state = json.loads((tmp_path / 'w' / 'state.json').read_text())
    committed = sum(s['rows'] for s in state['segments'])
    assert committed == 60                                             # 3 segments of 2 pages
    (tmp_path / 'w' / 'tx-999999.jsonl.gz').write_bytes(b'stray')      # uncommitted leftover
    chain2 = FakeChain()
    code, report = _run(tmp_path, chain2, '--segment-pages', '2', caps=('1000', '100000'),
                        costs='helius-conservative')
    assert code == 0 and report['complete']
    assert report['totals']['transactions'] == 173 and report['totals']['duplicate_signatures'] == 0
    assert not (tmp_path / 'w' / 'tx-999999.jsonl.gz').exists()
    assert report['budget']['requests'] == 7 + len(chain2.calls)       # caps are cumulative
    assert bf.verify(tmp_path / 'w')['ok']


def test_request_cap_counts_retries_before_transport(tmp_path):
    attempts = []

    def flaky(request, timeout):
        attempts.append(1)
        raise OSError('connection reset')
    rpc = bf.open_rpc(URL, bf.CreditBudget(3, 10**6, bf.COST_PRESETS['public']), opener=flaky)
    manifest = bf.Backfill(rpc, bf.Window(ADDRESS, SLOT_MIN, SLOT_MAX), tmp_path / 'w').run()
    assert manifest['stopped_by'] == 'request_cap_reached:3' and len(attempts) == 3


def test_secret_never_written_or_printed(tmp_path):
    chain = FakeChain()
    code, report = _run(tmp_path, chain)
    assert code == 0 and report['endpoint'] == 'https://rpc.example.test'
    assert chain.urls == {URL}                       # the key is used only on the wire
    for path in (tmp_path / 'w').iterdir():
        raw = path.read_bytes()
        if path.suffix == '.gz':
            raw = gzip.decompress(raw)
        assert SECRET.encode() not in raw and b'api-key' not in raw
    assert SECRET not in json.dumps(report)


def test_endpoint_errors_do_not_echo_the_value(tmp_path):
    buf = io.StringIO()
    code = cli.main(['run', '--network', '--slot-min', '1', '--slot-max', '2', '--max-requests',
                     '1', '--max-credits', '1', '--out', str(tmp_path / 'w')],
                    environ={'RUGGER_BACKFILL_RPC_URL': f'http://insecure.test/?api-key={SECRET}'},
                    opener=FakeChain(), out=buf)
    assert code == 2 and 'endpoint_must_be_https' in buf.getvalue()
    assert SECRET not in buf.getvalue()
    buf = io.StringIO()
    code = cli.main(['run', '--network', '--slot-min', '1', '--slot-max', '2', '--max-requests',
                     '1', '--max-credits', '1', '--out', str(tmp_path / 'w')],
                    environ={}, opener=FakeChain(), out=buf)
    assert code == 2 and 'endpoint_variable_missing:RUGGER_BACKFILL_RPC_URL' in buf.getvalue()


def test_reconciliation_failure_marks_the_archive_incomplete(tmp_path):
    missing = sorted(ROWS)[0]
    code, report = _run(tmp_path, FakeChain(drop_from_gsfa={missing}))
    assert code == 3 and not report['complete']
    assert report['reconciliation']['only_in_bodies'] == [missing]


def test_tampered_segment_is_detected(tmp_path):
    _run(tmp_path, FakeChain())
    segment = sorted((tmp_path / 'w').glob('tx-*.jsonl.gz'))[0]
    rows = bf.read_segment(segment)
    rows[0]['slot'] += 1
    segment.write_bytes(gzip.compress(''.join(json.dumps(r) + '\n' for r in rows).encode()))
    checked = bf.verify(tmp_path / 'w')
    assert not checked['ok'] and checked['problems'] == [f'sha256_mismatch:{segment.name}']


def test_only_read_methods_can_be_sent(tmp_path):
    chain = FakeChain()
    rpc = bf.open_rpc(URL, bf.CreditBudget(10, 10, bf.COST_PRESETS['public']), opener=chain)
    for method in ('sendTransaction', 'simulateTransaction', 'requestAirdrop'):
        with pytest.raises(bf.BackfillError, match='method_not_allowed'):
            rpc.call(method, [])
    assert chain.calls == [] and rpc.budget.used == 0


def test_resume_with_different_parameters_is_refused(tmp_path):
    _run(tmp_path, FakeChain())
    code, report = _run(tmp_path, FakeChain(), '--bodies', 'rpc')
    assert code == 2 and report['error'] == 'resume_parameters_differ_from_state'


def test_cost_table_must_price_every_read_method():
    with pytest.raises(bf.BackfillError):
        bf.CreditBudget(1, 1, {'getTransaction': 1})


# --------------------------------------------------------------------------- L1 export
from bot.market import backfill_export as bx               # noqa: E402
from bot.market.collector import PoolArchive, summarize      # noqa: E402


def _fixture_archives():
    manifest = json.loads((FIXTURES / 'MANIFEST.json').read_text())
    return manifest, {p['pool']: PoolArchive.from_json(json.loads(gzip.decompress(
        (FIXTURES / p['file']).read_bytes()))) for p in manifest['pools']}


def test_export_rebuilds_the_certified_pool_archives_for_the_l1_replay(tmp_path):
    code, _ = _run(tmp_path, FakeChain())
    assert code == 0
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools')
    fixture_manifest, fixtures = _fixture_archives()
    assert [p['pool'] for p in export['pools']] == sorted(fixtures) and export['skipped'] == {}
    by_pool = {p['pool']: p for p in fixture_manifest['pools']}
    written = json.loads((tmp_path / 'pools' / 'MANIFEST.json').read_text())
    for entry in written['pools']:
        data = (tmp_path / 'pools' / entry['file']).read_bytes()
        assert entry['file'] == f"{entry['pool']}.json.gz"
        assert entry['sha256'] == bx.hashlib.sha256(data).hexdigest()
        assert entry['quote_mint'] == by_pool[entry['pool']]['quote_mint']      # from creation
        exported = PoolArchive.from_json(json.loads(gzip.decompress(data)))
        original = fixtures[entry['pool']]
        assert exported.account is None and exported.signatures_complete
        assert exported.transactions == original.transactions                  # identical bodies
        assert [(r['signature'], r['err']) for r in exported.signatures] == \
            [(r['signature'], r['err']) for r in original.signatures]          # same order, newest first
        assert entry['signatures'] == by_pool[entry['pool']]['signatures']
        mine, theirs = summarize(exported)[0], summarize(original)[0]
        for key in ('complete', 'trades', 'signatures', 'transactions_missing', 'gaps',
                    'first_block_time', 'last_block_time', 'max_progress_ppm'):
            assert mine[key] == theirs[key], key


def test_export_refuses_an_unverified_or_incomplete_window(tmp_path):
    _run(tmp_path, FakeChain(drop_from_gsfa={sorted(ROWS)[0]}))
    with pytest.raises(bf.BackfillError, match='window_not_verified_or_incomplete'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'pools')


def test_export_skips_pools_created_before_the_window(tmp_path):
    first = min(ROWS.values(), key=lambda r: r['slot'])
    rpc = bf.open_rpc(URL, bf.CreditBudget(10**6, 10**9, bf.COST_PRESETS['public']),
                      opener=FakeChain())
    manifest = bf.Backfill(rpc, bf.Window(ADDRESS, first['slot'] + 1, SLOT_MAX),
                           tmp_path / 'w').run()
    assert manifest['complete']
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools')
    creators_cut = {p for p, a in _fixture_archives()[1].items()
                    if min(r['slot'] for r in a.signatures) <= first['slot']}
    assert creators_cut and set(export['skipped']) == creators_cut
    assert not {p['pool'] for p in export['pools']} & set(export['skipped'])


# --------------------------------------------------------------------------- R02 finding F1
def _down(sent):
    def opener(request, timeout):
        sent.append(1)
        raise OSError('provider down')
    return opener


def test_repeated_failures_never_send_more_than_the_cap(tmp_path):
    sent = []
    for _ in range(4):                               # each run dies on a transport failure
        buf = io.StringIO()
        code = cli.main(['run', '--network', '--slot-min', str(SLOT_MIN), '--slot-max',
                         str(SLOT_MAX), '--max-requests', '7', '--max-credits', '1000000000', '--costs', 'public',
                         '--out', str(tmp_path / 'w')], environ=ENV, opener=_down(sent), out=buf)
        assert code in (2, 3)
    assert len(sent) == 7                            # total sent across all runs == the cap
    ledger = json.loads((tmp_path / 'w' / 'spend.json').read_text())
    assert ledger['requests'] == 7


def test_spend_is_on_disk_before_each_send(tmp_path):
    seen = []

    class Spy(FakeChain):
        def __call__(self, request, timeout):
            ledger = json.loads((tmp_path / 'w' / 'spend.json').read_text())
            seen.append(ledger['requests'])
            return super().__call__(request, timeout)
    _run(tmp_path, Spy())
    assert seen == list(range(1, len(seen) + 1))      # request n was recorded before it left


def test_mid_segment_failure_keeps_the_spend(tmp_path):
    replies = []

    class Dies(FakeChain):
        def __call__(self, request, timeout):
            if len(replies) == 12:
                raise OSError('connection reset')
            replies.append(1)
            return super().__call__(request, timeout)
    code, _ = _run(tmp_path, Dies(), '--segment-pages', '50')
    assert code == 2
    ledger = json.loads((tmp_path / 'w' / 'spend.json').read_text())
    assert ledger['requests'] == 12 + 5               # 12 replies + 1 attempt and 4 retries


def test_resume_with_another_cost_table_is_refused(tmp_path):
    code, _ = _run(tmp_path, FakeChain(), costs='helius-conservative')
    assert code == 0
    code, report = _run(tmp_path, FakeChain(), costs='public')
    assert code == 2 and report['error'] == 'cost_table_differs_from_spend_ledger'


def test_cap_changes_are_recorded_and_spend_stays_cumulative(tmp_path):
    _run(tmp_path, FakeChain(), '--segment-pages', '2', caps=('1000', '700'),
         costs='helius-conservative')
    _run(tmp_path, FakeChain(), '--segment-pages', '2', caps=('1000', '100000'),
         costs='helius-conservative')
    ledger = json.loads((tmp_path / 'w' / 'spend.json').read_text())
    assert ledger['cap_history'] == [{'max_requests': 1000, 'max_credits': 700},
                                     {'max_requests': 1000, 'max_credits': 100000}]
    manifest = json.loads((tmp_path / 'w' / 'manifest.json').read_text())
    assert manifest['budget']['requests'] == ledger['requests']


def test_verify_recomputes_instead_of_trusting_the_manifest(tmp_path):
    _run(tmp_path, FakeChain(drop_from_gsfa={sorted(ROWS)[0]}))
    path = tmp_path / 'w' / 'manifest.json'
    forged = json.loads(path.read_text())
    forged['complete'], forged['reconciliation']['equal'] = True, True
    path.write_text(json.dumps(forged))
    checked = bf.verify(tmp_path / 'w')
    assert not checked['ok'] and not checked['complete']
    assert 'reconciliation_differs_from_segments' in checked['problems']


# --------------------------------------------------------------------------- R02 T-0030 findings
def test_export_keeps_only_sol_quoted_pools_for_l1(tmp_path, monkeypatch):
    _run(tmp_path, FakeChain())
    usd_pool = sorted(_fixture_archives()[1])[0]
    real = bx.creation_quote_mint
    usd1 = 'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB'
    monkeypatch.setattr(bx, 'creation_quote_mint',
                        lambda tx, pool, mint: usd1 if pool == usd_pool else real(tx, pool, mint))
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools')
    assert export['skipped'] == {usd_pool: f'quote_not_sol:{usd1}'}
    assert usd_pool not in {p['pool'] for p in export['pools']} and len(export['pools']) == 2
    assert all(p['quote_mint'] == bx.WSOL_MINT for p in export['pools'])


def test_m1_keeps_pools_active_near_the_end_and_writes_the_window(tmp_path):
    _run(tmp_path, FakeChain())
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools')
    assert len(export['pools']) == 3 and export['skipped'] == {}      # no survival filter
    assert all(p['active_near_window_end'] for p in export['pools'])  # flagged only
    written = json.loads((tmp_path / 'pools' / 'MANIFEST.json').read_text())
    assert written['window_slot_max'] == SLOT_MAX
    assert written['entry_cutoff_slot'] == SLOT_MAX - bx.DEFAULT_CUTOFF_GAP_SLOTS
    assert written['window_slot_max'] - written['entry_cutoff_slot'] >= bx.MIN_CUTOFF_GAP_SLOTS


def test_m1_gap_bounds_are_enforced(tmp_path):
    _run(tmp_path, FakeChain())
    with pytest.raises(bf.BackfillError, match='entry_cutoff_gap_slots_below_79'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'p1', entry_cutoff_gap_slots=78)
    with pytest.raises(bf.BackfillError, match='window_shorter_than_entry_cutoff_gap'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'p2', entry_cutoff_gap_slots=SLOT_MAX - SLOT_MIN)
    exact = bx.export_pools(tmp_path / 'w', tmp_path / 'p3', entry_cutoff_gap_slots=79)
    assert exact['window_slot_max'] - exact['entry_cutoff_slot'] == 79


def test_export_refuses_bodies_without_transaction_index(tmp_path):
    class Plain(FakeChain):
        def getTransaction(self, signature, options):
            body = dict(super().getTransaction(signature, options))
            body.pop('transactionIndex', None)
            return body
    code, _ = _run(tmp_path, Plain(), '--bodies', 'rpc')
    assert code == 0
    with pytest.raises(bf.BackfillError, match='transaction_index_missing_use_gtfa_bodies'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'pools')


def test_quote_mint_requires_the_decoded_base_mint(tmp_path):
    _run(tmp_path, FakeChain())
    pool, archive = sorted(_fixture_archives()[1].items())[0]
    creation = min(archive.transactions.values(), key=lambda t: (t['slot'], t['transactionIndex']))
    with pytest.raises(bf.BackfillError, match='creation_quote_mint_not_found'):
        bx.creation_quote_mint(creation, pool, 'NotTheBaseMint1111111111111111111111111111')


# --------------------------------------------------------------------------- SOL/USD series
from bot.market import sol_usd_collect as su                  # noqa: E402

SOL_POOL = 'SyntheticSoLUsdcPooL1111111111111111111111111'
SOL_VAULT = 'SyntheticSoLVauLt11111111111111111111111111'
USDC_VAULT = 'SyntheticUsdcVauLt1111111111111111111111111'


def _pool_tx(sig, slot, index, block_time, d_sol, d_usdc, *, err=None):
    pre_sol, pre_usdc = 1_000 * 10**9, 150_000 * 10**6
    balances = lambda sol, usdc: [                                  # noqa: E731
        {'accountIndex': 1, 'mint': su.WSOL_MINT, 'owner': SOL_POOL,
         'uiTokenAmount': {'amount': str(sol), 'decimals': 9}},
        {'accountIndex': 2, 'mint': su.USDC_MINT, 'owner': SOL_POOL,
         'uiTokenAmount': {'amount': str(usdc), 'decimals': 6}}]
    return {'slot': slot, 'transactionIndex': index, 'blockTime': block_time,
            'transaction': {'signatures': [sig],
                            'message': {'accountKeys': ['Payer11111111111111111111111111111111111111',
                                                        SOL_VAULT, USDC_VAULT, SOL_POOL]}},
            'meta': {'err': err, 'preTokenBalances': balances(pre_sol, pre_usdc),
                     'postTokenBalances': balances(pre_sol + d_sol, pre_usdc + d_usdc)}}


# (signature, slot, index, block_time, delta SOL vault, delta USDC vault, err)
POOL_TXS = [
    ('s1', 100, 3, 1000, -10**9, 150 * 10**6, None),          # buys 1 SOL for 150 USDC
    ('s2', 100, 9, 1000, 2 * 10**9, -301 * 10**6, None),      # sells 2 SOL for 301 USDC
    ('s3', 101, 0, 1001, 5 * 10**9, 750 * 10**6, None),       # liquidity add: no price
    ('s4', 102, 4, 1001, -10**9, 151 * 10**6, {'Custom': 1}),  # failed: no price
    ('s5', 103, 1, 1002, -3, 1, None),                        # tiny swap, exact fraction
]


class PoolChain(FakeChain):
    def __init__(self, txs=POOL_TXS):
        super().__init__()
        self.bodies = {s: _pool_tx(s, sl, i, bt, ds, du, err=e) for s, sl, i, bt, ds, du, e in txs}
        self.rows = {s: {'signature': s, 'slot': b['slot'], 'err': b['meta']['err'],
                         'blockTime': b['blockTime'], 'transactionIndex': b['transactionIndex']}
                     for s, b in self.bodies.items()}

    def getSignaturesForAddress(self, address, options):
        assert address == SOL_POOL
        order = sorted(self.rows.values(), key=lambda r: (r['slot'], r['transactionIndex']),
                       reverse=True)
        sigs = [r['signature'] for r in order]
        start = sigs.index(options['before']) + 1 if 'before' in options else 0
        return order[start:start + options['limit']]

    def getTransactionsForAddress(self, address, options):
        assert address == SOL_POOL
        slot = options['filters']['slot']
        order = sorted((r for r in self.rows.values() if slot['gte'] <= r['slot'] <= slot['lte']),
                       key=lambda r: (r['slot'], r['transactionIndex']))
        start = int(options.get('paginationToken') or 0)
        page = order[start:start + options['limit']]
        token = str(start + len(page)) if start + len(page) < len(order) else None
        data = [self.bodies[r['signature']] if options['transactionDetails'] == 'full' else r
                for r in page]
        return {'data': data, 'paginationToken': token}


def _pool_window(tmp_path, chain=None):
    rpc = bf.open_rpc(URL, bf.CreditBudget(10**6, 10**9, bf.COST_PRESETS['public']),
                      opener=chain or PoolChain())
    manifest = bf.Backfill(rpc, bf.Window(SOL_POOL, 100, 103), tmp_path / 'sol').run()
    assert manifest['complete']
    return tmp_path / 'sol'


def test_series_points_follow_the_spec_exactly(tmp_path):
    document = su.build_series(_pool_window(tmp_path), pool=SOL_POOL, sol_vault=SOL_VAULT,
                               usdc_vault=USDC_VAULT, label='SYNTHETIC_TEST_FIXTURE')
    assert document['schema'] == 'rugger-sol-usd-series-v1'
    points = document['points']
    assert [p['signature'] for p in points] == ['s1', 's2', 's5']      # no liquidity, no failure
    # s5: 1 micro-USDC for 3 lamports = 333.333... USD per SOL -> 33333333333 at 10^-8.
    assert [p["price"] for p in points] == [150 * 10**8, 150_50000000, 33333333333]
    keys = {'schema', 'slot', 'transaction_index', 'block_time', 'received_at_ms',
            'publish_time', 'price', 'exponent', 'confidence', 'source_kind', 'source_ref',
            'evidence_sha256', 'signature'}
    for point, (sig, slot, index, block_time, *_rest) in zip(points, [POOL_TXS[i] for i in (0, 1, 4)]):
        assert set(point) == keys and point['exponent'] == -8
        assert (point['slot'], point['transaction_index'], point['block_time']) == (slot, index, block_time)
        assert point['source_kind'] == 'sol_usdc_pool_last_trade' and point['source_ref'] == SOL_POOL
        assert point['publish_time'] is None and point['received_at_ms'] is None
        body = PoolChain().bodies[sig]
        assert point['evidence_sha256'] == su.canonical_sha256(body)    # sha256 of the raw tx


def test_series_half_even_rounding_and_refusals(tmp_path):
    assert su._half_even(bf_fraction(5, 2)) == 2 and su._half_even(bf_fraction(7, 2)) == 4
    window = _pool_window(tmp_path)
    with pytest.raises(bf.BackfillError, match='window_address_is_not_the_pool'):
        su.build_series(window, pool='Other1111111111111111111111111111111111111',
                        sol_vault=SOL_VAULT, usdc_vault=USDC_VAULT)
    with pytest.raises(bf.BackfillError, match='vault_mint_or_decimals_mismatch'):
        su.build_series(window, pool=SOL_POOL, sol_vault=USDC_VAULT, usdc_vault=SOL_VAULT)
    with pytest.raises(bf.BackfillError, match='series_label'):
        su.build_series(window, pool=SOL_POOL, sol_vault=SOL_VAULT, usdc_vault=USDC_VAULT,
                        label='MADE_UP')


def bf_fraction(a, b):
    from fractions import Fraction
    return Fraction(a, b)


def test_series_file_is_referenced_by_the_export_manifest(tmp_path):
    document = su.build_series(_pool_window(tmp_path), pool=SOL_POOL, sol_vault=SOL_VAULT,
                               usdc_vault=USDC_VAULT, label='SYNTHETIC_TEST_FIXTURE')
    digests = su.write_series(document, tmp_path / 'series.json.gz')
    _run(tmp_path, FakeChain())
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools',
                             sol_usd_series=tmp_path / 'series.json.gz')
    ref = export['sol_usd_series']
    assert ref['file'] == 'sol_usd_series.json.gz' and ref['points'] == 3
    assert ref['file_sha256'] == digests['file_sha256']
    assert ref['canonical_sha256'] == digests['canonical_sha256'] == su.canonical_sha256(document)
    assert ref['source_kinds'] == ['sol_usdc_pool_last_trade']
    assert (tmp_path / 'pools' / 'sol_usd_series.json.gz').read_bytes() == \
        (tmp_path / 'series.json.gz').read_bytes()
    assert su.density(document)['max_gap_s'] == 2
