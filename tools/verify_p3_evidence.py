#!/usr/bin/env python3
"""Verify Git-retained P3 evidence and replay explicit legacy analyses offline.

No SQLite, secret, network call, ledger or market-provider access is required.
Missing historical quote bodies are reported as missing, never reconstructed.
The Git index is an integrity anchor, not a provider authenticity certificate.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.p3.evidence import verify_bundle
from bot.p3.launchlab import analyze_snapshot
from bot.p3.replay import replay_quote_observation


def verify(evidence_root):
    root = Path(evidence_root)
    index_path = root / 'index.json'
    if index_path.is_symlink() or index_path.stat().st_size > 65536:
        raise ValueError('Unsupported evidence index')
    index = json.loads(index_path.read_text())
    if index.get('schema') != 'p3-private-evidence-index-v1' or type(index.get('bundles')) is not list:
        raise ValueError('Unsupported evidence index schema')
    seen, reports = set(), []
    for anchor in index['bundles']:
        run = anchor.get('run_id')
        if type(run) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', run) or run in seen:
            raise ValueError('Invalid or duplicate evidence run')
        seen.add(run)
        bundle = verify_bundle(root / run, expected_tail=anchor['tail_hash'])
        if any(key not in bundle or bundle[key] != value for key, value in anchor.items()):
            raise ValueError('Evidence index disagrees with bundle')
        events = bundle['events']
        by_id = {event['id']: event for event in events}
        provider_quotes = [event for event in events if event['kind'] == 'quote_attempt'
                           and event['payload'].get('provider') == 'raydium_trade_api']
        body_count = sum(event['payload'].get('retained_sanitized_response') is not None
                         for event in provider_quotes)
        replayed, missing_inputs = 0, 0
        for event in events:
            payload = event['payload']
            if event['kind'] != 'candidate_decision' or 'analysis' not in payload:
                continue
            snapshot = by_id.get(payload.get('snapshot_observation_id'))
            evidence = snapshot['payload'] if snapshot else {}
            addresses = evidence.get('requested_addresses')
            if not addresses:
                missing_inputs += 1
                continue
            result = evidence['raw_rpc_result']
            if (type(result) is not dict or type(result.get('value')) is not list
                    or len(result['value']) != len(addresses)):
                raise ValueError('Retained snapshot account order is incomplete')
            replay = analyze_snapshot(dict(zip(addresses, result['value'])),
                context_slot=result['context']['slot'], expected_mint=event['mint'],
                pool_address=evidence['addresses']['pool'], input_lamports=1_000_000_000,
                evidence_profile=evidence.get('evidence_profile', 'legacy'))
            if replay != payload['analysis']:
                raise ValueError('Legacy snapshot analysis replay differs from retained result')
            replayed += 1
        reports.append({'run_id': run, 'records': bundle['records'],
                        'tail_hash': bundle['tail_hash'],
                        'kind_counts': dict(Counter(event['kind'] for event in events)),
                        'legacy_snapshot_analyses_reproduced': replayed,
                        'analyses_missing_explicit_replay_inputs': missing_inputs,
                        'provider_quotes': len(provider_quotes),
                        'provider_quote_bodies_retained': body_count,
                        'provider_quote_bodies_missing': len(provider_quotes)-body_count,
                        'complete_raw_replay_declared': bundle['completeness'].get('complete_raw_replay')})
        # Preserve deterministic historical report shape when no quote body exists.
        if body_count:
            reports[-1]['quote_semantic_replays'] = dict(Counter(
                replay_quote_observation(event)['status'] for event in provider_quotes))
    return {'schema': 'p3-offline-evidence-verification-v1', 'network_used': False,
            'sqlite_used': False, 'integrity_vs_git_index': 'PASS',
            'provider_authenticity_certified': False, 'economic_validation': 'INSUFFICIENT DATA',
            'bundles_verified': len(reports), 'records_verified': sum(r['records'] for r in reports),
            'legacy_snapshot_analyses_reproduced': sum(r['legacy_snapshot_analyses_reproduced'] for r in reports),
            'bundles': reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path,
                        default=Path(__file__).resolve().parents[1]/'evidence/p3')
    args = parser.parse_args()
    try:
        report = verify(args.evidence_root)
    except (ValueError, KeyError, TypeError, OSError):
        parser.exit(1, 'Evidence verification failed; no completeness or replay success claimed.\n')
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
