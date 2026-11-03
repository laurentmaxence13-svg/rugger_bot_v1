#!/usr/bin/env python3
"""Execute one explicit diagnostic plan, never a P3 market acquisition.

Allowed traffic is proxy DNS, one TCP handshake to that configured proxy and
at most three HEAD / calls (no query or market body). No redirects or retry.
An independent parent kills this entire diagnostic child after 23 seconds.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['RUGGER_NO_DOTENV'] = '1'

ORIGINS = ('https://launch-mint-v1.raydium.io/',
           'https://api.mainnet.solana.com/',
           'https://transaction-v1.raydium.io/')


def validate(plan):
    if (type(plan) is not dict or plan.get('schema') != 'p3-010-transport-diagnostic-v1'
            or plan.get('origins') != list(ORIGINS)
            or plan.get('method') != 'HEAD' or plan.get('max_http_requests') != 3
            or plan.get('max_elapsed_seconds') != 25
            or plan.get('child_deadline_seconds') != 23
            or plan.get('market_acquisition') is not False
            or plan.get('stop_on_first_blocking_error') is not True
            or plan.get('redirects') is not False or plan.get('retry') is not False):
        raise ValueError('Exact bounded diagnostic plan required')


async def probe_origins(plan, proxy, recorder):
    from bot.p3.transport import probe_https_origins
    await probe_https_origins(plan['origins'], proxy, recorder)


def child(plan, events):
    from bot.p3.collect import _environment_proxy
    from bot.p3.transport import PhaseRecorder
    with events.open('x', encoding='utf-8') as handle:
        def sink(event):
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False)+'\n')
            handle.flush()
        recorder = PhaseRecorder(sink)
        policy = json.loads(Path('/etc/codex/network-policy.json').read_text())
        proxies = [_environment_proxy(url) for url in ORIGINS]
        if (not proxies[0] or len(set(proxies)) != 1
                or proxies[0] != policy.get('http_proxy')):
            recorder.emit('diagnostic_stopped', reason='configured_managed_proxy_required')
            return
        proxy = proxies[0]
        parsed = urlsplit(proxy)
        if (parsed.scheme != 'http' or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            recorder.emit('diagnostic_stopped', reason='anonymous_standard_proxy_required')
            return
        ca = ssl.create_default_context()
        recorder.emit('configuration_checked', proxy_matches_managed_policy=True,
            certificate_verification=ca.verify_mode == ssl.CERT_REQUIRED,
            hostname_verification=ca.check_hostname, no_proxy_bypass=True,
            ipv4_ipv6_policy='AF_UNSPEC', credentials_used=False)
        # This resolver operation reaches only the managed proxy hostname.
        recorder.emit('proxy_system_resolver_started')
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port, socket.AF_UNSPEC,
                socket.SOCK_STREAM)
            recorder.emit('proxy_system_resolver_completed', result_count=len(addresses),
                ipv4_count=sum(item[0] == socket.AF_INET for item in addresses),
                ipv6_count=sum(item[0] == socket.AF_INET6 for item in addresses))
            if not addresses:
                recorder.emit('diagnostic_stopped', reason='empty_proxy_resolution')
                return
            # One address only; trying multiple addresses would be a hidden fallback.
            family, kind, protocol, _, address = addresses[0]
            recorder.emit('proxy_tcp_started')
            with socket.socket(family, kind, protocol) as sock:
                sock.settimeout(2)
                sock.connect(address)
            recorder.emit('proxy_tcp_completed')
        except OSError as error:
            recorder.emit('diagnostic_stopped', reason='proxy_resolver_or_tcp_error',
                error_type=type(error).__name__)
            return
        asyncio.run(probe_origins(plan, proxy, recorder))
        recorder.emit('asyncio_cleanup_completed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--watchdog-report', type=Path, required=True)
    parser.add_argument('--network', action='store_true')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (not args.network or args.plan.is_symlink() or args.plan.name.startswith('.env')
            or args.plan.suffix != '.json' or args.events.exists() or args.events.is_symlink()
            or args.watchdog_report.exists() or args.watchdog_report.is_symlink()
            or len({p.resolve() for p in (args.plan,args.events,args.watchdog_report)}) != 3):
        parser.error('Explicit diagnostic opt-in, fixed plan and new separate outputs required')
    plan = json.loads(args.plan.read_text()); validate(plan)
    if args.child:
        child(plan, args.events)
        return 0
    from bot.p3.active_cohort_campaign import run_process_watchdog
    from bot.analyser.artifacts import atomic_write_json
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--network', '--child',
        '--plan', str(args.plan.resolve()), '--events', str(args.events.resolve()),
        '--watchdog-report', str(args.watchdog_report.resolve())]
    result = run_process_watchdog(command, timeout_seconds=23, working_directory=ROOT)
    result['diagnostic_plan'] = plan['schema']
    result['market_acquisition'] = False
    atomic_write_json(args.watchdog_report, result, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps(result))
    return 124 if result['process_deadline_exceeded'] else result['child_exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
