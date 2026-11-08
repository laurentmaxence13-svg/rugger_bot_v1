"""Offline tests of the bounded window backfill (fake HTTP opener, no network).

The fake chain replays the three certified SOL pool archives of T-0007
(tests/fixtures/launchlab_sol_pools, 173 signatures, 59 failed) through the real
JsonRpc client, so request building, metering and parsing are all exercised.
"""
from fractions import Fraction
import collections
import gzip
import hashlib
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
    with pytest.raises(bf.BackfillError, match='entry_cutoff_gap_slots_below_162'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'p1', entry_cutoff_gap_slots=161)
    with pytest.raises(bf.BackfillError, match='entry_cutoff_gap_slots_below_162'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'p0', entry_cutoff_gap_slots=160)   # the P0 gap
    with pytest.raises(bf.BackfillError, match='entry_cutoff_gap_slots_below_162'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'pa', entry_cutoff_gap_slots=79)    # old 400 ms value
    with pytest.raises(bf.BackfillError, match='window_shorter_than_entry_cutoff_gap'):
        bx.export_pools(tmp_path / 'w', tmp_path / 'p2', entry_cutoff_gap_slots=SLOT_MAX - SLOT_MIN)
    exact = bx.export_pools(tmp_path / 'w', tmp_path / 'p3', entry_cutoff_gap_slots=162)
    assert exact['window_slot_max'] - exact['entry_cutoff_slot'] == 162


def test_l1_minimum_gap_covers_the_exit_horizon_at_the_measured_slot_floor():
    # R02 C2 via R01 and R02's C1 decision (2026-11-07): the gap must hold the 30 s exit horizon
    # plus the entry and exit latency even if every slot lasts only the prudent short-horizon
    # floor (190 ms; 200 ms is proven only for windows >= 60 s).
    assert (bx.SLOT_MS_FLOOR, bx.SLOT_MS_FLOOR_SHORT) == (200, 190)
    assert bx.L1_EXIT_HORIZON_MS < 60_000                        # so the short floor applies
    assert bx.MIN_CUTOFF_GAP_SLOTS == 162
    assert (bx.MIN_CUTOFF_GAP_SLOTS - 2 * bx.L1_LATENCY_SLOTS) * bx.SLOT_MS_FLOOR_SHORT >= \
        bx.L1_EXIT_HORIZON_MS
    assert (bx.MIN_CUTOFF_GAP_SLOTS - 1 - 2 * bx.L1_LATENCY_SLOTS) * bx.SLOT_MS_FLOOR_SHORT < \
        bx.L1_EXIT_HORIZON_MS                                     # tight: one slot less fails
    assert bx.DEFAULT_CUTOFF_GAP_SLOTS >= bx.MIN_CUTOFF_GAP_SLOTS
    # The P0 gap (160) holds the revised P0 plan (25 s, latency 4) accepted by R02, not 30 s.
    assert -(-25_000 // bx.SLOT_MS_FLOOR_SHORT) + 2 * 4 <= 160 < bx.MIN_CUTOFF_GAP_SLOTS


def test_sample_plan_uses_the_measured_slot_duration():
    # R01 O2: at 400 ms the plan doubled the seconds (and the grid fetches) of a P0 window.
    window = bf.Window(SOL_POOL, 466226737, 466442736)
    plan = ss.plan_sample(window, bf.COST_PRESETS['public'], expected_tx_per_slot=1.0)
    assert ss.SLOT_MS_MEASURED_P0 == 215
    assert plan['seconds_estimate'] == 216000 * 215 // 1000            # 46 440 s; measured 46 328
    assert abs(plan['seconds_estimate'] - 46328) / 46328 < 0.01


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
from bot.market.launchlab_events import b58encode              # noqa: E402

SOL_POOL = 'SyntheticSoLUsdcPooL1111111111111111111111111'
SOL_VAULT = 'SyntheticSoLVauLt11111111111111111111111111'
USDC_VAULT = 'SyntheticUsdcVauLt1111111111111111111111111'


CPMM = su.SWAP_FILTERS['raydium-cpmm']
OTHER_POOL = 'SomeOtherPooL111111111111111111111111111111'


def _swap_ix(pool_key_index):
    # CPMM_SWAP_ROLES: pool_state 3, input_vault 6, output_vault 7 (keys 1 and 2 = vaults).
    data = sorted(CPMM.discriminators)[0] + bytes(16)
    return {'programIdIndex': 4, 'accounts': [0, 0, 0, pool_key_index, 0, 0, 1, 2],
            'data': b58encode(data)}


def _pool_tx(sig, slot, index, block_time, d_sol, d_usdc, *, err=None, swaps=None,
             other_pool_swaps=0):
    """Synthetic SOL/USDC CPMM transaction; ``swaps`` = swap instructions on the pool."""
    if swaps is None:
        swaps = 1 if (d_sol > 0) != (d_usdc > 0) else 0
    pre_sol, pre_usdc = 1_000 * 10**9, 150_000 * 10**6
    balances = lambda sol, usdc: [                                  # noqa: E731
        {'accountIndex': 1, 'mint': su.WSOL_MINT, 'owner': SOL_POOL,
         'uiTokenAmount': {'amount': str(sol), 'decimals': 9}},
        {'accountIndex': 2, 'mint': su.USDC_MINT, 'owner': SOL_POOL,
         'uiTokenAmount': {'amount': str(usdc), 'decimals': 6}}]
    return {'slot': slot, 'transactionIndex': index, 'blockTime': block_time,
            'transaction': {'signatures': [sig],
                            'message': {'accountKeys': ['Payer11111111111111111111111111111111111111',
                                                        SOL_VAULT, USDC_VAULT, SOL_POOL, CPMM.program,
                                                        OTHER_POOL],
                                        'instructions': [_swap_ix(3)] * swaps
                                        + [_swap_ix(5)] * other_pool_swaps}},
            'meta': {'err': err, 'preTokenBalances': balances(pre_sol, pre_usdc),
                     'postTokenBalances': balances(pre_sol + d_sol, pre_usdc + d_usdc)}}


# (signature, slot, index, block_time, delta SOL vault, delta USDC vault, err)
POOL_TXS = [
    ('s1', 100, 3, 1000, -10**9, 150 * 10**6, None),          # buys 1 SOL for 150 USDC
    ('s2', 100, 9, 1000, 2 * 10**9, -301 * 10**6, None),      # sells 2 SOL for 301 USDC
    ('s3', 101, 0, 1001, 5 * 10**9, 750 * 10**6, None),       # liquidity add: no price
    ('s4', 102, 4, 1001, -10**9, 151 * 10**6, {'Custom': 1}),  # failed: no price
    ('s5', 103, 1, 1002, -3, 1, None),                        # tiny swap: below the minimum size
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
                               usdc_vault=USDC_VAULT, swap_filter=CPMM,
                               label='SYNTHETIC_TEST_FIXTURE')
    assert document['schema'] == 'rugger-sol-usd-series-v1'
    points = document['points']
    assert [p['signature'] for p in points] == ['s1', 's2']      # no liquidity, failure, dust
    assert [p["price"] for p in points] == [150 * 10**8, 150_50000000]
    keys = {'schema', 'slot', 'transaction_index', 'block_time', 'received_at_ms',
            'publish_time', 'price', 'exponent', 'confidence', 'source_kind', 'source_ref',
            'evidence_sha256', 'signature'}
    for point, (sig, slot, index, block_time, *_rest) in zip(points, [POOL_TXS[i] for i in (0, 1)]):
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
                        sol_vault=SOL_VAULT, usdc_vault=USDC_VAULT, swap_filter=CPMM)
    with pytest.raises(bf.BackfillError, match='vault_mint_or_decimals_mismatch'):
        su.build_series(window, pool=SOL_POOL, sol_vault=USDC_VAULT, usdc_vault=SOL_VAULT, swap_filter=CPMM)
    with pytest.raises(bf.BackfillError, match='series_label'):
        su.build_series(window, pool=SOL_POOL, sol_vault=SOL_VAULT, usdc_vault=USDC_VAULT,
                        label='MADE_UP', swap_filter=CPMM)


