"""Slot-duration floor and outcome horizon (RUGGER 01, after the Deliverable D review).

Measured on the committed LaunchLab fixtures (slots 4646xxxxx), a slot lasts 210-222 ms,
far below the former 350 ms "floor": guards sized on 350 ms let a 45 s hold overrun a
160-slot window and an embargo cover only part of a pool's outcome period. The floor
is now 200 ms, and the embargo covers the entry age as well as the hold.
"""
import gzip
import json
from pathlib import Path

import pytest

from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol
from bot.master_v2 import registry
from bot.p4 import historical_research_replay as hrr

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'


def _slot_times(path):
    pairs = set()

    def walk(node):
        if isinstance(node, dict):
            slot, when = node.get('slot'), node.get('blockTime', node.get('block_time'))
            if type(slot) is int and type(when) is int:
                pairs.add((slot, when))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        walk(json.load(handle))
    return sorted(pairs)


def test_slot_floor_is_below_every_measured_fixture_slot():
    assert (hrr.SLOT_MS_FLOOR, hrr.SLOT_MS_FLOOR_SHORT, hrr.SHORT_HORIZON_MS) == (200, 190, 60_000)
    archives = sorted(PACK.glob('*.json.gz'))
    assert len(archives) == 3
    for path in archives:
        pairs = _slot_times(path)
        (first_slot, first_time), (last_slot, last_time) = pairs[0], pairs[-1]
        assert last_slot - first_slot >= 70
        # block_time has a 1 s resolution: take the fastest slot compatible with it.
        fastest_ms = 1000 * (last_time - first_time - 1) / (last_slot - first_slot)
        assert fastest_ms >= hrr.SLOT_MS_FLOOR_SHORT, path.name
        assert 1000 * (last_time - first_time) / (last_slot - first_slot) < 350   # the old floor was wrong


FAVOURABLE = dict(early_slot_payers=0, creator_token_share=0.0, creator_sold_lamports=0, buyers_30s=100,
                  net_flow_30s_lamports=10 ** 12, top1_token_share=0.0, drawdown_from_peak=0.0,
                  progress_ppm=200_000)
FACTS = dict(signed_creator_verified=True, pool='pool-x')
BOUNDS = ((pol.NoTrade(), 0), (pol.RandomEntry(), 120), (pol.ImmediateSnipe(), 5),
          (pol.DelayedConfirmation(), 180), (pol.FillMomentum(), 300),
          (pol.FixedDelay(delay_s=60, max_lateness_s=30), 90), (pol.FixedDelay(), 30))


@pytest.mark.parametrize('policy, bound', BOUNDS)
def test_every_policy_declares_a_tight_entry_age_bound(policy, bound):
    assert policy.max_entry_age_s() == bound
    for age in range(bound + 1, bound + 400, 7):
        assert policy.decide(dict(FAVOURABLE, age_s=age), FACTS)[0] != 'ENTER', age
    if bound:
        entered = [age for age in range(0, bound + 1) if policy.decide(dict(FAVOURABLE, age_s=age), FACTS)[0] == 'ENTER']
        assert entered and max(entered) <= bound


def test_an_undeclared_policy_has_no_entry_age_bound():
    assert h.Policy().max_entry_age_s() is None


def test_slot_floor_depends_on_the_duration_r02_c1_c3():
    """R02 C1: 200 ms is shown on P0 for spans >= 60 s only; 190 ms below (C3)."""
    assert hrr.slots_for_ms(59_999) == 316 and hrr.slots_for_ms(30_000) == 158     # 190 ms
    assert hrr.slots_for_ms(60_000) == 300 and hrr.slots_for_ms(347_000) == 1735   # 200 ms
    assert hrr.slots_for_ms(0) == 0


def test_hold_gap_counts_block_time_rounding_on_the_slot_floor():
    params = hrr.ReplayParams()
    assert params.latency_slots == 2
    assert h.hold_gap_slots(h.ExitRule(max_hold_s=30), params) == 164 + 4      # ceil(31 000 / 190) + 2 x 2
    assert h.hold_gap_slots(h.ExitRule(max_hold_s=60), params) == 305 + 4      # 61 s: 200 ms floor
    p0 = dict(entry_cutoff_slot=466_442_576, window_slot_max=466_442_736)     # P0: 160-slot gap
    # L1 defaults (30 s horizon, latency 2) need ceil(30 000 / 190) + 4 = 162 > 160: refused (R02 C3).
    with pytest.raises(ValueError, match='collection_window_gap_shorter_than_exit_horizon'):
        hrr.collection_window({}, p0, params)
    revised = hrr.ReplayParams(latency_slots=4, exit_horizon_ms=25_000)      # the P0 protocol
    assert hrr.collection_window({}, p0, revised)['minimum_gap_slots'] == 132 + 8
    assert h.policy_window({}, p0, revised, h.ExitRule(max_hold_s=25))['minimum_gap_slots'] == 137 + 8
    for hold in (28, 30, 45):
        with pytest.raises(ValueError, match='collection_window_gap_shorter_than_max_hold'):
            h.policy_window({}, p0, revised, h.ExitRule(max_hold_s=hold))


