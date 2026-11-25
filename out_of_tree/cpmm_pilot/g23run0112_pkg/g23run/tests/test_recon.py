"""The reconstruction step (cpmmrecon 0.1) inside the runner: rebuilt lines judged by the unchanged G-0, and the
identity with the anchored runner (g23run011_pkg) when no transaction is truncated."""
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from cpmmrecon.tests.test_rebuild import WV, Market
from cpmmx.tests.test_cpmmx import POOL_B58
from g23run import run as G
from g23run.tests.test_run import CONFIG_A, SHEET, T0, layout, small  # noqa: F401  (small: pytest fixture)

BASE_DIR, BASE_RUN_SHA256 = 'g23run011_pkg', '4e946371ba198e630746890371026880eb47835fa856456d34057c964e35b0a2'


def _market(truncated=(3,)):
    m = Market()
    for i in range(8):
        m.swap('buy' if i % 2 else 'sell', 10 ** 8 if i % 2 else 10 ** 12, truncated=i in truncated)
    for sig, t in m.txs.items():
        t.setdefault('transaction', dict(signatures=[sig], message=dict(accountKeys=['P' + sig], instructions=[])))
    return m


def test_rebuilt_lines_are_judged_by_the_unchanged_g0():
    m = _market()
    pairs = [(m.line(), m.txs)]
    selected = [dict(pool=POOL_B58, wsol_vault=WV)]
    new, report = G.rebuilt(pairs, selected, CONFIG_A)
    assert pairs[0][0].skipped and new[0][0].skipped == () and len(new[0][0].swaps) == len(pairs[0][0].swaps) + 1
    assert report[POOL_B58] == dict(skipped=1, rebuilt=1, rebuilt_swaps=1, kept={}, transactions={'sig003': 'rebuilt:1'})
    before, _ok = G.gates(pairs, CONFIG_A)
    after, _ok2 = G.gates(new, CONFIG_A)
    assert before[POOL_B58]['admitted'] is False and after[POOL_B58]['admitted'] is True
    clean = _market(truncated=())
    same, rep = G.rebuilt([(clean.line(), clean.txs)], selected, CONFIG_A)
    assert same[0][0] == clean.line() and rep[POOL_B58] == dict(skipped=0, rebuilt=0, rebuilt_swaps=0, kept={},
                                                                transactions={})
    tampered = _market()
    tampered.txs['sig003']['meta']['innerInstructions'][0]['instructions'].pop()
    kept, rep = G.rebuilt([(tampered.line(), tampered.txs)], selected, CONFIG_A)
    assert kept[0][0].skipped and rep[POOL_B58]['kept'] == {'kept:swap_transfers_not_identified': 1}


def test_a_line_without_a_creator_side_is_not_tried():
    m = _market(truncated=(0, 1, 2, 3, 4, 5, 6, 7))
    new, rep = G.rebuilt([(m.line(), m.txs)], [dict(pool=POOL_B58, wsol_vault=WV)], CONFIG_A)
    assert new[0][0] == m.line() and rep[POOL_B58]['kept'] == {'kept:not_tried_creator_side': 8}


def test_run_uses_the_rebuilt_lines_and_publishes_the_report(monkeypatch):
    m = _market()
    monkeypatch.setattr(G, 'POOLS', (POOL_B58,))
    monkeypatch.setattr(G, 'POOLS_SHA256', hashlib.sha256(POOL_B58.encode()).hexdigest())
    monkeypatch.setattr(G, 'B3', {POOL_B58: 1})
    monkeypatch.setattr(G, 'VERSIONS', dict(pilot=G.V.SCHEMA, confirmation=G.V.SCHEMA))
    monkeypatch.setattr(G, '_lines', lambda selected, root, start, end: [(m.line(), m.txs)])
    seen, real = [], G.gates
    monkeypatch.setattr(G, 'gates', lambda pairs, config: seen.append(real(pairs, config)) or seen[-1])
    recon = {}
    with pytest.raises(G.V.VerdictError, match='fewer_than_3'):                  # one pool only: by design
        G.run('pilot', selected=[dict(pool=POOL_B58, wsol_vault=WV)], root=None, config=CONFIG_A,
              sheet_sha=SHEET, credits=1_200, draws=50, recon=recon)
    assert seen[0][0][POOL_B58]['admitted'] is True                                # G-0 saw the rebuilt line
    assert recon[POOL_B58]['rebuilt'] == 1