def bf_fraction(a, b):
    from fractions import Fraction
    return Fraction(a, b)


def test_series_file_is_referenced_by_the_export_manifest(tmp_path):
    document = su.build_series(_pool_window(tmp_path), pool=SOL_POOL, sol_vault=SOL_VAULT,
                               usdc_vault=USDC_VAULT, swap_filter=CPMM,
                               label='SYNTHETIC_TEST_FIXTURE')
    digests = su.write_series(document, tmp_path / 'series.json.gz')
    _run(tmp_path, FakeChain())
    export = bx.export_pools(tmp_path / 'w', tmp_path / 'pools',
                             sol_usd_series=tmp_path / 'series.json.gz')
    ref = export['sol_usd_series']
    assert ref['file'] == 'sol_usd_series.json.gz' and ref['points'] == 2
    assert ref['file_sha256'] == digests['file_sha256']
    assert ref['canonical_sha256'] == digests['canonical_sha256'] == su.canonical_sha256(document)
    assert ref['source_kinds'] == ['sol_usdc_pool_last_trade']
    assert (tmp_path / 'pools' / 'sol_usd_series.json.gz').read_bytes() == \
        (tmp_path / 'series.json.gz').read_bytes()
    assert su.density(document)['max_gap_s'] == 0


# --------------------------------------------------------------------------- sampled SOL/USDC
from bot.market import sol_usd_sample as ss                    # noqa: E402

_REAL_WRITE_ATOMIC = bf._write_atomic


def _dense_txs(count=100, *, with_index=True):
    """One tx per slot, 2.5 slots per second; every 7th a liquidity add, every 11th failed."""
    txs = []
    for k in range(count):
        liquidity, failed = k % 7 == 3, k % 11 == 5
        d_sol = 5 * 10**9 if liquidity else -10**9
        d_usdc = 750 * 10**6 if liquidity else (150 + k % 3) * 10**6
        txs.append((f'd{k:03d}', 2000 + k, 0 if with_index else None, 9000 + (k * 2) // 5,
                    d_sol, d_usdc, {'Custom': 1} if failed else None))
    return txs


class DensePool(PoolChain):
    def __init__(self, txs=None, *, strip_index=False):
        super().__init__(txs or _dense_txs())
        self.strip = strip_index
        if strip_index:
            for row in self.rows.values():
                row.pop('transactionIndex')

    def getSignaturesForAddress(self, address, options):
        assert address == SOL_POOL
        order = sorted(self.rows.values(), key=lambda r: r['slot'], reverse=True)
        sigs = [r['signature'] for r in order]
        start = sigs.index(options['before']) + 1 if 'before' in options else 0
        return order[start:start + options['limit']]

    def getTransaction(self, signature, options):
        assert options['maxSupportedTransactionVersion'] == MAX_TX_VERSION
        body = dict(self.bodies[signature])
        if self.strip:
            body.pop('transactionIndex')
        return body


def _sample(tmp_path, chain, *extra, grid='4', caps=('100000', '100000000'), out='s',
            network=True):
    buf = io.StringIO()
    args = ['sample', '--pool', SOL_POOL, '--sol-vault', SOL_VAULT, '--usdc-vault', USDC_VAULT,
            '--slot-min', '2000', '--slot-max', '2099', '--grid-seconds', grid,
            '--costs', 'public', '--max-requests', caps[0], '--max-credits', caps[1],
            '--out', str(tmp_path / out), *extra]
    code = cli.main((['sample', '--network'] + args[1:]) if network else args,
                    environ=ENV, opener=chain, out=buf)
    return code, json.loads(buf.getvalue())


def test_sample_dry_run_sends_nothing(tmp_path):
    def forbidden(*_a, **_k):
        raise AssertionError('network used')
    code, report = _sample(tmp_path, forbidden, network=False)
    assert code == 0 and report['requests_sent'] == 0 and not (tmp_path / 's').exists()
    assert report['estimate']['grid_seconds'] == 4 and report['estimate']['credits'] == 0


def test_select_targets_takes_the_last_success_at_each_grid_second():
    rows = [{'signature': 'a', 'blockTime': 10, 'err': None},
            {'signature': 'b', 'blockTime': 11, 'err': None},
            {'signature': 'c', 'blockTime': 13, 'err': {'x': 1}},
            {'signature': 'd', 'blockTime': 13, 'err': None},
            {'signature': 'e', 'blockTime': 19, 'err': None}]
    assert [rows[i]['signature'] for i in ss.select_targets(rows, 4)] == ['a', 'd', 'e']
    assert [rows[i]['signature'] for i in ss.select_targets(rows, 2)] == ['a', 'b', 'd', 'e']
    with pytest.raises(bf.BackfillError, match='grid_seconds_must_be_2_or_4'):
        ss.select_targets(rows, 3)


def test_sample_grid_4_gives_a_dense_enough_series_with_few_calls(tmp_path):
    chain = DensePool()
    code, report = _sample(tmp_path, chain)
    assert code == 0 and report['complete']
    fetched = sum(1 for m, _ in chain.calls if m == 'getTransaction')
    sampling = report['sampling']
    assert sampling['grid_seconds'] == 4 and fetched == sampling['fetched']
    assert fetched < 100 // 3                                  # far fewer than the 100 bodies
    document = su.build_series(tmp_path / 's', pool=SOL_POOL, sol_vault=SOL_VAULT,
                               usdc_vault=USDC_VAULT, label='SYNTHETIC_TEST_FIXTURE', swap_filter=CPMM)
    assert su.density(document)['max_gap_s'] <= 4
    assert all(p['source_kind'] == 'sol_usdc_pool_last_trade' for p in document['points'])
    four = len(document['points'])
    code, _ = _sample(tmp_path, DensePool(), grid='2', out='s2')
    two = su.build_series(tmp_path / 's2', pool=SOL_POOL, sol_vault=SOL_VAULT,
                          usdc_vault=USDC_VAULT, label='SYNTHETIC_TEST_FIXTURE', swap_filter=CPMM)
    assert code == 0 and len(two['points']) > four and su.density(two)['max_gap_s'] <= 2


def test_sample_steps_back_from_a_non_swap(tmp_path):
    # blockTime = 9000 + (2k)//5: the grid second 9000 + 4m targets d(10m+2); d052 is a
    # liquidity add (52 % 7 == 3), so its grid second must step back to d051.
    rows = [{'signature': s, 'slot': sl, 'blockTime': bt, 'err': e, 'transactionIndex': i}
            for s, sl, i, bt, _ds, _du, e in _dense_txs()]
    targets = [rows[i]['signature'] for i in ss.select_targets(rows, 4)]
    assert targets[:2] == ['d002', 'd012'] and 'd052' in targets
    code, report = _sample(tmp_path, DensePool())
    assert code == 0 and report['sampling']['fallbacks'] >= 1
    stored = {r['signature'] for p in (tmp_path / 's').glob('tx-*.jsonl.gz')
              for r in bf.read_segment(p)}
    assert not {f'd{k:03d}' for k in range(100) if k % 7 == 3} & stored    # no liquidity tx kept
    assert 'd051' in stored and 'd052' not in stored


def test_sample_caps_are_cumulative_and_resume_selects_the_same(tmp_path):
    reference_chain = DensePool()
    _sample(tmp_path, reference_chain, out='ref')
    reference = {r['signature'] for p in (tmp_path / 'ref').glob('tx-*.jsonl.gz')
                 for r in bf.read_segment(p)}
    chain = DensePool()
    # 9 = 5 listing pages + 4 fetches, the smallest cap that affords one whole position (R2).
    code, report = _sample(tmp_path, chain, caps=('9', '100000000'))
    assert code == 3 and report['stopped_by'] == 'request_cap_reached:9' and len(chain.calls) == 9
    code, report = _sample(tmp_path, DensePool(), caps=('1000', '100000000'))
    assert code == 0 and report['complete']
    resumed = {r['signature'] for p in (tmp_path / 's').glob('tx-*.jsonl.gz')
               for r in bf.read_segment(p)}
    assert resumed == reference and report['totals']['duplicate_signatures'] == 0
    ledger = json.loads((tmp_path / 's' / 'spend.json').read_text())
    assert ledger['requests'] == report['budget']['requests']


