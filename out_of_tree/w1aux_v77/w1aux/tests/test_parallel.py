"""w1aux.parallel (R02 T-1, options c and e): pool-parallel, resumable, byte-identical replays."""
import contextlib
import hashlib
import json
import types
from pathlib import Path

import pytest

from bot.master_v2 import harness
from bot.master_v2 import w1_run as run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from w1aux import lazy, synthetic
from w1aux import parallel as P

PACK = Path('tests/fixtures/launchlab_sol_pools')
ENV = {'RUGGER_NO_DOTENV': '1'}


def _bundles(pack):
    """Every frozen replay kind of run_trials on ``pack``: V2 arms and the L1 replay (declared rate)."""
    params = hrr.ReplayParams(**dict(vars(run.l1_params()), sol_usd=150.0, sol_usd_provenance='TEST_DECLARED'))
    out = {}
    for trial_id, (make, rule) in run.V2_ARMS.items():
        out[trial_id] = harness.run_policy(pack, make(), rule, run.v2_params())['bundle_sha256']
    history = hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pack)[2]], 'manifest')
    out['L1'] = hrr.run_replay(pack, params, None, run.L1_EXIT, history, placebo_arm=True)['bundle_sha256']
    out['L1_event'] = hrr.run_replay(pack, params, None, hrr.ExitOptions(), history, placebo_arm=True)['bundle_sha256']
    return out


@pytest.fixture(scope='module')
def sequential():
    return _bundles(PACK)


@pytest.mark.parametrize('workers, use_lazy', [(1, True), (2, True), (3, False), (4, True)])
def test_parallel_bundles_are_byte_identical(sequential, workers, use_lazy):
    with (lazy.lazy_archives() if use_lazy else contextlib.nullcontext()), P.parallel_replays(workers):
        assert hrr.run_replay.__module__ == harness.run_policy.__module__ == 'w1aux.parallel'
        got = _bundles(PACK)
    assert got == sequential
    assert hrr.run_replay.__module__ == 'bot.p4.historical_research_replay'           # restored
    assert harness.run_policy.__module__ == 'bot.master_v2.harness'


def test_checkpoint_resume_reuses_verified_results_and_detects_changes(sequential, tmp_path):
    with lazy.lazy_archives(), P.parallel_replays(2, tmp_path / 'cp') as stats:
        before = dict(stats)
        assert _bundles(PACK) == sequential
        first = dict(computed=stats['computed'] - before['computed'], reused=stats['reused'] - before['reused'])
    assert first['computed'] > 0 and first['reused'] == 0
    with lazy.lazy_archives(), P.parallel_replays(3, tmp_path / 'cp') as stats:     # resumed session
        before = dict(stats)
        assert _bundles(PACK) == sequential
        assert stats['computed'] == before['computed'] and stats['reused'] - before['reused'] == first['computed']
    victim = sorted((tmp_path / 'cp').glob('*.pkl'))[0]
    victim.write_bytes(victim.read_bytes() + b'\0')
    with lazy.lazy_archives(), P.parallel_replays(2, tmp_path / 'cp'):
        with pytest.raises(P.ParallelError, match='checkpoint_file_changed'):
            _bundles(PACK)
    with P.parallel_replays(2, tmp_path / 'cp2'):                                    # eager archives: no key
        with pytest.raises(P.ParallelError, match='checkpoint_needs_lazy_archives'):
            _bundles(PACK)


def test_call_key_depends_on_every_argument():
    P._ACTIVE['frozen_code'] = 'f' * 64
    base = P.call_key('replay_pool', [], dict(params=hrr.ReplayParams(), window=dict(a=1), arms=('master',)))
    assert base == P.call_key('replay_pool', [], dict(params=hrr.ReplayParams(), window=dict(a=1), arms=('master',)))
    for kwargs in (dict(params=hrr.ReplayParams(latency_slots=10), window=dict(a=1), arms=('master',)),
                   dict(params=hrr.ReplayParams(), window=dict(a=2), arms=('master',)),
                   dict(params=hrr.ReplayParams(), window=dict(a=1), arms=['master'])):
        assert P.call_key('replay_pool', [], kwargs) != base
    assert P.call_key('run_policy_pool', [], dict(params=hrr.ReplayParams(), window=dict(a=1), arms=('master',))) != base
    with pytest.raises(P.ParallelError, match='cannot_key'):
        P.call_key('replay_pool', [], dict(x=object()))
    with pytest.raises(P.ParallelError, match='non_string'):
        P.call_key('replay_pool', [], dict(x={1: 2}))


def _fake(per_pool):
    module = types.SimpleNamespace(f=per_pool)

    def frozen(values, shift=None):
        out, excluded = [], []
        for n, v in enumerate(values):
            try:
                out.append(module.f(v, k=v + (shift(n) if shift else 0)))
            except hrr.PoolExcluded as exc:
                excluded.append(exc.reasons)
        return out, excluded
    return module, frozen


def test_assembly_refuses_a_call_that_differs_from_the_probe_and_keeps_exclusions():
    def per_pool(v, k):
        if v == 2:
            raise hrr.PoolExcluded(['too_small'])
        return v * 10 + k
    module, frozen = _fake(per_pool)
    assert P._run(module, 'f', frozen, ([1, 2, 3],), {}, 2, None) == frozen([1, 2, 3])
    assert module.f is per_pool
    calls = {'n': 0}

    def drifting(n):                                     # second pass sees other arguments
        calls['n'] += 1
        return 0 if calls['n'] <= 3 else 1
    with pytest.raises(P.ParallelError, match='differs_from_probe'):
        P._run(module, 'f', frozen, ([1, 2, 3],), dict(shift=drifting), 2, None)
    assert module.f is per_pool


