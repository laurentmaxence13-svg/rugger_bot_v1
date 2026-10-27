#!/usr/bin/env python3
"""Attach projected atomic inventory to retained control007 evidence offline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(repo))
from bot.analyser.artifacts import atomic_write_json
from bot.analyser.functional_report import summarize_atomic_market_events
from bot.p3.evidence import verify_bundle

ANCHOR = '2d2bf40400d62903995ad9ae0d746d5775a12decbd29819b37ea09fd505c2e0b'
PLAN = '6639407545df5accb89f80d48fdfa91a7dcd651ab54c154138743c6c57f680e9'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result_path = repo/'validation/P3_ACTIVE_EXIT_007.json'
    bundle_path = repo/'evidence/p3/active_exit_007'
    try:
        raw = result_path.read_bytes()
        control = json.loads(raw)
        if control['tail_hash'] != ANCHOR or control['plan_sha256'] != PLAN:
            raise ValueError('Control result differs from retained independent anchor')
        bundle = verify_bundle(bundle_path, expected_tail=ANCHOR)
        if bundle['plan_sha256'] != PLAN or bundle['records'] != control['records']:
            raise ValueError('Control bundle does not match preregistered evidence')
        first = next(e['payload']['analysis'] for e in bundle['events']
            if e['kind'] == 'candidate_decision' and isinstance(e['payload'].get('analysis'),dict))
        decimals = int(first['facts']['base_mint']['decimals'])
        report = summarize_atomic_market_events(bundle['events'],control,token_decimals=decimals)
        report['source_evidence'] = {
            'bundle':'evidence/p3/active_exit_007', 'tail_hash':ANCHOR, 'plan_sha256':PLAN,
            'result':'validation/P3_ACTIVE_EXIT_007.json', 'result_sha256':hashlib.sha256(raw).hexdigest(),
            'previous_analysis':'validation/P3_ACTIVE_EXIT_007_ANALYSIS.json',
            'source_revision':bundle['source_revision'], 'records':bundle['records']}
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        parser.exit(1,'Retained control007 evidence cannot support the atomic inventory summary.\n')
    if args.output:
        if args.output.resolve() in (result_path.resolve(), (bundle_path/'manifest.json').resolve(),
                                    (bundle_path/'events.jsonl.gz').resolve()):
            parser.error('Summary output cannot replace source evidence')
        atomic_write_json(args.output,report,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps(report,indent=2,sort_keys=True,allow_nan=False))


if __name__ == '__main__':
    main()
