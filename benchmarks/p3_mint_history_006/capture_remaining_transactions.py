"""Fixed remaining mint-history bodies, two bounded batches, no discovery or retry."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parent
REUSE = Path('/workspace/work/history-control-004/capture_history.py')
spec = importlib.util.spec_from_file_location('history_control_004_frozen', REUSE)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstruct_selection(plan):
    bundles = [h.verify_bundle(Path(p['path']), expected_tail=p['tail_hash'])
               for p in plan['evidence_pins']]
    original, prior4, prior5 = bundles
    page = next(e['payload']['raw_signature_page'] for e in prior4['events']
                if 'raw_signature_page' in e['payload'])
    fetched = {e['signature'] for b in (prior4, prior5) for e in b['events']
               if e['kind'] == 'transaction' and isinstance(e['payload'].get('raw_transaction'), dict)}
    rows = [{'signature': r['signature'], 'slot': r['slot']} for r in page
            if r['err'] is None and plan['creation_slot'] <= r['slot'] <= plan['first_snapshot_slot']
            and r['signature'] != plan['creation_signature'] and r['signature'] not in fetched]
    rows.sort(key=lambda r: (r['slot'], r['signature']))
    if rows != plan['transactions'] or len(rows) != 22 or len({r['signature'] for r in rows}) != 22:
        raise ValueError('Selection differs from the retained historical page and prior captures')
    return bundles


async def capture(plan, commit, plan_hash):
    started = time.monotonic_ns()
    attempted, received, burns, batches = [], [], [], []
    status = 'complete_fixed_remaining_transactions'
    with h.CaptureStore(ROOT/'history.sqlite') as store:
        def append(kind, **event):
            return store.append(kind, provenance='live', **event)
        append('checkpoint', received_at_ms=h.now_ms(), outcome='registered_remaining_history_plan',
               payload={'plan': plan, 'plan_sha256': plan_hash, 'preregistered_commit': commit})
        async with h.aiohttp.ClientSession(trust_env=False, cookie_jar=h.aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport, '_retry_connection', None)) is not bool:
                raise h.ReadOnlyPolicyError('Unsupported retry policy')
            transport._retry_connection = False
            for batch_number, rows in enumerate((plan['transactions'][:20], plan['transactions'][20:]), 1):
                batch_started = time.monotonic_ns()
                allowed = {r['signature'] for r in rows}
                dispatched = set()
                class ExactOnly(h.HistoricalSession):
                    def post(self, url, *, json=None, **kwargs):
                        signature = json.get('params', [None])[0]
                        if (json.get('method') != 'getTransaction' or signature not in allowed
                                or signature in dispatched):
                            raise h.ReadOnlyPolicyError('Only fixed batch signatures once each')
                        dispatched.add(signature)
                        return super().post(url, json=json, **kwargs)
                session = ExactOnly(transport, len(rows), proxy_resolver=h._environment_proxy,
                                    rpc_url=plan['rpc_endpoint'])
                session._deadline_ns = min(batch_started+30_000_000_000, started+60_000_000_000)
                append('checkpoint', received_at_ms=h.now_ms(), outcome='fixed_sub_batch_started',
                       payload={'batch': batch_number, 'transactions': rows, 'max_elapsed_ms': 30000})
                async def run():
                    for row in rows:
                        signature, slot = row['signature'], row['slot']
                        attempted.append(signature)
                        tx, receipt, request, outcome = await h._rpc(session, append, 'getTransaction',
                            [signature, {'encoding':'jsonParsed', 'commitment':'confirmed',
                                         'maxSupportedTransactionVersion':1}])
                        if outcome != 'observed':
                            raise ValueError('First source failure; stop all batches')
                        try:
                            append('transaction', received_at_ms=receipt, source_slot=slot,
                                   signature=signature, request_id=request,
                                   outcome='observed' if tx is not None else 'missing',
                                   payload={'raw_transaction':tx})
                        except ValueError:
                            append('transaction', received_at_ms=receipt, source_slot=slot,
                                   signature=signature, request_id=request, outcome='failed',
                                   reason='unsafe_raw_payload',
                                   payload={'response_sha256':hashlib.sha256(h.canonical(tx)).hexdigest()})
                            raise ValueError('Rejected evidence body; stop all batches')
                        if tx is None or tx.get('slot') != slot or tx.get('meta', {}).get('err') is not None:
                            raise ValueError('Missing, failed or mismatched historical transaction')
                        received.append(signature)
                        burns.extend(h.burns_from(tx, signature))
                try:
                    await asyncio.wait_for(run(), timeout=max(0, (session._deadline_ns-time.monotonic_ns())/1e9))
                except (ValueError, TypeError, KeyError, h.ReadOnlyPolicyError, asyncio.TimeoutError):
                    status = 'stopped_on_first_source_or_evidence_failure_or_deadline'
                batch = {'batch':batch_number, 'requests_used':session.requests_used,
                         'max_requests':len(rows), 'elapsed_ms':(time.monotonic_ns()-batch_started)//1_000_000,
                         'status':status}
                batches.append(batch)
                append('checkpoint', received_at_ms=h.now_ms(), outcome='fixed_sub_batch_closed', payload=batch)
                if status != 'complete_fixed_remaining_transactions':
                    break
        append('checkpoint', received_at_ms=h.now_ms(), outcome='remaining_history_control_closed',
               payload={'status':status, 'requests_used':sum(b['requests_used'] for b in batches),
                        'no_retry':True, 'real_orders_enabled':False})
        tail, records = store.verify_integrity(), len(store.events())
    return {'schema':'p3-remaining-historical-transactions-control-v1', 'status':status,
        'batches':batches, 'requests_used':sum(b['requests_used'] for b in batches),
        'elapsed_ms':(time.monotonic_ns()-started)//1_000_000, 'plan_sha256':plan_hash,
        'preregistered_commit':commit, 'attempted':attempted, 'received_transactions':received,
        'matching_parsed_burns':burns, 'observed_new_burn_sum_atomic':str(sum(int(b['amount_atomic']) for b in burns)),
        'not_received':[r for r in plan['transactions'] if r['signature'] not in received],
        'tail_hash':tail, 'records':records, 'complete_history_claimed':False,
        'reconciliation_certified':False, 'real_orders_enabled':False,
        'economic_verdict':'INSUFFICIENT DATA'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--preregistered-commit')
    parser.add_argument('--expected-plan-sha256')
    args = parser.parse_args()
    if not args.execute or not re.fullmatch(r'[0-9a-f]{40}', args.preregistered_commit or ''):
        parser.error('Explicit execution and preregistered commit required')
    plan = json.loads((ROOT/'protocol.json').read_text())
    plan_hash = hashlib.sha256(h.canonical(plan)).hexdigest()
    if (plan_hash != args.expected_plan_sha256 or digest(Path(__file__)) != plan['script_sha256']
            or digest(REUSE) != plan['reused_script_sha256']):
        raise ValueError('Frozen plan or script hash mismatch')
    for path, expected in plan['imported_module_sha256'].items():
        if digest(h.REPO/path) != expected:
            raise ValueError('Frozen capture module changed')
    reconstruct_selection(plan)
    if any((ROOT/p).exists() for p in ['history.sqlite','result.json','evidence']):
        raise ValueError('Already used run paths; no repeat allowed')
    result = asyncio.run(capture(plan, args.preregistered_commit, plan_hash))
    manifest = h.export_capture(ROOT/'history.sqlite', ROOT/'evidence', run_id='mint_history_006',
        source_revision=plan['source_revision'], plan_sha256=plan_hash,
        completeness={'complete_raw_replay':False, 'scope':'22_fixed_remaining_page_transactions_two_batches',
                      'signatures_fixed_before_reads':True, 'independent_history_exhaustiveness':False,
                      'sqlite_exported':False})
    restored = h.verify_bundle(ROOT/'evidence', expected_tail=result['tail_hash'])
    assert restored['records'] == result['records'] == manifest['records']
    result['closed_journal_export_and_restore_verified'] = True
    (ROOT/'result.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ['status','requests_used','elapsed_ms','observed_new_burn_sum_atomic']}))

if __name__ == '__main__':
    main()
