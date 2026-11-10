"""Technical rehearsal of the W1 chain WITHOUT reading any return of the pilot or of the holdout.

RUGGER 02 audit 7eae237e (protocol v2.6.2 data/pilot: "keeps counts only ... no return, no replay"):

* ``--run <pilot> --export-only``: the run must be exactly the pilot window (LaunchLab program,
  PILOT_SLOTS); only the frozen ``export_pools`` runs. Published: pool and transaction counts read
  from the exported MANIFEST, durations, peak RSS, the MANIFEST sha256; the pools directory is then
  DELETED. No archive is parsed by any strategy, no replay, no return.
* ``--frozen-pack``: the replay (V2 arms, L1 master/reference/placebo) and w1aux.ledger run only
  on the frozen 3-pool test pack (MANIFEST pinned below), with a declared SOL/USD rate labelled
  REHEARSAL_DECLARED_NOT_FOR_ECONOMICS; ``--lazy`` runs the same chain with w1aux.lazy archives.
  Published: durations, tracemalloc peak, counts, the ledger verdict; never a P&L figure.

Guards: RUGGER_NO_DOTENV=1; a new output directory; no other pools directory is accepted; every
slot read from the frozen pack's archives must lie outside [466248337, 466442736] (P0 beyond the
pilot) and before S0, a missing slot being refused (no default).
"""
import hashlib
import json
import os
import resource
import shutil
import time
import tracemalloc
from pathlib import Path

W1_S0 = 467_275_745                         # anchored by RUGGER 02 (ddcb2a57)
PILOT_SLOTS = (466_226_737, 466_248_336)    # frozen w1_collection.PILOT_SLOTS
P0_SEALED = (466_248_337, 466_442_736)      # p0_slots_excluded beyond the pilot (R02 C-R1)
FROZEN_PACK = Path('tests/fixtures/launchlab_sol_pools')
FROZEN_PACK_MANIFEST_SHA256 = '3224686db130e6b8e0c96a0a8e4bc19ad2cb5f62484ae7c0ae5707716b497e5e'
DECLARED_LABEL = 'REHEARSAL_DECLARED_NOT_FOR_ECONOMICS'
DECLARED_SOL_USD = 150.0


class RehearsalError(RuntimeError):
    pass


def _peak_rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _guard_environment(environ, out):
    if environ.get('RUGGER_NO_DOTENV') != '1':
        raise RehearsalError('set_RUGGER_NO_DOTENV_1')
    if Path(out).exists():
        raise RehearsalError('output_directory_already_exists')


def check_slots(slots):
    """Every slot known, outside the sealed P0 range and before S0 (R02 C-R1)."""
    slots = list(slots)
    if not slots or any(type(s) is not int for s in slots):
        raise RehearsalError('slot_missing_in_the_data')
    if any(P0_SEALED[0] <= s <= P0_SEALED[1] or s >= W1_S0 for s in slots):
        raise RehearsalError('data_reaches_the_sealed_p0_range_or_the_w1_window')


