"""W1 protocol R2: causal prior_launches for the Master scorer (CreatorHistory, unused by default).

prior_launches of a pool = verified creations by the same signer strictly before the pool's
creation transaction (slot, transaction index) in the collected set. Without a history the
scorer keeps prior_launches = 0 and every recorded L1 fingerprint is unchanged.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from bot.market.launchlab_events import WSOL_MINT
from bot.p4 import historical_research_replay as hrr

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
C7F9 = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'          # verified creator, creation (464661843, 108)
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'          # creator not verified
C7F9_CREATOR = 'BMsQK31aGf2VnWp7KoCvc78NuvPPzj1baBoEPSSRxjAD'
P5PZ_CREATOR = 'zXGT3P1BDDCBriUhscEC7ANRcGJ1EUbKSrdMRCSx8k7'
DECLARED = hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')


def _archive(pool):
    return next(archive for _entry, archive in hrr.load_fixtures(PACK)[2] if archive.pool == pool)


def _history(*rows, label='test'):
    return hrr.CreatorHistory(rows, label)


def test_count_is_strictly_before_by_slot_then_transaction_index():
    history = _history(('A', 10, 5, 'p1'), ('A', 10, 7, 'p2'), ('A', 12, 0, 'p3'), ('B', 9, 0, 'p4'))
    assert history.prior_launches('A', (10, 5)) == 0          # its own creation is not counted
    assert history.prior_launches('A', (10, 6)) == 1          # same slot, later transaction
    assert history.prior_launches('A', (10, 7)) == 1
    assert history.prior_launches('A', (12, 0)) == 2
    assert history.prior_launches('A', (99, 0)) == 3
    assert history.prior_launches('B', (99, 0)) == 1 and history.prior_launches('C', (99, 0)) == 0


def test_rows_are_validated_and_the_digest_does_not_depend_on_order():
    rows = [('A', 10, 5, 'p1'), ('B', 9, 0, 'p4')]
    assert _history(*rows).sha256 == _history(*reversed(rows)).sha256
    assert _history(*rows).record() == dict(label='test', creations=2, sha256=_history(*rows).sha256,
                                            rule=hrr.CreatorHistory.RULE)
    for bad in ((('', 1, 0, 'p'),), (('A', '1', 0, 'p'),), (('A', 1, None, 'p'),), (('A', 1, 0, 'p'), ('B', 2, 0, 'p')),
                (('A', None, 0, 'p'), ('A', 1, 0, 'q')), (('A', 1, 0),)):           # mixed types (R02 O-R2-2)
        with pytest.raises(ValueError):
            hrr.CreatorHistory(bad, 'x')
    with pytest.raises(ValueError, match='creator_history_label_required'):
        hrr.CreatorHistory([], ' ')


def test_history_from_the_fixtures_keeps_verified_creators_only():
    history = hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest')
    assert history.creations == 2 and set(history.by_creator) == {C7F9_CREATOR, 'Gy19aP52ydB8wXmi5EpqcwJh1BSACyubeh6mGaKytZSL'}
    assert history.prior_launches(C7F9_CREATOR, (464661843, 108)) == 0


def test_default_bundle_is_unchanged_and_the_history_is_recorded_when_given():
    default = hrr.run_replay(PACK, DECLARED)
    assert 'creator_history' not in default and all('prior_launches' not in p for p in default['pools'])
    assert default['flags']['creator_prior_launches_assumed'] == 0
    history = hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest')
    given = hrr.run_replay(PACK, DECLARED, creator_history=history)
    assert given['creator_history'] == history.record()
    assert given['flags']['creator_prior_launches_assumed'] is None
    assert given['flags']['creator_prior_launches_source'] == 'creator_history:manifest'
    assert {p['pool']: p['prior_launches'] for p in given['pools']} == {C7F9: 0, P5PZ: 0,
                                                                      'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r': 0}


def _scores(pool, history):
    record = hrr.replay_pool(_archive(pool), DECLARED, quote_mint=WSOL_MINT, creator_history=history)
    return record, [row['score'] for row in record['journal'] if row['arm'] == 'master']


def test_scorer_receives_the_causal_count(monkeypatch):
    frames = []
    original = hrr._PoolObserver._evaluate

    def spy(self, history):
        result = original(self, history)
        frames.append((self.pool, self.prior_launches))
        return result
    monkeypatch.setattr(hrr._PoolObserver, '_evaluate', spy)
    earlier = _history((C7F9_CREATOR, 464661000, 1, 'old1'), (C7F9_CREATOR, 464661843, 107, 'old2'),
                       (C7F9_CREATOR, 464661843, 108, C7F9), (C7F9_CREATOR, 464661900, 0, 'later'))
    record, scored = _scores(C7F9, earlier)
    assert record['prior_launches'] == 2 and {p for pool, p in frames if pool == C7F9} == {2}
    _record, baseline = _scores(C7F9, None)
    pairs = [(a, b) for a, b in zip(baseline, scored) if a is not None]
    assert pairs and all(b >= a for a, b in pairs) and any(b > a for a, b in pairs)   # creator_recurrent


def test_unverified_creator_keeps_zero():
    history = _history((P5PZ_CREATOR, 1, 0, 'old'))
    record = hrr.replay_pool(_archive(P5PZ), DECLARED, quote_mint=WSOL_MINT, creator_history=history)
    assert record['prior_launches'] == 0


def test_cli_flag(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location('hrr_cli', ROOT / 'tools' / 'historical_research_replay.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / 'b.json'
    cli.main(['--fixtures', str(PACK), '--creator-history-from-manifest', '--out', str(out)])
    capsys.readouterr()
    assert json.loads(out.read_text('utf-8'))['creator_history']['label'] == 'manifest'
