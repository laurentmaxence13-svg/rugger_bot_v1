"""w1diag.c1_table: only the shape of the selected bundle rows reaches the standard output (whitelist)."""
import gzip
import hashlib
import io
import json

import pytest

from w1diag import c1_table as C

UNIT = 105_000


def _row(outcome, tx, *, mark=None, notes=(), exit_index=None, pnl=None):
    row = dict(outcome=outcome, tx_costs=tx, failed_attempt_costs=0, notes=list(notes), exit_index=exit_index,
               pnl_lamports=pnl, spent=123456789, received=987654321)
    if mark is not None:
        row['mark_pnl_lamports'] = mark
    return row


def _case():
    pools = [
        dict(pool='P1' * 22, arms=dict(master=_row('open_at_window_end', 2 * UNIT, mark=-4242, exit_index=17),
                                      placebo_random=_row('open_at_window_end', 2 * UNIT, mark=-31, exit_index=9))),
        dict(pool='P2' * 22, arms=dict(placebo_random=_row('migrated_unpriced', 2 * UNIT, notes=['exit_after_migration'], exit_index=5),
                                      reference=_row('migrated_unpriced', 2 * UNIT, exit_index=8))),
        dict(pool='P3' * 22, arms=dict(placebo_random=_row('closed', 2 * UNIT, exit_index=4, pnl=777),
                                      master=_row('counterfactual_divergence', UNIT + 1))),
    ]
    bundle = dict(params=dict(base_fee_lamports=5_000, priority_fee_lamports=100_000), pools=pools)
    sel = [('master', 'P1' * 22), ('placebo_random', 'P1' * 22), ('placebo_random', 'P2' * 22), ('reference', 'P2' * 22),
           ('master', 'P3' * 22)]
    mismatches = [dict(trial=C.TRIAL, arm=a, pool=p, mismatches=['tx_costs:ledger=105000:bundle=210000']) for a, p in sel]
    mismatches.append(dict(trial='L1', arm='placebo_random', pool='P3' * 22, mismatches=['tx_costs:x']))   # another trial
    mismatches.append(dict(trial=C.TRIAL, arm='placebo_random', pool='P3' * 22, mismatches=['exit_index:x']))  # another check
    return dict(verdict='FAIL', mismatches=mismatches, cycles_with_entry=99), bundle


def _run(tmp_path, ledger, bundle, *, ledger_sha=None, bundle_sha=None):
    lp, bp = tmp_path / 'ledger.json', tmp_path / 'L1_event_horizon.json.gz'
    lp.write_text(json.dumps(ledger))
    bp.write_bytes(gzip.compress(json.dumps(bundle).encode(), mtime=0))
    buffer = io.StringIO()
    C.main(['--ledger', str(lp), '--ledger-sha256', ledger_sha or hashlib.sha256(lp.read_bytes()).hexdigest(),
            '--bundle', str(bp), '--bundle-sha256', bundle_sha or hashlib.sha256(bp.read_bytes()).hexdigest()], out=buffer)
    return buffer.getvalue()


def test_the_selected_rows_give_the_expected_cross_table(tmp_path):
    text = _run(tmp_path, *_case())
    line = json.loads(text)
    assert list(line) == list(C.OUTPUT_KEYS) and line['entries'] == 5 and text.count('\n') == 1
    assert sorted(map(tuple, line['table'])) == sorted([
        ('master', 'open_at_window_end', 2, True, False, True, 1),
        ('placebo_random', 'open_at_window_end', 2, True, False, True, 1),
        ('placebo_random', 'migrated_unpriced', 2, False, True, True, 1),
        ('reference', 'migrated_unpriced', 2, False, False, True, 1),
        ('master', 'counterfactual_divergence', 'non_integer', False, False, False, 1)])


def test_nothing_forbidden_reaches_the_standard_output(tmp_path):
    text = _run(tmp_path, *_case())
    for forbidden in ('P1', 'P2', 'P3', '4242', '-31', '777', '123456789', '987654321', '210000', '105000', 'pnl',
                      'spent', 'received', 'cycles', '99'):
        assert forbidden not in text, forbidden


def test_inputs_must_be_the_anchored_ones_and_complete(tmp_path):
    ledger, bundle = _case()
    with pytest.raises(C.C1TableError, match='file_is_not_the_anchored_one:ledger.json'):
        _run(tmp_path, ledger, bundle, ledger_sha='0' * 64)
    with pytest.raises(C.C1TableError, match='file_is_not_the_anchored_one:L1_event_horizon.json.gz'):
        _run(tmp_path, ledger, bundle, bundle_sha='0' * 64)
    bundle['pools'] = bundle['pools'][1:]
    with pytest.raises(C.C1TableError, match='selected_entries_missing_from_the_bundle'):
        _run(tmp_path, ledger, bundle)


def test_unknown_outcomes_and_arm_names_are_masked(tmp_path):
    ledger, bundle = _case()
    bundle['pools'][0]['arms']['master']['outcome'] = 'secret 1.5 SOL'
    bundle['pools'][0]['arms']['x y'] = bundle['pools'][0]['arms'].pop('placebo_random')
    for m in ledger['mismatches']:
        if m['arm'] == 'placebo_random' and m['pool'] == 'P1' * 22:
            m['arm'] = 'x y'
    text = _run(tmp_path, ledger, bundle)
    assert 'secret' not in text and 'SOL' not in text and '"other"' in text and 'unrecognized' in text
