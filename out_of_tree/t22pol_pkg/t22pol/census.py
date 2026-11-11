"""Census of the launched tokens of a set of pools: one class per pool, every reason, counts.

  python -I -B -m t22pol.census <pools.json> [--frozen-check]

Input: {"pools": [{"pool", "mint", "mint_account": {owner, executable, lamports, data}}, ...]} — the
raw mint account as already archived (getMultipleAccounts shape). Output: JSON on stdout. Descriptive:
no amount, no result, no outcome is read. With --frozen-check (run from the frozen tree), every
Token-2022 decision is compared with the frozen ``bot.p3.token2022.decode_mint``.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from t22pol import VERSION, policy


def census(document, frozen_check=False):
    rows, disagreements = [], []
    decode = None
    if frozen_check:
        from bot.p3.token2022 import TokenEvidenceError, decode_mint
        decode = (decode_mint, TokenEvidenceError)
    for entry in sorted(document['pools'], key=lambda e: e['pool']):
        row = dict(pool=entry['pool'], **policy.classify(entry.get('mint_account'), entry['mint']))
        if decode and row['token_program'] == 'token2022':
            try:
                facts, _raw = decode[0](entry['mint_account'], entry['mint'])
                frozen = 'accepts' if not (facts['mint_authority_present'] or facts['freeze_authority_present']) \
                    else 'accepts_extensions_but_authority_present'
            except decode[1] as exc:
                frozen = f'refuses:{exc}'
            row['frozen_reader'] = frozen
            if (row['class_'] == 'token2022_allowlisted') != (frozen == 'accepts'):
                disagreements.append(row['pool'])
        rows.append(row)
    counts = Counter(r['class_'] for r in rows)
    refusals = Counter(reason for r in rows for reason in r['reasons'])
    extensions = Counter(tuple(r['extensions']) for r in rows if r['token_program'] == 'token2022')
    return dict(schema='t22pol-census-v1', t22pol_version=VERSION, policy_source_sha256=policy.SOURCE_SHA256,
                mint_allow=sorted(policy.name(k) for k in policy.MINT_ALLOW), pools=len(rows),
                classes=dict(sorted(counts.items())), refusal_reasons=dict(sorted(refusals.items())),
                extension_sets={' + '.join(k) or '(none)': v for k, v in sorted(extensions.items())},
                frozen_check=frozen_check, disagreements_with_frozen_reader=disagreements,
                rows=rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Token-2022 census of launched tokens (descriptive)')
    parser.add_argument('pools', type=Path)
    parser.add_argument('--frozen-check', action='store_true')
    a = parser.parse_args(argv)
    raw = a.pools.read_bytes()
    out = census(json.loads(raw), a.frozen_check)
    out['input_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0 if not out['disagreements_with_frozen_reader'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
