#!/usr/bin/env python3
"""Summarize qualified archived quote evidence for the functional release offline.

First refresh the source with tools/qualify_p3_quote_pairs.py when code or source
archives change. This adapter does not repeat archive restoration or market calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(repo))
from bot.analyser.artifacts import atomic_write_json
from bot.analyser.functional_report import summarize_market_quote_admission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, default=repo/'validation/P3_QUOTE_PAIR_ADMISSION.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.admission.is_symlink() or args.admission.stat().st_size > 2*1024*1024:
            raise ValueError('Unsupported admission artifact')
        raw = args.admission.read_bytes()
        report = summarize_market_quote_admission(json.loads(raw))
        report['source_evidence'] = {
            'quote_pair_admission_path': str(args.admission.relative_to(repo)) if args.admission.is_relative_to(repo) else args.admission.name,
            'quote_pair_admission_sha256': hashlib.sha256(raw).hexdigest(),
            'reproduce_qualification': 'python -B tools/qualify_p3_quote_pairs.py',
            'source_archives_index': 'evidence/p3/index.json',
            'quote_admission_code': 'bot/p3/exit_qualification.py',
        }
    except (OSError, ValueError, TypeError, KeyError):
        parser.exit(1, 'Offline market admission report is unavailable or inconsistent.\n')
    if args.output:
        if args.output.resolve() == args.admission.resolve():
            parser.error('Market summary cannot replace its source admission evidence')
        atomic_write_json(args.output, report, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
