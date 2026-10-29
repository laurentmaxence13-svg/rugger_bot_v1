"""Offline011 replay: report, exact quote bodies and eight retained bank analyses."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True;os.environ['RUGGER_NO_DOTENV']='1'
def guard(event,args):
    if event in ('socket.connect','socket.bind','socket.getaddrinfo','sqlite3.connect'):
        raise AssertionError('Replay forbids network and SQLite')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and Path(os.fsdecode(args[0])).name.startswith('.env'):
        raise AssertionError('Replay forbids private configuration')
sys.addaudithook(guard)
from bot.p3.evidence import verify_bundle
from bot.p3.research_campaign import build_report,validate_plan
from bot.p3.launchlab import analyze_snapshot
from bot.p3.replay import replay_quote_observation
BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'PLAN.json').read_text())
index=json.loads((ROOT/'evidence/p3/index.json').read_text())
anchor=next(r for r in index['bundles'] if r['run_id']=='research_011')
b=verify_bundle(ROOT/'evidence/p3/research_011',expected_tail=anchor['tail_hash'])
assert all(b[k]==v for k,v in anchor.items())
events=b['events'];by_id={e['id']:e for e in events}
class Journal:
    def events(self):return events
    def verify_integrity(self):return b['tail_hash']
original=gzip.decompress((BASE/'RESULT.json.gz').read_bytes());report=build_report(Journal(),plan)
assert report==json.loads(original)
assert validate_plan(plan)==anchor['plan_sha256']
publication=json.loads((BASE/'PUBLICATION_RECEIPT.json').read_text())
first=next(e['payload']['requested_at_ms'] for e in events if e['kind']=='request')
assert plan['registered_at_ms']<publication['verified_at_ms']<first
assert report['requests_used']==20 and report['elapsed_ms']<60000
assert events[-1]['outcome']=='research_capture_closed'
intents=next(e for e in events if e['outcome']=='research_quote_intents_fixed')
quotes=[e for e in events if e['kind']=='quote_attempt' and e['payload'].get('provider')=='raydium_trade_api']
assert len(quotes)==12 and all(e['id']>intents['id'] for e in quotes)
assert all(replay_quote_observation(e)['status']=='REPLAYED' for e in quotes)
assert all(e['received_at_ms']<=e['available_at_ms'] for e in events)
analyses=0
for e in events:
    if e['kind']!='candidate_decision' or 'analysis' not in e['payload']:continue
    snapshot=by_id[e['payload']['snapshot_observation_id']];p=snapshot['payload'];raw=p['raw_rpc_result']
    group=by_id[p['source_group_observation_id']];gp=group['payload']
    accounts=dict(zip(p['requested_addresses'],raw['value']))
    full=dict(zip(gp['requested_addresses'],gp['raw_rpc_result']['value']))
    assert all(accounts[k]==full[k] for k in accounts)
    assert snapshot['id']<e['id'] and snapshot['available_at_ms']<=e['available_at_ms']
    replay=analyze_snapshot(accounts,context_slot=snapshot['source_slot'],expected_mint=e['mint'],pool_address=p['addresses']['pool'],input_lamports=plan['primary_model_input_lamports'],evidence_profile=p['evidence_profile'])
    assert replay==e['payload']['analysis'];analyses+=1
assert analyses==8
assert report['economics']['complete_receipt_linked_live_market_pairs']==8
assert report['qualified_economic_cycles']==0 and report['net_market_pnl_sol'] is None
print(json.dumps(dict(schema='p3-011-offline-replay-verification-v1',report_reproduced_exactly=True,report_bytes_sha256=hashlib.sha256(original).hexdigest(),events=len(events),tail_hash=b['tail_hash'],bank_analyses_reproduced=analyses,provider_quote_bodies_replayed=len(quotes),complete_indicative_market_pairs=8,strict_cycles=0,net_market_pnl_sol=None,network_used=False,sqlite_used=False),indent=2,sort_keys=True))
