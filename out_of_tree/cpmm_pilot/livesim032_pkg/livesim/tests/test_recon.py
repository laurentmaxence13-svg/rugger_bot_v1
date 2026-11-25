"""livesim 0.3.2 (variant B, PROJECT): cpmmrecon on the pre-start and live lines before b3, G-0 and the positions, and
the identity with livesim 0.3.1 (livesim_pkg, sim.py sha checked) when no transaction is truncated."""
import hashlib
import importlib.util
from dataclasses import replace
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A
from cpmmpilot.store import write_gz_page
from livesim import sim as L
from livesim.tests.test_sim import HOUR, NAMES, START, eligible_doc, three

BASE_DIR, BASE_SIM_SHA256 = 'livesim_pkg', '128143eced83fdcb68dc79029bb687ed2b44c39442cb5d0ead2dc99b42d8d886'
CPMM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
CLEAN = dict(skipped=0, rebuilt=0, rebuilt_swaps=0, kept={}, transactions={})


def _v031():
    path = Path(__file__).resolve().parents[3] / BASE_DIR / 'livesim' / 'sim.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == BASE_SIM_SHA256
    spec = importlib.util.spec_from_file_location('livesim_v031', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strip(doc):
    return {k: v for k, v in doc.items() if k not in ('schema', 'reconstruction')}


def test_without_truncation_eligible_and_bilan_equal_livesim_0_3_1(tmp_path, monkeypatch):
    old = _v031()
    now = START + 4 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    monkeypatch.setattr(old, 'LIST_L_SHA256', L.LIST_L_SHA256)
    ll = L.list_l_doc(list_l)
    new_e, old_e = L.eligibility(out, ll), old.eligibility(out, ll)
    assert new_e['schema'] == 'livesim-v0.3.2' and old_e['schema'] == 'livesim-v0.3.1'
    assert _strip(new_e) == _strip(old_e) and new_e['reconstruction'] == dict(pre={x: CLEAN for x in NAMES[:3]})
    new_b, old_b = L.bilan(out, ll, new_e, now), old.bilan(out, ll, old_e, now)
    assert _strip(new_b) == _strip(old_b)
    assert new_b['reconstruction'] == dict(pre={x: CLEAN for x in NAMES[:3]}, live={x: CLEAN for x in NAMES[:3]})
    assert L.render(new_b).replace('livesim-v0.3.2', 'v') == old.render(old_b).replace('livesim-v0.3.1', 'v')


def truncated_tx(t, sig):
    return dict(slot=2 * t + 1, transactionIndex=0, blockTime=t,
                meta=dict(err=None, logMessages=['Program %s invoke [1]' % CPMM, 'Log truncated']),
                transaction=dict(signatures=[sig], message=dict(accountKeys=[], instructions=[])))


def cut(out, now):
    write_gz_page(out / 'collect' / 'pre' / NAMES[2] / 'page_09999.json.gz', dict(data=[truncated_tx(START - HOUR, 'c1')]))
    write_gz_page(out / 'collect' / 'live_000' / NAMES[0] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(START + 600, 'c2')]))


def test_a_truncated_transaction_that_stays_undecoded_is_refused_by_the_unchanged_g0(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    cut(out, now)
    write_gz_page(out / 'collect' / 'pre' / NAMES[2] / 'page_09998.json.gz', dict(data=[truncated_tx(START - 2 * HOUR, 'c0')]))
    doc = eligible_doc(out, list_l)
    rows = {r['pool']: r for r in doc['rows']}
    assert rows[NAMES[2]]['g0_admitted'] is False and 'undecoded_transactions' in rows[NAMES[2]]['g0_reasons']
    rep = doc['reconstruction']['pre'][NAMES[2]]
    assert rep['skipped'] == 2 and rep['rebuilt'] == 0 and list(rep['kept'].values()) == [2]
    assert sorted(rep['transactions']) == ['c0', 'c1'] and rep['transactions']['c1'].startswith('kept')
    assert doc['pools'] == NAMES[:2] and doc['evaluable'] is False


def test_the_rebuilt_lines_feed_b3_g0_and_the_positions(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    cut(out, now)
    calls = []

    def fake(line, txs, *, wsol_vault, fees, on_input):
        calls.append((line.pool, wsol_vault, fees, on_input, line.skipped[0][0] in txs))
        return replace(line, skipped=()), {line.skipped[0][0]: 'rebuilt:1'}
    monkeypatch.setattr(L.RB, 'rebuild', fake)
    ll = L.list_l_doc(list_l)
    doc = L.eligibility(out, ll)
    fees_b = CC.fees_from_amm_config(L.pool_config(ll, NAMES[2]))
    assert calls == [(NAMES[2], 'W', fees_b, True, True)] and doc['pools'] == NAMES[:3]
    assert doc['reconstruction']['pre'][NAMES[2]] == dict(skipped=1, rebuilt=1, rebuilt_swaps=0, kept={},
                                                          transactions={'c1': 'rebuilt:1'})
    seen, real = [], L.simulate
    monkeypatch.setattr(L, 'simulate', lambda pairs, *a, **k: seen.append(pairs) or real(pairs, *a, **k))
    got = L.bilan(out, ll, doc, now)
    assert [p[0].skipped for p in seen[0]] == [()] * 3 and [p[2].skipped for p in seen[0]] == [()] * 3
    assert got['eligible'] == NAMES[:3] and got['pool_gate'][NAMES[0]]['admitted'] is True     # live line rebuilt
    assert got['reconstruction']['live'][NAMES[0]]['transactions'] == {'c2': 'rebuilt:1'}
    assert got['reconstruction']['pre'][NAMES[2]]['rebuilt'] == 1
    assert [c[0] for c in calls] == [NAMES[2], NAMES[0], NAMES[2]]       # eligible; bilan: live of A, pre of B


def test_rebuilt_is_the_rule_of_g23run_0_1_2():
    from livesim.tests.test_sim import IDS, FEES_A, raw_txs, market_rows
    from cpmmx import timeline as TL
    from cpmmx.tests.test_cpmmx import BASE_B58
    txs = raw_txs(IDS[0], market_rows(START + HOUR)[:40], FEES_A)
    line = TL.build(NAMES[0], txs, base_mint=BASE_B58)
    assert L.rebuilt(line, txs, 'W', CONFIG_A) == (line, CLEAN)
    odd = replace(line, skipped=(('s', 'log_truncated'),), swaps=(replace(line.swaps[0], event=replace(
        line.swaps[0].event, creator_fee_on_input=False)),) + line.swaps[1:])
    assert L.rebuilt(odd, txs, 'W', CONFIG_A) == (odd, dict(skipped=1, rebuilt=0, rebuilt_swaps=0,
                                                            kept={'kept:not_tried_creator_side': 1}, transactions={}))
    empty = replace(line, skipped=(('s', 'x'), ('t', 'x')), swaps=())
    assert L.rebuilt(empty, txs, 'W', CONFIG_A)[1]['kept'] == {'kept:not_tried_creator_side': 2}
    assert L.pool_wsol_vault(dict(list=[dict(pool='p', wsol_vault='V')]), 'p') == 'V'
    import pytest
    with pytest.raises(L.SimError, match='pool_not_once_in_list_l'):
        L.pool_wsol_vault(dict(list=[dict(pool='p', wsol_vault='V')] * 2), 'p')
