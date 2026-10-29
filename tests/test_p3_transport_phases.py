"""Transport phase telemetry is bounded and omits destination/exception secrets."""
import asyncio
import json
import socket
from types import SimpleNamespace

import aiohttp
import pytest

from bot.p3 import transport


def test_phase_timeout_supplies_stage_limits_without_rounding():
    timeout = transport.phase_timeout()
    assert (timeout.total, timeout.connect, timeout.sock_connect, timeout.sock_read) == (8, 4, 3, 4)
    assert timeout.ceil_threshold == float('inf')


def test_phase_timeout_preserves_stricter_caller_and_global_limits():
    original = aiohttp.ClientTimeout(total=2, connect=1, sock_connect=.5, sock_read=.75)
    timeout = transport.phase_timeout(original, remaining=.25)
    assert (timeout.total, timeout.connect, timeout.sock_connect, timeout.sock_read) == (.25, 1, .5, .75)
    assert (original.total, original.connect, original.sock_connect, original.sock_read) == (2, 1, .5, .75)


def test_phase_timeout_does_not_expand_stage_budgets_for_a_lenient_caller():
    original = aiohttp.ClientTimeout(total=100, connect=100, sock_connect=100, sock_read=100)
    timeout = transport.phase_timeout(original, remaining=100)
    assert (timeout.total, timeout.connect, timeout.sock_connect, timeout.sock_read) == (8, 4, 3, 4)


@pytest.mark.parametrize('remaining', [0, -1])
def test_exhausted_global_time_fails_before_transport(remaining):
    with pytest.raises(ValueError, match='deadline exhausted'):
        transport.phase_timeout(remaining=remaining)


class Delegate:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.calls = []
        self.close_count = 0

    async def resolve(self, host, port, family):
        self.calls.append((host, port, family))
        if self.error is not None:
            raise self.error
        return self.result

    async def close(self):
        self.close_count += 1


@pytest.mark.parametrize('proxy', [True, False])
def test_resolver_success_preserves_host_and_dual_stack_results_without_recording_them(proxy):
    host = 'private-host-secret.invalid'
    answers = [dict(host='private-ipv4-address', family=socket.AF_INET),
               dict(host='private-ipv6-address', family=socket.AF_INET6)]
    delegate = Delegate(result=answers)
    events = []
    recorder = transport.PhaseRecorder(events.append)
    resolver = transport.ObservedResolver(recorder,
        proxy_host=host if proxy else 'configured-proxy.invalid', delegate=delegate)

    async def run():
        result = await resolver.resolve(host, 8080, socket.AF_UNSPEC)
        await resolver.close()
        return result

    assert asyncio.run(run()) is answers
    assert delegate.calls == [(host, 8080, socket.AF_UNSPEC)]
    assert delegate.close_count == 1
    assert [event['phase'] for event in events] == ['dns_started', 'dns_completed']
    assert {event['host_role'] for event in events} == {'configured_proxy' if proxy else 'endpoint'}
    assert events[-1]['result_count'] == 2
    assert (events[-1]['ipv4_count'], events[-1]['ipv6_count']) == (1, 1)
    serialized = json.dumps(events)
    assert host not in serialized
    assert 'private-ipv4-address' not in serialized
    assert 'private-ipv6-address' not in serialized


@pytest.mark.parametrize('error,phase', [(OSError('api_key=secret-value'), 'dns_failed'),
                                      (asyncio.CancelledError('private-host-secret'), 'dns_cancelled')])
def test_resolver_failure_and_cancellation_preserve_exception_identity_but_not_text(error, phase):
    events = []
    delegate = Delegate(error=error)
    resolver = transport.ObservedResolver(transport.PhaseRecorder(events.append), delegate=delegate)
    with pytest.raises(type(error)) as raised:
        asyncio.run(resolver.resolve('private-host-secret.invalid', 443, socket.AF_UNSPEC))
    assert raised.value is error
    assert len(delegate.calls) == 1
    assert [event['phase'] for event in events] == ['dns_started', phase]
    assert events[-1]['error_type'] == type(error).__name__
    serialized = json.dumps(events)
    assert 'private-host-secret' not in serialized
    assert 'secret-value' not in serialized
    assert 'api_key' not in serialized


def test_trace_callbacks_emit_only_phase_status_and_error_class():
    events = []
    recorder = transport.PhaseRecorder(events.append)
    trace = recorder.trace_config()
    untrusted = SimpleNamespace(url='https://private.invalid/?api_key=secret',
        headers={'Authorization': 'secret'}, response=SimpleNamespace(status=403),
        exception=OSError('private.invalid api_key=secret'))

    async def callbacks():
        for name in ('on_request_start', 'on_connection_queued_start', 'on_connection_create_start',
                     'on_connection_create_end', 'on_request_headers_sent', 'on_request_end',
                     'on_request_exception'):
            await getattr(trace, name)[0](None, None, untrusted)

    asyncio.run(callbacks())
    assert [event['phase'] for event in events] == ['request_started', 'connection_queued',
        'connection_started', 'connection_ready', 'request_headers_sent',
        'response_headers_received', 'request_exception']
    assert [event['sequence'] for event in events] == list(range(1, 8))
    assert events[-2]['http_status'] == 403
    assert events[-1]['error_type'] == 'OSError'
    assert all(event['wall_time_ms'] > 0 and event['elapsed_ms'] >= 0 for event in events)
    serialized = json.dumps(events)
    assert 'secret' not in serialized and 'private.invalid' not in serialized
    assert 'Authorization' not in serialized


def test_connector_factory_preserves_standard_resolver_dual_stack_and_verified_tls(monkeypatch):
    delegate = Delegate(result=[])
    monkeypatch.setattr(transport.aiohttp, 'ThreadedResolver', lambda: delegate)
    monkeypatch.setattr(transport.aiohttp, 'TCPConnector', lambda **kwargs: kwargs)
    configuration = transport.connector(transport.PhaseRecorder(lambda event: None),
        proxy_host='configured-proxy.invalid')
    assert configuration['family'] == socket.AF_UNSPEC
    assert configuration['ssl'] is True and configuration['limit'] == 1
    assert isinstance(configuration['resolver'], transport.ObservedResolver)
    assert configuration['resolver'].delegate is delegate
    assert configuration['resolver'].proxy_host == 'configured-proxy.invalid'
    assert delegate.calls == []


def test_disable_retries_requires_supported_switch_before_mutating_transport():
    session = SimpleNamespace(_retry_connection=True)
    transport.disable_retries(session)
    assert session._retry_connection is False
    for invalid in (SimpleNamespace(), SimpleNamespace(_retry_connection=1)):
        with pytest.raises(ValueError, match='Unsupported'):
            transport.disable_retries(invalid)
