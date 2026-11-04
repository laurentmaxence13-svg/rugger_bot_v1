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
            else:   # failed: fixtures keep no body, synthesize a minimal one
                bodies[sig] = {'slot': row['slot'], 'blockTime': row.get('blockTime'),
                               'transaction': {'signatures': [sig], 'message': {}},
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
