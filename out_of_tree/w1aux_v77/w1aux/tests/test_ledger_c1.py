"""w1aux.ledger_c1 (owner decision 20/11, C1-b + D2): the declared C1 rule for priced-then-relabelled rows.

The frozen-pack rehearsal has no relabelled row: with C1 its ledger is byte-identical to v7.4. Relabelled rows are made
by rewriting a bundle row exactly as hrr does (_apply_window, _migrated, _exit_after_migration): v7.4 FAILs on them
(the W1 defect), C1 PASSes; inconsistent or tampered relabellings FAIL with C1.
"""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from bot.p4 import sol_usd_series as sus
from w1aux import ledger as L
from w1aux import ledger_c1 as C1
from w1aux import ledger_parallel as LP
from w1aux import ledger_resume as LR
from w1aux.tests.test_ledger import PACK, _copy, _rewrite, rehearsal  # noqa: F401  (module fixture)
from w1aux.tests.test_ledger_parallel import _main


def _series(rehearsal):
    return rehearsal / 'sol_usd.json'


def _row(bundle, outcome, arm='placebo_random'):
    return next(p['arms'][arm] for p in bundle['pools'] if arm in p['arms'] and p['arms'][arm]['outcome'] == outcome)


def _apply_window(row):                                             # hrr l. 658-665
    mark = row['mark_pnl_lamports'] if row['outcome'] == 'open_at_end' else row['pnl_lamports']
    row.update(outcome='open_at_window_end', mark_pnl_lamports=mark, pnl_lamports=None, net_return=None)


def _migrated(row):                                                 # hrr l. 651-655 (open_at_end, no note)
    row.update(outcome='migrated_unpriced', pnl_lamports=None, net_return=None)


def _exit_after_migration(row):                                     # hrr l. 639-648 (closed, with the note)
    row.update(outcome='migrated_unpriced', pnl_lamports=None, net_return=None,
               notes=row['notes'] + ['exit_after_migration'])


def _ledger(bundles, rehearsal, *, c1):
    series = sus.load_series(_series(rehearsal))
    if not c1:
        return L.build_ledger(PACK, bundles, series=series)
    with C1.c1_rule():
        return L.build_ledger(PACK, bundles, series=series)


def _entry(led, trial, arm='placebo_random'):
    return next(e for e in led['entries'] if e['trial'] == trial and e['arm'] == arm)


def test_without_relabelled_rows_the_ledger_is_byte_identical(rehearsal, tmp_path):
    seq = _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'v74', series=_series(rehearsal))
    with C1.c1_rule() as rule:
        c1 = _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'c1', series=_series(rehearsal))
    assert seq == c1 and json.loads(c1[1])['verdict'] == 'PASS'
    assert rule['module'] == 'w1aux/ledger_c1.py' and rule['sha256'] == C1.module_sha256()
    assert rule['outcomes'] == ['open_at_window_end', 'migrated_unpriced'] and 'l. 337' in rule['replaced']


@pytest.mark.parametrize('trial, source, relabel', [
    ('L1_event_horizon', 'open_at_end', _apply_window),             # the 91 W1 rows
    ('L1_event_horizon', 'open_at_end', _migrated),                 # the 2 W1 rows
    ('L1', 'closed', _apply_window),
    ('L1', 'closed', _exit_after_migration)])
def test_a_priced_then_relabelled_row_fails_v7_4_and_passes_c1(rehearsal, tmp_path, trial, source, relabel):
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, trial, lambda b: relabel(_row(b, source)))
    v74 = _ledger(bundles, rehearsal, c1=False)
    assert v74['verdict'] == 'FAIL' and [m['mismatches'] for m in v74['mismatches']] == [
        [f'tx_costs:ledger=105000:bundle=210000']]                  # the W1 defect, reproduced
    c1 = _ledger(bundles, rehearsal, c1=True)
    entry = _entry(c1, trial)
    assert c1['verdict'] == 'PASS' and entry['verified'] is True and entry['scope'] == 'entry_only'
    assert entry['checks']['c1_rule_applied'] and entry['checks']['tx_costs'] and entry['checks']['exit_index']
    assert entry['checks']['c1_relabel_consistent'] and entry['checks']['failed_attempt_costs']
    others = [e for e in c1['entries'] if e is not entry]
    assert others == [e for e in v74['entries'] if (e['trial'], e['arm'], e['pool']) != (entry['trial'], entry['arm'], entry['pool'])]


