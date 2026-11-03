"""Existing scanner callbacks, not detected-token age, feed operational health."""
import asyncio
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bot.scanner.supervision import ScannerHealth
from bot.analyser import paper_engine as pe
from bot import main as scanner
from test_scanner_entry_integrity import database, state


def lifetime():
    clocks = [1_000_000, 1000]
    health = ScannerHealth(require_observations=True,
        clock_ms=lambda: clocks[0], monotonic_ms=lambda: clocks[1])
    task = SimpleNamespace(done=lambda: False, cancelling=lambda: 0, get_name=lambda: 'child')
    health.tasks.append(task)
    return health, clocks, task


def healthy(health):
    health.observe_rpc(True)
    health.observe_websocket('subscribed')


def test_unknown_startup_and_notification_without_ack_never_establish_health():
    health, clocks, _ = lifetime()
    assert not health.permits_entries()
    health.observe_websocket('notification')
    health.observe_rpc(True)
    assert not health.permits_entries()
    assert 'websocket' not in health.operational_observations()
    health.observe_websocket('subscribed')
    assert health.permits_entries()
    before = health.operational_observations()
    clocks[0] += 1000; clocks[1] += 1000
    assert health.operational_observations() == before  # Inspecting never renews proof.


@pytest.mark.parametrize('clock_index', [0, 1])
@pytest.mark.parametrize('delta', [-1, 120001])
def test_wall_or_monotonic_discontinuity_and_staleness_deny(clock_index, delta):
    health, clocks, _ = lifetime(); healthy(health)
    clocks[clock_index] += delta
    assert not health.services_fresh()
    assert not health.permits_entries()


def test_each_source_must_renew_and_disconnect_or_failed_lifetime_cannot_be_masked():
    health, clocks, _ = lifetime(); healthy(health)
    clocks[0] += 120001; clocks[1] += 120001
    health.observe_websocket('notification')
    assert not health.permits_entries()  # Fresh WS does not manufacture RPC success.
    health.observe_rpc(True)
    assert health.permits_entries()
    health.observe_rpc(False)
    assert not health.permits_entries()
    health.observe_rpc(True);health.observe_websocket('disconnected')
    assert not health.permits_entries()
    health.observe_websocket('notification')
    assert not health.permits_entries()  # Cannot revive a disconnected subscription.
    health.observe_websocket('subscribed')
    assert health.permits_entries()
    health.fail('synthetic permanent failure')
    healthy(health)
    assert not health.permits_entries()
    assert health.operational_observations()['scanner']['state'] == 'unavailable'


def test_live_guard_needs_transport_callbacks_even_with_fresh_sql_and_reports_real_states(tmp_path):
    path = tmp_path/'book.sqlite'
    with closing(database(path)) as con:
        health, clocks, task = lifetime()
        guard = pe._ScannerEntryGuard(path, task, health=health, clock=lambda: 999)
        guard.clock = lambda: 1000
        state(con)
        assert not guard.allows(con)
        healthy(health)
        assert guard.allows(con)
        snapshot = guard.operational_snapshot(con)
        assert snapshot['source_health']['rpc']['healthy'] is True
        assert snapshot['source_health']['websocket']['healthy'] is True
        assert snapshot['source_health']['scanner']['healthy'] is True
        state(con, history='catching_up')
        assert guard.operational_snapshot(con)['allow_new_entries'] is False
        state(con)
        health.observe_websocket('disconnected')
        assert not guard.allows(con)
        assert guard.operational_snapshot(con)['allow_new_entries'] is False


def test_paper_report_persists_internal_health_without_other_source_activity(tmp_path):
    with closing(database()) as con:
        source = {'schema':'rugger-paper-operational-health-v1','allow_new_entries':False,
                  'scope':'internal_callbacks'}
        result = pe.paper_report(con,1000,0,output=tmp_path/'report.json',operational_health=source)
        import json
        assert result['operational_health'] == source
        assert json.loads((tmp_path/'report.json').read_text())['operational_health'] == source


def test_main_actual_wrappers_observe_only_existing_page_transaction_and_stream(tmp_path):
    health, _, _ = lifetime(); health.tasks.clear()
    calls, snapshots = [], []
    primary = RuntimeError('synthetic stop after existing observations')
    settings = SimpleNamespace(db_path=tmp_path/'scanner.sqlite', rpc_url='https://synthetic.invalid',
        ws_url='wss://synthetic.invalid', raydium_launchpad_program_id='program')
    class RPC:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Backfill:
        def __init__(self, store, program, fetch): self.fetch = fetch
        async def run(self):
            await self.fetch('program', {'limit':1})
            await asyncio.Event().wait()
        async def on_state(self, message): pass
    async def rpc(_rpc,_url,_gate,method,params,**kwargs):
        calls.append(method)
        return [] if method=='getSignaturesForAddress' else {'meta':{'err':None}}
    async def stream(*args,on_state,on_failure):
        await on_state({'state':'subscribed'})
        yield {'signature':'synthetic','slot':1}
        await asyncio.Event().wait()
    async def recovery(source,store,fetch,**kwargs):
        try:
            await anext(source)
            await fetch('synthetic')
            snapshots.append(health.operational_observations())
            raise primary
        finally:
            await source.aclose()
    async def run():
        with patch.object(scanner,'get_settings',return_value=settings), \
             patch.object(scanner,'SolanaRPC',RPC), patch.object(scanner,'ProgramBackfill',Backfill), \
             patch.object(scanner,'rpc_json',rpc), patch.object(scanner,'stream_program_logs',stream), \
             patch.object(scanner,'recover_transactions',recovery):
            with pytest.raises(RuntimeError) as raised:
                await scanner.run(health=health)
            assert raised.value is primary
    asyncio.run(run())
    assert sorted(calls)==['getSignaturesForAddress','getTransaction']
    assert snapshots[0]['rpc']['evidence']=='existing_rpc_result'
    assert snapshots[0]['websocket']['evidence']=='existing_subscribed_notification'
    assert snapshots[0]['scanner']['state']=='ready'
    assert health.failed and not health.permits_entries()