def _tx_rows(out):
    """Stored bodies in segment order (the order a series build reads them)."""
    manifest = json.loads((out / 'state.json').read_text())
    return [r['signature'] for s in manifest['segments'] if s['kind'] == 'tx'
            for r in bf.read_segment(out / s['path'])]


@pytest.mark.parametrize('cap', [9, 10, 12, 14, 16])
def test_cap_inside_a_batch_keeps_acquired_points_and_resume_has_no_loss_or_duplicate(
        tmp_path, cap):
    # D1 (P0 2026-11-07): the cap hit before the 500-row batch was committed, so the points
    # already acquired were dropped and a resume re-fetched every target. Batches of 500 rows
    # never fill here, which is the P0 situation.
    reference_chain = DensePool()
    code, reference = _sample(tmp_path, reference_chain, out='ref')
    assert code == 0 and reference['complete']
    ref_rows = _tx_rows(tmp_path / 'ref')
    ref_fetches = sum(1 for m, _ in reference_chain.calls if m == 'getTransaction')
    listing = sum(1 for m, _ in reference_chain.calls if m == 'getSignaturesForAddress')
    assert 0 < cap - listing < ref_fetches                    # the cap falls inside the sample

    first = DensePool()
    code, report = _sample(tmp_path, first, caps=(str(cap), '100000000'))
    assert code == 3 and report['stopped_by'] == f'request_cap_reached:{cap}'
    kept = _tx_rows(tmp_path / 's')
    state = json.loads((tmp_path / 's' / 'state.json').read_text())
    assert kept == ref_rows[:len(kept)]                        # acquired points are on disk
    cursor = state['phases']['sample']['cursor']
    assert state['phases']['sample']['done'] is False and cursor >= len(kept) > 0
    assert state['sample_stats']['fetched'] <= cap - listing

    second = DensePool()
    code, report = _sample(tmp_path, second, caps=('100000', '100000000'))
    assert code == 0 and report['complete']
    assert _tx_rows(tmp_path / 's') == ref_rows                # no loss, same order
    assert report['totals']['duplicate_signatures'] == 0
    assert report['sampling'] == reference['sampling']         # counters as if never stopped
    refetched = [o for m, o in second.calls if m == 'getTransaction']
    first_fetched = {o[0] for m, o in first.calls if m == 'getTransaction'}
    assert not set(kept) & {o[0] for o in refetched}           # no kept body is fetched again
    # Only the interrupted position is redone: at most MAX_FALLBACK + 1 repeated fetches.
    assert len(first_fetched & {o[0] for o in refetched}) <= ss.MAX_FALLBACK + 1
    ledger = json.loads((tmp_path / 's' / 'spend.json').read_text())
    assert ledger['requests'] == cap + len(second.calls)


def test_cap_on_the_first_fetch_commits_nothing_and_resumes_from_zero(tmp_path):
    reference_chain = DensePool()
    _sample(tmp_path, reference_chain, out='ref')
    listing = sum(1 for m, _ in reference_chain.calls if m == 'getSignaturesForAddress')
    code, _ = _sample(tmp_path, DensePool(), caps=(str(listing), '100000000'))
    state = json.loads((tmp_path / 's' / 'state.json').read_text())
    assert code == 3 and _tx_rows(tmp_path / 's') == []
    assert state['phases'].get('sample', {'cursor': None})['cursor'] in (None, 0)
    code, report = _sample(tmp_path, DensePool())
    assert code == 0 and report['complete'] and _tx_rows(tmp_path / 's') == _tx_rows(tmp_path / 'ref')


class DiesAfter(DensePool):
    """Persistent transport failure after ``n`` successful getTransaction replies."""

    def __init__(self, n, exc=OSError('connection reset')):
        super().__init__()
        self.n, self.exc, self.served = n, exc, 0

    def __call__(self, request, timeout):
        if json.loads(request.data)['method'] == 'getTransaction':
            if self.served >= self.n:
                raise self.exc
            self.served += 1
        return super().__call__(request, timeout)


@pytest.mark.parametrize('n', [1, 3, 7, 10])
def test_any_failure_inside_the_sample_keeps_acquired_points(tmp_path, n):
    # R02 R1 on 061b210: a persistent transport failure lost the uncommitted batch.
    _, reference = _sample(tmp_path, DensePool(), out='ref')
    ref_rows = _tx_rows(tmp_path / 'ref')
    code, report = _sample(tmp_path, DiesAfter(n))
    assert code == 2
    kept = _tx_rows(tmp_path / 's')
    assert kept and kept == ref_rows[:len(kept)]
    state = json.loads((tmp_path / 's' / 'state.json').read_text())
    assert state['phases']['sample']['done'] is False and state['sample_stats']['fetched'] <= n
    code, report = _sample(tmp_path, DensePool())
    assert code == 0 and report['complete'] and _tx_rows(tmp_path / 's') == ref_rows
    assert report['sampling'] == reference['sampling']
    assert report['totals']['duplicate_signatures'] == 0


def test_keyboard_interrupt_inside_the_sample_keeps_acquired_points(tmp_path):
    ref_chain = DensePool()
    _sample(tmp_path, ref_chain, out='ref')
    with pytest.raises(KeyboardInterrupt):
        _sample(tmp_path, DiesAfter(5, KeyboardInterrupt()))
    kept = _tx_rows(tmp_path / 's')
    assert kept and kept == _tx_rows(tmp_path / 'ref')[:len(kept)]
    code, report = _sample(tmp_path, DensePool())
    assert code == 0 and _tx_rows(tmp_path / 's') == _tx_rows(tmp_path / 'ref')


@pytest.mark.parametrize('headroom', [1, 2, 3])
def test_sample_refuses_a_run_that_cannot_afford_one_position(tmp_path, headroom):
    # R02 R2 on 061b210: the unfinished position is redone in full, so +1 request per resume
    # never progressed. A run with less than MAX_FALLBACK + 1 requests left sends nothing.
    ref_chain = DensePool()
    _sample(tmp_path, ref_chain, out='ref')
    listing = sum(1 for m, _ in ref_chain.calls if m == 'getSignaturesForAddress')
    chain = DensePool()
    code, report = _sample(tmp_path, chain, caps=(str(listing + headroom), '100000000'))
    assert code == 3
    assert report['stopped_by'] == f'sample_headroom_below_one_position:{ss.MAX_FALLBACK + 1}_requests'
    assert not [m for m, _ in chain.calls if m == 'getTransaction']
    resumed = DensePool()                            # the same cap again: nothing more is spent
    code, report = _sample(tmp_path, resumed, caps=(str(listing + headroom), '100000000'))
    assert code == 3 and resumed.calls == []
    code, report = _sample(tmp_path, DensePool(), caps=(str(listing + 4), '100000000'))
    assert report['budget']['requests'] > listing    # one whole position is affordable


def test_sample_headroom_is_also_checked_in_credits(tmp_path):
    ref_chain = DensePool()
    _sample(tmp_path, ref_chain, out='ref')
    listing = sum(1 for m, _ in ref_chain.calls if m == 'getSignaturesForAddress')
    costs = bf.COST_PRESETS['helius-conservative']
    credits = listing * costs['getSignaturesForAddress'] + 3 * costs['getTransaction']
    code, report = _sample(tmp_path, DensePool(), '--costs', 'helius-conservative',
                           caps=('100000', str(credits)))
    assert code == 3 and report['stopped_by'].startswith('sample_headroom_below_one_position:')
    assert report['stopped_by'].endswith('_credits')


def _faulty_writes(monkeypatch, suffix, fail_at, exc):
    """Make the ``fail_at``-th write of a file ending in ``suffix`` raise ``exc``."""
    real, seen = bf._write_atomic, []

    def write(path, data):
        if str(path).endswith(suffix):
            seen.append(path)
            if len(seen) == fail_at:
                raise exc
        return real(path, data)
    monkeypatch.setattr(bf, '_write_atomic', write)
    return seen