@pytest.mark.parametrize('trial, source, relabel, field, expected', [
    ('L1', 'closed', _migrated, None, 'c1_relabel_consistent'),                     # closed relabelled without the note
    ('L1_event_horizon', 'open_at_end', _exit_after_migration, None, 'c1_relabel_consistent'),
    ('L1_event_horizon', 'open_at_end', _apply_window, ('tx_costs', 105_000), 'tx_costs'),
    ('L1', 'closed', _apply_window, ('tx_costs', 315_000), 'tx_costs'),
    ('L1_event_horizon', 'open_at_end', _migrated, ('exit_index', -1), 'exit_index'),
    ('L1', 'closed', _exit_after_migration, ('failed_attempt_costs', 1), 'failed_attempt_costs')])
def test_an_inconsistent_or_tampered_relabelling_fails_with_c1(rehearsal, tmp_path, trial, source, relabel, field, expected):
    def mutate(b):
        row = _row(b, source)
        relabel(row)
        if field is not None:
            name, value = field
            row[name] = row[name] + value if name == 'exit_index' else (value if name == 'tx_costs' else row[name] + value)
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, trial, mutate)
    c1 = _ledger(bundles, rehearsal, c1=True)
    assert c1['verdict'] == 'FAIL'
    names = [x.split(':', 1)[0] for m in c1['mismatches'] for x in m['mismatches']]
    assert expected in names and len(c1['mismatches']) == 1


@pytest.mark.parametrize('forced, tx, expected', [
    ('migrated_unpriced', 105_000, set()),                                  # same unpriced outcome, 1 x: no mismatch
    ('migrated_unpriced', 210_000, {'tx_costs'}),                           # 2 x where the re-derivation is unpriced
    ('counterfactual_divergence', 105_000, {'outcome'})])                   # another unpriced outcome
def test_an_unpriced_re_derivation_keeps_1x_and_requires_the_same_outcome(rehearsal, tmp_path, monkeypatch,
                                                                          forced, tx, expected):
    bundles = _copy(rehearsal, tmp_path)

    def mutate(b):
        row = _row(b, 'closed')
        _exit_after_migration(row)
        row['tx_costs'] = tx
    _rewrite(bundles, 'L1', mutate)
    target = _row(json.loads(gzip.decompress((bundles / 'L1.json.gz').read_bytes())), 'migrated_unpriced')
    real = L.derive_hold

    def hold(events, land, spent, tokens, rate, rule, latency):
        out = real(events, land, spent, tokens, rate, rule, latency)
        if land == target['entry_index'] and spent == target['spent'] and isinstance(rule, L._L1Rule):
            return dict(out, outcome=forced, exit_index=None)             # as if the replay itself stopped unpriced
        return out
    monkeypatch.setattr(L, 'derive_hold', hold)
    c1 = _ledger(bundles, rehearsal, c1=True)
    entry = _entry(c1, 'L1')
    assert {x.split(':', 1)[0] for x in entry['mismatches']} == expected
    assert 'exit_index' not in entry['checks'] and 'c1_relabel_consistent' not in entry['checks']


