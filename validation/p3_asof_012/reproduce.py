"""Replay012 public evidence offline; SQLite is allowed only for two memory books."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True;os.environ['RUGGER_NO_DOTENV']='1'

def guard(event,args):
    if event in ('socket.connect','socket.bind','socket.getaddrinfo'):
        raise AssertionError('Replay forbids network')
    if event=='sqlite3.connect' and args[0]!=':memory:':
        raise AssertionError('Replay forbids file databases')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and Path(os.fsdecode(args[0])).name.startswith('.env'):
        raise AssertionError('Replay forbids private configuration')

sys.addaudithook(guard)
from bot.p3.evidence import verify_bundle
from bot.p3.asof_campaign_012 import build_report
from bot.p3.asof_protocol_012 import validate_plan

BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'plan.json').read_text())
anchor=next(r for r in json.loads((ROOT/'evidence/p3/index.json').read_text())['bundles'] if r['run_id']=='asof_012')
bundle=verify_bundle(ROOT/'evidence/p3/asof_012',expected_tail=anchor['tail_hash'])
assert all(bundle[k]==v for k,v in anchor.items())
events=bundle['events']

class Journal:
    def events(self):return events
    def verify_integrity(self):return bundle['tail_hash']

report=build_report(Journal(),plan)
raw=gzip.decompress((BASE/'result.json.gz').read_bytes())
assert report==json.loads(raw)
assert validate_plan(plan)==anchor['plan_sha256']
registration=json.loads((BASE/'REGISTRATION_READBACK.json').read_text())
first=next(e['payload']['requested_at_ms'] for e in events if e['kind']=='request')
assert plan['registered_at_ms']<registration['verified_at_ms']<first
assert registration['local_plan_blob']==registration['readback_plan_blob']
assert report['requests_used']<=12 and report['elapsed_ms']<60000
assert report['closed'] and events[-1]['outcome']=='asof_capture_closed'
assert report['qualified_economic_cycles']==0 and report['net_market_pnl_sol'] is None
assert report['actual_executed_transactions']==0
print(json.dumps(dict(schema='p3-012-offline-replay-verification-v1',
    report_reproduced_exactly=True,report_bytes_sha256=hashlib.sha256(raw).hexdigest(),
    records=len(events),tail_hash=bundle['tail_hash'],
    raw_bank_analyses_replayed=report['replayed_raw_analyses'],
    paired_admission_decisions=report['master_reference']['paired_admission_decisions'],
    strict_cycles=0,network_requests=0,file_database_used=False,
    comparison_book_scope='two_disposable_in_memory_PAPER_books',
    full_discovery_JSON_retained=False),sort_keys=True,indent=2))