@pytest.mark.parametrize('rows_per_segment', [2, 3, 500])
@pytest.mark.parametrize('suffix', ['state.json', '.jsonl.gz'])
@pytest.mark.parametrize('exc', [OSError, KeyboardInterrupt], ids=['oserror', 'interrupt'])
def test_a_failed_commit_never_stores_rows_twice(tmp_path, monkeypatch, rows_per_segment,
                                                 suffix, exc):
    # R02 B1 on 13b5eea: a failure while state.json was written left the new segment in the
    # in-memory state; the stop path committed the same batch again under the next name.
    monkeypatch.setattr(ss, 'SAMPLE_SEGMENT_ROWS', rows_per_segment)
    _, reference = _sample(tmp_path, DensePool(), out='ref')
    ref_rows = _tx_rows(tmp_path / 'ref')
    counted = _faulty_writes(monkeypatch, suffix, 0, exc('never'))
    _sample(tmp_path, DensePool(), out='count')
    total = len(counted)
    assert total >= 2
    for fail_at in range(1, total + 1):
        out = f'f{fail_at}'
        _faulty_writes(monkeypatch, suffix, fail_at, exc('injected'))
        with pytest.raises(exc):                     # a local disk failure is not swallowed
            _sample(tmp_path, DensePool(), out=out)
        monkeypatch.setattr(bf, '_write_atomic', _REAL_WRITE_ATOMIC)
        stored = _tx_rows(tmp_path / out) if (tmp_path / out / 'state.json').exists() else []
        assert len(stored) == len(set(stored)), (fail_at, stored)
        assert stored == ref_rows[:len(stored)], fail_at
        code, report = _sample(tmp_path, DensePool(), out=out)
        assert code == 0 and report['complete'], (fail_at, report.get('stopped_by'))
        assert _tx_rows(tmp_path / out) == ref_rows, fail_at
        assert report['totals']['duplicate_signatures'] == 0
        assert report['sampling'] == reference['sampling'], fail_at


def test_sample_resume_with_another_grid_is_refused(tmp_path):
    _sample(tmp_path, DensePool())
    code, report = _sample(tmp_path, DensePool(), grid='2')
    assert code == 2 and report['error'] == 'resume_sampling_parameters_differ_from_state'


def test_series_without_provider_index_keeps_only_unambiguous_points(tmp_path):
    code, _ = _sample(tmp_path, DensePool(strip_index=True))
    assert code == 0
    document = su.build_series(tmp_path / 's', pool=SOL_POOL, sol_vault=SOL_VAULT,
                               usdc_vault=USDC_VAULT, label='SYNTHETIC_TEST_FIXTURE', swap_filter=CPMM)
    assert document['points'] and all(p['transaction_index'] is None for p in document['points'])
    slots = [p['slot'] for p in document['points']]
    assert slots == sorted(set(slots))                       # one point per slot, strictly sorted


# --------------------------------------------------------------------------- R02 B1 on T-0032
def _single(tx, **kw):
    return su.point_from_transaction(dict(tx, signature='x'), pool=SOL_POOL, sol_vault=SOL_VAULT,
                                     usdc_vault=USDC_VAULT, swap_filter=CPMM, **kw)


def test_round_trip_on_the_pool_is_rejected_as_multi_swap():
    # Two swaps through the pool leave a 1-lamport / 0.01 USDC residue: 10 000 000 USD per SOL.
    rejected = {}
    tx = _pool_tx('r', 10, 0, 100, 1, -10_000, swaps=2)
    assert _single(tx, rejected=rejected) is None and rejected == {'multi_swap': 1}


def test_multi_hop_route_with_one_swap_on_this_pool_is_kept():
    tx = _pool_tx('h', 10, 0, 100, -2 * 10**9, 300 * 10**6, swaps=1, other_pool_swaps=2)
    point = _single(tx)
    assert point is not None and point['price'] == 150 * 10**8


def test_dust_and_missing_swap_instruction_are_rejected_and_counted(tmp_path):
    rejected = {}
    assert _single(_pool_tx('d', 10, 0, 100, -10**6, 150_000), rejected=rejected) is None
    assert _single(_pool_tx('n', 10, 1, 100, -10**9, 150 * 10**6, swaps=0),
                   rejected=rejected) is None
    assert rejected == {'below_min_size': 1, 'no_swap_instruction': 1}
    report = {}
    su.build_series(_pool_window(tmp_path), pool=SOL_POOL, sol_vault=SOL_VAULT,
                    usdc_vault=USDC_VAULT, swap_filter=CPMM, label='SYNTHETIC_TEST_FIXTURE',
                    report=report)
    assert report['accepted'] == 2 and report['candidates'] == 5
    assert report['rejected'] == {'below_min_size': 1, 'failed': 1, 'same_direction': 1}


def test_custom_filter_requires_all_fields():
    with pytest.raises(bf.BackfillError, match='custom_filter_needs'):
        su.swap_filter_from_args('custom', program='P')
    with pytest.raises(bf.BackfillError, match='discriminator_must_be_1_or_8_bytes_hex'):
        su.swap_filter_from_args('custom', program='P', discriminators=['abcd'],
                                 pool_account_index=2)
    built = su.swap_filter_from_args('custom', program='P', discriminators=['00' * 8],
                                     pool_account_index=2, min_sol_lamports=5)
    assert built.pool_account_index == 2 and built.min_sol_lamports == 5


def test_sample_commits_small_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, 'SAMPLE_SEGMENT_ROWS', 3)
    code, report = _sample(tmp_path, DensePool())
    assert code == 0 and report['complete']
    sizes = [json.loads((tmp_path / 's' / 'manifest.json').read_text())['segments']]
    tx_rows = [s['rows'] for s in sizes[0] if s['kind'] == 'tx']
    assert len(tx_rows) > 1 and max(tx_rows) <= 3


# --------------------------------------------------------------------------- T-0034
from bot.market import sol_usd_compare as sc                   # noqa: E402

DEPOSIT = bytes(range(8))                                      # not a swap discriminator


def test_swap_combined_with_a_deposit_on_the_same_pool_is_rejected():
    tx = _pool_tx('c', 10, 0, 100, -2 * 10**9, 300 * 10**6)
    other = {'programIdIndex': 4, 'accounts': [0, 3, 1, 2], 'data': b58encode(DEPOSIT + bytes(8))}
    tx['transaction']['message']['instructions'].append(other)
    rejected = {}
    assert _single(tx, rejected=rejected) is None and rejected == {'other_pool_instruction': 1}
    assert su.pool_instruction_counts(tx, SOL_POOL, CPMM) == (1, 1)


def test_inner_deposit_is_seen_and_aggregator_cpi_is_kept():
    tx = _pool_tx('i', 10, 0, 100, -2 * 10**9, 300 * 10**6)
    tx['meta']['innerInstructions'] = [{'index': 0, 'instructions': [
        {'programIdIndex': 4, 'accounts': [3], 'data': b58encode(DEPOSIT)}]}]
    assert _single(tx) is None                                  # inner withdraw on the pool
    agg = _pool_tx('g', 10, 0, 100, -2 * 10**9, 300 * 10**6, swaps=0)
    keys = agg['transaction']['message']['accountKeys']
    keys.append('AggregatorProgram1111111111111111111111111')
    agg['transaction']['message']['instructions'] = [
        {'programIdIndex': len(keys) - 1, 'accounts': [0, 3, 1, 2], 'data': b58encode(bytes(8))}]
    agg['meta']['innerInstructions'] = [{'index': 0, 'instructions': [_swap_ix(3)]}]
    point = _single(agg)                                        # the CPI swap is the only one
    assert point is not None and point['price'] == 150 * 10**8


def _series(points, *, ref='PoolA', tag='a', received_delay_ms=None):
    """Synthetic series; ``tag`` keeps the evidence of two series disjoint."""
    def received(bt):
        return None if received_delay_ms is None else bt * 1000 + received_delay_ms
    return {'schema': 'rugger-sol-usd-series-v1', 'label': 'SYNTHETIC_TEST_FIXTURE',
            'points': [{'schema': 'rugger-sol-usd-point-v1', 'slot': 1000 + i,
                        'transaction_index': 0, 'block_time': bt, 'received_at_ms': received(bt),
                        'publish_time': None, 'price': price, 'exponent': -8, 'confidence': None,
                        'source_kind': 'sol_usdc_pool_last_trade', 'source_ref': ref,
                        'evidence_sha256': hashlib.sha256(f'{tag}{i}'.encode()).hexdigest(),
                        'signature': f'{tag}{i}'}
                       for i, (bt, price) in enumerate(points)]}


