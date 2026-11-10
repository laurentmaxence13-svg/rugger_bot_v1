"""w1aux.lazy (R02 audit 21ba4f9a, C-Z1): one-pool cache, parses O(pools) per pass, byte-identical outputs."""
import gzip
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from bot.market.collector import PoolArchive, summarize
from bot.market.launchlab_curve import fee_for
from bot.market.launchlab_events import TradeEvent, check_trade
from bot.market.pool_timeline import build_timeline
from bot.market import w1_collection
from bot.master_v2 import harness
from bot.master_v2 import w1_run as run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from w1aux import lazy

PACK = Path('tests/fixtures/launchlab_sol_pools')
C7F9 = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
DECLARED = dict(sol_usd=150.0, sol_usd_provenance='REHEARSAL_DECLARED_NOT_FOR_ECONOMICS')


def _parses(pack, call):
    lazy.PARSES.clear()
    with lazy.lazy_archives():
        out = call()
    return out, {path.name: n for path, n in lazy.PARSES.items() if Path(path).parent == Path(pack)}


def test_one_pass_parses_each_pool_at_most_three_times_whatever_its_size():
    entries = {e['file']: e for e in json.loads((PACK / 'MANIFEST.json').read_text())['pools']}
    for name, call in (
            ('v2', lambda: harness.run_policy(PACK, run.V2_ARMS['S1'][0](), run.V2_ARMS['S1'][1], run.v2_params())),
            ('l1', lambda: hrr.run_replay(PACK, hrr.ReplayParams(**dict(vars(run.l1_params()), **DECLARED)),
                                          None, run.L1_EXIT, None, placebo_arm=True))):
        _out, parses = _parses(PACK, call)
        assert set(parses) == set(entries), name
        assert all(1 <= n <= 3 for n in parses.values()), (name, parses)
        sizes = {f: entries[f]['signatures'] for f in parses}
        assert max(sizes.values()) > 3 * min(sizes.values())                # independent of the number of events


def test_full_chain_is_byte_identical_eager_and_lazy(tmp_path):
    point = dict(schema=sus.POINT_SCHEMA, slot=464661843 - 50, transaction_index=0, block_time=1793658217 - 12,
                 received_at_ms=None, publish_time=1793658217 - 13, price=15_000_000_000, exponent=-8,
                 confidence=7_500_000, source_kind='pyth_onchain_account', source_ref='synthetic-test-account',
                 evidence_sha256='0' * 64, signature=None)
    (tmp_path / 's.json').write_text(json.dumps(dict(schema=sus.SERIES_SCHEMA, label='COLLECTED', points=[point],
                                                     acceptance=dict(max_age_ms=120_000, max_confidence_ppm=1_000))))
    mp = pytest.MonkeyPatch()
    mp.setenv('RUGGER_NO_DOTENV', '1')
    try:
        for name in ('eager', 'lazy'):
            o = tmp_path / name
            o.mkdir()

            def chain():
                run.run_trials(PACK, tmp_path / 's.json', registry_path=o / 't.jsonl', sensitivity_registry_path=o / 's.jsonl',
                               registered_at='2026-11-08T00:00:00+00:00', out=o / 'out')
                run.evaluate(PACK, o / 'out', 464661843 - w1_collection.WARMUP_SLOTS, registry_paths=[o / 't.jsonl'],
                             registry_path=o / 't.jsonl', sensitivity_registry_path=o / 's.jsonl', n_boot=200)
            if name == 'lazy':
                _out, parses = _parses(PACK, chain)
                assert all(n <= 40 for n in parses.values()), parses           # a bounded number of passes, not per event
            else:
                chain()
    finally:
        mp.undo()
    files = sorted(p.relative_to(tmp_path / 'eager') for p in (tmp_path / 'eager').rglob('*') if p.is_file())
    assert files and files == sorted(p.relative_to(tmp_path / 'lazy') for p in (tmp_path / 'lazy').rglob('*') if p.is_file())
    for rel in files:
        a, b = (tmp_path / 'eager' / rel).read_bytes(), (tmp_path / 'lazy' / rel).read_bytes()
        if rel.suffix == '.jsonl':                                          # registries: registered_at is the same input
            a, b = [json.loads(x) for x in a.splitlines()], [json.loads(x) for x in b.splitlines()]
        assert a == b, rel


