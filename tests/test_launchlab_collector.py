"""Offline tests of the budgeted LaunchLab collector (fake RPC, no network)."""
import base64
import io
import json
from pathlib import Path
import struct
import urllib.error

import pytest

from bot.market import collector as col
from bot.market.launchlab_events import LAUNCHLAB_PROGRAM, EventDecodeError, b58decode

FIXTURES = Path(__file__).parent / 'fixtures' / 'launchlab_trades'
POOL = '5BFfimP4k3rZwTDFwP5koAM8UUW8iXKJUydFSLWbc4qU'


def _pool_account_bytes(quote_mint=col.WSOL_MINT):
    data = bytearray(429)
    data[:8] = col.POOL_DISCRIMINATOR
    data[17], data[18], data[19], data[20] = 0, 6, 9, 1
    struct.pack_into('<Q', data, 21, 10**15)
    data[205:237] = b58decode('FCmkzUH9WRQdeTpGcP8cQobgBpb4yTsesL3uNottqwYv')
    data[237:269] = b58decode(quote_mint)
    data[333:365] = b58decode('EnGndrtgy4YbZy41T4CWKekhdXgycgFqUMNMy42TnNuq')
    return bytes(data)


class FakeRpc:
    """Serves fixture transactions; charges a real Budget per call."""

    def __init__(self, max_calls, *, page_size=None, fail_tx=()):
        self.budget = col.Budget(max_calls)
        self.txs = {}
        for path in FIXTURES.glob('*.json'):
            result = json.loads(path.read_text())['result']
            self.txs[result['transaction']['signatures'][0]] = result
        self.order = sorted(self.txs, key=lambda s: self.txs[s]['slot'], reverse=True)
        self.page_size = page_size
        self.fail_tx = set(fail_tx)
        self.calls = []

    def call(self, method, params):
        self.budget.charge()
        self.calls.append(method)
        if method == 'getAccountInfo':
            raw = base64.b64encode(_pool_account_bytes()).decode()
            return {'value': {'owner': LAUNCHLAB_PROGRAM, 'data': [raw, 'base64']}}
        if method == 'getSignaturesForAddress':
            options = params[1]
            start = self.order.index(options['before']) + 1 if 'before' in options else 0
            size = self.page_size or options['limit']
            return [{'signature': s, 'slot': self.txs[s]['slot'], 'err': None}
                    for s in self.order[start:start + size]]
        if method == 'getTransaction':
            if params[0] in self.fail_tx:
                return None
            return self.txs[params[0]]
        raise AssertionError(method)


def test_full_collection_archives_raw_results_and_summarizes(tmp_path, monkeypatch):
    monkeypatch.setattr(col, 'SIGNATURE_PAGE', 3)
    rpc = FakeRpc(50, page_size=3)
    archive = col.collect_pool(rpc, POOL, tmp_path)
    assert len(archive.transactions) == 7 and archive.signatures_complete
    reloaded = col.load_archive(tmp_path, POOL)
    assert reloaded.transactions == archive.transactions
    summary, timeline = col.summarize(reloaded)
    assert summary['trades'] == 7 and summary['quote_is_sol']
    assert summary['transactions_missing'] == 0
    # Fixtures are a sample of the pool, so the chain must not claim completeness.
    assert not summary['complete'] and 'history_starts_mid_curve' in summary['gaps']
    assert rpc.calls.count('getSignaturesForAddress') == 3


def test_budget_exhaustion_keeps_progress_and_resume_does_not_refetch(tmp_path):
    rpc = FakeRpc(4)                       # account + signatures + 2 transactions
    with pytest.raises(col.BudgetExhausted):
        col.collect_pool(rpc, POOL, tmp_path)
    partial = col.load_archive(tmp_path, POOL)
    assert len(partial.transactions) == 2
    assert col.summarize(partial)[0]['transactions_missing'] == 5

    rpc2 = FakeRpc(50)
    archive = col.collect_pool(rpc2, POOL, tmp_path)
    assert len(archive.transactions) == 7
    assert rpc2.calls.count('getTransaction') == 5
    assert 'getAccountInfo' not in rpc2.calls


def test_unavailable_transaction_is_counted_missing_not_dropped(tmp_path):
    rpc = FakeRpc(50)
    missing = rpc.order[0]
    rpc.fail_tx = {missing}
    archive = col.collect_pool(rpc, POOL, tmp_path)
    summary = col.summarize(archive)[0]
    assert summary['transactions_missing'] == 1 and not summary['complete']


def test_incremental_listing_stops_at_known_newest(tmp_path):
    rpc = FakeRpc(50)
    rows, reached = col.fetch_signatures(rpc, POOL, max_pages=5, known_newest=rpc.order[2])
    assert [r['signature'] for r in rows] == rpc.order[:2] and not reached


def test_pool_account_requires_launchlab_discriminator():
    assert col.decode_pool_account(_pool_account_bytes())['mint_quote'] == col.WSOL_MINT
    with pytest.raises(EventDecodeError):
        col.decode_pool_account(bytes(8) + _pool_account_bytes()[8:])
    with pytest.raises(EventDecodeError):
        col.decode_pool_account(_pool_account_bytes()[:400])


# --- JsonRpc ------------------------------------------------------------------

SECRET_URL = 'https://rpc.example/?api-key=SECRET-KEY-123'


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(responses, max_calls=10):
    sleeps = []
    seq = iter(responses)

    def opener(request, timeout):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return _Response(json.dumps(item).encode())

    rpc = col.JsonRpc(SECRET_URL, col.Budget(max_calls), sleep=sleeps.append,
                      clock=lambda: 0.0, opener=opener)
    return rpc, sleeps


def _http(code):
    return urllib.error.HTTPError(SECRET_URL, code, 'x', {}, None)


def test_rate_limit_is_retried_with_backoff_and_charged():
    rpc, sleeps = _client([_http(429), {'result': 42}])
    assert rpc.call('getSlot', []) == 42
    assert rpc.budget.used == 2 and sleeps and max(sleeps) >= 2.0


def test_errors_never_leak_the_endpoint_or_key():
    rpc, _ = _client([_http(401)])
    with pytest.raises(col.RpcError) as info:
        rpc.call('getSlot', [])
    rendered = str(info.value) + repr(info.value) + repr(rpc)
    assert 'SECRET' not in rendered and 'rpc.example' not in rendered
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_rpc_error_payload_and_budget_limit():
    rpc, _ = _client([{'error': {'code': -32015, 'message': 'version'}}])
    with pytest.raises(col.RpcError, match='rpc_error_-32015'):
        rpc.call('getTransaction', [])
    rpc, _ = _client([{'result': 1}] * 3, max_calls=2)
    rpc.call('a', [])
    rpc.call('b', [])
    with pytest.raises(col.BudgetExhausted):
        rpc.call('c', [])
