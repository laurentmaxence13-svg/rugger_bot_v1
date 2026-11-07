"""R02 B1 and O1-O6 on the MASTER V2 harness: collection window, binding pre-registration,
append-only trial registry, embargo, population-matched placebo, segment-limited lifecycle."""
import json
from pathlib import Path
import shutil

import pytest

from bot.market.collector import summarize
from bot.market.launchlab_events import WSOL_MINT
from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol
from bot.master_v2 import registry
from bot.p4 import historical_research_replay as hrr
from test_historical_research_replay import _EnterAt
from test_master_v2_harness import _Script

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
C7F9 = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'
RULE = h.ExitRule(stop_loss=0.08, take_profit=0.10, max_hold_s=30)


def _archive(pool=C7F9):
    return next(a for _e, a in hrr.load_fixtures(PACK)[2] if a.pool == pool)


def _windowed_pack(tmp_path, cutoff, end):
    pack = tmp_path / 'pack'
    shutil.copytree(PACK, pack)
    manifest = json.loads((pack / 'MANIFEST.json').read_text('utf-8'))
    manifest['entry_cutoff_slot'], manifest['window_slot_max'] = cutoff, end
    (pack / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    return pack


def test_no_entry_after_the_cutoff_r02_probe(tmp_path):
    """R02's probe: cutoff in the middle of C7F9, entry wanted at three quarters of the history."""
    events = summarize(_archive())[1].events
    late = 3 * len(events) // 4
    pack = _windowed_pack(tmp_path, 464661907, 464661907 + 10_000)
    doc = h.run_policy(pack, _Script(enter_at=late), RULE)
    pool = next(p for p in doc['pools'] if p['pool'] == C7F9)
    assert pool['trade']['outcome'] == 'no_entry' and pool['trade']['pnl_lamports'] is None
    assert pool['journal'][-1]['intent'] == 'NO_TRADE'
    assert pool['journal'][-1]['reasons'] == ['after_entry_cutoff_slot']
    assert pool['journal'][-1]['slot'] > 464661907
    assert all(r['slot'] <= 464661907 for r in pool['journal'][:-1])
    assert pool['window']['entry_cutoff_slot'] == 464661907 and 'collection_window_rule' in doc['flags']


def test_v2_and_l1_treat_the_same_forced_entry_identically_under_a_window():
    params = hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')
    archive = _archive()
    timeline = summarize(archive)[1]
    decision_slot = timeline.events[_EnterAt.enter_index].slot
    for end_gap in (90, 10_000):
        window = h.policy_window({}, dict(entry_cutoff_slot=decision_slot, window_slot_max=decision_slot + end_gap),
                                 params, RULE)
        observer = _EnterAt(archive, timeline, hrr.creation_facts(archive), params)
        arm = hrr.ResearchArm('master', observer, params, window)
        l1 = hrr._apply_window(hrr._trade(hrr.replay(timeline, arm, params.execution_model(), quote_mint=WSOL_MINT),
                                          timeline.events, arm, params), window)
        v2 = h.run_policy_pool(archive, _Script(enter_at=_EnterAt.enter_index), RULE, params,
                               quote_mint=WSOL_MINT, window=window)['trade']
        for key in ('decision_index', 'entry_index', 'entry_slot', 'spent', 'tokens', 'fee_rate_ppm',
                    'fee_rate_source'):
            assert v2[key] == l1[key], key
        for row in (v2, l1):
            if row['outcome'] == 'closed':
                assert row['exit_slot'] <= window['window_slot_max'] and row['pnl_lamports'] is not None
            else:
                assert row['outcome'] == 'open_at_window_end' and row['pnl_lamports'] is None
                assert row['mark_pnl_lamports'] is not None


def test_window_must_cover_the_bounded_hold(tmp_path):
    params = hrr.ReplayParams()
    with pytest.raises(ValueError, match='collection_window_requires_bounded_max_hold_s'):
        h.policy_window({}, dict(entry_cutoff_slot=100, window_slot_max=10_000), params, h.ExitRule(stop_loss=0.1))
    with pytest.raises(ValueError, match='collection_window_gap_shorter_than_max_hold'):
        h.policy_window({}, dict(entry_cutoff_slot=100, window_slot_max=200), params, h.ExitRule(max_hold_s=60))
    window = h.policy_window({}, dict(entry_cutoff_slot=100, window_slot_max=100 + 176), params,
                             h.ExitRule(max_hold_s=60))
    assert window['minimum_gap_slots'] == 176 == h.hold_gap_slots(h.ExitRule(max_hold_s=60), params)
    assert h.policy_window({}, {}, params, h.ExitRule()) is None
    with pytest.raises(ValueError):
        h.run_policy(_windowed_pack(tmp_path, 100, 200), _Script(), h.ExitRule(max_hold_s=60))


def test_preregistration_binds_code_data_and_window(tmp_path):
    base = h.preregister(PACK, _Script(), RULE)
    assert base['code_sha256'] == h.code_fingerprint() and len(base['code_sha256']) == 64
    doc = h.run_policy(PACK, _Script(), RULE)
    assert doc['preregistration_sha256'] == base['preregistration_sha256']
    assert doc['fixtures']['manifest_sha256'] == base['manifest_sha256'] and doc['code_sha256'] == base['code_sha256']
    windowed = h.preregister(_windowed_pack(tmp_path, 464661907, 464661907 + 10_000), _Script(), RULE)
    assert windowed['manifest_sha256'] != base['manifest_sha256']
    assert windowed['windows_sha256'] != base['windows_sha256']
    assert windowed['preregistration_sha256'] != base['preregistration_sha256']


def test_code_fingerprint_follows_the_source(monkeypatch, tmp_path):
    copy = tmp_path / 'root'
    for path in h.CODE_MODULES:
        (copy / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(h._ROOT / path, copy / path)
    monkeypatch.setattr(h, '_ROOT', copy)
    same = h.code_fingerprint()
    (copy / 'bot/market/replay.py').write_text((copy / 'bot/market/replay.py').read_text() + '\n# edit\n')
    assert h.code_fingerprint() != same


def _record(sha, manifest='m' * 64):
    return dict(preregistration_sha256=sha, manifest_sha256=manifest, policy='p')


def test_registry_is_append_only_and_hash_chained(tmp_path):
    path = tmp_path / 'trials.jsonl'
    first, new = registry.register(path, _record('a' * 64), registered_at='2026-11-07T00:00:00+00:00')
    assert new and first['index'] == 0 and first['previous_sha256'] == registry.GENESIS
    again, new = registry.register(path, _record('a' * 64), registered_at='2026-11-07T00:00:01+00:00')
    assert not new and again == first
    second, _ = registry.register(path, _record('b' * 64), registered_at='2026-11-07T00:00:02+00:00')
    assert second['previous_sha256'] == first['entry_sha256'] and registry.head(path) == second['entry_sha256']
    assert len(registry.load(path)) == 2
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered['policy'] = 'other'
    path.write_text(json.dumps(tampered, sort_keys=True, separators=(',', ':')) + '\n' + lines[1] + '\n')
    with pytest.raises(ValueError, match='registry_chain_broken_at:0'):
        registry.load(path)
    path.write_text(lines[1] + '\n')                                # first line deleted
    with pytest.raises(ValueError, match='registry_chain_broken_at:0'):
        registry.load(path)
    with pytest.raises(ValueError):
        registry.register(tmp_path / 'x.jsonl', _record('c' * 64), registered_at='')


def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location('mv2_cli_w', h._ROOT / 'tools' / 'master_v2_research.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def test_evaluate_counts_every_registered_trial_and_unseals_only_registered(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    paths = []
    for name in ('immediate-snipe', 'placebo-no-trade', 'placebo-random-entry'):
        out = tmp_path / f'{name}.json'
        cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), '--policy', name,
                  '--exit', 'max_hold_s=30', '--out', str(out), '--at', '2026-11-07T00:00:00+00:00'])
        paths.append(out)
    capsys.readouterr()
    docs = [json.loads(p.read_text('utf-8')) for p in paths]
    entries = registry.load(reg)
    result = cli.evaluate(docs, registry_entries=entries, n_boot=200)
    assert result['trials'] == 3 and result['registry_head'] == registry.head(reg)
    with pytest.raises(ValueError, match='registered_trials_missing:1'):
        cli.evaluate(docs[:2], registry_entries=entries, n_boot=200)
    with pytest.raises(ValueError, match='unregistered_runs:1'):
        cli.evaluate(docs, registry_entries=entries[:2], n_boot=200)
    with pytest.raises(ValueError, match='unseal_of_unregistered_preregistration'):
        cli.evaluate(docs, registry_entries=entries, holdout=True, unseal=['f' * 64], n_boot=200)


