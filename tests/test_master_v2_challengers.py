"""CH1 / CH2 veto challengers and the exact-ablation partition (Deliverable C §2.5, §5.1)."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from bot.master_v2 import challengers as ch
from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol
from bot.master_v2 import registry
from bot.p4 import historical_research_replay as hrr

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
CLEAN = dict(creator_sold_lamports=0, early_slot_payers=0, creator_token_share=0.0, progress_ppm=100_000)
FACTS = dict(signed_creator_verified=True, pool='p')
RULE = h.ExitRule(max_hold_s=25)
PROTOCOL = hrr.ReplayParams(latency_slots=4, exit_horizon_ms=25_000)


def _cli():
    spec = importlib.util.spec_from_file_location('mv2r', Path(__file__).parents[1] / 'tools' / 'master_v2_research.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ch1_truth_table():
    p = ch.InsiderVeto5s()
    assert p.decide(dict(CLEAN, age_s=4), FACTS) == ('WAIT', ['before_target_delay'])
    assert p.decide(dict(CLEAN, age_s=5), FACTS) == ('ENTER', ['insiders_not_visible'])
    assert p.decide(dict(CLEAN, age_s=35), FACTS)[0] == 'ENTER'
    assert p.decide(dict(CLEAN, age_s=36), FACTS) == ('NO_TRADE', ['no_trade_near_the_target_delay'])
    assert p.decide(dict(CLEAN, age_s=10), dict(FACTS, signed_creator_verified=False)) == (
        'NO_TRADE', ['signed_creator_unverified'])
    assert p.decide(dict(CLEAN, age_s=10, creator_sold_lamports=1), FACTS) == ('NO_TRADE', ['veto_creator_sold'])
    assert p.decide(dict(CLEAN, age_s=10, early_slot_payers=2), FACTS)[0] == 'ENTER'
    assert p.decide(dict(CLEAN, age_s=10, early_slot_payers=3), FACTS) == ('NO_TRADE', ['veto_early_slot_cluster'])
    # overhang = share x progress: 0.4 x 0.1 = 0.04 is not above the threshold; 0.41 x 0.1 is.
    assert p.decide(dict(CLEAN, age_s=10, creator_token_share=0.4), FACTS)[0] == 'ENTER'
    assert p.decide(dict(CLEAN, age_s=10, creator_token_share=0.41), FACTS) == ('NO_TRADE', ['veto_creator_overhang'])
    every = dict(CLEAN, age_s=10, creator_sold_lamports=5, early_slot_payers=9, creator_token_share=0.9)
    assert p.decide(every, FACTS) == ('NO_TRADE', ['veto_creator_sold', 'veto_early_slot_cluster',
                                                   'veto_creator_overhang'])
    assert p.max_entry_age_s() == 35
    assert p.base_arm() == dict(policy='diagnostic-fixed-delay',
                                params=dict(delay_s=5, max_lateness_s=30, require_signed_creator=True))


def test_ch2_groups():
    p = ch.CreatorBag30s()
    assert p.decide(dict(CLEAN, age_s=29), FACTS)[0] == 'WAIT'
    assert p.decide(dict(CLEAN, age_s=61), FACTS)[0] == 'NO_TRADE'
    assert p.decide(dict(CLEAN, age_s=30, creator_sold_lamports=1, creator_token_share=0.9), FACTS) == (
        'NO_TRADE', ['G1_creator_sold'])                               # G1 takes precedence over G2
    assert p.decide(dict(CLEAN, age_s=30, creator_token_share=0.11), FACTS) == ('NO_TRADE', ['G2_creator_overhang'])
    assert p.decide(dict(CLEAN, age_s=60, creator_token_share=0.1), FACTS) == ('ENTER', ['G3_kept'])
    assert p.max_entry_age_s() == 60 and p.base_arm()['params']['delay_s'] == 30


@pytest.mark.parametrize('policy', [ch.InsiderVeto5s(), ch.CreatorBag30s()])
def test_challenger_enters_only_where_its_base_arm_enters(policy):
    """Same instant as the base arm: wherever the challenger ENTERs, the base arm ENTERs too."""
    base = pol.FixedDelay(**policy.base_arm()['params'])
    for age in range(0, 120):
        for variant in (CLEAN, dict(CLEAN, creator_sold_lamports=3), dict(CLEAN, creator_token_share=0.9)):
            for facts in (FACTS, dict(FACTS, signed_creator_verified=False)):
                features = dict(variant, age_s=age)
                if policy.decide(features, facts)[0] == 'ENTER':
                    assert base.decide(features, facts)[0] == 'ENTER', (age, variant, facts)
                if base.decide(features, facts)[0] != 'ENTER':
                    assert policy.decide(features, facts)[0] != 'ENTER'


def test_challengers_are_registered_and_fingerprinted():
    cli = _cli()
    for cls in ch.CHALLENGERS:
        assert cli.POLICIES[cls.name] is cls
    assert 'bot/master_v2/challengers.py' in h.CODE_MODULES


def test_partition_is_exact_on_the_fixtures():
    base = h.run_policy(PACK, pol.FixedDelay(delay_s=5), RULE, PROTOCOL)
    filtered = h.run_policy(PACK, ch.InsiderVeto5s(), RULE, PROTOCOL)
    pools = {row['pool'] for row in base['pools']}
    report = ch.veto_partition(base, filtered, pools, n_perm=200)
    assert report['kept_entries'] + report['removed_entries'] == report['base_entries']
    assert sum(report['removed_by_reason'].values()) >= report['removed_entries']
    tampered = copy.deepcopy(filtered)
    entered = [row for row in tampered['pools'] if row['trade']['entry_index'] is not None]
    if entered:
        entered[0]['trade']['spent'] += 1
        with pytest.raises(ValueError, match='partition_not_exact'):
            ch.veto_partition(base, tampered, pools, n_perm=10)


def _row(pool, outcome, pnl, reasons=None, entered=True):
    trade = dict(outcome=outcome, pnl_lamports=pnl, spent=100_000_000, tx_costs=0, failed_attempt_costs=0,
                 entry_index=3 if entered else None)
    journal = [dict(intent='NO_TRADE', reasons=reasons)] if reasons else []
    return dict(pool=pool, trade=trade, journal=journal)


def test_partition_statistics_on_a_synthetic_case():
    winners = [_row(f'w{i}', 'closed', 10_000_000) for i in range(10)]
    losers = [_row(f'l{i}', 'closed', -20_000_000) for i in range(10)]
    base = dict(pools=winners + losers)
    filtered = dict(pools=winners + [dict(_row(r['pool'], 'no_entry', None, ['veto_creator_sold'], entered=False))
                                     for r in losers])
    pools = {r['pool'] for r in base['pools']}
    report = ch.veto_partition(base, filtered, pools, n_perm=2_000, seed=3)
    assert (report['kept_closed'], report['removed_closed']) == (10, 10)
    assert report['kept_mean'] == pytest.approx(0.1) and report['removed_mean'] == pytest.approx(-0.2)
    assert report['kept_minus_removed'] == pytest.approx(0.3)
    assert report['removed_by_reason'] == {'veto_creator_sold': 10}
    assert report['random_abstention_p'] < 0.01                     # kept = all winners: rare by chance
    neutral = ch.veto_partition(base, dict(pools=winners[:5] + losers[:5] + [
        _row(r['pool'], 'no_entry', None, ['veto_x'], entered=False) for r in winners[5:] + losers[5:]]),
        pools, n_perm=2_000, seed=3)
    assert neutral['random_abstention_p'] > 0.2


def test_cli_partition_refuses_the_holdout_and_mismatched_bases(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    common = ['--fixtures', str(PACK), '--registry', str(reg), '--exit', 'max_hold_s=25',
              '--replay', 'latency_slots=4', '--replay', 'exit_horizon_ms=25000', '--at', '2026-11-08T00:00:00+00:00']
    out = {}
    for name, argv in (('base', ['--policy', 'diagnostic-fixed-delay', '--param', 'delay_s=5']),
                       ('ch1', ['--policy', 'challenger-insider-veto-5s']),
                       ('other', ['--policy', 'diagnostic-fixed-delay', '--param', 'delay_s=15'])):
        out[name] = tmp_path / f'{name}.json'
        cli.main(['run', *common, *argv, '--out', str(out[name])])
    capsys.readouterr()
    docs = {name: json.loads(path.read_text('utf-8')) for name, path in out.items()}
    entries = registry.load(reg)
    report = cli.partition(docs['base'], docs['ch1'], registry_entries=entries, segment='exploration', n_perm=100)
    assert report['segment'] == 'exploration' and report['base'] == 'diagnostic-fixed-delay'
    for segment in ('holdout', 'all'):
        with pytest.raises(ValueError, match='partition_segment_not_allowed'):
            cli.partition(docs['base'], docs['ch1'], registry_entries=entries, segment=segment)
    with pytest.raises(SystemExit):
        cli.main(['partition', str(out['base']), str(out['ch1']), '--registry', str(reg), '--segment', 'holdout'])
    capsys.readouterr()
    with pytest.raises(ValueError, match='base_arm_mismatch'):
        cli.partition(docs['other'], docs['ch1'], registry_entries=entries, segment='exploration')
    with pytest.raises(ValueError, match='not_a_veto_challenger'):
        cli.partition(docs['ch1'], docs['base'], registry_entries=entries, segment='exploration')
    with pytest.raises(ValueError, match='unregistered_runs'):
        cli.partition(docs['base'], docs['ch1'], registry_entries=entries[:1], segment='exploration')


def test_partition_refuses_a_kept_entry_that_differs_from_the_base_arm():
    base = dict(pools=[_row('a', 'closed', 5_000_000), _row('b', 'closed', -5_000_000)])
    moved = dict(pools=[dict(_row('a', 'closed', 5_000_000), trade=dict(_row('a', 'closed', 5_000_000)['trade'],
                                                                         entry_index=4)),
                        _row('b', 'no_entry', None, ['veto_x'], entered=False)])
    with pytest.raises(ValueError, match='partition_not_exact:a'):
        ch.veto_partition(base, moved, {'a', 'b'}, n_perm=10)
    extra = dict(pools=[_row('a', 'closed', 5_000_000), _row('c', 'closed', 1)])
    with pytest.raises(ValueError, match='partition_not_exact:c'):
        ch.veto_partition(base, extra, {'a', 'b', 'c'}, n_perm=10)


def test_partition_guards_manifest_rule_params_and_embargo_r02(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    common = ['--fixtures', str(PACK), '--registry', str(reg), '--exit', 'max_hold_s=25',
              '--replay', 'latency_slots=4', '--replay', 'exit_horizon_ms=25000', '--at', '2026-11-08T00:00:00+00:00']
    paths = {}
    for name, argv in (('base', ['--policy', 'diagnostic-fixed-delay', '--param', 'delay_s=5']),
                       ('ch1', ['--policy', 'challenger-insider-veto-5s'])):
        paths[name] = tmp_path / f'{name}.json'
        cli.main(['run', *common, *argv, '--out', str(paths[name])])
    capsys.readouterr()
    base, filtered = (json.loads(paths[n].read_text('utf-8')) for n in ('base', 'ch1'))
    entries = registry.load(reg)
    other_manifest = dict(filtered, fixtures=dict(filtered['fixtures'], manifest_sha256='0' * 64))
    with pytest.raises(ValueError, match='runs_on_different_fixtures'):
        cli.partition(base, other_manifest, registry_entries=entries, segment='exploration')
    for tampered in (dict(filtered, exit_rule=dict(filtered['exit_rule'], max_hold_s=24)),
                     dict(filtered, params=dict(filtered['params'], priority_fee_lamports=1))):
        with pytest.raises(ValueError, match='base_arm_mismatch'):
            cli.partition(base, tampered, registry_entries=entries, segment='exploration')
    with pytest.raises(ValueError, match='embargo_shorter_than_outcome_horizon'):
        cli.partition(base, filtered, registry_entries=entries, segment='exploration', embargo_slots=10)
    with pytest.raises(ValueError, match='code_sha256_mismatch'):
        cli.partition(base, dict(filtered, code_sha256='f' * 64), registry_entries=entries, segment='exploration')
    report = cli.partition(base, filtered, registry_entries=entries, segment='exploration', n_perm=50)
    assert report['evaluator_code_sha256'] == h.code_fingerprint() and report['run_code_sha256']


def test_random_abstention_counts_ties_and_is_seeded():
    same = [_row(f'p{i}', 'closed', 1_000_000) for i in range(6)]
    filtered = dict(pools=same[:3] + [_row(r['pool'], 'no_entry', None, ['veto_x'], entered=False) for r in same[3:]])
    tie = ch.veto_partition(dict(pools=same), filtered, {r['pool'] for r in same}, n_perm=200)
    assert tie['random_abstention_p'] == 1.0          # every draw ties the kept mean: counted as >=
    mixed = [_row(f'm{i}', 'closed', (i - 5) * 1_000_000) for i in range(12)]
    kept = dict(pools=mixed[::2] + [_row(r['pool'], 'no_entry', None, ['veto_x'], entered=False) for r in mixed[1::2]])
    pools = {r['pool'] for r in mixed}
    first = ch.veto_partition(dict(pools=mixed), kept, pools, n_perm=300)
    again = ch.veto_partition(dict(pools=mixed), kept, pools, n_perm=300)
    assert first['random_abstention_p'] == again['random_abstention_p'] and first['seed'] == 7
