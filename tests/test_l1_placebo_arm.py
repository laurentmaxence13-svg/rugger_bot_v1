"""W1 protocol R9: placebo P1b in the L1 replay (opt-in).

Entry rule of the V2 placebo-random-entry (hashed age in 0..120 s, salt 'v1', signed creator
required), never where the Master scorer waits on its inputs; exit exactly the Master arm's
(scorer TP/SL at the entry decision, research horizon, same ExitOptions). Off by default: the
two historical arms and every recorded fingerprint are unchanged.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from bot.master_v2 import policies as pol
from bot.p4 import historical_research_replay as hrr

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
DVP = 'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r'          # verified creator, target age 11 s
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'          # creator not verified
DECLARED = hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')


def _pool(bundle, pool):
    return next(p for p in bundle['pools'] if p['pool'] == pool)


def test_target_age_is_the_v2_placebo_rule():
    for _entry, archive in hrr.load_fixtures(PACK)[2]:
        assert hrr.placebo_target_age(archive.pool) == pol.RandomEntry().target_age(archive.pool)
    assert (hrr.PLACEBO_MAX_AGE_S, hrr.PLACEBO_SALT) == (pol.RandomEntry().max_age_s, pol.RandomEntry().salt)


def test_off_by_default_and_the_historical_arms_are_untouched():
    default = hrr.run_replay(PACK, DECLARED)
    assert 'placebo_arm' not in default and set(default['totals']) == set(hrr.ARMS)
    with_placebo = hrr.run_replay(PACK, DECLARED, placebo_arm=True)
    assert set(with_placebo['totals']) == set(hrr.ARMS) | {hrr.PLACEBO_ARM}
    assert with_placebo['placebo_arm']['exit_rule'] == 'identical to the master arm'
    for pool in default['pools']:
        other = _pool(with_placebo, pool['pool'])
        assert {a: other['arms'][a] for a in hrr.ARMS} == pool['arms']
        assert [r for r in other['journal'] if r['arm'] in hrr.ARMS] == pool['journal']
    for arm in hrr.ARMS:
        assert with_placebo['totals'][arm] == default['totals'][arm]


def test_entry_at_the_hashed_age_with_the_master_exit():
    bundle = hrr.run_replay(PACK, DECLARED, placebo_arm=True)
    pool = _pool(bundle, DVP)
    row = pool['arms'][hrr.PLACEBO_ARM]
    rows = [r for r in pool['journal'] if r['arm'] == hrr.PLACEBO_ARM]
    entered = [r for r in rows if r['intent'] == 'ENTER']
    assert len(entered) == 1 and row['decision_index'] == entered[0]['index']
    creation = pool['creation_block_time']
    assert entered[0]['block_time'] - creation >= hrr.placebo_target_age(DVP)
    assert all(r['block_time'] - creation < hrr.placebo_target_age(DVP) and r['blocking_reasons'] == ['placebo_waiting']
               for r in rows if r['index'] < entered[0]['index'])
    assert set(row['exit_conditions']) == {'tp_pct', 'sl_pct'}            # the scorer plan, as the master arm
    clocked = hrr.run_replay(PACK, DECLARED, placebo_arm=True, exit_options=hrr.ExitOptions(clock_horizon=True))
    timed = _pool(clocked, DVP)['arms'][hrr.PLACEBO_ARM]
    assert timed['outcome'] == 'closed' and timed['exit_trigger']['reason'] == 'exit_horizon_clock'


def test_no_entry_for_an_unverified_creator_or_without_scorer_inputs():
    bundle = hrr.run_replay(PACK, DECLARED, placebo_arm=True)
    rows = [r for r in _pool(bundle, P5PZ)['journal'] if r['arm'] == hrr.PLACEBO_ARM]
    assert rows and all(r['blocking_reasons'] == ['signed_creator_unverified'] for r in rows)
    assert _pool(bundle, P5PZ)['arms'][hrr.PLACEBO_ARM]['entry_index'] is None
    blind = hrr.run_replay(PACK, placebo_arm=True)                      # no SOL/USD: the scorer waits
    assert blind['totals'][hrr.PLACEBO_ARM]['entries'] == 0
    assert blind['totals'][hrr.PLACEBO_ARM]['blocking_reasons'].get('sol_usd_rate_unavailable')


def test_window_closes_after_the_maximum_age():
    observer = SimpleNamespace(facts=dict(signed_creator_verified=True, creation_block_time=1_000), pool=DVP)
    arm = hrr.ResearchArm(hrr.PLACEBO_ARM, observer, DECLARED)
    result = dict(exit_conditions=dict(tp_pct=10.0, sl_pct=8.0), decisions=dict(master=dict(blocking_reasons=[])))
    at = lambda age: arm._placebo_decision([SimpleNamespace(block_time=1_000 + age)], result)
    target = hrr.placebo_target_age(DVP)
    assert at(target - 1)['blocking_reasons'] == ['placebo_waiting']
    assert at(target)['intent'] == 'ENTER' and at(120)['intent'] == 'ENTER'
    assert at(121)['blocking_reasons'] == ['placebo_window_closed']
    waiting = dict(exit_conditions=None, decisions=dict(master=dict(blocking_reasons=['sol_usd_stale'])))
    assert arm._placebo_decision([SimpleNamespace(block_time=1_050)], waiting) == dict(
        intent='WAIT', blocking_reasons=['sol_usd_stale'])


def test_cli_flag(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location('hrr_cli', ROOT / 'tools' / 'historical_research_replay.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / 'b.json'
    cli.main(['--fixtures', str(PACK), '--sol-usd', '150', '--sol-usd-provenance', 'X', '--placebo-arm',
              '--out', str(out)])
    assert f'[{hrr.PLACEBO_ARM}]' in capsys.readouterr().out
    assert hrr.PLACEBO_ARM in json.loads(out.read_text('utf-8'))['totals']


def test_entry_cutoff_applies_to_the_placebo_r02_o_r9_1():
    from bot.market.launchlab_events import WSOL_MINT
    archive = next(a for _e, a in hrr.load_fixtures(PACK)[2] if a.pool == DVP)
    free = hrr.replay_pool(archive, DECLARED, quote_mint=WSOL_MINT, arms=hrr.ARMS + (hrr.PLACEBO_ARM,))
    entry = free['arms'][hrr.PLACEBO_ARM]
    decision_slot = entry['decision_slot']

    def run(cutoff):
        window = dict(entry_cutoff_slot=cutoff, window_slot_max=decision_slot + 10 ** 6)
        return hrr.replay_pool(archive, DECLARED, quote_mint=WSOL_MINT, window=window,
                               arms=hrr.ARMS + (hrr.PLACEBO_ARM,))
    blocked = run(decision_slot - 1)
    assert blocked['arms'][hrr.PLACEBO_ARM]['entry_index'] is None
    assert any('after_entry_cutoff_slot' in r['blocking_reasons'] for r in blocked['journal']
               if r['arm'] == hrr.PLACEBO_ARM)
    assert run(decision_slot)['arms'][hrr.PLACEBO_ARM]['entry_index'] == entry['entry_index']


def test_placebo_flag_type_is_validated_r02_o_r9_1():
    import pytest
    for bad in (1, 'yes', None):
        with pytest.raises(ValueError, match='invalid_placebo_arm'):
            hrr.run_replay(PACK, DECLARED, placebo_arm=bad)