def test_embargo_must_cover_the_longest_hold(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    out = tmp_path / 'r.json'
    cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), '--policy', 'immediate-snipe',
              '--exit', 'max_hold_s=600', '--out', str(out), '--at', '2026-11-07T00:00:00+00:00'])
    capsys.readouterr()
    doc = json.loads(out.read_text('utf-8'))
    need = h.hold_gap_slots(h.ExitRule(max_hold_s=600), hrr.ReplayParams())
    assert need == 1719
    with pytest.raises(ValueError, match='embargo_shorter_than_max_hold:1719'):
        cli.evaluate([doc], registry_entries=registry.load(reg), embargo_slots=750, n_boot=200)
    assert cli.evaluate([doc], registry_entries=registry.load(reg), n_boot=200)['embargo_slots'] == 1719
    unbounded = dict(doc, exit_rule=dict(doc['exit_rule'], max_hold_s=None))
    with pytest.raises(ValueError, match='evaluation_requires_bounded_max_hold_s'):
        cli.required_embargo_slots([unbounded])


def test_random_entry_placebo_uses_the_challenger_population():
    doc = h.run_policy(PACK, pol.RandomEntry(max_age_s=20), RULE)
    unsigned = next(p for p in doc['pools'] if p['pool'] == P5PZ)
    assert unsigned['signed_creator_verified'] is False
    assert [r['intent'] for r in unsigned['journal']] == ['NO_TRADE']
    assert unsigned['journal'][0]['reasons'] == ['signed_creator_unverified']


