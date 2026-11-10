"""Visible-only data pack for V3 (R02 V-A): the sealed holdout is never copied, W1 is refused.

``build`` reads the source export (same format as ``w1_collection.export``: MANIFEST.json plus
``<pool>.json.gz``), computes the chronological split of the frozen tree over ALL usable pools
(creator and creation slot only, as the V2 evaluation did), then copies ONLY the pool files of the
exploration, train and validation segments. It writes:

* ``MANIFEST.json``: the source manifest restricted to the visible pools, with a ``v3_visible``
  block (source manifest hash, embargo, counts, hashes of the two files below);
* ``SEGMENTS.json``: pool -> segment, for the visible pools only;
* ``SEALED_SHA256.txt``: the sha256 of every pool file that was NOT copied (holdout, embargoed,
  creator overlap, unusable), so that a run can refuse any of them.

``open_pack`` is the only way the runner reads data. It refuses a pack whose MANIFEST hash is not
the anchored one, a pack without the ``v3_visible`` block (a raw export, P0 or W1), any sealed file,
and any transaction at or after the first W1 slot. Every file read is listed with its sha256.
"""
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from bot.market.collector import PoolArchive, summarize
from bot.master_v2.harness import ExitRule, outcome_horizon_slots
from bot.master_v2.validation import chronological_split
from bot.p4 import historical_research_replay as hrr

from v3lab import plan
from v3lab.policies import POLICIES

VISIBLE_SCHEMA = 'rugger-master-v3-visible-pack-v1'
VISIBLE_SEGMENTS = plan.SEGMENTS


class PackError(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def trial_objects(row):
    """(policy, exit rule, replay parameters) of a plan trial."""
    policy = POLICIES[row['policy']](**row['params'])
    return policy, ExitRule(**row['exit']), hrr.ReplayParams(**plan.REPLAY)


def required_embargo_slots():
    """Largest outcome horizon of the plan's trials (frozen ``outcome_horizon_slots``)."""
    needs = []
    for row in plan.TRIALS:
        policy, rule, params = trial_objects(row)
        need = outcome_horizon_slots(policy, rule, params)
        if need is None:
            raise PackError('trial_without_bounded_horizon:%s' % row['id'])
        needs.append(need)
    return max(needs)


def _max_slot(archive):
    slots = [tx.get('slot') for tx in archive.transactions.values()]
    slots += [row.get('slot') for row in archive.signatures]
    slots = [slot for slot in slots if type(slot) is int]
    if not slots:
        raise PackError('pool_without_slot:%s' % archive.pool)
    return max(slots)


def _guard_slots(archive):
    top = _max_slot(archive)
    if top >= plan.S0_W1:
        raise PackError('w1_slot_refused:%s:%d' % (archive.pool, top))
    return top


def _archive(data, entry):
    archive = PoolArchive.from_json(json.loads(gzip.decompress(data)))
    if archive.pool != entry['pool']:
        raise PackError('pool_mismatch:%s' % entry['file'])
    return archive


TABLE_DROPPED_KEYS = frozenset(('trade', 'trades', 'journal', 'window', 'migration'))


def _without_outcomes(pairs):
    """JSON object hook: a table bundle also holds the trade rows and journals of the sealed pools;
    they are dropped as the text is parsed, so no outcome of any pool ever reaches this module."""
    return {key: value for key, value in pairs if key not in TABLE_DROPPED_KEYS}


def _table_from_bundle(path, manifest, source_sha256):
    """Pool table of an existing bundle of the same export: no non-visible pool file is opened at all.

    Only ``pool``, ``creator`` and ``created_slot`` (and the exclusion reasons) are kept; every
    ``trade``, ``trades``, ``journal``, ``window`` and ``migration`` value is discarded at parse time.
    """
    bundle = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_without_outcomes)
    if bundle.get('fixtures', {}).get('manifest_sha256') != source_sha256:
        raise PackError('table_bundle_is_not_of_this_export')
    table = [dict(pool=row['pool'], creator=row['creator'], created_slot=row['created_slot'])
             for row in bundle['pools']]
    excluded = {row['pool']: row['reasons'] for row in bundle.get('excluded_pools', [])}
    listed = {entry['pool'] for entry in manifest['pools']}
    if {row['pool'] for row in table} | set(excluded) != listed or len(table) + len(excluded) != len(listed):
        raise PackError('table_bundle_pools_differ_from_manifest')
    return table, excluded