def _pair(seconds=range(5000, 6200), price_b=150 * 10**8):
    a = _series([(t, 150 * 10**8) for t in seconds])
    b = _series([(t, price_b) for t in seconds], ref='PoolB', tag='b')
    return a, b


def _thresholds(**changes):
    # Test values only (the owner validates the real ones before they are frozen).
    doc = {'schema': 'rugger-compare-thresholds-v1', 'max_median': '0.003', 'max_p99': '0.01',
           'min_compared': 1000, 'max_missing_share': '0.01', 'step_seconds': 1, 'window': None}
    doc.update(changes)
    return doc


def _treg_event(payload, *, event_id='T-9001-OWNER-0001', from_agent='OWNER', kind='create'):
    event = {'schema': 'rugger-treg-event-v1', 'event_id': event_id, 'task_id': event_id[:6],
             'seq': 1, 'prev_digest': None, 'from_agent': from_agent, 'type': kind, 'hop': 0,
             'utc': '2026-11-06T18:00:00Z', 'payload': payload}
    event['digest'] = sc.sha256_of(event)
    return event


def _registry(tmp_path, *events):
    path = tmp_path / 'snap.json'
    path.write_text(json.dumps({'schema': 'rugger-treg-snapshot-v1', 'events': list(events)}))
    return path


def _prereg(tmp_path, thresholds=None):
    event = _treg_event({'compare_series_thresholds': thresholds or _thresholds(), 'task': {}})
    return sc.load_preregistration(_registry(tmp_path, event), event['event_id'])


def test_compare_preregistered_pass_fail_and_insufficient(tmp_path):
    doc, ref = _prereg(tmp_path)
    a, b = _pair()
    same = sc.compare(a, b, thresholds=doc, preregistration=ref)
    assert same['verdict'] == 'PASS' and same['failed_checks'] == []
    assert same['seconds']['missing_share'] == '0.000000000'      # no end-of-window artefact
    assert same['preregistration']['event_id'] == 'T-9001-OWNER-0001'
    shifted = sc.compare(_pair(price_b=1485 * 10**7)[0], _pair(price_b=1485 * 10**7)[1],
                         thresholds=doc, preregistration=ref)                      # ~1 %
    assert shifted['verdict'] == 'FAIL' and shifted['failed_checks'] == ['median', 'p99']
    short = _pair(seconds=range(5000, 5500))
    small = sc.compare(*short, thresholds=doc, preregistration=ref)
    assert small['verdict'] == 'INSUFFICIENT' and small['failed_checks'] == ['min_compared']


def test_compare_without_preregistration_never_passes():
    a, b = _pair()
    report = sc.compare(a, b, thresholds=_thresholds())
    assert report['verdict'] == 'NOT_PREREGISTERED' and report['failed_checks'] == []
    assert sc.compare(a, b)['verdict'] == 'NOT_PREREGISTERED'


def test_o1_one_second_in_two_missing_fails_on_coverage(tmp_path):
    # R02 O1: each point of b is usable for exactly one decision second (received 4.4 s
    # after its block second), one second in two. Deviation and count alone would PASS.
    doc, ref = _prereg(tmp_path)
    seconds = range(5000, 9000)
    a = _series([(t, 150 * 10**8) for t in seconds])
    b = _series([(t, 150 * 10**8) for t in seconds if t % 2 == 0], ref='PoolB', tag='b',
                received_delay_ms=4400)
    report = sc.compare(a, b, thresholds=doc, preregistration=ref)
    assert report['checks']['min_compared'] and report['checks']['median'] and report['checks']['p99']
    assert report['verdict'] == 'FAIL' and report['failed_checks'] == ['coverage']
    # Alternating inside the window; the 3-second run is b's start (first usable at 5004).
    assert report['seconds']['compared'] == 2000 and report['seconds']['longest_missing_run'] == 3
    assert Fraction(report['seconds']['missing_share']) > Fraction(49, 100)


def test_o1_a_second_series_that_stops_early_is_missing_on_the_union_window(tmp_path):
    doc, ref = _prereg(tmp_path)
    a = _series([(t, 150 * 10**8) for t in range(5000, 8600)])
    b = _series([(t, 150 * 10**8) for t in range(5000, 6100)], ref='PoolB', tag='b')
    report = sc.compare(a, b, thresholds=doc, preregistration=ref)
    assert report['window_rule'] == 'union_of_usable_spans'
    assert report['seconds']['missing']['b'] > 2400 and report['failed_checks'] == ['coverage']
    late = sc.compare(b, a, thresholds=doc, preregistration=ref)            # order does not matter
    assert late['failed_checks'] == ['coverage']


def test_o2_preregistration_event_is_checked(tmp_path):
    good = _treg_event({'compare_series_thresholds': _thresholds()})
    tampered = json.loads(json.dumps(good))
    tampered['payload']['compare_series_thresholds']['max_p99'] = '0.5'   # digest not updated
    cases = {
        'preregistration_event_digest_mismatch': [tampered],
        'preregistration_must_be_an_owner_create_event': [
            _treg_event({'compare_series_thresholds': _thresholds()}, from_agent='R03')],
        'preregistration_event_not_found_once': [good, good],
    }
    for code, events in cases.items():
        with pytest.raises(bf.BackfillError, match=code):
            sc.load_preregistration(_registry(tmp_path, *events), good['event_id'])
    transition = _treg_event({'compare_series_thresholds': _thresholds()}, kind='transition')
    with pytest.raises(bf.BackfillError, match='owner_create_event'):
        sc.load_preregistration(_registry(tmp_path, transition), transition['event_id'])
    for bad in (_thresholds(max_median=0.003), _thresholds(max_median='1.5'),
                _thresholds(min_compared=0), _thresholds(window={'start_second': 9}),
                {k: v for k, v in _thresholds().items() if k != 'max_missing_share'},
                dict(_thresholds(), extra=1)):
        event = _treg_event({'compare_series_thresholds': bad})
        with pytest.raises(bf.BackfillError, match='threshold'):
            sc.load_preregistration(_registry(tmp_path, event), event['event_id'])
    with pytest.raises(bf.BackfillError, match='not_a_treg_snapshot'):
        path = tmp_path / 'x.json'
        path.write_text(json.dumps({'events': [good]}))
        sc.load_preregistration(path, good['event_id'])


def test_o2_cli_refuses_a_divergent_override_and_uses_the_registry(tmp_path):
    a, b = _pair()
    event = _treg_event({'compare_series_thresholds': _thresholds()})
    snap = _registry(tmp_path, event)
    for name, doc in (('a.json', a), ('b.json', b)):
        (tmp_path / name).write_text(json.dumps(doc))
    base = ['compare-series', '--a', str(tmp_path / 'a.json'), '--b', str(tmp_path / 'b.json'),
            '--registry', str(snap), '--preregistration-event', event['event_id']]
    for extra, code in ((['--max-median', '0.01'], 'max_median'), (['--max-p99', '0.02'], 'max_p99'),
                        (['--min-compared', '10'], 'min_compared'),
                        (['--max-missing-share', '0.5'], 'max_missing_share'),
                        (['--step-seconds', '2'], 'step_seconds'),
                        (['--start-second', '5100'], 'start_second')):
        buf = io.StringIO()
        assert cli.main(base + extra, out=buf) == 2
        assert json.loads(buf.getvalue())['error'] == 'cli_value_differs_from_preregistration:' + code
    buf = io.StringIO()
    assert cli.main(base + ['--max-median', '0.0030', '--report-out', str(tmp_path / 'r.json')],
                    out=buf) == 0                                       # equal value accepted
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['verdict'] == 'PASS' and report['preregistration']['digest'] == event['digest']
    assert report['thresholds']['sha256'] == sc.sha256_of(_thresholds())
    buf = io.StringIO()
    explore = ['compare-series', '--a', str(tmp_path / 'a.json'), '--b', str(tmp_path / 'b.json'),
               '--max-median', '0.003', '--max-p99', '0.01', '--max-missing-share', '0.01',
               '--min-compared', '1000']
    assert cli.main(explore, out=buf) == 4                              # never PASS unregistered
    assert json.loads(buf.getvalue())['verdict'] == 'NOT_PREREGISTERED'
    buf = io.StringIO()
    assert cli.main(base[:5] + ['--registry', str(snap)], out=buf) == 2