def test_other_outcomes_and_early_stops_keep_the_v7_4_result(rehearsal):
    bundles, _sums = L.load_bundles(rehearsal / 'out' / 'bundles')
    timelines = L.timelines(PACK)[1]
    C1._ORIGINAL['verify_cycle'] = L.verify_cycle
    try:
        for trial, bundle in bundles.items():
            for _arm, pool, row, params, spec in L.cycles(trial, bundle):
                if row['entry_index'] is None or pool not in timelines:
                    continue
                assert C1.verify_cycle_c1(timelines[pool], row, params, spec) == L.verify_cycle(timelines[pool], row, params, spec)
        _arm, pool, closed, params, spec = next(c for c in L.cycles('L1', bundles['L1'])
                                                 if c[2]['outcome'] == 'closed')
        row = dict(closed, decision_index=10 ** 6)                                   # early stop: indices out of range
        _apply_window(row)
        assert C1.verify_cycle_c1(timelines[pool], row, params, spec) == L.verify_cycle(timelines[pool], row, params, spec)
        assert C1.verify_cycle_c1(timelines[pool], row, params, None) == L.verify_cycle(timelines[pool], row, params, None)
    finally:
        C1._ORIGINAL.clear()


def test_c1_reuses_the_whole_resume_cache(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, 'L1_event_horizon', lambda b: _apply_window(_row(b, 'open_at_end')))
    with LR.resumable_ledger(tmp_path / 'cache', 'trials:test') as first:          # the FAIL run (v7.4 rule)
        fail = _main(PACK, bundles, tmp_path / 'fail', series=_series(rehearsal))
    assert json.loads(fail[1])['verdict'] == 'FAIL' and first['computed'] == 4
    with C1.c1_rule(), LR.resumable_ledger(tmp_path / 'cache', 'trials:test') as again:
        fixed = _main(PACK, bundles, tmp_path / 'fixed', series=_series(rehearsal))
    assert json.loads(fixed[1])['verdict'] == 'PASS'
    assert again['reused'] == 4 and again['computed'] == 0 and again['rejected'] == 0 and again['resumes'] == 1
    with C1.c1_rule():
        plain = _main(PACK, bundles, tmp_path / 'plain', series=_series(rehearsal))
    assert plain == fixed                                            # resumed C1 == direct C1, byte for byte


def test_guards(monkeypatch):
    with C1.c1_rule():
        assert L.verify_cycle is C1.verify_cycle_c1
        with pytest.raises(C1.LedgerC1Error, match='not_reentrant'):
            with C1.c1_rule():
                pass
    assert L.verify_cycle.__module__ == 'w1aux.ledger' and not C1._ACTIVE['on'] and C1._ORIGINAL == {}
    monkeypatch.setattr(L, 'verify_cycle', lambda *a: None)
    with pytest.raises(C1.LedgerC1Error, match='verify_cycle_is_already_replaced'):
        with C1.c1_rule():
            pass
    monkeypatch.undo()
    monkeypatch.setattr(LP, 'LEDGER_SHA256', '0' * 64)
    with pytest.raises(LP.LedgerParallelError, match='w1aux_ledger_is_not_v7_4'):
        with C1.c1_rule():
            pass
    assert L.verify_cycle.__module__ == 'w1aux.ledger'


def test_c1_fails_cleanly_without_a_file(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, 'L1', lambda b: _migrated(_row(b, 'closed')))                # inconsistent: FAIL, code 4
    with C1.c1_rule():
        code, line, _json, _md = _main(PACK, bundles, tmp_path / 'out', series=_series(rehearsal))
    assert code == 4 and json.loads(line)['verdict'] == 'FAIL'


# ---- R02 da66ca80 / 4f6cb0b0 additions ---------------------------------------------------------------------------
LEDGER_RESUME_V76_SHA256 = '1ec071f4de84387e8a41287ae990b4a35d1a08e37af472582e7ed8579a8f2770'


