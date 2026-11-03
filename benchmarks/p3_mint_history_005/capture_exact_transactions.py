"""Five fixed historical transaction reads; no page, discovery, quote or retry."""
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


async def capture(plan, commit, plan_hash):
    started=time.monotonic_ns()
    attempted, received_transactions, burns=[],[],[]
    status='complete_fixed_five_transactions'
    with h.CaptureStore(ROOT/'history.sqlite') as store:
        def append(kind,**event):
            return store.append(kind,provenance='live',**event)
        append('checkpoint',received_at_ms=h.now_ms(),outcome='registered_exact_history_plan',
            payload={'plan':plan,'plan_sha256':plan_hash,'preregistered_commit':commit})
        async with h.aiohttp.ClientSession(trust_env=False,cookie_jar=h.aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport,'_retry_connection',None)) is not bool:
                raise h.ReadOnlyPolicyError('Unsupported retry policy')
            transport._retry_connection=False
            class ExactOnly(h.HistoricalSession):
                def post(self,url,*,json=None,**kwargs):
                    if json.get('method')!='getTransaction' or json.get('params',[None])[0] not in {x['signature'] for x in plan['transactions']}:
                        raise h.ReadOnlyPolicyError('Only five preregistered transaction reads allowed')
                    return super().post(url,json=json,**kwargs)
            session=ExactOnly(transport,5,proxy_resolver=h._environment_proxy)
            session._deadline_ns=started+20_000_000_000
            async def run():
                for row in plan['transactions']:
                    signature,slot=row['signature'],row['slot']
                    attempted.append(signature)
                    tx,receipt,request,outcome=await h._rpc(session,append,'getTransaction',
                        [signature,{'encoding':'jsonParsed','commitment':'confirmed','maxSupportedTransactionVersion':1}])
                    if outcome!='observed':
                        raise ValueError('First source failure; stop')
                    try:
                        append('transaction',received_at_ms=receipt,source_slot=slot,signature=signature,
                            request_id=request,outcome='observed' if tx is not None else 'missing',payload={'raw_transaction':tx})
                    except ValueError:
                        append('transaction',received_at_ms=receipt,source_slot=slot,signature=signature,
                            request_id=request,outcome='failed',reason='unsafe_raw_payload',
                            payload={'response_sha256':hashlib.sha256(h.canonical(tx)).hexdigest()})
                        raise ValueError('Rejected evidence body; stop')
                    if tx is None or tx.get('slot')!=slot or tx.get('meta',{}).get('err') is not None:
                        raise ValueError('Missing, failed or mismatched historical transaction')
                    received_transactions.append(signature)
                    burns.extend(h.burns_from(tx,signature))
            try:
                await asyncio.wait_for(run(),timeout=max(0,(session._deadline_ns-time.monotonic_ns())/1e9))
            except (ValueError,TypeError,KeyError,h.ReadOnlyPolicyError,asyncio.TimeoutError):
                status='stopped_on_first_source_or_evidence_failure_or_deadline'
            requests=session.requests_used
        append('checkpoint',received_at_ms=h.now_ms(),outcome='fixed_history_control_closed',
            payload={'status':status,'requests_used':requests,'no_retry':True,'real_orders_enabled':False})
        tail,records=store.verify_integrity(),len(store.events())
    total=sum(int(b['amount_atomic']) for b in burns)
    return {'schema':'p3-fixed-historical-transactions-control-v1','status':status,
        'requests_used':requests,'elapsed_ms':(time.monotonic_ns()-started)//1_000_000,
        'plan_sha256':plan_hash,'preregistered_commit':commit,'attempted':attempted,
        'received_transactions':received_transactions,'matching_parsed_burns':burns,
        'not_received':[r for r in plan['transactions'] if r['signature'] not in received_transactions],
        'observed_burn_sum_atomic':str(total),'target_supply_deficit_atomic':plan['target_supply_deficit_atomic'],
        'observed_burn_sum_equals_target':total==int(plan['target_supply_deficit_atomic']),
        'complete_history_claimed':False,'reconciliation_certified':False,
        'tail_hash':tail,'records':records,'real_orders_enabled':False,'economic_verdict':'INSUFFICIENT DATA'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--preregistered-commit');parser.add_argument('--expected-plan-sha256')
    args=parser.parse_args()
    if not args.execute or not re.fullmatch(r'[0-9a-f]{40}',args.preregistered_commit or ''):
        parser.error('Explicit execution and preregistered commit required')
    plan=json.loads((ROOT/'protocol.json').read_text());plan_hash=hashlib.sha256(h.canonical(plan)).hexdigest()
    if plan_hash!=args.expected_plan_sha256 or digest(Path(__file__))!=plan['script_sha256'] or digest(REUSE)!=plan['reused_script_sha256']:
        raise ValueError('Frozen plan or script hash mismatch')
    for path,expected in plan['imported_module_sha256'].items():
        if digest(h.REPO/path)!=expected:raise ValueError('Frozen capture module changed')
    for evidence in plan['evidence_pins']:
        h.verify_bundle(Path(evidence['path']),expected_tail=evidence['tail_hash'])
    if digest(Path(plan['selection_qualification_path']))!=plan['selection_qualification_sha256']:
        raise ValueError('Frozen selection qualification changed')
    if len(plan['transactions'])!=5 or len({r['signature'] for r in plan['transactions']})!=5:
        raise ValueError('Exactly five distinct fixed signatures required')
    if any((ROOT/p).exists() for p in ['history.sqlite','result.json','evidence']):
        raise ValueError('Already used run paths; no repeat allowed')
    result=asyncio.run(capture(plan,args.preregistered_commit,plan_hash))
    manifest=h.export_capture(ROOT/'history.sqlite',ROOT/'evidence',run_id='mint_history_005',
        source_revision=plan['source_revision'],plan_sha256=plan_hash,
        completeness={'complete_raw_replay':False,'scope':'exactly_five_pre_registered_historical_transactions',
            'signatures_fixed_before_reads':True,'unfetched_history_not_assumed_absent':True,'sqlite_exported':False})
    restored=h.verify_bundle(ROOT/'evidence',expected_tail=result['tail_hash'])
    assert restored['records']==result['records']==manifest['records']
    result['closed_journal_export_and_restore_verified']=True
    (ROOT/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ['status','requests_used','elapsed_ms','observed_burn_sum_atomic','observed_burn_sum_equals_target']}))

if __name__=='__main__':main()
