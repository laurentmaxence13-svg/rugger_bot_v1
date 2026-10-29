"""One preregistered historical public mint page and at most seven transactions."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time

REPO = Path('/workspace/rugger_bot_v1')
sys.path.insert(0, str(REPO))
import aiohttp
from bot.p3.campaign import CampaignSession
from bot.p3.collect import RPC_URL, _rpc, _environment_proxy, now_ms, ReadOnlyPolicyError
from bot.p3.store import CaptureStore
from bot.p3.evidence import export_capture, verify_bundle

ROOT = Path(__file__).resolve().parent
MINT = 'BNbNtWCfULYXXDNbm4VanecLox1geFsgKbWooke8iTFm'
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class HistoricalSession(CampaignSession):
    def get(self, *args, **kwargs):
        raise ReadOnlyPolicyError('Historical control permits only fixed read-only RPC')

    def post(self, url, *, json=None, **kwargs):
        if json.get('method') not in ('getSignaturesForAddress', 'getTransaction'):
            raise ReadOnlyPolicyError('Historical RPC method rejected')
        return super().post(url, json=json, **kwargs)


def burns_from(tx, signature):
    found = []
    if not isinstance(tx, dict) or tx.get('meta', {}).get('err') is not None:
        return found
    msg = tx.get('transaction', {}).get('message', {})
    if signature not in tx.get('transaction', {}).get('signatures', []):
        raise ValueError('Transaction signature mismatch')
    instructions = list(msg.get('instructions', []))
    for group in tx['meta'].get('innerInstructions', []):
        instructions.extend(group.get('instructions', []))
    for index, instruction in enumerate(instructions):
        if instruction.get('programId') != TOKEN:
            continue
        parsed = instruction.get('parsed')
        if not isinstance(parsed, dict) or parsed.get('type') not in ('burn', 'burnChecked'):
            continue
        info = parsed.get('info', {})
        if info.get('mint') != MINT:
            continue
        amount = info.get('amount') if parsed['type'] == 'burn' else info.get('tokenAmount', {}).get('amount')
        if type(amount) is not str or re.fullmatch(r'[0-9]+', amount) is None:
            raise ValueError('Unusable parsed burn amount')
        found.append({'signature': signature, 'slot':tx['slot'], 'instruction_index':index,
                      'type':parsed['type'], 'amount_atomic':str(int(amount)),
                      'source_token_account':info.get('account'), 'mint':MINT})
    return found


async def capture(plan, database, preregistered_commit, plan_hash):
    started = time.monotonic_ns()
    status, selected, burns, attempted = 'complete_bounded_sample', [], [], []
    missing, page_count, wire_count = [], None, 0
    with CaptureStore(database) as store:
        def append(kind, **event):
            return store.append(kind, provenance='live', **event)
        append('checkpoint', received_at_ms=now_ms(), outcome='registered_history_plan',
               payload={'plan':plan, 'plan_sha256':plan_hash,
                        'preregistered_commit':preregistered_commit})
        async with aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport, '_retry_connection', None)) is not bool:
                raise ReadOnlyPolicyError('Unsupported retry policy')
            transport._retry_connection = False
            session = HistoricalSession(transport, 8, proxy_resolver=_environment_proxy)
            session._deadline_ns = started + 30_000_000_000
            async def run():
                nonlocal selected, burns, missing, page_count
                page, received, request, outcome = await _rpc(session, append,
                    'getSignaturesForAddress', [MINT, {'limit':1000, 'commitment':'confirmed'}])
                if outcome != 'observed':
                    raise ValueError('First source failure; no retry')
                if type(page) is not list or len(page) > 1000:
                    raise ValueError('Invalid bounded signature page')
                append('checkpoint', received_at_ms=received, outcome='historical_mint_signature_page',
                       mint=MINT, request_id=request, payload={'raw_signature_page':page})
                page_count = len(page)
                candidates, seen = [], set()
                for row in page:
                    if (type(row) is not dict or type(row.get('slot')) is not int
                            or type(row.get('signature')) is not str or row.get('err') is not None):
                        continue
                    if not plan['creation_slot'] < row['slot'] <= plan['first_snapshot_slot']:
                        continue
                    signature = row['signature']
                    if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{64,88}',signature) or signature in seen:
                        raise ValueError('Invalid or duplicate selected signature')
                    seen.add(signature)
                    candidates.append({'signature':signature,'slot':row['slot']})
                candidates.sort(key=lambda row:(row['slot'], row['signature']))
                selected, missing = candidates[:7], candidates[7:]
                append('checkpoint', received_at_ms=now_ms(), outcome='fixed_transaction_selection',
                       mint=MINT, payload={'selected':selected,'not_selected_due_to_budget':missing,
                        'selection':'slot_ascending_then_signature_lexicographic',
                        'page_exhaustive_claimed':False})
                for row in selected:
                    signature, slot = row['signature'], row['slot']
                    attempted.append(signature)
                    tx, receipt, tx_request, tx_outcome = await _rpc(session, append,
                        'getTransaction', [signature, {'encoding':'jsonParsed',
                            'commitment':'confirmed','maxSupportedTransactionVersion':1}])
                    if tx_outcome != 'observed':
                        raise ValueError('First source failure; no retry')
                    try:
                        append('transaction', received_at_ms=receipt, source_slot=slot,
                            signature=signature, request_id=tx_request,
                            outcome='observed' if tx is not None else 'missing',
                            payload={'raw_transaction':tx})
                    except ValueError:
                        append('transaction', received_at_ms=receipt, source_slot=slot,
                            signature=signature, request_id=tx_request, outcome='failed',
                            reason='unsafe_raw_payload',payload={'response_sha256':hashlib.sha256(canonical(tx)).hexdigest()})
                        raise ValueError('Evidence body rejected; stop')
                    if tx is None:
                        raise ValueError('Transaction unavailable; stop')
                    if tx.get('slot') != slot or tx.get('meta',{}).get('err') is not None:
                        raise ValueError('Transaction slot or success mismatch')
                    burns.extend(burns_from(tx, signature))
            try:
                await asyncio.wait_for(run(),timeout=max(0,(session._deadline_ns-time.monotonic_ns())/1e9))
            except (ValueError, TypeError, KeyError, ReadOnlyPolicyError, asyncio.TimeoutError):
                status = 'stopped_on_first_source_or_evidence_failure_or_deadline'
            wire_count = session.requests_used
        append('checkpoint', received_at_ms=now_ms(), outcome='historical_control_closed',
            payload={'status':status,'requests_used':wire_count,'no_retry':True,
                     'economic_verdict':'INSUFFICIENT DATA','real_orders_enabled':False})
        tail, records = store.verify_integrity(), len(store.events())
    total = sum(int(b['amount_atomic']) for b in burns)
    return {'schema':'p3-historical-mint-control-v1','plan_sha256':plan_hash,
        'preregistered_commit':preregistered_commit,'status':status,
        'requests_used':wire_count,'elapsed_ms':(time.monotonic_ns()-started)//1_000_000,
        'page_signature_count':page_count,'selected':selected,'attempted_signatures':attempted,
        'not_fetched_within_interval':missing+[r for r in selected if r['signature'] not in attempted],
        'matching_parsed_burns':burns,'observed_burn_sum_atomic':str(total),
        'target_supply_deficit_atomic':plan['target_supply_deficit_atomic'],
        'observed_burn_sum_equals_target':total==int(plan['target_supply_deficit_atomic']),
        'complete_history_claimed':False,'reconciliation_certified':False,
        'raw_instructions_without_parser_not_assumed_absent':True,
        'tail_hash':tail,'records':records,'economic_verdict':'INSUFFICIENT DATA',
        'real_orders_enabled':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--preregistered-commit')
    parser.add_argument('--expected-plan-sha256')
    args=parser.parse_args()
    if not args.execute or not re.fullmatch(r'[0-9a-f]{40}',args.preregistered_commit or ''):
        parser.error('Explicit execution and preregistered Git commit required')
    plan=json.loads((ROOT/'protocol.json').read_text())
    digest=hashlib.sha256(canonical(plan)).hexdigest()
    if digest!=args.expected_plan_sha256:
        raise ValueError('Preregistered plan hash mismatch')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=plan['script_sha256']:
        raise ValueError('Preregistered script hash mismatch')
    for path,expected in plan['imported_module_sha256'].items():
        if hashlib.sha256((REPO/path).read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen capture module changed')
    database, report_path, destination = ROOT/'history.sqlite',ROOT/'result.json',ROOT/'evidence'
    if any(p.exists() for p in (database,report_path,destination)):
        raise ValueError('Run paths already used; no repeat allowed')
    result=asyncio.run(capture(plan,database,args.preregistered_commit,digest))
    manifest=export_capture(database,destination,run_id='mint_history_004',
        source_revision=plan['source_revision'],plan_sha256=digest,
        completeness={'complete_raw_replay':False,'scope':'one_mint_page_and_fixed_seven_tx_prefix',
                      'page_retained':True,'unfetched_transactions_explicit':True,'sqlite_exported':False})
    restored=verify_bundle(destination,expected_tail=result['tail_hash'])
    assert restored['records']==result['records']==manifest['records']
    result['closed_journal_export_and_restore_verified']=True
    report_path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ('status','requests_used','elapsed_ms','observed_burn_sum_atomic','observed_burn_sum_equals_target')}))

if __name__=='__main__':
    main()
