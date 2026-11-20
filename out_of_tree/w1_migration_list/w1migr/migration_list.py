"""w1migr 0.1.1 — READ-ONLY list of the W1 pools that reached the LaunchLab migration boundary (population of the frozen
HW1-M2 / pilot CPMM), admitted by RUGGER 02 before the official W1 verdict (f5ad8d36): a population fact, no value.

INPUT: the L1 bundle (sha256 given, the one the anchored ledger recorded). Only these fields are read (tested):
``pools[].pool``, ``pools[].migration.boundary_slot``, ``pools[].migration.boundary_transaction_index``,
``excluded_pools[].pool``, ``excluded_pools[].reasons``. No arm, journal, trade, value or progress is read.

RULE (collection draft v0.3, R02): member if the migration boundary slot is in [slot_min, slot_max). The boundary is
the slot of the first buy that crosses the migration boundary (frozen ``usable_timeline``). A pool excluded from the
replay ONLY because events follow its migration boundary (``events_after_migration_boundary``) has migrated too, but
its slot is not in the bundle: it is listed apart, never selected, and counted.

PILOT SELECTION (fixed before any look): the first ``pilot_size`` members by (boundary slot, transaction index,
pool), nothing else.

OUTPUT: ``MIGRATION_LIST.json`` (rule, declared limit (POPULATION_LIMIT), counts, members with pool id and boundary slot/index, pilot list, migrated
pools without slot). Nothing is printed. Out of N (population).
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

SCHEMA = 'rugger-w1-migration-list-v0.1.1'
POPULATION_LIMIT = ('population = the EXPORTED pools, i.e. created in the collected window: a pool created before W1 '
                    'and migrated during W1 is not in it (R02 45813426)')
SLOT_MIN, SLOT_MAX, PILOT_SIZE = 467_678_395, 469_291_345, 10
AFTER_BOUNDARY = 'events_after_migration_boundary'


class MigrationListError(RuntimeError):
    pass


def migration_list(bundle, *, slot_min=SLOT_MIN, slot_max=SLOT_MAX, pilot_size=PILOT_SIZE):
    if not (type(slot_min) is int and type(slot_max) is int and slot_min < slot_max):
        raise MigrationListError('invalid_slot_range')
    members, seen = [], set()
    for pool in bundle['pools']:
        name = pool['pool']
        if name in seen:
            raise MigrationListError('duplicate_pool_in_bundle')
        seen.add(name)
        migration = pool.get('migration')
        if migration is None:
            continue
        slot, index = migration['boundary_slot'], migration['boundary_transaction_index']
        if type(slot) is not int or type(index) is not int:
            raise MigrationListError('migration_without_slot:' + name)
        if slot_min <= slot < slot_max:
            members.append(dict(pool=name, boundary_slot=slot, boundary_transaction_index=index))
    members.sort(key=lambda m: (m['boundary_slot'], m['boundary_transaction_index'], m['pool']))
    without_slot = sorted(p['pool'] for p in bundle.get('excluded_pools') or []
                          if AFTER_BOUNDARY in (p.get('reasons') or []))
    return dict(schema=SCHEMA, category='POPULATION_FACT',
                rule=dict(member=f'migration boundary slot in [{slot_min}, {slot_max})', slot_min=slot_min,
                          slot_max=slot_max, boundary='slot of the first buy crossing the LaunchLab migration boundary',
                          pilot=f'first {pilot_size} members by (boundary slot, transaction index, pool)'),
                limits=[POPULATION_LIMIT],
                counts=dict(members=len(members), pilot=min(pilot_size, len(members)),
                            migrated_without_slot=len(without_slot)),
                members=members, pilot=[m['pool'] for m in members[:pilot_size]],
                migrated_without_slot=without_slot,
                flags=dict(values_read=False, arms_read=False, counted_in_n=False, official_w1_verdict=False))


def run(bundle_path, bundle_sha256, out_dir, **kwargs):
    raw = Path(bundle_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != bundle_sha256:
        raise MigrationListError('bundle_is_not_the_anchored_one')
    out = Path(out_dir)
    if out.exists():
        raise MigrationListError('output_exists')
    doc = migration_list(json.loads(gzip.decompress(raw)), **kwargs)
    doc['input'] = dict(bundle_sha256=bundle_sha256)
    out.mkdir(parents=True)
    path = out / 'MIGRATION_LIST.json'
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--l1-bundle', type=Path, required=True)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    run(a.l1_bundle, a.bundle_sha256, a.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