def test_counterfactual_divergence_and_no_entry_keep_the_v7_4_result(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)

    def mutate(b):                                                  # an unpriced replay outcome: 1 x, no exit
        row = _row(b, 'closed')
        row.update(outcome='counterfactual_divergence', exit_index=None, exit_slot=None, exit_signature=None,
                   exit_block_time=None, received=0, pnl_lamports=None, net_return=None, tx_costs=105_000,
                   notes=row['notes'] + ['exit_refused:test'])
    _rewrite(bundles, 'L1', mutate)
    v74, c1 = _ledger(bundles, rehearsal, c1=False), _ledger(bundles, rehearsal, c1=True)
    assert json.dumps(v74, sort_keys=True) == json.dumps(c1, sort_keys=True)       # not a relabelled outcome: v7.4
    loaded, _sums = L.load_bundles(bundles)                         # a row without entry is never verified
    with_entry = {(t, a, p) for t, b in loaded.items() for a, p, row, _p, _s in L.cycles(t, b) if row['entry_index'] is not None}
    without = {(t, a, p) for t, b in loaded.items() for a, p, row, _p, _s in L.cycles(t, b) if row['entry_index'] is None}
    assert without and {(e['trial'], e['arm'], e['pool']) for e in c1['entries']} == with_entry
    assert not with_entry & without and 'no_entry' not in {e['outcome'] for e in c1['entries']}


def test_synthetic_pack_without_relabelling_is_byte_identical(rehearsal, tmp_path):
    from w1aux import synthetic
    from bot.master_v2 import w1_run as run
    synthetic.build(tmp_path / 'pack', 2)
    mp = pytest.MonkeyPatch()
    mp.setenv('RUGGER_NO_DOTENV', '1')
    try:
        run.run_trials(tmp_path / 'pack', _series(rehearsal), registry_path=tmp_path / 't.jsonl',
                       sensitivity_registry_path=tmp_path / 's.jsonl', registered_at='2026-11-08T00:00:00+00:00',
                       out=tmp_path / 'out')
    finally:
        mp.undo()
    seq = _main(tmp_path / 'pack', tmp_path / 'out' / 'bundles', tmp_path / 'v74', series=_series(rehearsal))
    with C1.c1_rule():
        c1 = _main(tmp_path / 'pack', tmp_path / 'out' / 'bundles', tmp_path / 'c1', series=_series(rehearsal))
    assert seq == c1


def test_ledger_resume_is_the_v7_6_file():
    assert hashlib.sha256(Path(LR.__file__).read_bytes()).hexdigest() == LEDGER_RESUME_V76_SHA256


def test_a_cache_written_by_v7_6_is_fully_reused_by_v7_7_with_c1(rehearsal, tmp_path):
    v76 = Path(__file__).resolve().parents[3] / 'w1aux_v76'
    if not (v76 / 'w1aux' / 'ledger_resume.py').is_file():
        pytest.skip('w1aux_v76 is not next to this package')
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, 'L1_event_horizon', lambda b: _migrated(_row(b, 'open_at_end')))
    script = (
        'import io, sys\n'
        'from pathlib import Path\n'
        'from w1aux import ledger as L, ledger_resume as LR\n'
        'assert "w1aux_v76" in L.__file__, L.__file__\n'
        'with LR.resumable_ledger(Path(sys.argv[1]), "trials:test") as st:\n'
        '    L.main(["--pools", sys.argv[2], "--bundles", sys.argv[3], "--series", sys.argv[4], "--out", sys.argv[5]], out=io.StringIO())\n'
        'print(st["computed"])\n')
    env = dict(__import__('os').environ, PYTHONPATH=':'.join([str(Path.cwd()), str(v76)]))
    done = __import__('subprocess').run([__import__('sys').executable, '-B', '-c', script, str(tmp_path / 'cache'), str(PACK),
                                         str(bundles), str(_series(rehearsal)), str(tmp_path / 'v76_fail')],
                                        env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    computed_by_v76 = int(done.stdout.strip().splitlines()[-1])
    assert computed_by_v76 == 4 and json.loads((tmp_path / 'v76_fail' / 'ledger.json').read_text())['verdict'] == 'FAIL'
    with C1.c1_rule(), LR.resumable_ledger(tmp_path / 'cache', 'trials:test') as st:
        fixed = _main(PACK, bundles, tmp_path / 'v77_c1', series=_series(rehearsal))
    assert json.loads(fixed[1])['verdict'] == 'PASS'
    assert st['reused'] == computed_by_v76 and st['computed'] == 0 and st['rejected'] == 0 and st['resumes'] == 1