def test_worker_errors_propagate_and_guards():
    def per_pool(v, k):
        raise ZeroDivisionError('boom')
    module, frozen = _fake(per_pool)
    with pytest.raises(ZeroDivisionError):
        P._run(module, 'f', frozen, ([1, 2, 3],), {}, 2, None)
    for bad in (0, -1, 1.0, '2'):
        with pytest.raises(P.ParallelError, match='positive_integer'):
            with P.parallel_replays(bad):
                pass
    with P.parallel_replays(2):
        with pytest.raises(P.ParallelError, match='not_reentrant'):
            with P.parallel_replays(2):
                pass
    assert hrr.run_replay.__module__ == 'bot.p4.historical_research_replay'


def _series(root):
    point = dict(schema=sus.POINT_SCHEMA, slot=464661843 - 50, transaction_index=0, block_time=1793658217 - 12,
                 received_at_ms=None, publish_time=1793658217 - 13, price=15_000_000_000, exponent=-8,
                 confidence=7_500_000, source_kind='pyth_onchain_account', source_ref='synthetic',
                 evidence_sha256='0' * 64, signature=None)
    path = root / 's.json'
    path.write_text(json.dumps(dict(schema=sus.SERIES_SCHEMA, label='COLLECTED', points=[point],
                                    acceptance=dict(max_age_ms=120000, max_confidence_ppm=1000))))
    return path


def test_full_run_trials_chain_identical_sequential_and_parallel(tmp_path, monkeypatch):
    """The whole frozen run_trials (registries, every bundle, SHA256SUMS) on a synthetic x2 pack."""
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    pack = tmp_path / 'pack'
    synthetic.build(pack, 2)
    series = _series(tmp_path)
    files = {}
    for mode in ('seq', 'par'):
        root = tmp_path / mode
        root.mkdir()
        with lazy.lazy_archives(), (P.parallel_replays(4, root / 'cp') if mode == 'par' else contextlib.nullcontext()):
            run.run_trials(pack, series, registry_path=root / 't.jsonl', sensitivity_registry_path=root / 's.jsonl',
                           registered_at='2026-11-09T00:00:00+00:00', out=root / 'out')
        files[mode] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(root.rglob('*')) if p.is_file() and 'cp' not in p.relative_to(root).parts}
    assert files['seq'] == files['par'] and 'out/bundles/L1.json.gz' in files['seq']


# --- R02 P-1: the frozen determinism re-runs must stay real checks with a checkpoint -------------

def _run_trials(root, series, ctx):
    root.mkdir()
    with lazy.lazy_archives(), ctx:
        run.run_trials(PACK, series, registry_path=root / 't.jsonl', sensitivity_registry_path=root / 's.jsonl',
                       registered_at='2026-11-09T00:00:00+00:00', out=root / 'out')
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and 'cp' not in p.relative_to(root).parts}


def test_occurrence_is_part_of_the_key():
    P._ACTIVE['frozen_code'] = 'f' * 64
    args = ([], dict(params=hrr.ReplayParams()))
    assert P.call_key('replay_pool', *args) == P.call_key('replay_pool', *args, 0)
    assert len({P.call_key('replay_pool', *args, n) for n in range(3)}) == 3
    for bad in (-1, 1.0, '1', None):
        with pytest.raises(P.ParallelError, match='invalid_occurrence'):
            P.call_key('replay_pool', *args, bad)


def test_run_trials_with_checkpoint_recomputes_the_determinism_reruns_then_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    series = _series(tmp_path)
    cp = tmp_path / 'cp'
    before = dict(P.STATS)                                                    # (i) fresh run: nothing reused
    fresh = _run_trials(tmp_path / 'a', series, P.parallel_replays(2, cp))
    first = dict(computed=P.STATS['computed'] - before['computed'], reused=P.STATS['reused'] - before['reused'])
    pools = len(json.loads((PACK / 'MANIFEST.json').read_text())['pools'])
    assert first['reused'] == 0 and first['computed'] == (8 + 5) * pools     # 8 L1 replays (4 x 2) + 5 V2
    before = dict(P.STATS)                                                    # (ii) second session: all reused
    again = _run_trials(tmp_path / 'b', series, P.parallel_replays(3, cp))
    assert P.STATS['computed'] == before['computed'] and P.STATS['reused'] - before['reused'] == first['computed']
    plain = _run_trials(tmp_path / 'c', series, contextlib.nullcontext())
    assert fresh == again == plain


@pytest.mark.parametrize('mode', ['sequential', 'parallel_checkpoint'])
def test_injected_non_determinism_on_the_second_occurrence_fails_run_trials(tmp_path, monkeypatch, mode):
    """(iii) a per-pool result that changes on the second identical call is caught by the frozen check."""
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
    series = _series(tmp_path)
    original, seen = hrr.replay_pool, {}

    def drifting(archive, params, **kwargs):
        record = original(archive, params, **kwargs)
        key = (archive.pool, repr(params), repr(kwargs.get('exit_options')))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            record = dict(record, trades=record['trades'] + 1)
        return record
    monkeypatch.setattr(hrr, 'replay_pool', drifting)
    ctx = P.parallel_replays(1, tmp_path / 'cp') if mode == 'parallel_checkpoint' else contextlib.nullcontext()
    with pytest.raises(run.W1RunError, match='l1_replay_not_deterministic'):
        _run_trials(tmp_path / 'r', series, ctx)