def test_o2_registered_window_is_the_only_window(tmp_path):
    window = {'start_second': 5100, 'end_second': 6150}
    doc, ref = _prereg(tmp_path, _thresholds(window=window))
    report = sc.compare(*_pair(), thresholds=doc, preregistration=ref)
    assert report['window_rule'] == 'registered'
    assert (report['seconds']['start'], report['seconds']['end']) == (5100, 6150)
    with pytest.raises(bf.BackfillError, match='window_and_step'):
        sc.compare(*_pair(), thresholds=doc, preregistration=ref, window=(5000, 5050))
    with pytest.raises(bf.BackfillError, match='end_second'):
        sc.reconcile_overrides(sc.parse_thresholds(doc), {'end_second': 6000})


def test_series_that_are_not_independent_fail(tmp_path):
    doc, ref = _prereg(tmp_path)
    a, b = _pair()
    itself = sc.compare(a, a, thresholds=doc, preregistration=ref)
    assert itself['verdict'] == 'FAIL' and itself['failed_checks'] == ['independent']
    assert itself['independence']['identical_documents']
    same_pool = _series([(t, 150 * 10**8) for t in range(5000, 6200)], ref='PoolA', tag='b')
    report = sc.compare(a, same_pool, thresholds=doc, preregistration=ref)
    assert report['failed_checks'] == ['independent']
    assert report['independence']['shared_source_refs'] == ['PoolA']


def test_compare_uses_the_spec_timing_rule():
    # One point at second 100: usable from second 101 (end of its second) to 104 (age 4.4 s).
    a = _series([(100, 150 * 10**8)])
    seen = [s for s in range(99, 107) if sc._Reader(a).at(s * 1000 + 400) is not None]
    assert seen == [101, 102, 103, 104] and sc._Reader(a).span_seconds() == (101, 104)
    b = _series([(t, 150 * 10**8) for t in range(95, 110)], ref='PoolB', tag='b')
    report = sc.compare(a, b, window=(99, 106))
    assert report['seconds']['compared'] == 4 and report['seconds']['missing']['a'] == 4


# --------------------------------------------------------------------------- AMM v4 preset
AMM = su.SWAP_FILTERS['raydium-amm-v4']


def _amm_ix(tag, accounts, size=16):
    return {'programIdIndex': 4, 'accounts': accounts, 'data': b58encode(bytes((tag,)) + bytes(size))}


def _amm_tx(instructions, d_sol=-10**9, d_usdc=150 * 10**6):
    tx = _pool_tx('a', 10, 0, 100, d_sol, d_usdc, swaps=0)
    tx['transaction']['message']['accountKeys'][4] = AMM.program
    tx['transaction']['message']['instructions'] = instructions
    return tx


def _amm_point(tx, rejected=None):
    return su.point_from_transaction(dict(tx, signature='x'), pool=SOL_POOL, sol_vault=SOL_VAULT,
                                     usdc_vault=USDC_VAULT, swap_filter=AMM, rejected=rejected)


V1 = [0, 3, 0, 0, 1, 2] + [0] * 11          # SwapBaseIn without target orders (17): vaults 4/5
V1_TARGET = [0, 3, 0, 0, 0, 1, 2] + [0] * 11  # with the optional target orders (18): vaults 5/6
V2 = [0, 3, 0, 1, 2, 0, 0, 0]                 # SwapBaseInV2: AMM at 1, vaults at 3 and 4


def test_amm_v4_preset_is_pinned_from_the_official_source():
    assert AMM.program == '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8'
    assert AMM.discriminators == frozenset({b'\x09', b'\x0b', b'\x10', b'\x11'})
    assert AMM.pool_account_index == 1 and su.AMM_V4_SWAP_DATA_LEN == 17
    assert su.describe_filter(AMM)['discriminators'] == ['09', '0b', '10', '11']


def test_amm_v4_each_swap_variant_gives_one_point():
    for tag, accounts in ((9, V1), (11, V1), (9, V1_TARGET), (11, V1_TARGET), (16, V2),
                          (17, V2)):
        point = _amm_point(_amm_tx([_amm_ix(tag, accounts)]))
        assert point is not None and point['price'] == 150 * 10**8, tag


def test_amm_v4_rejections():
    cases = {
        'other_pool_instruction': [_amm_ix(9, V1), _amm_ix(3, [0, 3, 0, 0])],   # swap + deposit
        'multi_swap': [_amm_ix(9, V1), _amm_ix(16, V2)],
        'no_swap_instruction': [_amm_ix(9, [0, 0, 0, 3] + [0] * 14)],          # pool not at 1
    }
    for reason, instructions in cases.items():
        rejected = {}
        assert _amm_point(_amm_tx(instructions), rejected) is None and reason in rejected, reason
    rejected = {}                                  # tag 9 with a non-swap layout (9 bytes)
    assert _amm_point(_amm_tx([_amm_ix(9, V1, size=8)]), rejected) is None
    assert su.pool_instruction_counts(_amm_tx([_amm_ix(9, V1, size=8)]), SOL_POOL, AMM) == (0, 1)
    rejected = {}                                  # same minimum size rule as CPMM
    assert _amm_point(_amm_tx([_amm_ix(9, V1)], d_sol=-3, d_usdc=1), rejected) is None
    assert rejected == {'below_min_size': 1}


def test_amm_v4_tags_do_not_change_the_cpmm_preset():
    tx = _pool_tx('c', 10, 0, 100, -10**9, 150 * 10**6)       # real CPMM swap still a point
    assert _single(tx) is not None
    tx['transaction']['message']['instructions'] = [_amm_ix(9, [0, 0, 0, 3] + [0] * 14)]
    assert su.pool_instruction_counts(tx, SOL_POOL, CPMM) == (0, 1)    # 1-byte tag is not CPMM
    custom = su.swap_filter_from_args('custom', program=AMM.program, discriminators=['09'],
                                      pool_account_index=1)
    assert custom.discriminators == frozenset({b'\x09'})
    with pytest.raises(bf.BackfillError, match='1_or_8_bytes'):
        su.swap_filter_from_args('custom', program=AMM.program, discriminators=['0909'],
                                 pool_account_index=1)
    assert su.swap_filter_from_args('raydium-amm-v4').program == AMM.program


def test_prefix_match_uses_the_whole_discriminator_and_refuses_mixed_lengths():
    # R02 O4: same first byte as a CPMM discriminator, different 8 bytes: not a swap.
    disc = sorted(CPMM.discriminators)[0]
    tx = _pool_tx('o', 10, 0, 100, -10**9, 150 * 10**6, swaps=0)
    tx['transaction']['message']['instructions'] = [
        {'programIdIndex': 4, 'accounts': [0, 0, 0, 3], 'data': b58encode(disc[:1] + bytes(7) + bytes(16))}]
    assert su.pool_instruction_counts(tx, SOL_POOL, CPMM) == (0, 1)
    # R02 O1: overlapping prefixes of different lengths are refused for custom filters.
    with pytest.raises(bf.BackfillError, match='share_one_length'):
        su.swap_filter_from_args('custom', program='P', discriminators=['09', '09' + '00' * 7],
                                 pool_account_index=1)


# --------------------------------------------------------------------------- Orca Whirlpool preset
WP = su.SWAP_FILTERS['orca-whirlpool']
_WP_KEYS = ['Payer11111111111111111111111111111111111111', SOL_VAULT, USDC_VAULT, SOL_POOL,
            WP.program, OTHER_POOL, 'Filler1111111111111111111111111111111111111',
            'AggregatorProgram1111111111111111111111111']
_FILL, _POOL_K, _OTHER_K, _AGG = 6, 3, 5, 7


