"""w1diag.histogram: only the structure of the mismatches reaches the standard output (whitelist)."""
import hashlib
import io
import json

import pytest

from w1diag import histogram as H

POOL_A, POOL_B, POOL_C = 'A' * 44, 'B' * 44, 'C' * 44


def _ledger():
    entries = [
        dict(trial='L1', arm='master', pool=POOL_A, pnl_lamports=123456789, net_return=0.4242,
             checks=dict(l1_exit_plan_re_derived=False, exit_index=False), verified=False,
             mismatches=['l1_exit_plan:ledger={"tp_pct": 50}:bundle={"tp_pct": 40}', 'exit_index:ledger=17:bundle=18']),
        dict(trial='L1', arm='placebo_random', pool=POOL_B, pnl_lamports=-987654321, net_return=-0.1313,
             checks=dict(l1_exit_plan_re_derived=True), verified=False, mismatches=['exit_index:ledger=3:bundle=4']),
        dict(trial='S1', arm='immediate-snipe', pool=POOL_A, pnl_lamports=555, net_return=0.0001, checks={}, verified=False,
             mismatches=['pool_not_in_the_exported_pools', 'buy_refused:bad', 'WEIRD NAME:x', 'exit_index:a', 'exit_index:b']),
        dict(trial='S1', arm='immediate-snipe', pool=POOL_C, pnl_lamports=777, net_return=0.0002, verified=True, mismatches=[],
             checks=dict(tokens=True)),
        dict(trial='M1_latency10', arm='master', pool=POOL_C, verified=None, mismatches=[], note='not_re_derived:x'),
    ]
    mismatches = [dict(trial=e['trial'], arm=e['arm'], pool=e['pool'], mismatches=e['mismatches']) for e in entries if e['mismatches']]
    return dict(verdict='FAIL', mismatches=mismatches, entries=entries, cycles_with_entry=5, cycles_verified=1,
                comparison={'L1:master': dict(mean_pnl_lamports=31415926)})


def _run(tmp_path, doc, sha=None):
    path = tmp_path / 'ledger.json'
    path.write_bytes(json.dumps(doc).encode())
    buffer = io.StringIO()
    code = H.main(['--ledger', str(path), '--ledger-sha256', sha or hashlib.sha256(path.read_bytes()).hexdigest()], out=buffer)
    return code, buffer.getvalue()


def test_known_mismatches_give_the_expected_structure(tmp_path):
    code, text = _run(tmp_path, _ledger())
    line = json.loads(text)
    assert code == 0 and text.count('\n') == 1 and list(line) == list(H.OUTPUT_KEYS)
    assert line['verdict'] == 'FAIL' and line['mismatch_entries'] == 3
    assert line['histogram'] == [['L1', 'master', 'exit_index', 1], ['L1', 'master', 'l1_exit_plan', 1],
                                 ['L1', 'placebo_random', 'exit_index', 1],
                                 ['S1', 'immediate-snipe', 'buy_refused', 1], ['S1', 'immediate-snipe', 'exit_index', 1],
                                 ['S1', 'immediate-snipe', 'pool_not_in_the_exported_pools', 1],
                                 ['S1', 'immediate-snipe', 'unrecognized_check_name', 1]]
    assert line['pools_touched_by_trial'] == {'L1': 2, 'S1': 1}
    assert line['l1_plan_not_re_derived_by_trial'] == {'L1': 1}


def test_nothing_forbidden_reaches_the_standard_output(tmp_path):
    _code, text = _run(tmp_path, _ledger())
    for forbidden in (POOL_A, POOL_B, POOL_C, '123456789', '987654321', '0.4242', '0.1313', '31415926', '"tp_pct"',
                      'pnl', 'net_return', 'comparison', 'cycles_with_entry', 'cycles_verified', 'ledger=', 'bundle=',
                      'WEIRD', 'bad'):
        assert forbidden not in text, forbidden
    assert set(json.loads(text)) == set(H.OUTPUT_KEYS)


def test_names_outside_the_vocabulary_are_masked(tmp_path):
    doc = _ledger()
    doc['mismatches'][0]['trial'] = POOL_A + ' 1.5 SOL'
    doc['mismatches'][0]['arm'] = {'x': 1}
    _code, text = _run(tmp_path, doc)
    assert POOL_A not in text and 'SOL' not in text and 'unrecognized' in text


def test_the_ledger_must_be_the_anchored_one_and_have_a_mismatch_list(tmp_path):
    with pytest.raises(H.DiagnosisError, match='ledger_is_not_the_anchored_one'):
        _run(tmp_path, _ledger(), sha='0' * 64)
    with pytest.raises(H.DiagnosisError, match='ledger_without_a_mismatch_list'):
        _run(tmp_path, dict(verdict='PASS'))


def test_a_pass_ledger(tmp_path):
    _code, text = _run(tmp_path, dict(verdict='PASS', mismatches=[], entries=[]))
    assert json.loads(text) == dict(verdict='PASS', mismatch_entries=0, histogram=[], pools_touched_by_trial={},
                                    l1_plan_not_re_derived_by_trial={})


def test_a_verdict_outside_pass_fail_is_masked(tmp_path):
    doc = dict(_ledger(), verdict='FAIL with pnl 42')
    _code, text = _run(tmp_path, doc)
    assert json.loads(text)['verdict'] == 'unrecognized' and '42' not in text
