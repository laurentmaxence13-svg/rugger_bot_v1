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
    # The fixture window ends on the pools' last trades: they count as truncated.
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools', include_truncated=True)
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
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools', include_truncated=True)
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
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools', include_truncated=True)
    assert export['skipped'] == {usd_pool: f'quote_not_sol:{usd1}'}
    assert usd_pool not in {p['pool'] for p in export['pools']} and len(export['pools']) == 2
    assert all(p['quote_mint'] == bx.WSOL_MINT for p in export['pools'])


def test_truncated_pools_are_left_out_by_default(tmp_path):
    _run(tmp_path, FakeChain())
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools')
    assert export['pools'] == []
    assert set(export['skipped'].values()) == {'active_near_window_end'}
    flagged = bx.export_pools(tmp_path / 'w', tmp_path / 'p2', include_truncated=True)
    assert all(p['active_near_window_end'] for p in flagged['pools'])


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
