"""ps051verdict 0.2 -- one-pass, read-only verdict of the paperstream 0.5.1 --fast-analyser verification run on W1.

Owner decision 22/11 ~14:45Z (point 3, via R04): offline verification on already authorized data, after R02's
validation; goal: prove that the accelerated engine reproduces EXACTLY the W1 result and respects the memory limits;
the 0.4 run (out3) and its result are never replaced or modified. Standard library only; reads the run directory and
the memory log, prints whitelisted booleans and counts; no P&L, no pool id.

  python -I -B -m ps051verdict.verdict --run <RUN> --printed-sha256 <sha printed by the run> --rc <exit code> \
         --mem-log <memory monitor log>

Identity (I-1..I-6): schema paperstream-v0.5.1; fast_analyser true; verify_fast false; the three expected shas given to
the run are the anchored W1 ones AND matched (file 3409bf9d, json 9eb43426, field c7556f14); bundle_sha256 field =
its recomputation; reconciled_cycles = closed_cycles_all_arms > 0 and counts.master.closed_cycles = 191 (the
WHOLE-bundle count of the anchored W1 L1 bundle, documented by R02: not the 128 of the evaluation range).
Integrity (G-1..G-6): printed sha = PAPERSTREAM.json sha; rc = 0; input MANIFEST ebe1959d and series file 7458f615;
network false, trials_added 0, identity_check_not_a_trial; checkpoint index sha and one entry per pool, context
mode stream with fast_analyser true, no sha_mismatch / key_mismatch state.
Memory: M-1 the dayj guard passed WITHOUT override with the memo margin (memory.fits, memory_override false,
fast_memo_mb present). M-2 (0.2, R02 registry, fixed before any result; host in cgroup v1): the log has EXACTLY five
columns per line, '<iso> <rss of memory.stat> <sum of VmRSS of the run processes> <usage_in_bytes>
<max_usage_in_bytes>' (bytes); a log without any sample, or a malformed line, is refused. Rule, against the memory
available recorded by the run at its start (memory.available_mb): (1) max(max_usage_in_bytes) <= available -> PASS;
(2) otherwise max(sum RSS) <= available AND max(rss) <= available -> PASS with the note 'unsampled window
15:29:53-15:32:51Z' (usage/max_usage include the page cache and the whole container since its boot); (3) otherwise
MEMORY_EXCEEDED. Every column's peak is published.
Verdict: VERIFIED (all), IDENTITY_FAILED (an identity check fails on a valid run), MEMORY_EXCEEDED, INVALID_RUN.
"""
import argparse
import hashlib
import json
from pathlib import Path

W1 = dict(manifest='ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e',
          series='7458f61579bed089cde4ac2037839d2da1cc36c44e13d3f63252111e98e0dbdc',
          file='3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657',
          json='9eb4342674fdc85e002d08f4945d742800e585a50e9386a85c4bf68392a9680f',
          field='c7556f140fe8e2007ced5bd6c0a20a4202f2bfcda1a49370df1e1bbaabe62aa8',
          master_closed=191)
IDENTITY = ('I1_schema_and_flags', 'I2_file', 'I3_json', 'I4_field', 'I5_field_consistent', 'I6_cycles')
MEMORY = ('M1_guard_without_override', 'M2_peak_within_available')


class VerdictError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


UNSAMPLED_WINDOW = '15:29:53-15:32:51Z'          # R02 registry: run start to the first sample of the sampler
COLUMNS = ('rss', 'sum_vmrss', 'usage', 'max_usage')


