"""poolprof 0.1 -- cProfile of the frozen W1 L1 replay of ONE pool (R02, 22:02Z). Audited BEFORE any execution.

  python -B -m poolprof.profile --pools <W1 export> --manifest-sha256 <ebe1959d... anchored> \
         --sol-usd-series <series> --sol-usd-series-sha256 <7458f615... anchored> --rank 50 --out <NEW DIR>

* the pool is designated by its RANK of gz size in the MANIFEST (1 = largest file; ties by file name), computed here;
  the sha256 of that archive file is checked against its MANIFEST entry before it is read;
* the replay is THE frozen per-pool call of ``hrr.run_replay`` as ``w1_run.run_trials`` makes it for the L1 bundle:
  ``replay_pool(archive, l1_params(), quote_mint, the series, collection_window(entry, manifest, params), L1_EXIT,
  CreatorHistory.from_archives(<every archive of the pack>, 'manifest'), arms + placebo)``, with the frozen batch
  trade engine; NO fast analyser, no memo, no paperstream swap. The creator history (all archives) is built BEFORE the
  profile and is not profiled; the archives are read one at a time (``w1aux.lazy``);
* output ``POOLPROF.json``: the cProfile table only (function as 'file:line(name)' with the file's base name, ncalls,
  tottime, cumtime), the top 30 by cumtime, and the total profiled time. NO result, NO pool identifier, NO P&L: the
  replay record is discarded.
"""
import argparse
import cProfile
import hashlib
import json
import os
import pstats
from pathlib import Path

from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from paperstream import engine as PS
from w1aux import lazy

SCHEMA = 'poolprof-v0.1'
TOP = 30


class ProfError(RuntimeError):
    pass


def _sha_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def ranked_entries(pools_dir, manifest):
    """MANIFEST pool entries by gz file size, largest first, ties by file name."""
    sized = [(os.path.getsize(Path(pools_dir) / entry['file']), entry['file'], entry) for entry in manifest['pools']]
    return [entry for _size, _name, entry in sorted(sized, key=lambda row: (-row[0], row[1]))]


def profile_pool(pools_dir, manifest_sha256, series_path, series_sha256, rank, *, keep_record=False):
    pools_dir = Path(pools_dir)
    if _sha_file(pools_dir / 'MANIFEST.json') != manifest_sha256:
        raise ProfError('manifest_is_not_the_anchored_one')
    series = PS.load_anchored_series(series_path, series_sha256)       # sha checked before the series is read
    params = w1_run.l1_params()
    if params.sol_usd is not None:
        raise ProfError('declared_sol_usd_rate_refused')
    manifest = json.loads((pools_dir / 'MANIFEST.json').read_bytes())
    entries = ranked_entries(pools_dir, manifest)
    if type(rank) is not int or not 1 <= rank <= len(entries):
        raise ProfError('rank_out_of_range')
    chosen = entries[rank - 1]
    if _sha_file(pools_dir / chosen['file']) != chosen['sha256']:
        raise ProfError('archive_is_not_the_manifest_one')
    arms = hrr.ARMS + (hrr.PLACEBO_ARM,)
    with lazy.lazy_archives():
        try:
            found_sha, _digests, archives, loaded = hrr.load_fixtures(pools_dir)
            if found_sha != manifest_sha256:
                raise ProfError('manifest_is_not_the_anchored_one')
            history = hrr.CreatorHistory.from_archives([a for _e, a in archives], 'manifest')
            pair = [(e, a) for e, a in archives if e['file'] == chosen['file']]
            if len(pair) != 1:
                raise ProfError('archive_not_in_the_loaded_pack')
            entry, archive = pair[0]
            profiler = cProfile.Profile()
            profiler.enable()
            record = hrr.replay_pool(archive, params, quote_mint=entry['quote_mint'], sol_usd_series=series,
                                     window=hrr.collection_window(entry, loaded, params), exit_options=w1_run.L1_EXIT,
                                     creator_history=history, arms=arms)
            profiler.disable()
        finally:
            lazy.clear_cache()
    stats = pstats.Stats(profiler)
    rows = []
    for (filename, line, name), (_cc, ncalls, tottime, cumtime, _callers) in stats.stats.items():
        rows.append(dict(function='%s:%d(%s)' % (os.path.basename(filename), line, name), ncalls=ncalls,
                         tottime=round(tottime, 6), cumtime=round(cumtime, 6)))
    rows.sort(key=lambda row: (-row['cumtime'], row['function']))
    doc = dict(schema=SCHEMA, rank=rank, input=dict(manifest_sha256=manifest_sha256, series_sha256=series_sha256),
               fast_analyser=False, total_time_s=round(stats.total_tt, 6), top_by_cumtime=rows[:TOP],
               label='HISTORICAL_REPLAY', contains_results=False)
    return (doc, record) if keep_record else doc


def main(argv=None):
    parser = argparse.ArgumentParser(prog='poolprof.profile')
    parser.add_argument('--pools', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--sol-usd-series', type=Path, required=True)
    parser.add_argument('--sol-usd-series-sha256', required=True)
    parser.add_argument('--rank', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise ProfError('output_exists')
    doc = profile_pool(a.pools, a.manifest_sha256, a.sol_usd_series, a.sol_usd_series_sha256, a.rank)
    a.out.mkdir(parents=True)
    raw = (json.dumps(doc, sort_keys=True, indent=1) + '\n').encode()
    (a.out / 'POOLPROF.json').write_bytes(raw)
    print(json.dumps(dict(sha256=hashlib.sha256(raw).hexdigest(), total_time_s=doc['total_time_s']), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
