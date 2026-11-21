"""psverdict 0.2 -- ONE-PASS reading of the paperstream 0.4 W1 output (R04 18:35Z, point 3). Read-only, offline,
standard library only; it does not import paperstream and changes nothing.

  python -B -m psverdict.verdict --run <RUN dir> --printed-sha256 <sha printed by the run> --rc <exit code> \
         --manifest-sha256 <anchored> --series-file-sha256 <anchored> --expect-master-closed <anchored by R02>

Checks, all required for IDENTITY_PROVEN (each one listed by name if it fails):
  run integrity  : PAPERSTREAM.json sha == the sha the run printed; rc == 0; schema paperstream-v0.4; category
                   HISTORICAL_REPLAY; network false; trials_added 0; identity_check_not_a_trial; memory_override false
  inputs         : manifest and SOL/USD series file sha == the anchored ones; the three expected bundle shas given to the
                   run == the anchored W1 values (file 3409bf9d, json 9eb43426, field c7556f14)
  identity       : matches_expected_bundle_file / _json / _field true AND the computed shas themselves equal the anchors;
                   bundle_sha256_consistent true
  journal        : reconciled_cycles == closed_cycles_all_arms
  master cycles  : counts.master.closed_cycles == --expect-master-closed (anchored by R02, W1: 128)
  checkpoint     : if used, CHECKPOINT_INDEX.json sha == checkpoint_index_sha256, one entry per pool (pools + excluded)
  firewall (0.2, R02 V-1): STRUCTURAL, recursive over the KEYS of the output: no key contains a forbidden token
                   (pnl, return, mark_, hypothes, HW, genuine, master_cycle, live_); the keys of every
                   ``blocking_reasons`` mapping are frozen reason names and are exempt, but their values must be integers
  labels (F-4)   : thresholds.these_cycles_count_toward_them and thresholds.operational_master_entry are false
  cycles (C-3)   : closed_cycles_all_arms == the sum of counts.*.closed_cycles, and reconciled_cycles > 0
Verdict: IDENTITY_PROVEN, IDENTITY_FAILED (a run that is valid but differs) or INVALID_RUN (inputs, integrity).
The summary holds counts only (decisions, entries, outcomes, closed cycles, top blocking reasons per arm): no P&L.
It is an identity check of the streaming engine, NOT a trial (N unchanged) and NOT a genuine Master trade.
"""
import argparse
import hashlib
import json
from pathlib import Path

W1_FILE = '3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657'
W1_JSON = '9eb4342674fdc85e002d08f4945d742800e585a50e9386a85c4bf68392a9680f'
W1_FIELD = 'c7556f140fe8e2007ced5bd6c0a20a4202f2bfcda1a49370df1e1bbaabe62aa8'
W1_MANIFEST = 'ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e'      # anchored by R02 (d67570d9)
W1_SERIES = '7458f61579bed089cde4ac2037839d2da1cc36c44e13d3f63252111e98e0dbdc'
W1_MASTER_CLOSED = 128
FORBIDDEN_KEY_TOKENS = ('pnl', 'return', 'mark_', 'hypothes', 'genuine', 'master_cycle', 'live_')
FORBIDDEN_KEY_CASED = ('HW',)
INTEGRITY = ('printed_sha', 'rc', 'schema', 'category', 'network', 'trials_added', 'not_a_trial', 'memory_override',
             'firewall', 'manifest', 'series', 'expected_file', 'expected_json', 'expected_field', 'checkpoint',
             'labels')