def _wp_ix(disc, pool_at, *, size=24, n_accounts=16, other_at=(), vaults=True):
    """A Whirlpool instruction; the pool key sits at each position in ``pool_at``."""
    accounts = [_FILL] * n_accounts
    rules = dict(WP.vault_positions).get(disc, ())
    for position in pool_at:
        accounts[position] = _POOL_K
        for rule_pool, i, j, _count in rules:      # the vaults of the hop on this pool
            if rule_pool == position and vaults:
                accounts[i], accounts[j] = 1, 2
    for position in other_at:
        accounts[position] = _OTHER_K
    return {'programIdIndex': 4, 'accounts': accounts, 'data': b58encode(disc + bytes(size - 8))}


def _wp_tx(outer, d_sol=-2 * 10**9, d_usdc=180 * 10**6, *, inner=()):
    tx = _pool_tx('w', 10, 0, 100, d_sol, d_usdc, swaps=0)
    tx['transaction']['message']['accountKeys'] = list(_WP_KEYS)
    tx['transaction']['message']['instructions'] = list(outer)
    if inner:
        tx['meta']['innerInstructions'] = [{'index': 0, 'instructions': list(inner)}]
    return tx


def _wp_point(tx, rejected=None):
    return su.point_from_transaction(dict(tx, signature='w'), pool=SOL_POOL, sol_vault=SOL_VAULT,
                                     usdc_vault=USDC_VAULT, swap_filter=WP, rejected=rejected)


def test_whirlpool_discriminators_follow_the_anchor_rule_and_the_pinned_client():
    names = {'swap': su.WHIRLPOOL_SWAP, 'swap_v2': su.WHIRLPOOL_SWAP_V2,
             'two_hop_swap': su.WHIRLPOOL_TWO_HOP_SWAP,
             'two_hop_swap_v2': su.WHIRLPOOL_TWO_HOP_SWAP_V2}
    for name, disc in names.items():
        assert disc == hashlib.sha256(f'global:{name}'.encode()).digest()[:8]
    # ts-sdk/client/src/generated/instructions/*.ts @ cc683ec92acb5e7606caa3d8e514d9383e9c7c11
    assert list(su.WHIRLPOOL_SWAP) == [248, 198, 158, 145, 225, 117, 135, 200]
    assert list(su.WHIRLPOOL_SWAP_V2) == [43, 4, 237, 11, 26, 201, 30, 98]
    assert list(su.WHIRLPOOL_TWO_HOP_SWAP) == [195, 96, 237, 108, 68, 162, 219, 230]
    assert list(su.WHIRLPOOL_TWO_HOP_SWAP_V2) == [186, 143, 209, 29, 254, 2, 194, 117]
    assert WP.program == 'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc'
    assert WP.discriminators == frozenset(names.values())
    assert dict(WP.pool_positions) == {su.WHIRLPOOL_SWAP: {2}, su.WHIRLPOOL_SWAP_V2: {4},
                                       su.WHIRLPOOL_TWO_HOP_SWAP: {2, 3},
                                       su.WHIRLPOOL_TWO_HOP_SWAP_V2: {0, 1}}


@pytest.mark.parametrize('disc,pool_at', [
    (su.WHIRLPOOL_SWAP, (2,)), (su.WHIRLPOOL_SWAP_V2, (4,)),
    (su.WHIRLPOOL_TWO_HOP_SWAP, (2,)), (su.WHIRLPOOL_TWO_HOP_SWAP, (3,)),
    (su.WHIRLPOOL_TWO_HOP_SWAP_V2, (0,)), (su.WHIRLPOOL_TWO_HOP_SWAP_V2, (1,))])
def test_each_whirlpool_swap_variant_on_the_pool_gives_one_point(disc, pool_at):
    tx = _wp_tx([_wp_ix(disc, pool_at, n_accounts=24)])
    assert su.pool_instruction_counts(tx, SOL_POOL, WP) == (1, 0)
    point = _wp_point(tx)
    assert point is not None and point['price'] == 90 * 10**8      # 180 USDC / 2 SOL


@pytest.mark.parametrize('disc,wrong_at', [
    (su.WHIRLPOOL_SWAP, 4), (su.WHIRLPOOL_SWAP_V2, 2), (su.WHIRLPOOL_TWO_HOP_SWAP, 0),
    (su.WHIRLPOOL_TWO_HOP_SWAP_V2, 2)])
def test_pool_at_a_position_that_is_not_the_variants_whirlpool_is_not_a_swap(disc, wrong_at):
    # e.g. a swap_v2 whose account 2 (memo program slot) is the pool: not this pool's swap.
    tx = _wp_tx([_wp_ix(disc, (wrong_at,), n_accounts=24)])
    rejected = {}
    assert su.pool_instruction_counts(tx, SOL_POOL, WP) == (0, 1)
    assert _wp_point(tx, rejected) is None and rejected == {'no_swap_instruction': 1}


def test_two_hop_through_the_pool_twice_is_multi_swap():
    rejected = {}
    tx = _wp_tx([_wp_ix(su.WHIRLPOOL_TWO_HOP_SWAP, (2, 3), n_accounts=24)])
    assert su.pool_instruction_counts(tx, SOL_POOL, WP) == (2, 0)
    assert _wp_point(tx, rejected) is None and rejected == {'multi_swap': 1}


def test_two_hop_with_the_other_hop_on_another_pool_keeps_this_hop():
    tx = _wp_tx([_wp_ix(su.WHIRLPOOL_TWO_HOP_SWAP_V2, (1,), other_at=(0,), n_accounts=24)])
    assert _wp_point(tx)['price'] == 90 * 10**8


def test_aggregator_cpi_swap_v2_is_kept_and_two_swaps_are_rejected():
    agg = {'programIdIndex': _AGG, 'accounts': [0, 3, 1, 2], 'data': b58encode(bytes(8))}
    one = _wp_tx([agg], inner=[_wp_ix(su.WHIRLPOOL_SWAP_V2, (4,))])
    assert _wp_point(one)['price'] == 90 * 10**8
    rejected = {}
    two = _wp_tx([agg], inner=[_wp_ix(su.WHIRLPOOL_SWAP_V2, (4,)), _wp_ix(su.WHIRLPOOL_SWAP, (2,))])
    assert _wp_point(two, rejected) is None and rejected == {'multi_swap': 1}


def test_whirlpool_swap_with_a_liquidity_change_on_the_pool_is_rejected():
    # increase_liquidity runs on the pinocchio fast path but keeps its Anchor discriminator.
    increase = hashlib.sha256(b'global:increase_liquidity').digest()[:8]
    tx = _wp_tx([_wp_ix(su.WHIRLPOOL_SWAP, (2,)), _wp_ix(increase, (1,))])
    rejected = {}
    assert su.pool_instruction_counts(tx, SOL_POOL, WP) == (1, 1)
    assert _wp_point(tx, rejected) is None and rejected == {'other_pool_instruction': 1}


def test_whirlpool_small_wrong_direction_and_mutated_swaps_are_rejected():
    rejected = {}
    assert _wp_point(_wp_tx([_wp_ix(su.WHIRLPOOL_SWAP, (2,))], -10**7, 9 * 10**5),
                     rejected) is None                                   # 0.01 SOL
    assert _wp_point(_wp_tx([_wp_ix(su.WHIRLPOOL_SWAP, (2,))], 2 * 10**9, 180 * 10**6),
                     rejected) is None                                   # both vaults up
    mutated = bytes([su.WHIRLPOOL_SWAP[0]]) + bytes(7)                   # same first byte
    assert _wp_point(_wp_tx([_wp_ix(mutated, (2,))]), rejected) is None
    cpmm = sorted(CPMM.discriminators)[0]                                # other program's swap
    assert _wp_point(_wp_tx([_wp_ix(cpmm, (2,))]), rejected) is None
    assert rejected == {'below_min_size': 1, 'same_direction': 1, 'no_swap_instruction': 2}


def test_whirlpool_swap_on_another_pool_only_gives_no_point():
    rejected = {}
    tx = _wp_tx([_wp_ix(su.WHIRLPOOL_SWAP, (), other_at=(2,))])
    assert su.pool_instruction_counts(tx, SOL_POOL, WP) == (0, 0)
    assert _wp_point(tx, rejected) is None and rejected == {'no_swap_instruction': 1}