def export_only(*, run_dir, out, environ=None):
    from bot.market import backfill as bf
    from bot.market import backfill_export as bx
    from bot.market import w1_collection
    environ = os.environ if environ is None else environ
    _guard_environment(environ, out)
    manifest = json.loads((Path(run_dir) / 'manifest.json').read_text(encoding='utf-8'))
    window = manifest['window']
    if (window['address'], window['slot_min'], window['slot_max']) != (bf.LAUNCHLAB_PROGRAM,) + PILOT_SLOTS:
        raise RehearsalError('export_only_accepts_only_the_pilot_window')
    out = Path(out)
    out.mkdir(parents=True)
    pools = out / 'pools'
    t = time.monotonic()
    bx.export_pools(run_dir, pools, entry_cutoff_gap_slots=w1_collection.GAP_SLOTS,
                    collector_code=w1_collection.collector_code())
    seconds = round(time.monotonic() - t, 1)
    raw = (pools / 'MANIFEST.json').read_bytes()
    exported = json.loads(raw)
    entries = exported['pools']
    summary = dict(kind='PILOT_EXPORT_ONLY_COUNTS', pools=len(entries),
                   stored_signatures=sum(e.get('signatures', 0) for e in entries),
                   decoded_trades=sum(e.get('trades', 0) for e in entries),
                   compressed_bytes=sum((pools / e['file']).stat().st_size for e in entries),
                   export_s=seconds, peak_rss_mb=_peak_rss_mb(),
                   pools_manifest_sha256=hashlib.sha256(raw).hexdigest(), pools_directory_deleted=True,
                   note='counts only (protocol data/pilot): no archive parsed, no replay, no return')
    shutil.rmtree(pools)
    (out / 'rehearsal_summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True))
    return summary


def frozen_pack(*, out, lazy=False, environ=None):
    import contextlib
    import gzip
    from bot.master_v2 import harness
    from bot.master_v2 import w1_run as run
    from bot.p4 import historical_research_replay as hrr
    from w1aux import ledger as L
    from w1aux.lazy import lazy_archives
    environ = os.environ if environ is None else environ
    _guard_environment(environ, out)
    raw = (FROZEN_PACK / 'MANIFEST.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_PACK_MANIFEST_SHA256:
        raise RehearsalError('not_the_frozen_test_pack')
    _sha, _digests, pools, _manifest = hrr.load_fixtures(FROZEN_PACK)
    check_slots([row.get('slot') for _e, a in pools for row in a.signatures]
                + [tx.get('slot') for _e, a in pools for tx in a.transactions.values()])
    events = sum(len(a.transactions) for _e, a in pools)
    del pools
    out = Path(out)
    (out / 'bundles').mkdir(parents=True)
    params = hrr.ReplayParams(**dict(vars(run.l1_params()), sol_usd=DECLARED_SOL_USD, sol_usd_provenance=DECLARED_LABEL))
    timing, sums = {}, {}

    def write(name, bundle):
        data = gzip.compress(json.dumps(bundle, sort_keys=True).encode(), mtime=0)
        (out / 'bundles' / f'{name}.json.gz').write_bytes(data)
        sums[name] = hashlib.sha256(data).hexdigest()

    tracemalloc.start()
    with (lazy_archives() if lazy else contextlib.nullcontext()):
        t = time.monotonic()
        for trial_id, (make, rule) in run.V2_ARMS.items():
            write(trial_id, harness.run_policy(FROZEN_PACK, make(), rule, run.v2_params()))
        timing['v2_arms_s'] = round(time.monotonic() - t, 1)
        t = time.monotonic()
        history = hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(FROZEN_PACK)[2]], 'manifest')
        write('L1', hrr.run_replay(FROZEN_PACK, params, None, run.L1_EXIT, history, placebo_arm=True))
        timing['l1_s'] = round(time.monotonic() - t, 1)
    (out / 'bundles' / 'SHA256SUMS.json').write_text(json.dumps(sums, sort_keys=True))
    t = time.monotonic()
    led = L.build_ledger(FROZEN_PACK, out / 'bundles')
    timing['ledger_s'] = round(time.monotonic() - t, 1)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    data = json.dumps(led, indent=1, sort_keys=True).encode() + b'\n'
    (out / 'ledger.json').write_bytes(data)
    summary = dict(kind='TECHNICAL_REHEARSAL_FROZEN_TEST_PACK', lazy_archives=lazy, stored_transactions=events,
                   timing=timing, traced_peak_mb=round(peak / 1e6, 2), peak_rss_mb=_peak_rss_mb(),
                   ledger_verdict=led['verdict'], cycles_with_entry=led['cycles_with_entry'],
                   cycles_verified=led['cycles_verified'], mismatches=len(led['mismatches']),
                   arms={k: dict(pools=v['pools'], entries=v['entries'], closed=v['closed'])
                         for k, v in led['comparison'].items()},
                   bundles_sha256=sums, ledger_sha256=hashlib.sha256(data).hexdigest(), sol_usd=DECLARED_LABEL,
                   note='frozen test pack only; no P&L figure is reported here on purpose')
    (out / 'rehearsal_summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True))
    return summary


def main(argv=None, *, out=None):
    import argparse
    import sys
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description='W1 technical rehearsal (no pilot or holdout return is read)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', type=Path, help='the pilot run directory, with --export-only')
    mode.add_argument('--frozen-pack', action='store_true')
    parser.add_argument('--export-only', action='store_true')
    parser.add_argument('--lazy', action='store_true', help='frozen pack only: use w1aux.lazy archives')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.run is not None:
        if not args.export_only or args.lazy:
            raise RehearsalError('the_pilot_run_is_accepted_only_with_export_only')
        summary = export_only(run_dir=args.run, out=args.out)
    else:
        if args.export_only:
            raise RehearsalError('export_only_needs_the_pilot_run')
        summary = frozen_pack(out=args.out, lazy=args.lazy)
    out.write(json.dumps(summary, sort_keys=True) + '\n')
    return 0 if summary.get('ledger_verdict', 'PASS') == 'PASS' else 4


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