def test_outcome_horizon_covers_entry_age_hold_and_rounding():
    params = hrr.ReplayParams()
    rule = h.ExitRule(max_hold_s=45)
    assert h.outcome_horizon_slots(pol.FillMomentum(), rule, params) == 1735 + 4    # ceil(347 000 / 200) + 4
    assert h.outcome_horizon_slots(pol.NoTrade(), rule, params) == 248 + 4      # 47 s on 190 ms
    assert h.outcome_horizon_slots(pol.ImmediateSnipe(), h.ExitRule(stop_loss=0.1), params) is None
    assert h.outcome_horizon_slots(h.Policy(), rule, params) is None


def _run(cli, tmp_path, capsys, reg, name, *argv):
    out = tmp_path / f'{name}.json'
    cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), *argv, '--out', str(out),
              '--at', '2026-11-07T00:00:00+00:00'])
    capsys.readouterr()
    return json.loads(out.read_text('utf-8'))


def test_evaluate_embargo_covers_the_longest_outcome_horizon(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location('mv2r', Path(__file__).parents[1] / 'tools' / 'master_v2_research.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    reg = tmp_path / 'trials.jsonl'
    snipe = _run(cli, tmp_path, capsys, reg, 'snipe', '--policy', 'immediate-snipe', '--exit', 'max_hold_s=45')
    fill = _run(cli, tmp_path, capsys, reg, 'fill', '--policy', 'fill-momentum', '--exit', 'max_hold_s=45')
    entries = registry.load(reg)
    assert cli.required_embargo_slots([snipe]) == 274 + 4                      # (5 + 45 + 2) s on 190 ms
    assert cli.required_embargo_slots([snipe, fill]) == 1739                   # (300 + 45 + 2) s
    with pytest.raises(ValueError, match='embargo_shorter_than_outcome_horizon:1739'):
        cli.evaluate([snipe, fill], registry_entries=entries, embargo_slots=1738, n_boot=200)
    assert cli.evaluate([snipe, fill], registry_entries=entries, n_boot=200)['embargo_slots'] == 1739
    for broken, error in ((dict(fill, exit_rule=dict(fill['exit_rule'], max_hold_s=None)),
                           'evaluation_requires_bounded_max_hold_s'),
                          (dict(fill, policy='unknown-policy'), 'unknown_policy:unknown-policy')):
        with pytest.raises(ValueError, match=error):
            cli.required_embargo_slots([broken])

    class Unbounded(h.Policy):              # a registered policy that declares no entry-age bound
        name = 'unbounded-test-policy'

    cli.POLICIES[Unbounded.name] = Unbounded
    with pytest.raises(ValueError, match='evaluation_requires_bounded_entry_age'):
        cli.required_embargo_slots([dict(fill, policy=Unbounded.name, policy_params={})])


def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location('mv2r', Path(__file__).parents[1] / 'tools' / 'master_v2_research.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_parameters_are_explicit_and_pre_registered(tmp_path, capsys):
    """R02 O1: 2 slots are ~0.43 s at 214 ms per slot; latency is set explicitly per run."""
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    base = _run(cli, tmp_path, capsys, reg, 'base', '--policy', 'immediate-snipe', '--exit', 'max_hold_s=25')
    slow = _run(cli, tmp_path, capsys, reg, 'slow', '--policy', 'immediate-snipe', '--exit', 'max_hold_s=25',
                '--replay', 'latency_slots=4', '--replay', 'exit_horizon_ms=25000')
    assert base['params']['latency_slots'] == 2 and slow['params']['latency_slots'] == 4
    assert slow['params']['exit_horizon_ms'] == 25000
    assert base['preregistration_sha256'] != slow['preregistration_sha256']
    assert len(registry.load(reg)) == 2
    assert cli.required_embargo_slots([slow]) == 169 + 8          # ceil((5 + 25 + 2) s / 190 ms) + 2 x 4
    p0 = dict(entry_cutoff_slot=466_442_576, window_slot_max=466_442_736)
    params = hrr.ReplayParams(latency_slots=4, exit_horizon_ms=25_000)
    assert h.policy_window({}, p0, params, h.ExitRule(max_hold_s=25))['minimum_gap_slots'] == 137 + 8
    for bad in (['--replay', 'latency_slots=-1'], ['--replay', 'no_such_field=1'], ['--replay', 'latency_slots'],
                ['--replay', 'latency_slots=0'], ['--replay', 'exit_horizon_ms=24000']):   # R02 O3
        with pytest.raises(SystemExit):
            cli.main(['run', '--fixtures', str(PACK), '--registry', str(tmp_path / 'x.jsonl'), '--policy',
                      'immediate-snipe', '--exit', 'max_hold_s=25', '--out', str(tmp_path / 'x.json'), *bad])
        capsys.readouterr()
    assert not (tmp_path / 'x.jsonl').exists()                     # nothing registered on a refused run