def memory_peaks_mb(log_path):
    """Peaks in MB of the 5-column cgroup v1 log '<iso> <rss> <sum VmRSS> <usage_in_bytes> <max_usage_in_bytes>'."""
    peaks, samples = dict.fromkeys(COLUMNS, 0), 0
    for number, line in enumerate(Path(log_path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5 or not all(v.isdigit() for v in parts[1:]):
            raise VerdictError(f'memory_log_malformed_line:{number}')
        for name, value in zip(COLUMNS, parts[1:]):
            peaks[name] = max(peaks[name], int(value))
        samples += 1
    if not samples:
        raise VerdictError('memory_log_has_no_sample')
    return {name: round(value / 2 ** 20) for name, value in peaks.items()}, samples


def memory_rule(peaks, available):
    """(rule number, PASS?, note) of R02's M-2 rule."""
    if type(available) not in (int, float):
        return 3, False, 'available_memory_not_recorded'
    if peaks['max_usage'] <= available:
        return 1, True, None
    if peaks['sum_vmrss'] <= available and peaks['rss'] <= available:
        return 2, True, 'unsampled window ' + UNSAMPLED_WINDOW
    return 3, False, None


def check(run_dir, *, printed_sha256, rc, mem_log, anchors=W1):
    run_dir = Path(run_dir)
    path = run_dir / 'PAPERSTREAM.json'
    if not path.is_file():
        raise VerdictError('no_paperstream_output')
    doc = json.loads(path.read_text(encoding='utf-8'))
    c = {}
    c['G1_printed_sha'] = _sha(path) == printed_sha256
    c['G2_rc'] = rc == 0
    c['G3_inputs'] = (doc.get('input', {}).get('manifest_sha256') == anchors['manifest']
                      and doc.get('input', {}).get('sol_usd_series_file_sha256') == anchors['series'])
    c['G4_labels'] = (doc.get('network') is False and doc.get('trials_added') == 0
                      and doc.get('identity_check_not_a_trial') is True and doc.get('category') == 'HISTORICAL_REPLAY')
    c['G5_expected_are_the_anchors'] = (doc.get('expected_bundle_file_sha256') == anchors['file']
                                        and doc.get('expected_bundle_json_sha256') == anchors['json']
                                        and doc.get('expected_bundle_field_sha256') == anchors['field'])
    index_path = run_dir / 'CHECKPOINT_INDEX.json'
    if 'checkpoint_index_sha256' in doc and index_path.is_file():
        index = json.loads(index_path.read_text(encoding='utf-8'))
        states = set((index.get('counts') or {}))
        c['G6_checkpoint'] = (_sha(index_path) == doc['checkpoint_index_sha256']
                              and len(index.get('entries', {})) == doc.get('pools', -1) + doc.get('excluded', -1)
                              and index.get('context', {}).get('mode') == 'stream'
                              and index.get('context', {}).get('fast_analyser') is True
                              and states <= {'absent', 'reused'})
    else:
        c['G6_checkpoint'] = False
    c['I1_schema_and_flags'] = (doc.get('schema') == 'paperstream-v0.5.1' and doc.get('fast_analyser') is True
                                and doc.get('verify_fast') is False)
    c['I2_file'] = doc.get('matches_expected_bundle_file') is True and doc.get('bundle_file_sha256') == anchors['file']
    c['I3_json'] = doc.get('matches_expected_bundle_json') is True and doc.get('bundle_json_sha256') == anchors['json']
    c['I4_field'] = doc.get('matches_expected_bundle_field') is True and doc.get('bundle_sha256') == anchors['field']
    c['I5_field_consistent'] = (doc.get('bundle_sha256_consistent') is True
                                and doc.get('bundle_sha256') == doc.get('bundle_sha256_recomputed'))
    master = doc.get('counts', {}).get('master', {})
    c['I6_cycles'] = (type(doc.get('reconciled_cycles')) is int and doc['reconciled_cycles'] > 0
                      and doc['reconciled_cycles'] == doc.get('closed_cycles_all_arms')
                      and master.get('closed_cycles') == anchors['master_closed'])
    memory = doc.get('memory') or {}
    c['M1_guard_without_override'] = (memory.get('fits') is True and doc.get('memory_override') is False
                                      and type(memory.get('fast_memo_mb')) is int)
    peaks, samples = memory_peaks_mb(mem_log)
    available = memory.get('available_mb')
    rule, ok, note = memory_rule(peaks, available)
    c['M2_peak_within_available'] = ok
    failed = sorted(name for name, ok in c.items() if not ok)
    if not failed:
        verdict = 'VERIFIED'
    elif any(name.startswith('G') for name in failed):
        verdict = 'INVALID_RUN'
    elif any(name in IDENTITY for name in failed):
        verdict = 'IDENTITY_FAILED'
    else:
        verdict = 'MEMORY_EXCEEDED'
    projected = memory.get('projected_with_memo_mb')
    return dict(schema='ps051verdict-v0.2', verdict=verdict, failed=failed, checks=dict(sorted(c.items())),
                memory=dict(peaks_mb=peaks, samples=samples, available_mb=available, rule=rule, note=note,
                            projected_with_memo_mb=projected, fast_memo_mb=memory.get('fast_memo_mb'),
                            sum_vmrss_over_projection=round(peaks['sum_vmrss'] / projected, 3) if projected else None),
                checkpoint_counts=doc.get('checkpoint_counts'), perf_counters_sha256=doc.get('perf_counters_sha256'),
                scope='identity of the accelerated streaming engine with the anchored W1 L1 bundle: HISTORICAL_REPLAY, '
                      'not a trial, not a genuine Master trade; the 0.4 result (out3) is unchanged')


def main(argv=None):
    p = argparse.ArgumentParser(prog='ps051verdict.verdict')
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--printed-sha256', required=True)
    p.add_argument('--rc', type=int, required=True)
    p.add_argument('--mem-log', type=Path, required=True)
    a = p.parse_args(argv)
    out = check(a.run, printed_sha256=a.printed_sha256, rc=a.rc, mem_log=a.mem_log)
    print(json.dumps(out, sort_keys=True, indent=1))
    return 0 if out['verdict'] == 'VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
