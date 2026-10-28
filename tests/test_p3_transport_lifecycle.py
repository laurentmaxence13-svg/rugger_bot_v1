"""Real transport lifecycle failures with DNS and socket I/O replaced locally.

These tests reproduce a timeout/cleanup mechanism, not the cause of control009.
Every child replaces socket I/O before constructing an aiohttp transport.
"""
import json
import os
import signal
import sys
import textwrap

import pytest

from bot.p3.active_cohort_campaign import run_process_watchdog


pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX process-group watchdog')


def test_blocked_dns_executor_times_out_request_but_needs_external_cleanup_watchdog(tmp_path):
    report = tmp_path / 'committed-before-cleanup.json'
    program = textwrap.dedent('''
        import asyncio,json,socket,sys,time
        from pathlib import Path
        import aiohttp

        report=Path(sys.argv[1]);events=[]
        def record(event):
            events.append(event)
            report.write_text(json.dumps(events))
        def no_socket_io(*args,**kwargs):
            raise AssertionError('Network I/O forbidden in lifecycle regression')
        socket.socket.connect=no_socket_io
        socket.socket.connect_ex=no_socket_io
        socket.socket.sendto=no_socket_io
        def blocked_resolver(*args,**kwargs):
            record('synthetic_proxy_dns_started')
            time.sleep(20)
            return []
        socket.getaddrinfo=blocked_resolver

        async def capture():
            async with aiohttp.ClientSession(trust_env=False) as client:
                client._retry_connection=False
                try:
                    async with client.get(
                        'https://launch-mint-v1.raydium.io/get/list',
                        proxy='http://synthetic-proxy.invalid:8080',
                        timeout=aiohttp.ClientTimeout(total=.1,ceil_threshold=float('inf'))):
                        raise AssertionError('Synthetic DNS must never finish')
                except asyncio.TimeoutError:
                    record('request_timeout_retained')
            record('capture_returned_after_http_session_cleanup')
        asyncio.run(capture())
        record('asyncio_executor_cleanup_finished')
    ''')
    receipt = run_process_watchdog(
        [sys.executable, '-B', '-c', program, str(report)], timeout_seconds=.5)
    assert json.loads(report.read_text()) == [
        'synthetic_proxy_dns_started', 'request_timeout_retained',
        'capture_returned_after_http_session_cleanup']
    assert receipt['process_deadline_exceeded'] is True
    assert receipt['child_exit_code'] == -signal.SIGTERM
    assert receipt['child_execution_count'] == 1
    assert receipt['retry_performed'] is False


def test_watchdog_escalates_when_stalled_child_ignores_termination(tmp_path):
    report = tmp_path / 'retained.json'
    program = textwrap.dedent('''
        import json,signal,socket,sys,time
        from pathlib import Path
        def no_socket_io(*args,**kwargs):
            raise AssertionError('Network I/O forbidden in watchdog regression')
        socket.socket.connect=no_socket_io
        socket.socket.connect_ex=no_socket_io
        socket.socket.sendto=no_socket_io
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        Path(sys.argv[1]).write_text(json.dumps({'capture_closed':True,'requests':0}))
        time.sleep(20)
    ''')
    receipt = run_process_watchdog(
        [sys.executable, '-B', '-c', program, str(report)], timeout_seconds=.3)
    assert json.loads(report.read_text()) == {'capture_closed': True, 'requests': 0}
    assert receipt['process_deadline_exceeded'] is True
    assert receipt['child_exit_code'] == -signal.SIGKILL
    assert receipt['child_execution_count'] == 1
    assert receipt['retry_performed'] is False
