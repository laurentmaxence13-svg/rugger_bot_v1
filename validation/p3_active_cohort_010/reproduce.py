"""Reproduce the original010 report and six bank analyses from Git artifacts only."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.environ['RUGGER_NO_DOTENV']='1'
sys.dont_write_bytecode=True

def guard(event,args):
    if event in ('socket.connect','socket.bind','socket.getaddrinfo','sqlite3.connect'):
        raise AssertionError('Recovery replay forbids network and SQLite')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        if Path(os.fsdecode(args[0])).name.startswith('.env'):
            raise AssertionError('Recovery replay forbids private configuration')
sys.addaudithook(guard)

from bot.p3.active_cohort_campaign import build_active_cohort_report,validate_plan
from bot.p3.evidence import verify_bundle
from bot.p3.launchlab import analyze_snapshot

BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'PLAN.json').read_text())
index=json.loads((ROOT/'evidence/p3/index.json').read_text())
anchor=next(x for x in index['bundles'] if x['run_id']=='active_cohort_010')
bundle=verify_bundle(ROOT/'evidence/p3/active_cohort_010',expected_tail=anchor['tail_hash'])
assert all(bundle[k]==v for k,v in anchor.items())
events=bundle['events'];by_id={e['id']:e for e in events}
assert validate_plan(plan)==anchor['plan_sha256']
assert bundle['source_revision']==plan['source_revision']
class Journal:
    def events(self):return events
    def verify_integrity(self):return bundle['tail_hash']
replayed=build_active_cohort_report(Journal(),plan)
original_bytes=gzip.decompress((BASE/'RESULT.json.gz').read_bytes())
original=json.loads(original_bytes)
assert replayed==original
publication=json.loads((BASE/'PUBLICATION_RECEIPT.json').read_text())
requests=[e for e in events if e['kind']=='request']
assert plan['registered_at_ms']<publication['verified_at_ms']<requests[0]['payload']['requested_at_ms']
assert events[-1]['outcome']=='active_cohort_closed'
assert len(requests)==replayed['requests_used']<=20 and replayed['elapsed_ms']<=60000
assert all(e['payload']['http_status']==200 for e in requests)
assert all(e['received_at_ms']<=e['available_at_ms'] for e in events)
reproduced=[]
for event in events:
    if event['kind']!='candidate_decision' or 'analysis' not in event['payload']:continue
    snapshot=by_id[event['payload']['snapshot_observation_id']];data=snapshot['payload']
    accounts=dict(zip(data['requested_addresses'],data['raw_rpc_result']['value']))
    group=by_id[data['source_group_observation_id']]
    full=dict(zip(group['payload']['requested_addresses'],group['payload']['raw_rpc_result']['value']))
    assert all(accounts[k]==full[k] for k in accounts)
    assert snapshot['source_slot']==event['source_slot']==group['source_slot']
    assert snapshot['id']<event['id'] and snapshot['available_at_ms']<=event['available_at_ms']
    result=analyze_snapshot(accounts,context_slot=snapshot['source_slot'],expected_mint=event['mint'],pool_address=data['addresses']['pool'],input_lamports=plan['acquisition']['criteria']['research_input_lamports'],evidence_profile=data['evidence_profile'])
    assert result==event['payload']['analysis']
    reproduced.append(dict(mint=event['mint'],slot=event['source_slot']))
assert len(reproduced)==6
print(json.dumps(dict(schema='p3-010-offline-recovery-verification-v1',original_report_exactly_reproduced=True,original_report_bytes_sha256=hashlib.sha256(original_bytes).hexdigest(),six_analyses_reproduced=reproduced,events=len(events),tail_hash=bundle['tail_hash'],universe_rows=replayed['selection']['universe_size'],retained_discovery_rows=len(next(e for e in events if e['kind']=='discovery')['payload']['rows']),raw_discovery_response_retained=next(e for e in events if e['kind']=='discovery')['payload']['raw_response_retained'],requests=len(requests),capture_elapsed_ms=replayed['elapsed_ms'],qualified_economic_cycles=0,sqlite_used=False,network_used=False),indent=2,sort_keys=True))
