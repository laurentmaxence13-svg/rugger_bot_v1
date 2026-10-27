"""One preregistered, anonymous WSOL-mint RPC read; never a quota certificate.

The probe shares the next experiment's exact RPC alias and transport policy.
It makes one attempt, retains a failure receipt, and never retries or switches
hosts. A successful mint read does not qualify any pool, trade or later request.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

import aiohttp

from bot.p3.campaign import CampaignSession, canonical, digest
from bot.p3.collect import RPC_URL, ReadOnlyPolicyError, _environment_proxy, _rpc, now_ms
from bot.p3.evidence import _publish_new
from bot.p3.launchlab import _mint_state
from bot.p3.quotes import SOL_MINT
from bot.p3.store import CaptureStore

BASE_REVISION = 'fb8584dcf4c0fbbcd7c936169b4f7d7301821098'
_PARAMS = [[SOL_MINT], {'encoding': 'base64', 'commitment': 'finalized'}]


def validate_plan(plan):
    required = {
        'schema': 'p3-rpc-health-once-v1', 'plan_id': 'health-before-007',
        'source_revision': BASE_REVISION, 'source_revision_role': 'base_before_probe',
        'rpc_endpoint': RPC_URL, 'max_requests': 1, 'max_elapsed_ms': 5000,
        'rpc_method': 'getMultipleAccounts', 'addresses': [SOL_MINT],
        'encoding': 'base64', 'commitment': 'finalized', 'retry': False,
        'success_claim': 'one_valid_WSOL_mint_read_at_receipt_not_future_quota',
    }
    if type(plan) is not dict or set(plan) != set(required) | {'registered_at_ms'}:
        raise ValueError('Unsupported RPC health plan schema')
    if any(type(plan[key]) is not type(value) or plan[key] != value
           for key, value in required.items()):
        raise ValueError('Unsupported RPC health plan parameters')
    registered = plan['registered_at_ms']
    if type(registered) is not int or not 0 < registered < now_ms():
        raise ValueError('RPC health plan must precede the read')
    return hashlib.sha256(canonical(plan)).hexdigest()


def _validate_wsol(result):
    if type(result) is not dict or type(result.get('context')) is not dict:
        raise ValueError('Missing RPC account context')
    slot = result['context'].get('slot')
    values = result.get('value')
    if (type(slot) is not int or slot < 0 or type(values) is not list or len(values) != 1
            or type(values[0]) is not dict):
        raise ValueError('Missing WSOL mint at the returned slot')
    mint, _ = _mint_state(values[0], 'health_WSOL_mint')
    if mint['decimals'] != 9:
        raise ValueError('Invalid WSOL mint decimals')
    return slot


async def probe(store, session, plan, *, provenance='live'):
    plan_hash = validate_plan(plan)
    if (session.max_requests != 1 or session.requests_used != 0 or session.rpc_url != RPC_URL):
        raise ReadOnlyPolicyError('The health probe requires a fresh one-attempt alias session')
    start_ns = time.monotonic_ns()
    session._deadline_ns = start_ns + plan['max_elapsed_ms'] * 1_000_000
    def append(kind, **event):
        return store.append(kind, provenance=provenance, **event)
    append('checkpoint', received_at_ms=now_ms(), outcome='registered',
           payload={'plan': plan, 'plan_sha256': plan_hash, 'purpose': 'one_rpc_health_read'})
    healthy, reason, slot = False, 'no_valid_response', None
    try:
        result, received, request_id, outcome = await asyncio.wait_for(
            _rpc(session, append, 'getMultipleAccounts', _PARAMS), timeout=5)
        if outcome == 'observed':
            try:
                slot = _validate_wsol(result)
            except ValueError:
                reason = 'invalid_WSOL_mint_response'
                append('pool_snapshot', received_at_ms=received, request_id=request_id,
                       outcome='rejected', reason=reason,
                       payload={'purpose': 'one_rpc_health_read',
                                'response_sha256': digest(result)})
            else:
                try:
                    append('pool_snapshot', received_at_ms=received, request_id=request_id,
                           source_slot=slot, mint=SOL_MINT, outcome='observed',
                           payload={'purpose': 'one_rpc_health_read',
                                    'requested_addresses': [SOL_MINT], 'raw_rpc_result': result})
                except ValueError:
                    reason = 'unsafe_or_invalid_WSOL_response'
                else:
                    healthy, reason = True, 'valid_WSOL_mint_read'
        else:
            reason = 'source_request_failed'
    except (asyncio.TimeoutError, ReadOnlyPolicyError):
        reason = 'health_deadline_or_policy_exhausted'
    append('checkpoint', received_at_ms=now_ms(), outcome='health_probe_complete',
           payload={'requests_used': session.requests_used, 'healthy_at_receipt': healthy,
                    'reason': reason, 'future_quota_certified': False, 'real_orders_enabled': False})
    requests = store.events(kind='request')
    receipt = requests[-1] if requests else None
    files = ('rpc_health.py', 'campaign.py', 'collect.py', 'launchlab.py')
    return {'schema': 'p3-rpc-health-once-report-v1', 'plan': plan, 'plan_sha256': plan_hash,
            'healthy_at_receipt': healthy, 'reason': reason, 'context_slot': slot,
            'requests_used': session.requests_used,
            'elapsed_ms': (time.monotonic_ns()-start_ns)//1_000_000,
            'request_receipt': receipt, 'tail_hash': store.verify_integrity(),
            'records': len(store.events()), 'wire_retry_disabled': True,
            'future_quota_certified': False, 'other_rpc_methods_certified': False,
            'market_or_trade_qualified': False, 'real_orders_enabled': False,
            'source_sha256': {name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                              for name in files}}


async def _capture(plan, database):
    with CaptureStore(database) as store:
        async with aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport, '_retry_connection', None)) is not bool:
                raise ReadOnlyPolicyError('Unsupported transport retry policy')
            transport._retry_connection = False
            session = CampaignSession(transport, 1, proxy_resolver=_environment_proxy, rpc_url=RPC_URL)
            return await probe(store, session, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', action='store_true')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.network:
        parser.error('Explicit --network is required')
    paths = (args.plan, args.db, args.output)
    if (len({p.resolve() for p in paths}) != len(paths)
            or any(p.exists() or p.is_symlink() for p in (args.db, args.output))
            or args.output.suffix != '.json'):
        parser.error('Use a separate new capture database and new JSON report')
    if args.plan.is_symlink() or args.plan.stat().st_size > 65536:
        parser.error('Unsupported preregistered plan file')
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    report = asyncio.run(_capture(plan, args.db))
    with CaptureStore(args.db, readonly=True) as store:
        if store.verify_integrity() != report['tail_hash']:
            raise ValueError('Closed health journal anchor mismatch')
    report['closed_journal_integrity_verified'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _publish_new(args.output, (json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())
    print(json.dumps({key: report[key] for key in
                      ('healthy_at_receipt', 'reason', 'requests_used', 'future_quota_certified')}))


if __name__ == '__main__':
    main()
