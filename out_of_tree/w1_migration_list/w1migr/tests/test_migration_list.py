"""w1migr: the migrated-pool list, its fixed pilot selection and its read whitelist."""
import gzip
import hashlib
import json

import pytest

from w1migr import migration_list as M


def _pool(name, slot=None, index=0, extra=True):
    pool = dict(pool=name, creation_slot=1, creator='C' + name, trades=7)
    if extra:
        pool['arms'] = dict(master=dict(outcome='closed', pnl_lamports=123, net_return=0.5))
        pool['journal'] = [dict(score=9)]
    if slot is not None:
        pool['migration'] = dict(rule='r', boundary_signatures=['s'], boundary_slot=slot,
                                 boundary_transaction_index=index, max_progress_ppm=1_000_000)
    return pool


def _bundle(n=13):
    pools = [_pool(f'p{i:02d}', slot=467_700_000 + (i % 5) * 10, index=12 - i) for i in range(n)]
    pools += [_pool('early', slot=467_678_394), _pool('edge_low', slot=467_678_395), _pool('edge_high', slot=469_291_345),
              _pool('none')]
    return dict(pools=pools, excluded_pools=[dict(pool='x_after', reasons=['events_after_migration_boundary']),
                                             dict(pool='x_other', reasons=['signatures_incomplete'])])


def test_members_rule_pilot_order_and_counts():
    doc = M.migration_list(_bundle())
    names = [m['pool'] for m in doc['members']]
    assert 'early' not in names and 'edge_high' not in names and 'none' not in names    # [min, max)
    assert names[0] == 'edge_low' and len(names) == 14
    keys = [(m['boundary_slot'], m['boundary_transaction_index'], m['pool']) for m in doc['members']]
    assert keys == sorted(keys)
    assert doc['pilot'] == names[:10] and doc['counts'] == dict(members=14, pilot=10, migrated_without_slot=1)
    assert doc['migrated_without_slot'] == ['x_after']
    assert doc['limits'] == [M.POPULATION_LIMIT] and 'created before W1' in M.POPULATION_LIMIT
    assert doc['flags'] == dict(values_read=False, arms_read=False, counted_in_n=False, official_w1_verdict=False)
    # same slot: the transaction index decides, then the pool
    same = [m for m in doc['members'] if m['boundary_slot'] == 467_700_000]
    assert [m['boundary_transaction_index'] for m in same] == sorted(m['boundary_transaction_index'] for m in same)


def test_output_has_no_value_arm_or_progress():
    text = json.dumps(M.migration_list(_bundle()))
    for word in ('pnl', 'net_return', 'master', 'closed', 'score', 'max_progress', 'creator', 'trades', 'journal'):
        assert word not in text, word


class _Spy(dict):
    def __init__(self, data, log, path):
        super().__init__({k: _spy(v, log, path + (k,)) for k, v in data.items()})
        self._log, self._path = log, path

    def __getitem__(self, key):
        self._log.add(self._path + (key,))
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._log.add(self._path + (key,))
        return super().get(key, default)


def _spy(value, log, path):
    if isinstance(value, dict):
        return _Spy(value, log, path)
    if isinstance(value, list):
        return [_spy(v, log, path + ('[]',)) for v in value]
    return value


def test_only_the_whitelisted_fields_are_read():
    log = set()
    M.migration_list(_spy(_bundle(), log, ('b',)))
    allowed = {('b', 'pools'), ('b', 'pools', '[]', 'pool'), ('b', 'pools', '[]', 'migration'),
               ('b', 'pools', '[]', 'migration', 'boundary_slot'),
               ('b', 'pools', '[]', 'migration', 'boundary_transaction_index'), ('b', 'excluded_pools'),
               ('b', 'excluded_pools', '[]', 'pool'), ('b', 'excluded_pools', '[]', 'reasons')}
    assert log - allowed == set(), sorted(log - allowed)
    assert ('b', 'pools', '[]', 'migration', 'boundary_slot') in log


def test_guards_and_run(tmp_path):
    with pytest.raises(M.MigrationListError, match='invalid_slot_range'):
        M.migration_list(_bundle(), slot_min=5, slot_max=5)
    bad = _bundle()
    bad['pools'].append(_pool('p00'))
    with pytest.raises(M.MigrationListError, match='duplicate_pool_in_bundle'):
        M.migration_list(bad)
    broken = _bundle()
    broken['pools'][0]['migration']['boundary_slot'] = None
    with pytest.raises(M.MigrationListError, match='migration_without_slot:p00'):
        M.migration_list(broken)
    raw = gzip.compress(json.dumps(_bundle()).encode(), mtime=0)
    (tmp_path / 'L1.json.gz').write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(M.MigrationListError, match='bundle_is_not_the_anchored_one'):
        M.run(tmp_path / 'L1.json.gz', '0' * 64, tmp_path / 'o')
    assert M.main(['--l1-bundle', str(tmp_path / 'L1.json.gz'), '--bundle-sha256', sha, '--out', str(tmp_path / 'out')]) == 0
    doc = json.loads((tmp_path / 'out' / 'MIGRATION_LIST.json').read_text())
    assert doc['input'] == dict(bundle_sha256=sha) and doc['counts']['members'] == 14
    with pytest.raises(M.MigrationListError, match='output_exists'):
        M.run(tmp_path / 'L1.json.gz', sha, tmp_path / 'out')
