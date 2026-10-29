"""Offline new-profile diagnosis; no historical artifact is changed."""
import hashlib
import json
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(repo))
from bot.p3.evidence import verify_bundle
from bot.p3.launchlab import analyze_snapshot

root = repo / 'evidence/p3'
index = json.loads((root/'index.json').read_text())
anchor = next(x for x in index['bundles'] if x['run_id'] == 'launchlab_002')
events = verify_bundle(root/'launchlab_002', expected_tail=anchor['tail_hash'])['events']
rows = []
for event in events:
    p = event['payload']
    if event['kind'] != 'pool_snapshot' or 'requested_addresses' not in p:
        continue
    raw = p['raw_rpc_result']
    report = analyze_snapshot(dict(zip(p['requested_addresses'], raw['value'])),
        context_slot=raw['context']['slot'], expected_mint=event['mint'],
        pool_address=p['addresses']['pool'], evidence_profile='published_metadata_v1')
    rows.append({'mint': event['mint'], 'period': p['period'],
        'snapshot_observation_id': event['id'],
        'supply_consistency': report['facts'].get('supply_consistency'),
        'projection_available': report['conditional_projection'] is not None,
        'blocking_reasons': report['blocking_reasons'],
        'candidate_eligible': report['candidate_eligible'],
        'real_orders_enabled': report['real_orders_enabled']})
assert len(rows) == 4
quotes = [e for e in events if e['kind'] == 'quote_attempt'
          and e['payload'].get('provider') == 'raydium_trade_api']
result = {'schema': 'p3-offline-exit-diagnostics-v1',
    'bundle': 'launchlab_002', 'tail_hash': anchor['tail_hash'],
    'analysis_code_sha256': hashlib.sha256((repo/'bot/p3/launchlab.py').read_bytes()).hexdigest(),
    'network_used': False, 'sqlite_used': False,
    'historical_results_modified': False,
    'historical_quote_bodies_missing': sum(e['payload'].get('retained_sanitized_response') is None for e in quotes),
    'provider_rejections': [{'observation_id':e['id'],
        'http_status':e['payload']['http_status'], 'reason':e['payload']['reason'],
        'provider_body_available':e['payload'].get('retained_sanitized_response') is not None}
        for e in quotes if e['payload']['outcome'] != 'quoted'],
    'observations': rows, 'economic_verdict': 'INSUFFICIENT DATA'}
print(json.dumps(result, indent=2, sort_keys=True))