def _anchored():
    path = Path(__file__).resolve().parents[3] / BASE_DIR / 'g23run' / 'run.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == BASE_RUN_SHA256
    spec = importlib.util.spec_from_file_location('g23run_anchored', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_without_truncation_the_outputs_are_byte_identical_to_the_anchored_runner(tmp_path, small, monkeypatch, capsys):
    old = _anchored()
    for name in ('POOLS', 'POOLS_SHA256', 'B3', 'T0', 'T0_C', 'D_PILOT', 'VERSIONS'):
        monkeypatch.setattr(old, name, getattr(G, name))
    layout(tmp_path / 'pilot', T0, 7)
    for mod in (G, old):
        monkeypatch.setattr(mod.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
        monkeypatch.setattr(mod.V, 'DRAWS', 200)
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0, selected=small)))
    outs = {}
    for tag, mod in (('new', G), ('old', old)):
        mod.main(['--phase', 'pilot', '--u2', str(tmp_path / 'u2.json'), '--root', str(tmp_path / 'pilot'),
                  '--t0-slot', '5', '--sheet-sha', SHEET, '--g23-credits', '1200', '--out', str(tmp_path / tag)])
        outs[tag] = json.loads(capsys.readouterr().out)
    for name in ('ROWS.json', 'RESULT.json'):
        assert (tmp_path / 'new' / name).read_bytes() == (tmp_path / 'old' / name).read_bytes()
        assert outs['new'][name] == outs['old'][name]
    recon = json.loads((tmp_path / 'new' / 'RECONSTRUCTION.json').read_text())
    assert recon['schema'] == G.RECONSTRUCTION_SCHEMA and set(recon['pools']) == set(G.POOLS)
    assert all(v['skipped'] == 0 and v['rebuilt'] == 0 for v in recon['pools'].values())
    assert not (tmp_path / 'old' / 'RECONSTRUCTION.json').exists()


def test_a_line_whose_creator_side_changes_is_not_tried():
    m = _market()
    line = m.line()
    first = line.swaps[0]
    flipped = replace(first, event=replace(first.event, creator_fee_on_input=not first.event.creator_fee_on_input))
    line = replace(line, swaps=(flipped,) + line.swaps[1:])
    new, rep = G.rebuilt([(line, m.txs)], [dict(pool=POOL_B58, wsol_vault=WV)], CONFIG_A)
    assert new[0][0] == line and rep[POOL_B58] == dict(skipped=1, rebuilt=0, rebuilt_swaps=0,
                                                       kept={'kept:not_tried_creator_side': 1}, transactions={})


def test_kept_reasons_are_counted_and_an_empty_clean_line_has_an_empty_report():
    m = _market(truncated=(3, 5))
    for sig in ('sig003', 'sig005'):
        m.txs[sig]['meta']['innerInstructions'][0]['instructions'].pop()
    new, rep = G.rebuilt([(m.line(), m.txs)], [dict(pool=POOL_B58, wsol_vault=WV)], CONFIG_A)
    assert len(new[0][0].skipped) == 2 and rep[POOL_B58]['kept'] == {'kept:swap_transfers_not_identified': 2}
    assert rep[POOL_B58]['skipped'] == 2 and rep[POOL_B58]['rebuilt'] == 0
    empty = Market()
    same, rep = G.rebuilt([(empty.line(), empty.txs)], [dict(pool=POOL_B58, wsol_vault=WV)], CONFIG_A)
    assert same[0][0] == empty.line() and rep[POOL_B58] == dict(skipped=0, rebuilt=0, rebuilt_swaps=0, kept={},
                                                                transactions={})
