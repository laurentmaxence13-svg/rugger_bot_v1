"""w1aux.dayj_c1p1 (v7.8, package v2.6.4 / option A2): the official dayj ledger step with C1 and P1 together.

* C1 + P1 together give byte-identical ledger files to C1 alone (sequential), with and without relabelled rows;
* on the frozen-pack dayj chain, the launcher gives the same ledger digest and the same ledger/ files as the plain
  dayj ledger step (no relabelled row there), writes its trace outside the dayj directory, restores the modules;
* any other step, a non-positive worker count and an existing trace are refused.
"""
import io
import json
import shutil

import pytest

from w1aux import dayj as D
from w1aux import dayj_c1p1 as DC
from w1aux import ledger as L
from w1aux import ledger_c1 as C1
from w1aux import ledger_parallel as LP
from w1aux.tests.test_dayj import chain  # noqa: F401  (fixture)
from w1aux.tests.test_ledger import PACK, _copy, _rewrite, rehearsal  # noqa: F401  (module fixture)
from w1aux.tests.test_ledger_c1 import _apply_window, _migrated, _row, _series
from w1aux.tests.test_ledger_parallel import _main


@pytest.mark.parametrize('relabel', [None, _apply_window, _migrated])
@pytest.mark.parametrize('workers', [1, 3])
def test_c1_and_p1_together_equal_c1_alone(rehearsal, tmp_path, relabel, workers):
    bundles = rehearsal / 'out' / 'bundles'
    if relabel is not None:
        bundles = _copy(rehearsal, tmp_path)
        _rewrite(bundles, 'L1_event_horizon', lambda b: relabel(_row(b, 'open_at_end')))
    with C1.c1_rule():
        alone = _main(PACK, bundles, tmp_path / 'c1', series=_series(rehearsal))
    with C1.c1_rule(), LP.parallel_ledger(workers) as stats:
        both = _main(PACK, bundles, tmp_path / 'c1p1', series=_series(rehearsal))
        calls = stats['calls']
    assert both == alone and json.loads(both[1])['verdict'] == 'PASS' and calls > 0
    if relabel is not None:                                     # the W1 defect is there, and v7.4 alone still FAILs
        assert json.loads(_main(PACK, bundles, tmp_path / 'v74', series=_series(rehearsal))[1])['verdict'] == 'FAIL'
    assert L.verify_cycle.__module__ == 'w1aux.ledger' and L.build_ledger.__module__ == 'w1aux.ledger'


def test_launcher_gives_the_plain_dayj_ledger_step_on_the_frozen_chain(chain, tmp_path):
    tmp, out, calls, ctl, step = chain
    for name in D.STEPS[:D.STEPS.index('ledger')]:
        step(name)
    twin = tmp / 'w1_twin'
    shutil.copytree(out, twin)
    plain = json.loads(step('ledger'))
    state = json.loads((twin / D.STATE).read_text())
    argv = ['--step', 'ledger', '--out', str(twin), '--s0', str(state['s0']),
            '--expect-sha', state['steps']['evaluate']['digest']]
    buffer = io.StringIO()
    trace_path = tmp / 'trace_c1p1.json'
    assert DC.main(['--ledger-workers', '2', '--trace', str(trace_path), '--', *argv], out=buffer) == 0
    launched = json.loads(buffer.getvalue())
    assert launched['digest'] == plain['digest'] and launched['details']['verdict'] == 'PASS'
    for name in ('ledger.json', 'ledger.md'):
        assert (twin / 'ledger' / name).read_bytes() == (out / 'ledger' / name).read_bytes()
    trace = json.loads(trace_path.read_text())
    assert trace['c1']['sha256'] == C1.module_sha256() and trace['c1']['module'] == 'w1aux/ledger_c1.py'
    assert trace['p1']['workers'] == 2 and trace['p1']['stats']['calls'] > 0 and trace['dayj_exit_code'] == 0
    assert not any(p.name == trace_path.name for p in twin.rglob('*'))       # outside the dayj directory
    assert L.verify_cycle.__module__ == 'w1aux.ledger' and L.build_ledger.__module__ == 'w1aux.ledger'
    with pytest.raises(DC.DayjC1P1Error, match='trace_exists'):
        DC.main(['--ledger-workers', '2', '--trace', str(trace_path), '--', *argv], out=io.StringIO())


def test_refusals(tmp_path):
    with pytest.raises(DC.DayjC1P1Error, match='only_the_ledger_step'):
        DC.main(['--ledger-workers', '2', '--trace', str(tmp_path / 't'), '--', '--step', 'trials', '--out',
                 str(tmp_path), '--s0', '1'])
    with pytest.raises(DC.DayjC1P1Error, match='ledger_workers_must_be_positive'):
        DC.main(['--ledger-workers', '0', '--trace', str(tmp_path / 't'), '--', '--step', 'ledger', '--out',
                 str(tmp_path), '--s0', '1'])
    assert not (tmp_path / 't').exists()


def test_a_dayj_failure_inside_restores_the_modules(tmp_path, monkeypatch):
    def boom(argv, *, out=None):
        assert L.verify_cycle is C1.verify_cycle_c1 and L.build_ledger.__module__ == 'w1aux.ledger_parallel'
        raise D.DayJError('ledger_verdict_not_pass')
    monkeypatch.setattr(D, 'main', boom)
    with pytest.raises(D.DayJError, match='ledger_verdict_not_pass'):
        DC.main(['--ledger-workers', '2', '--trace', str(tmp_path / 't'), '--', '--step', 'ledger', '--out',
                 str(tmp_path), '--s0', '1'])
    assert L.verify_cycle.__module__ == 'w1aux.ledger' and L.build_ledger.__module__ == 'w1aux.ledger'
    assert not (tmp_path / 't').exists()                                       # no trace without a finished step