def _crossing(previous, signature, rate=12_500):
    state = previous.state_after()
    amount_in = 10 ** 14
    fee = fee_for(amount_in, rate)
    values = {name: getattr(previous, name) for name in (
        'slot', 'block_time', 'fee_payer', 'pool', 'pool_status', 'total_base_sell', 'virtual_base', 'virtual_quote')}
    values.update(signature=signature, event_index=0, side='buy', exact_in=True,
                  real_base_before=state.real_base, real_quote_before=state.real_quote,
                  real_base_after=state.total_base_sell, real_quote_after=state.real_quote + amount_in - fee,
                  amount_in=amount_in, amount_out=state.total_base_sell - state.real_base,
                  protocol_fee=fee, platform_fee=0, creator_fee=0, share_fee=0)
    return TradeEvent(violations=check_trade(values), **values)


def _migrated_pack(tmp_path, boundary=18):
    """The frozen pack with C7F9 cut at its event ``boundary`` (on disk), which becomes the migrating buy."""
    pack = tmp_path / 'migrated'
    shutil.copytree(PACK, pack)
    manifest = json.loads((pack / 'MANIFEST.json').read_text())
    entry = next(e for e in manifest['pools'] if e['pool'] == C7F9)
    archive = PoolArchive.from_json(json.loads(gzip.decompress((pack / entry['file']).read_bytes())))
    timeline = summarize(archive)[1]
    cut = hrr._tx_key(archive.transactions[timeline.events[boundary].signature])
    data = archive.to_json()
    data['transactions'] = {s: tx for s, tx in archive.transactions.items() if hrr._tx_key(tx) <= cut}
    data['signatures'] = [r for r in archive.signatures if r['signature'] in data['transactions'] or r.get('err') is not None]
    raw = gzip.compress(json.dumps(data).encode(), mtime=0)
    (pack / entry['file']).write_bytes(raw)
    entry['sha256'] = hashlib.sha256(raw).hexdigest()
    (pack / 'MANIFEST.json').write_text(json.dumps(manifest))
    return pack, timeline.events[boundary].signature


def test_migrated_pool_reads_through_the_cache_identically(tmp_path, monkeypatch):
    pack, signature = _migrated_pack(tmp_path)
    real = hrr.summarize

    def summarize_with_crossing(archive):                     # the archive is NOT mutated (lazy archives are read-only)
        summary, timeline = real(archive)
        if archive.pool != C7F9:
            return summary, timeline
        kept = [e for e in timeline.events if e.signature != signature]
        migrated = build_timeline(C7F9, kept + [_crossing(kept[-1], signature)])
        return dict(summary, complete=False, trades=len(migrated.events), rejected=1,
                    max_progress_ppm=max(e.state_after().progress_ppm for e in kept)), migrated
    monkeypatch.setattr(hrr, 'summarize', summarize_with_crossing)
    params = hrr.ReplayParams(**dict(vars(run.l1_params()), **DECLARED))
    eager = hrr.run_replay(pack, params, None, run.L1_EXIT, None, placebo_arm=True)
    lazy_doc, parses = _parses(pack, lambda: hrr.run_replay(pack, params, None, run.L1_EXIT, None, placebo_arm=True))
    assert [p['pool'] for p in eager['pools'] if 'migration' in p] == [C7F9]       # usable_timeline l. 700-701 was read
    assert json.dumps(eager, sort_keys=True) == json.dumps(lazy_doc, sort_keys=True)
    assert all(n <= 3 for n in parses.values()), parses