def firewall(value, path=()):
    """R02 V-1: the forbidden tokens are looked for in KEYS (recursively), never in the frozen reason names that are the
    keys of a ``blocking_reasons`` mapping, whose values must be integers. Returns the offending key paths."""
    bad = []
    if isinstance(value, dict):
        reasons = bool(path) and path[-1] == 'blocking_reasons'
        for key, item in value.items():
            if reasons:
                if type(item) is not int:
                    bad.append('/'.join(path + (str(key),)) + ':not_an_integer')
                continue
            k = str(key)
            if any(t in k.lower() for t in FORBIDDEN_KEY_TOKENS) or any(t in k for t in FORBIDDEN_KEY_CASED):
                bad.append('/'.join(path + (k,)))
            bad.extend(firewall(item, path + (k,)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            bad.extend(firewall(item, path + (str(i),)))
    return bad


class VerdictError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(run_dir, *, printed_sha256, rc, manifest_sha256, series_file_sha256, expect_master_closed,
          anchors=(W1_FILE, W1_JSON, W1_FIELD)):
    run_dir = Path(run_dir)
    path = run_dir / 'PAPERSTREAM.json'
    if not path.is_file():
        raise VerdictError('no_paperstream_output')
    doc = json.loads(path.read_text(encoding='utf-8'))
    file_a, json_a, field_a = anchors
    c = {}
    c['printed_sha'] = _sha(path) == printed_sha256
    c['rc'] = rc == 0
    c['schema'] = doc.get('schema') == 'paperstream-v0.4'
    c['category'] = doc.get('category') == 'HISTORICAL_REPLAY'
    c['network'] = doc.get('network') is False
    c['trials_added'] = doc.get('trials_added') == 0
    c['not_a_trial'] = doc.get('identity_check_not_a_trial') is True
    c['memory_override'] = doc.get('memory_override') is False
    c['firewall'] = not firewall(doc)
    thresholds = doc.get('thresholds', {})
    c['labels'] = (thresholds.get('these_cycles_count_toward_them') is False
                   and thresholds.get('operational_master_entry') is False)
    c['manifest'] = doc.get('input', {}).get('manifest_sha256') == manifest_sha256
    c['series'] = doc.get('input', {}).get('sol_usd_series_file_sha256') == series_file_sha256
    c['expected_file'] = doc.get('expected_bundle_file_sha256') == file_a
    c['expected_json'] = doc.get('expected_bundle_json_sha256') == json_a
    c['expected_field'] = doc.get('expected_bundle_field_sha256') == field_a
    c['identity_file'] = doc.get('matches_expected_bundle_file') is True and doc.get('bundle_file_sha256') == file_a
    c['identity_json'] = doc.get('matches_expected_bundle_json') is True and doc.get('bundle_json_sha256') == json_a
    c['identity_field'] = doc.get('matches_expected_bundle_field') is True and doc.get('bundle_sha256') == field_a
    c['field_consistent'] = (doc.get('bundle_sha256_consistent') is True
                             and doc.get('bundle_sha256') == doc.get('bundle_sha256_recomputed'))
    c['journal'] = (type(doc.get('reconciled_cycles')) is int and doc['reconciled_cycles'] > 0
                    and doc.get('reconciled_cycles') == doc.get('closed_cycles_all_arms'))
    per_arm = [row.get('closed_cycles') for row in doc.get('counts', {}).values()]
    c['cycles_sum'] = (bool(per_arm) and all(type(n) is int for n in per_arm)
                       and sum(per_arm) == doc.get('closed_cycles_all_arms'))
    master = doc.get('counts', {}).get('master', {})
    c['master_closed'] = master.get('closed_cycles') == expect_master_closed
    index_path = run_dir / 'CHECKPOINT_INDEX.json'
    if 'checkpoint_index_sha256' in doc:
        index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.is_file() else {}
        c['checkpoint'] = (index_path.is_file() and _sha(index_path) == doc['checkpoint_index_sha256']
                           and len(index.get('entries', {})) == doc.get('pools', -1) + doc.get('excluded', -1)
                           and index.get('context', {}).get('mode') == 'stream')
    else:
        c['checkpoint'] = not index_path.exists()
    failed = sorted(name for name, ok in c.items() if not ok)
    if not failed:
        verdict = 'IDENTITY_PROVEN'
    elif any(name in INTEGRITY for name in failed):
        verdict = 'INVALID_RUN'
    else:
        verdict = 'IDENTITY_FAILED'
    summary = {arm: dict(decisions=row.get('decisions'), entries=row.get('entries'),
                         closed_cycles=row.get('closed_cycles'), outcomes=row.get('outcomes'),
                         top_blocking_reasons=dict(list(row.get('blocking_reasons', {}).items())[:5]))
               for arm, row in sorted(doc.get('counts', {}).items())}
    return dict(schema='psverdict-v0.2', verdict=verdict, failed=failed, checks=dict(sorted(c.items())),
                firewall_offending_keys=firewall(doc),
                pools=doc.get('pools'), excluded=doc.get('excluded'), zlib_runtime_version=doc.get('zlib_runtime_version'),
                checkpoint_counts=doc.get('checkpoint_counts'), counts=summary,
                expect_master_closed=expect_master_closed,
                scope='identity check of the streaming engine on W1: HISTORICAL_REPLAY, not a trial (N unchanged), '
                      'not a genuine Master trade, never counted toward the 50 / 20 thresholds')


def main(argv=None):
    p = argparse.ArgumentParser(prog='psverdict.verdict')
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--printed-sha256', required=True)
    p.add_argument('--rc', type=int, required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--series-file-sha256', required=True)
    p.add_argument('--expect-master-closed', type=int, required=True)
    a = p.parse_args(argv)
    out = check(a.run, printed_sha256=a.printed_sha256, rc=a.rc, manifest_sha256=a.manifest_sha256,
                series_file_sha256=a.series_file_sha256, expect_master_closed=a.expect_master_closed)
    print(json.dumps(out, sort_keys=True, indent=1))
    return 0 if out['verdict'] == 'IDENTITY_PROVEN' else 1


if __name__ == '__main__':
    raise SystemExit(main())
