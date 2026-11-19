"""Step 1 of the W1X ledger FAIL diagnosis (R02 82340a82): the STRUCTURE of the mismatches, nothing else.

Offline, read-only, standard library only. Reads ONE ledger.json whose sha256 must equal the anchored one, and writes
ONE line on the standard output with exactly these keys (whitelist, tested):
- ``verdict``;
- ``mismatch_entries``: len(mismatches);
- ``histogram``: [trial, arm, check, count] rows, ``check`` = the prefix of a mismatch string before its first ``:``
  (only ``[a-z0-9_]+``; anything else is counted as ``unrecognized_check_name``), sorted;
- ``pools_touched_by_trial``: {trial: number of distinct pools with a mismatch};
- ``l1_plan_not_re_derived_by_trial``: {trial: number of entries whose checks.l1_exit_plan_re_derived is false}.
Trial and arm names are checked against ``[A-Za-z0-9_.:-]+`` (else ``unrecognized``). FORBIDDEN on the output, never
read into it: cycles_with_entry, cycles_verified or any absolute number of cycles, any value, any pool, pnl,
net_return, comparison. The script never prints a pool address: pools are only counted.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

OUTPUT_KEYS = ('verdict', 'mismatch_entries', 'histogram', 'pools_touched_by_trial', 'l1_plan_not_re_derived_by_trial')
_CHECK = re.compile(r'[a-z0-9_]+')
_NAME = re.compile(r'[A-Za-z0-9_.:-]+')


class DiagnosisError(RuntimeError):
    pass


def _name(value):
    return value if isinstance(value, str) and _NAME.fullmatch(value) else 'unrecognized'


def _check(mismatch):
    prefix = mismatch.split(':', 1)[0] if isinstance(mismatch, str) else ''
    return prefix if _CHECK.fullmatch(prefix) else 'unrecognized_check_name'


def histogram(doc):
    mismatches = doc.get('mismatches')
    if not isinstance(mismatches, list):
        raise DiagnosisError('ledger_without_a_mismatch_list')
    rows, pools = Counter(), {}
    for m in mismatches:
        trial, arm = _name(m.get('trial')), _name(m.get('arm'))
        pools.setdefault(trial, set()).add(m.get('pool'))
        for check in sorted({_check(x) for x in m.get('mismatches') or ()}):    # one count per entry and check
            rows[(trial, arm, check)] += 1
    not_derived = Counter()
    for e in doc.get('entries') or ():
        if (e.get('checks') or {}).get('l1_exit_plan_re_derived') is False:
            not_derived[_name(e.get('trial'))] += 1
    verdict = doc.get('verdict')
    return dict(verdict=verdict if verdict in ('PASS', 'FAIL') else 'unrecognized',
                mismatch_entries=len(mismatches),
                histogram=[[t, a, c, n] for (t, a, c), n in sorted(rows.items())],
                pools_touched_by_trial={t: len(p) for t, p in sorted(pools.items())},
                l1_plan_not_re_derived_by_trial=dict(sorted(not_derived.items())))


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    p = argparse.ArgumentParser(description='W1X ledger FAIL diagnosis, step 1: structure of the mismatches only')
    p.add_argument('--ledger', type=Path, required=True, help='the frozen copy of ledger/ledger.json')
    p.add_argument('--ledger-sha256', required=True, help='its sha256, as anchored by RUGGER 02')
    a = p.parse_args(argv)
    data = a.ledger.read_bytes()
    if hashlib.sha256(data).hexdigest() != a.ledger_sha256:
        raise DiagnosisError('ledger_is_not_the_anchored_one')
    result = histogram(json.loads(data))
    if tuple(result) != OUTPUT_KEYS:
        raise DiagnosisError('output_keys_not_the_whitelist')
    out.write(json.dumps(result, sort_keys=False, separators=(',', ':')) + '\n')
    return 0


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
