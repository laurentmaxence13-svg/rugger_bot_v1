"""Phase evidence for the anonymous P3 HTTP path; no endpoint fallback or retry.

The proxy resolver needs its own instrumentation: aiohttp does not pass request
TraceConfig callbacks through its internal HTTPS proxy connection. DNS cancellation
cannot terminate a running getaddrinfo thread; the external watchdog remains
mandatory. No exception text, arbitrary hostname, header or body is recorded.
"""
import asyncio
import json
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver


PHASE_TIMEOUTS = dict(total=8, connect=4, sock_connect=3, sock_read=4)


def phase_timeout(original=None, *, remaining=None):
    """Retain a stricter caller/global cap and add explicit stage ceilings."""
    values = dict(PHASE_TIMEOUTS)
    for name in values:
        value = getattr(original, name, None)
        if value is not None and value > 0:
            values[name] = min(values[name], value)
    if remaining is not None:
        if remaining <= 0:
            raise ValueError('Transport deadline exhausted')
        values['total'] = min(values['total'], remaining)
    return aiohttp.ClientTimeout(**values, ceil_threshold=float('inf'))


class PhaseRecorder:
    def __init__(self, sink):
        self.sink = sink
        self.started_ns = time.monotonic_ns()
        self.sequence = 0

    def emit(self, phase, **fields):
        self.sequence += 1
        self.sink(dict(sequence=self.sequence, phase=phase,
            wall_time_ms=time.time_ns() // 1_000_000,
            elapsed_ms=(time.monotonic_ns()-self.started_ns)/1_000_000, **fields))

    def trace_config(self):
        trace = aiohttp.TraceConfig()
        for signal_name, phase in (
                ('on_request_start', 'request_started'),
                ('on_connection_queued_start', 'connection_queued'),
                ('on_connection_create_start', 'connection_started'),
                ('on_connection_create_end', 'connection_ready'),
                ('on_request_headers_sent', 'request_headers_sent'),
                ('on_request_end', 'response_headers_received')):
            async def callback(session, context, params, *, phase=phase):
                fields = {}
                if phase == 'response_headers_received':
                    fields['http_status'] = params.response.status
                self.emit(phase, **fields)
            getattr(trace, signal_name).append(callback)

        async def exception(session, context, params):
            self.emit('request_exception', error_type=type(params.exception).__name__)
        trace.on_request_exception.append(exception)
        return trace


class ObservedResolver(AbstractResolver):
    """Same threaded system resolver as the installed aiohttp, with safe phases."""
    def __init__(self, recorder, *, proxy_host=None, delegate=None):
        self.recorder = recorder
        self.proxy_host = proxy_host
        self.delegate = delegate if delegate is not None else aiohttp.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        role = 'configured_proxy' if host == self.proxy_host else 'endpoint'
        self.recorder.emit('dns_started', host_role=role, family=int(family))
        try:
            result = await self.delegate.resolve(host, port, family)
        except BaseException as error:
            self.recorder.emit('dns_cancelled' if isinstance(error, asyncio.CancelledError)
                else 'dns_failed', host_role=role, error_type=type(error).__name__)
            raise
        self.recorder.emit('dns_completed', host_role=role, result_count=len(result),
            ipv4_count=sum(item['family'] == socket.AF_INET for item in result),
            ipv6_count=sum(item['family'] == socket.AF_INET6 for item in result))
        return result

    async def close(self):
        await self.delegate.close()


def connector(recorder, *, proxy_host=None):
    # family=AF_UNSPEC preserves normal dual-stack resolution. No forced IP,
    # DNS server, certificate relaxation or proxy bypass is introduced.
    return aiohttp.TCPConnector(resolver=ObservedResolver(recorder, proxy_host=proxy_host),
        family=socket.AF_UNSPEC, ssl=True, limit=1)


def disable_retries(session):
    if type(getattr(session, '_retry_connection', None)) is not bool:
        raise ValueError('Unsupported aiohttp retry control')
    session._retry_connection = False


def managed_proxy_routes(origins, *, policy=None):
    """Fail before transport when NO_PROXY/missing routes contradict the plan."""
    from bot.p3.collect import _environment_proxy
    if policy is None:
        policy = json.loads(Path('/etc/codex/network-policy.json').read_text())
    expected = policy.get('http_proxy') if isinstance(policy, dict) else None
    routes = {origin: _environment_proxy(origin) for origin in origins}
    if not expected or not routes or any(value != expected for value in routes.values()):
        raise ValueError('Configured managed proxy required for every registered source')
    parsed = urlsplit(expected)
    if (parsed.scheme != 'http' or not parsed.hostname or not parsed.port
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ValueError('Anonymous standard managed HTTP proxy required')
    return routes


async def probe_https_origins(origins, proxy, recorder):
    """HEAD root only. Callers must validate their fixed diagnostic plan first."""
    limits = aiohttp.ClientTimeout(total=4, connect=3, sock_connect=2,
        sock_read=2, ceil_threshold=float('inf'))
    async with aiohttp.ClientSession(connector=connector(recorder, proxy_host=urlsplit(proxy).hostname),
            trace_configs=[recorder.trace_config()], trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(), timeout=limits) as session:
        disable_retries(session)
        for ordinal, origin in enumerate(origins):
            recorder.emit('diagnostic_head_attempt', ordinal=ordinal, origin=origin)
            try:
                async with session.head(origin, proxy=proxy, allow_redirects=False) as response:
                    recorder.emit('diagnostic_head_response', ordinal=ordinal,
                        http_status=response.status, tls_verification_enabled=True)
                    if response.status not in (200, 204, 404, 405):
                        recorder.emit('diagnostic_stopped', reason='http_blocking_response')
                        return
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as error:
                recorder.emit('diagnostic_stopped', reason='transport_error',
                    error_type=type(error).__name__)
                return
    recorder.emit('diagnostic_completed', origins_with_http_response=len(origins),
        evidence_scope='HTTPS_peer_connectivity_only; no_market_content_or_API_readiness_claim')