def test_existing_presets_and_their_description_are_unchanged():
    # A resume compares the stored description: CPMM and AMM v4 must describe as before.
    # Exception: the vault rules (R02 C-b on 43cc1d1) are new and stricter, so a stored
    # sampling state of an older archive is refused on resume instead of mixing rules.
    for kind in ('raydium-cpmm', 'raydium-amm-v4'):
        described = su.describe_filter(su.swap_filter_from_args(kind))
        assert set(described) == {'program', 'discriminators', 'pool_account_index',
                                  'min_sol_lamports', 'vault_positions'}
    described = su.describe_filter(su.swap_filter_from_args('orca-whirlpool'))
    assert described['pool_positions'] == {su.WHIRLPOOL_SWAP.hex(): [2],
                                           su.WHIRLPOOL_SWAP_V2.hex(): [4],
                                           su.WHIRLPOOL_TWO_HOP_SWAP.hex(): [2, 3],
                                           su.WHIRLPOOL_TWO_HOP_SWAP_V2.hex(): [0, 1]}
    assert su.swap_filter_from_args('orca-whirlpool', min_sol_lamports=5).pool_positions == \
        WP.pool_positions


def test_whirlpool_preset_on_real_p0_transactions():
    # 9 real successful transactions of the Orca SOL/USDC Whirlpool, P0 window (slots
    # 466226737-466442736), fetched 2026-11-07 (getTransactionsForAddress, full).
    path = Path(__file__).parent / 'fixtures' / 'whirlpool_p0_real_9tx.json.gz'
    txs = json.loads(gzip.decompress(path.read_bytes()))
    pool, sol_vault, usdc_vault = ('Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE',
                                   'EUuUbDcafPrmVTD5M6qoJAoyyNbihBhugADAxRMn5he9',
                                   '2WLWEuKDgkDUccTpbwYp1GToYktiSB1cXvreHUwiSUVP')
    seen = collections.Counter()
    for tx in txs:
        rejected = {}
        point = su.point_from_transaction(
            {k: v for k, v in tx.items() if k != '_expect'}, pool=pool, sol_vault=sol_vault,
            usdc_vault=usdc_vault, swap_filter=WP, rejected=rejected)
        expect = tx['_expect']
        if expect.startswith('kept'):
            assert point is not None and 89 * 10**8 < point['price'] < 91 * 10**8
            assert point['slot'] == tx['slot'] and point['block_time'] == tx['blockTime']
        else:
            assert point is None and rejected == {expect: 1}, (tx['signature'], rejected)
        seen[expect] += 1
    assert seen == {'kept_swap': 2, 'kept_swap_v2': 2, 'below_min_size': 2,
                    'same_direction': 2, 'no_vault_balance': 1}


# --------------------------------------------------------------------------- R02 C-b on 43cc1d1
def test_amm_v4_vaults_must_be_at_the_positions_of_the_account_count():
    rejected = {}
    shifted_17 = [0, 3, 0, 0, 0, 1, 2] + [0] * 10           # 17 accounts but vaults at 5/6
    shifted_18 = [0, 3, 0, 0, 1, 2] + [0] * 12              # 18 accounts but vaults at 4/5
    for accounts in (shifted_17, shifted_18, [0, 3, 0, 2, 0, 1, 0, 0]):
        assert _amm_point(_amm_tx([_amm_ix(9, accounts)]), rejected) is None
    assert _amm_point(_amm_tx([_amm_ix(16, [0, 3, 0, 0, 1, 2, 0, 0])]), rejected) is None
    assert rejected == {'vault_position_mismatch': 4}
    swapped = [0, 3, 0, 0, 2, 1] + [0] * 11                 # pc/coin order: same two vaults
    assert _amm_point(_amm_tx([_amm_ix(9, swapped)])) is not None


def test_cpmm_vaults_must_be_the_input_and_output_vaults():
    rejected = {}
    tx = _pool_tx('v', 10, 0, 100, -10**9, 150 * 10**6)
    tx['transaction']['message']['instructions'][0]['accounts'] = [0, 0, 0, 3, 1, 2, 0, 0]
    assert _single(tx, rejected=rejected) is None and rejected == {'vault_position_mismatch': 1}
    tx['transaction']['message']['instructions'][0]['accounts'] = [0, 0, 0, 3, 0, 0, 2, 1]
    assert _single(tx) is not None                            # direction swaps input/output


@pytest.mark.parametrize('disc,pool_at,i,j', [
    (su.WHIRLPOOL_SWAP, 2, 4, 6), (su.WHIRLPOOL_SWAP_V2, 4, 8, 10),
    (su.WHIRLPOOL_TWO_HOP_SWAP, 2, 5, 7), (su.WHIRLPOOL_TWO_HOP_SWAP, 3, 9, 11),
    (su.WHIRLPOOL_TWO_HOP_SWAP_V2, 0, 9, 10), (su.WHIRLPOOL_TWO_HOP_SWAP_V2, 1, 11, 12)])
def test_whirlpool_vaults_must_be_those_of_the_hop_on_the_pool(disc, pool_at, i, j):
    assert _wp_point(_wp_tx([_wp_ix(disc, (pool_at,), n_accounts=24)])) is not None
    rejected = {}
    missing = _wp_ix(disc, (pool_at,), n_accounts=24, vaults=False)
    assert _wp_point(_wp_tx([missing]), rejected) is None
    other_hop = _wp_ix(disc, (pool_at,), n_accounts=24, vaults=False)
    for rule_pool, a, b, _count in dict(WP.vault_positions)[disc]:
        if rule_pool != pool_at:                         # vaults at the OTHER hop's places
            other_hop['accounts'][a], other_hop['accounts'][b] = 1, 2
    if len(dict(WP.vault_positions)[disc]) > 1:
        assert _wp_point(_wp_tx([other_hop]), rejected) is None
    one_vault = _wp_ix(disc, (pool_at,), n_accounts=24)
    one_vault['accounts'][j] = _FILL                     # only the SOL vault is named
    assert _wp_point(_wp_tx([one_vault]), rejected) is None
    assert set(rejected) == {'vault_position_mismatch'}


def test_custom_filters_are_not_vault_checked_and_every_preset_discriminator_has_rules():
    custom = su.swap_filter_from_args('custom', program=CPMM.program,
                                      discriminators=[sorted(CPMM.discriminators)[0].hex()],
                                      pool_account_index=3)
    assert custom.vault_positions == ()
    tx = _pool_tx('c', 10, 0, 100, -10**9, 150 * 10**6)
    tx['transaction']['message']['instructions'][0]['accounts'] = [0, 0, 0, 3]
    assert su.swap_vaults_conform(tx, SOL_POOL, SOL_VAULT, USDC_VAULT, custom)
    assert not su.swap_vaults_conform(tx, SOL_POOL, SOL_VAULT, USDC_VAULT, CPMM)
    for name, preset in su.SWAP_FILTERS.items():
        assert set(dict(preset.vault_positions)) == set(preset.discriminators), name
        for disc, rules in preset.vault_positions:
            assert {rule[0] for rule in rules} <= set(preset.positions_for(disc)), name


def test_cli_export_defaults_to_the_module_gap_and_refuses_the_old_minimum(tmp_path):
    # The CLI used to hard-code 160 ("minimum 79"); it now defers to backfill_export.
    _run(tmp_path, FakeChain())
    buf = io.StringIO()
    code = cli.main(['export', '--out', str(tmp_path / 'w'), '--pools-dir', str(tmp_path / 'd')],
                    out=buf)
    written = json.loads((tmp_path / 'd' / 'MANIFEST.json').read_text())
    assert code == 0 and written['window_slot_max'] - written['entry_cutoff_slot'] == \
        bx.DEFAULT_CUTOFF_GAP_SLOTS == 170
    buf = io.StringIO()
    code = cli.main(['export', '--out', str(tmp_path / 'w'), '--pools-dir', str(tmp_path / 'e'),
                     '--entry-cutoff-gap-slots', '160'], out=buf)
    assert code != 0 and 'entry_cutoff_gap_slots_below_162' in buf.getvalue()
