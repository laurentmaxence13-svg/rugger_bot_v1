"""First MASTER V2 challenger families and placebos on the committed fixtures (no claims)."""
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.market.replay import Position
from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'
RULE = h.ExitRule(take_profit=0.5, stop_loss=0.3, trailing=0.2, max_hold_s=120, exit_progress_ppm=900_000)


def _pool(doc, address):
    return next(p for p in doc['pools'] if p['pool'] == address)


def test_no_trade_placebo_abstains_once_per_pool():
    doc = h.run_policy(PACK, pol.NoTrade(), RULE)
    assert doc['outcomes'] == {'no_entry': 3}
    assert all([r['intent'] for r in p['journal']] == ['NO_TRADE'] for p in doc['pools'])


def test_random_entry_placebo_is_deterministic_and_respects_its_draw():
    policy = pol.RandomEntry(max_age_s=20, salt='t1')
    doc = h.run_policy(PACK, policy, RULE)
    assert doc == h.run_policy(PACK, policy, RULE)
    for pool in doc['pools']:
        target = policy.target_age(pool['pool'])
        assert 0 <= target <= 20
        enters = [r for r in pool['journal'] if r['intent'] == 'ENTER']
        if enters:
            assert len(enters) == 1 and enters[0]['block_time'] - pool['journal'][0]['block_time'] >= 0
    assert pol.RandomEntry(salt='a').target_age('x') == pol.RandomEntry(salt='a').target_age('x')


def test_immediate_snipe_requires_a_signed_creator_and_enters_first():
    doc = h.run_policy(PACK, pol.ImmediateSnipe(), RULE)
    unsigned = _pool(doc, P5PZ)
    assert unsigned['signed_creator_verified'] is False
    assert [r['intent'] for r in unsigned['journal']] == ['NO_TRADE'] and unsigned['trade']['outcome'] == 'no_entry'
    for pool in doc['pools']:
        if pool['signed_creator_verified']:
            assert pool['journal'][0]['intent'] == 'ENTER' and len(pool['journal']) == 1
            assert pool['trade']['entry_index'] is not None


@pytest.mark.parametrize('policy', [pol.DelayedConfirmation(), pol.FillMomentum(),
                                    pol.ImmediateSnipe(max_early_slot_payers=0, max_creator_token_share=0.05)])
def test_challengers_run_and_are_preregistered(policy):
    doc = h.run_policy(PACK, policy, RULE)
    assert doc['policy'] == policy.name and doc['policy_params'] == policy.params()
    assert sum(doc['outcomes'].values()) == 3 and doc['flags']['sol_usd_used'] is False
    for pool in doc['pools']:
        intents = [r['intent'] for r in pool['journal']]
        assert intents.count('ENTER') <= 1 and intents.count('NO_TRADE') <= 1
        if 'ENTER' in intents:
            assert intents[-1] == 'ENTER'
    other = type(policy)(**dict(policy.params(), require_signed_creator=not policy.require_signed_creator))
    assert h.run_policy(PACK, other, RULE)['preregistration_sha256'] != doc['preregistration_sha256']


def test_pre_migration_exit_fires_on_observed_progress():
    arm = h.PolicyArm(pol.NoTrade(), h.ExitRule(exit_progress_ppm=900_000, max_hold_s=600), {}, Counter(), 1_000)
    position = Position(0, 1, 100, 1_000, 5)
    near = SimpleNamespace(block_time=101, state_after=lambda: SimpleNamespace(progress_ppm=900_000))
    far = SimpleNamespace(block_time=101, state_after=lambda: SimpleNamespace(progress_ppm=899_999))
    assert arm.exit([far], position, 1_000) is False
    assert arm.exit([near], position, 1_000) is True and arm.exit_trigger['reason'] == 'pre_migration'
    with pytest.raises(ValueError):
        h.ExitRule(exit_progress_ppm=1_000_000)


@pytest.mark.parametrize('delay', [0, 5, 15])
def test_fixed_delay_enters_at_or_after_its_target(delay):
    from bot.p4 import historical_research_replay as hrr
    created = {a.pool: hrr.creation_facts(a)['creation_block_time'] for _e, a in hrr.load_fixtures(PACK)[2]}
    doc = h.run_policy(PACK, pol.FixedDelay(delay_s=delay, max_lateness_s=30), RULE)
    entered = 0
    for pool in doc['pools']:
        enters = [r for r in pool['journal'] if r['intent'] == 'ENTER']
        if not pool['signed_creator_verified']:
            assert [r['intent'] for r in pool['journal']] == ['NO_TRADE']
        for row in pool['journal']:
            age = row['block_time'] - created[pool['pool']]
            assert row['intent'] == ('WAIT' if age < delay else 'ENTER' if age <= delay + 30 else 'NO_TRADE') \
                or not pool['signed_creator_verified']
        entered += len(enters)
        assert len(enters) <= 1
    assert entered >= 1


def test_lifecycle_table_is_policy_free_and_complete():
    from bot.master_v2.lifecycle import HORIZONS_S, lifecycle_table
    rows, excluded, segment = lifecycle_table(PACK, segment='all')
    assert len(rows) == 3 and excluded == [] and segment == 'all'
    for row in rows:
        assert row['peak_multiple'] >= row['final_multiple']
        assert row['peak_multiple'] >= max(row[f'multiple_at_{h}s'] for h in HORIZONS_S) - 1e-12
        assert 0 <= row['max_progress_ppm'] < 1_000_000 and row['migrated'] is False
