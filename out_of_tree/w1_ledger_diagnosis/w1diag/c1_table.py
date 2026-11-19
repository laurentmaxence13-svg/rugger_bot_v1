"""Step 2 of the W1X ledger FAIL diagnosis (R02 abb5fb04): the shape of the 93 tx_costs mismatches of L1_event_horizon.

Hypothesis under test (R02, checked by R01 in the frozen code): the frozen replay (bot/market/replay.py l. 224, 239,
256, 290) counts 1 x tx_cost at the buy and +1 x at the sale or the end-of-data mark; hrr then RELABELS some priced rows
(_apply_window: closed past the window / open_at_end -> open_at_window_end; _migrated and _exit_after_migration ->
migrated_unpriced) without touching tx_costs (2 x) nor failed_attempt_costs (2 x, through ``priced``), while ledger
v7.4 (verify_cycle l. 344-347) expects 1 x for every outcome outside {closed, open_at_end}.

Sources (read-only, both sha256-checked):
- ``ledger.json`` (anchored sha): ONLY to select the entries of TRIAL whose mismatches carry ``tx_costs``, by (arm, pool);
  the ledger entries do not carry tx_costs, the notes or mark_pnl_lamports;
- the bundle ``L1_event_horizon.json.gz`` (anchored sha): the replayed ROW of each selected (arm, pool), because
  tx_costs, notes, mark_pnl_lamports and exit_index are fields of the bundle row.
Standard output: ONE line, whitelisted keys ``entries`` and ``table``; ``table`` rows = [arm, bundle outcome,
tx_costs multiple of (base + priority) or "non_integer", has mark_pnl_lamports, note exit_after_migration, has
exit_index, count]. No amount, no pool, no other field.
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

TRIAL = 'L1_event_horizon'
OUTCOMES = ('closed', 'open_at_end', 'open_at_window_end', 'migrated_unpriced', 'counterfactual_divergence', 'no_entry')
OUTPUT_KEYS = ('entries', 'table')
_NAME = re.compile(r'[A-Za-z0-9_.:-]+')


class C1TableError(RuntimeError):
    pass


def _checked(path, sha):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise C1TableError('file_is_not_the_anchored_one:' + Path(path).name)
    return data


def table(ledger_doc, bundle):
    wanted = {(m.get('arm'), m.get('pool')) for m in ledger_doc.get('mismatches') or ()
              if m.get('trial') == TRIAL and any(str(x).split(':', 1)[0] == 'tx_costs' for x in m.get('mismatches') or ())}
    params = bundle['params']
    unit = params['base_fee_lamports'] + params['priority_fee_lamports']
    rows, found = Counter(), 0
    for pool in bundle['pools']:
        for arm, row in pool['arms'].items():
            if (arm, pool['pool']) not in wanted:
                continue
            found += 1
            cost = row.get('tx_costs')
            multiple = cost // unit if isinstance(cost, int) and unit and cost % unit == 0 else 'non_integer'
            outcome = row.get('outcome') if row.get('outcome') in OUTCOMES else 'other'
            rows[(arm if isinstance(arm, str) and _NAME.fullmatch(arm) else 'unrecognized', outcome, multiple,
                  'mark_pnl_lamports' in row and row['mark_pnl_lamports'] is not None,
                  'exit_after_migration' in (row.get('notes') or ()), row.get('exit_index') is not None)] += 1
    if found != len(wanted):
        raise C1TableError('selected_entries_missing_from_the_bundle')
    return dict(entries=found, table=[[*key, n] for key, n in sorted(rows.items(), key=lambda kv: json.dumps(kv[0]))])


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    p = argparse.ArgumentParser(description='W1X ledger FAIL diagnosis, step 2: shape of the L1_event_horizon tx_costs rows')
    p.add_argument('--ledger', type=Path, required=True)
    p.add_argument('--ledger-sha256', required=True)
    p.add_argument('--bundle', type=Path, required=True, help='run/bundles/L1_event_horizon.json.gz')
    p.add_argument('--bundle-sha256', required=True, help='its sha256 in the anchored run/bundles/SHA256SUMS.json')
    a = p.parse_args(argv)
    ledger_doc = json.loads(_checked(a.ledger, a.ledger_sha256))
    bundle = json.loads(gzip.decompress(_checked(a.bundle, a.bundle_sha256)))
    result = table(ledger_doc, bundle)
    if tuple(result) != OUTPUT_KEYS:
        raise C1TableError('output_keys_not_the_whitelist')
    out.write(json.dumps(result, separators=(',', ':')) + '\n')
    return 0


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
