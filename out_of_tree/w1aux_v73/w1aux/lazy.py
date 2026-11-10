"""Lazy pool archives: run the FROZEN W1 chain without holding every archive in memory.

The frozen loader ``hrr.load_fixtures`` parses every pool archive of the pools directory and the
chain keeps them all (and, in ``w1_run.run_trials``, twice at once): about 30 KB of memory per
stored transaction, i.e. far more than the session's RAM for W1. ``lazy_archives()`` replaces,
for the duration of a ``with`` block, ``hrr.load_fixtures`` by a loader that performs the SAME
checks on the SAME bytes (file name, sha256 against the MANIFEST, pool of the parsed archive) and
returns ``LazyArchive`` objects backed by a cache of ONE pool (R02 C-Z1): the last parsed archive,
keyed by its path; a different pool re-reads its file, checks its sha256 again and replaces the
cache. Memory is bounded by the largest pool, parses are O(number of pools) instead of one per
event, and a mutation of a pool's archive behaves as with the full load while that pool is used.
The frozen code, the data and therefore the bundles are unchanged (byte-identical outputs, tested);
only the moment of parsing and the memory differ.
No network, no change to any rule.
"""
import contextlib
import gzip
import hashlib
import json
from pathlib import Path

from bot.market.collector import PoolArchive
from bot.p4 import historical_research_replay as hrr


class LazyArchiveError(RuntimeError):
    pass


_CACHE = {'path': None, 'archive': None}
PARSES = {}                                                   # path -> number of parses (tests, R02 C-Z1)


def clear_cache():
    _CACHE.update(path=None, archive=None)


class LazyArchive(PoolArchive):
    """A PoolArchive whose content comes from its checked file through the one-pool cache."""

    def __init__(self, path, pool, sha256):                 # noqa: no dataclass __init__: nothing is held
        object.__setattr__(self, '_path', Path(path))
        object.__setattr__(self, '_pool', pool)
        object.__setattr__(self, '_sha256', sha256)

    def _data(self):
        data = self._path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self._sha256:
            raise LazyArchiveError(f'archive_changed_on_disk:{self._path.name}')
        return json.loads(gzip.decompress(data))

    def _archive(self):
        if _CACHE['path'] != self._path:
            _CACHE.update(path=None, archive=None)            # release the previous pool first
            archive = PoolArchive.from_json(self._data())
            PARSES[self._path] = PARSES.get(self._path, 0) + 1
            _CACHE.update(path=self._path, archive=archive)
        return _CACHE['archive']

    @property
    def pool(self):
        return self._pool

    @property
    def account(self):
        return self._archive().account

    @property
    def signatures(self):
        return self._archive().signatures

    @property
    def signatures_complete(self):
        return self._archive().signatures_complete

    @property
    def transactions(self):
        return self._archive().transactions

    def __setattr__(self, name, value):
        raise LazyArchiveError('lazy_archive_is_read_only')

    def __repr__(self):
        return f'LazyArchive({self._pool})'


def load_fixtures_lazy(directory):
    """Same contract and checks as hrr.load_fixtures; archives returned as LazyArchive."""
    directory = Path(directory)
    raw = (directory / 'MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    digests, pools = {}, []
    for entry in sorted(manifest['pools'], key=lambda item: item['pool']):
        if entry['file'] != f"{entry['pool']}.json.gz":
            raise ValueError(f"fixture_file_name_mismatch:{entry['file']}")
        data = (directory / entry['file']).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f"fixture_sha256_mismatch:{entry['file']}")
        archive = PoolArchive.from_json(json.loads(gzip.decompress(data)))      # parsed once to check, then dropped
        if archive.pool != entry['pool']:
            raise ValueError(f"fixture_pool_mismatch:{entry['file']}")
        del archive, data
        digests[entry['file']] = digest
        pools.append((entry, LazyArchive(directory / entry['file'], entry['pool'], digest)))
    return hashlib.sha256(raw).hexdigest(), digests, pools, manifest


@contextlib.contextmanager
def lazy_archives():
    """Within the block, every frozen caller of hrr.load_fixtures gets lazy archives."""
    original = hrr.load_fixtures
    hrr.load_fixtures = load_fixtures_lazy
    clear_cache()
    try:
        yield
    finally:
        hrr.load_fixtures = original
        clear_cache()