def build(source_dir, out_dir, *, embargo_slots=None, table_bundle=None, read_all_pools=False):
    """Write the visible-only pack; return its summary (counts and hashes, no result of any kind).

    ``table_bundle`` is REQUIRED on real data (R02 P-1): an existing bundle of this very export (a
    registered P0 run) gives the pool table (creator, creation slot, exclusions); the files of the
    non-visible pools are then never opened, their sha256 comes from the source MANIFEST.
    ``read_all_pools=True`` instead derives the table by reading every pool file. It exists for
    packs that have no sealed part (the committed test fixtures) and is not offered by the CLI.
    """
    source_dir, out_dir = Path(source_dir), Path(out_dir)
    if table_bundle is None and not read_all_pools:
        raise PackError('table_bundle_required')
    if table_bundle is not None and read_all_pools:
        raise PackError('table_bundle_and_read_all_pools_are_exclusive')
    if out_dir.exists():
        raise PackError('output_directory_already_exists')
    required = required_embargo_slots()
    embargo_slots = required if embargo_slots is None else embargo_slots
    if type(embargo_slots) is not int or embargo_slots < required:
        raise PackError('embargo_shorter_than_outcome_horizon:%d' % required)
    raw = (source_dir / 'MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    if 'v3_visible' in manifest:
        raise PackError('source_is_already_a_visible_pack')
    end = manifest.get('window_slot_max')
    if end is not None and (type(end) is not int or end >= plan.S0_W1):
        raise PackError('w1_window_refused')
    for entry in manifest['pools']:
        if entry['file'] != f"{entry['pool']}.json.gz":
            raise PackError('file_name_mismatch:%s' % entry['file'])
    digests = {entry['pool']: entry['sha256'] for entry in manifest['pools']}
    if table_bundle is not None:
        table, excluded = _table_from_bundle(table_bundle, manifest, _sha(raw))
        table_sha256 = _sha(Path(table_bundle).read_bytes())
    else:
        table, excluded, table_sha256 = [], {}, None
        for pool in sorted(digests):
            archive = _checked_archive(source_dir, pool, digests[pool])
            summary, timeline = summarize(archive)
            try:
                hrr.usable_timeline(archive, summary, timeline)
            except hrr.PoolExcluded as exc:
                excluded[pool] = exc.reasons
                continue
            facts = hrr.creation_facts(archive)
            table.append(dict(pool=pool, creator=facts['creator'], created_slot=facts['creation_slot']))
    split = chronological_split(table, embargo_slots=embargo_slots)
    segments = {pool: name for name in VISIBLE_SEGMENTS for pool in split[name]}
    created = {row['pool']: row['created_slot'] for row in table}
    for pool in sorted(segments):                      # every file that will be copied: hash and W1 guard
        _checked_archive(source_dir, pool, digests[pool])
        # R02 P-2 (c): the export must cover the whole outcome horizon of a visible pool, otherwise a
        # clock exit would be valued on a state that is merely the end of the data.
        if end is not None and created[pool] + embargo_slots > end:
            raise PackError('visible_pool_not_covered_to_its_horizon:%s' % pool)
    counts = {name: len(split[name]) for name in split}
    counts['excluded'] = len(excluded)
    extra = dict(table_source='bundle' if table_bundle is not None else 'all_pool_files_read',
                 table_bundle_sha256=table_sha256, horizon_coverage_checked=end is not None)
    return _write(source_dir, out_dir, manifest, raw, segments, digests, excluded, counts, embargo_slots, required,
                  extra)


def _checked_archive(source_dir, pool, sha256):
    data = (source_dir / f'{pool}.json.gz').read_bytes()
    if _sha(data) != sha256:
        raise PackError('sha256_mismatch:%s' % pool)
    archive = _archive(data, dict(pool=pool, file=f'{pool}.json.gz'))
    _guard_slots(archive)
    return archive


def _write(source_dir, out_dir, manifest, raw, segments, digests, excluded, counts, embargo_slots, required,
           extra=None):
    """Copy the visible pool files and write MANIFEST, SEGMENTS and SEALED_SHA256 (see ``build``)."""
    out_dir.mkdir(parents=True)
    for pool in sorted(segments):
        shutil.copyfile(source_dir / f'{pool}.json.gz', out_dir / f'{pool}.json.gz')
    segments_raw = (json.dumps(dict(sorted(segments.items())), indent=1, sort_keys=True) + '\n').encode()
    sealed = sorted(sha for pool, sha in digests.items() if pool not in segments)
    sealed_raw = ''.join(line + '\n' for line in sealed).encode()
    (out_dir / 'SEGMENTS.json').write_bytes(segments_raw)
    (out_dir / 'SEALED_SHA256.txt').write_bytes(sealed_raw)
    block = dict(schema=VISIBLE_SCHEMA, source_manifest_sha256=_sha(raw), source_pools=len(manifest['pools']),
                 embargo_slots=embargo_slots, required_embargo_slots=required, counts=dict(sorted(counts.items())),
                 excluded=dict(sorted(excluded.items())), segments_sha256=_sha(segments_raw),
                 sealed_sha256=_sha(sealed_raw), s0_w1_guard=plan.S0_W1, **(extra or {}),
                 rule='only exploration, train and validation pool files are copied; holdout, embargoed, '
                      'creator-overlap and unusable pools are listed by file sha256 in SEALED_SHA256.txt')
    visible = dict(manifest, pools=[entry for entry in manifest['pools'] if entry['pool'] in segments],
                   v3_visible=block)
    out_raw = (json.dumps(visible, indent=1, sort_keys=True) + '\n').encode()
    (out_dir / 'MANIFEST.json').write_bytes(out_raw)
    return dict(manifest_sha256=_sha(out_raw), visible_pools=len(segments), **block)


class Pack:
    """An opened visible-only pack; ``pools()`` yields (entry, archive, segment) with every guard applied."""

    def __init__(self, directory, expect_manifest_sha256):
        self.directory = Path(directory)
        raw = (self.directory / 'MANIFEST.json').read_bytes()
        self.manifest_sha256 = _sha(raw)
        if type(expect_manifest_sha256) is not str or self.manifest_sha256 != expect_manifest_sha256:
            raise PackError('pack_manifest_sha256_is_not_the_anchored_one')
        self.manifest = json.loads(raw)
        block = self.manifest.get('v3_visible')
        if not isinstance(block, dict) or block.get('schema') != VISIBLE_SCHEMA:
            raise PackError('not_a_visible_only_pack')
        if block.get('s0_w1_guard') != plan.S0_W1:
            raise PackError('pack_built_with_another_w1_guard')
        end = self.manifest.get('window_slot_max')
        if end is not None and (type(end) is not int or end >= plan.S0_W1):
            raise PackError('w1_window_refused')
        if block['embargo_slots'] < required_embargo_slots():
            raise PackError('pack_embargo_shorter_than_outcome_horizon')
        segments_raw = (self.directory / 'SEGMENTS.json').read_bytes()
        sealed_raw = (self.directory / 'SEALED_SHA256.txt').read_bytes()
        if _sha(segments_raw) != block['segments_sha256'] or _sha(sealed_raw) != block['sealed_sha256']:
            raise PackError('pack_side_file_changed')
        self.segments = json.loads(segments_raw)
        self.sealed = set(sealed_raw.decode().split())
        self.block = block
        if set(self.segments.values()) - set(VISIBLE_SEGMENTS):
            raise PackError('pack_contains_a_non_visible_segment')
        entries = sorted(self.manifest['pools'], key=lambda item: item['pool'])
        if [entry['pool'] for entry in entries] != sorted(self.segments):
            raise PackError('pack_pools_and_segments_differ')
        if any(entry['sha256'] in self.sealed for entry in entries):
            raise PackError('sealed_file_in_pack')
        present = sorted(path.name for path in self.directory.glob('*.json.gz'))
        if present != [entry['file'] for entry in entries]:
            raise PackError('pack_files_differ_from_manifest')
        self.entries = entries
        self.files_read = {'MANIFEST.json': self.manifest_sha256, 'SEGMENTS.json': block['segments_sha256'],
                           'SEALED_SHA256.txt': block['sealed_sha256']}

    def pools_of(self, segment):
        return {pool for pool, name in self.segments.items() if name == segment}

    def pools(self):
        for entry in self.entries:
            if entry['file'] != f"{entry['pool']}.json.gz":
                raise PackError('file_name_mismatch:%s' % entry['file'])
            data = (self.directory / entry['file']).read_bytes()
            digest = _sha(data)
            if digest != entry['sha256'] or digest in self.sealed:
                raise PackError('pool_file_refused:%s' % entry['file'])
            archive = _archive(data, entry)        # the very bytes that were hashed
            _guard_slots(archive)
            self.files_read[entry['file']] = digest
            yield entry, archive, self.segments[entry['pool']]