def test_lifecycle_reads_only_the_requested_segment():
    from bot.master_v2.lifecycle import lifecycle_table
    from bot.master_v2.validation import chronological_split
    rows, excluded, segment = lifecycle_table(PACK, embargo_slots=0)
    table = []
    for _e, a in hrr.load_fixtures(PACK)[2]:
        facts = hrr.creation_facts(a)
        table.append(dict(pool=a.pool, creator=facts['creator'], created_slot=facts['creation_slot']))
    expected = set(chronological_split(table, embargo_slots=0)['exploration'])
    assert segment == 'exploration' and {r['pool'] for r in rows} == expected and excluded == []
    assert len(lifecycle_table(PACK, segment='all')[0]) == 3
    with pytest.raises(ValueError):
        lifecycle_table(PACK, segment='holdout')


def test_a_run_is_registered_before_its_replay(tmp_path, monkeypatch):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'

    def boom(*args, **kwargs):
        raise ValueError('replay_failed_after_registration')
    monkeypatch.setattr(cli, 'run_policy', boom)
    with pytest.raises(SystemExit):
        cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), '--policy', 'immediate-snipe',
                  '--exit', 'max_hold_s=30', '--out', str(tmp_path / 'r.json'), '--at', '2026-11-07T00:00:00+00:00'])
    entries = registry.load(reg)
    assert len(entries) == 1 and not (tmp_path / 'r.json').exists()
    assert entries[0]['preregistration_sha256'] == h.preregister(
        PACK, pol.ImmediateSnipe(), h.ExitRule(max_hold_s=30))['preregistration_sha256']


@pytest.mark.parametrize('cutoff,intent', [(464661848, 'NO_TRADE'), (464661849, 'ENTER')])
def test_cutoff_bound_is_exact(tmp_path, cutoff, intent):
    """Index 11 of C7F9 trades at slot 464661849: refused at cutoff+1, admitted at the cutoff (R02 T1)."""
    events = summarize(_archive())[1].events
    assert events[11].slot == 464661849 and events[10].slot == 464661848
    window = h.policy_window({}, dict(entry_cutoff_slot=cutoff, window_slot_max=cutoff + 10_000),
                             hrr.ReplayParams(), RULE)
    record = h.run_policy_pool(_archive(), _Script(enter_at=11), RULE, hrr.ReplayParams(),
                               quote_mint=WSOL_MINT, window=window)
    last = record['journal'][-1]
    assert last['index'] == 11 and last['intent'] == intent
    if intent == 'NO_TRADE':
        assert last['reasons'] == ['after_entry_cutoff_slot'] and record['trade']['entry_index'] is None
    else:
        assert record['trade']['decision_index'] == 11


def test_rewritten_middle_line_with_recomputed_hash_breaks_the_chain(tmp_path):
    """Rewriting a line and recomputing its own digest still breaks the next link (R02 T2)."""
    path = tmp_path / 'trials.jsonl'
    for letter in 'abc':
        registry.register(path, _record(letter * 64), registered_at='2026-11-07T00:00:00+00:00')
    lines = path.read_text().splitlines()
    middle = json.loads(lines[1])
    middle['policy'] = 'rewritten'
    middle['entry_sha256'] = registry._digest(middle)
    path.write_text('\n'.join([lines[0], json.dumps(middle, sort_keys=True, separators=(',', ':')), lines[2]]) + '\n')
    with pytest.raises(ValueError, match='registry_chain_broken_at:2'):
        registry.load(path)


def test_evaluate_publishes_open_positions_and_a_pessimistic_mean(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    out = tmp_path / 'snipe.json'
    cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), '--policy', 'immediate-snipe',
              '--exit', 'max_hold_s=600', '--out', str(out), '--at', '2026-11-07T00:00:00+00:00'])
    capsys.readouterr()
    doc = json.loads(out.read_text('utf-8'))
    result = cli.evaluate([doc], registry_entries=registry.load(reg), embargo_slots=1719, n_boot=200)
    seen = 0
    for segment in result['runs'][0]['segments'].values():
        open_positions = segment['open_positions']
        assert set(open_positions) == {'count', 'marked', 'mark_pnl_lamports', 'unpriced'}
        assert open_positions['count'] == open_positions['marked'] + open_positions['unpriced']
        assert sum(segment['outcomes'].values()) >= segment['n'] + open_positions['count']
        entered = segment['n'] + open_positions['count']
        expected = (((segment['mean_return'] or 0) * segment['n'] - open_positions['count']) / entered
                    if entered else None)
        assert segment['mean_return_open_as_total_loss'] == pytest.approx(expected) if entered \
            else segment['mean_return_open_as_total_loss'] is None
        seen += open_positions['count']
    assert seen >= 1          # the immediate snipe leaves open positions on the short fixtures
