"""livepaper 0.1 on synthetic CPMM pools only (no collected page, no network): the live anchor equals the frozen
cost on the trigger, the loop is causal (records before a receipt never depend on later data), the journal is a
verifiable hash chain that the replay reproduces byte for byte, the source modes, the budget, the stops and S-4."""
import hashlib
import json
from dataclasses import replace

import pytest

from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A, FEES_A
from cpmmpilot import budget as B, rpc as RPC
from cpmmprereg import rule as R
from cpmmx import events, timeline as TL
from cpmmx.tests.test_cpmmx import BASE_B58
from livesim.tests.test_sim import IDS, NAMES, START, market_rows, raw_txs
from livepaper import cli as C, engine as E, fill as F, journal as J, source as S

HOUR = 3_600
SEED = 'cd' * 32
CFG = dict(CONFIG_A, sha256='ef' * 32)


def feed(now, ids=IDS[:3], extra=None):
    """{pool: {sig: raw}} of synthetic pools (bursts of buyers every hour); slot = 2 x time (livesim fixtures)."""
    out = {}
    for pid in ids:
        rows = market_rows(now)
        if extra and pid in extra:
            rows = sorted(rows + extra[pid])
        out[events.b58encode(pid)] = raw_txs(pid, rows, FEES_A)
    return out


def pools(names=NAMES[:3], b3=2):
    return [dict(pool=p, base_mint=BASE_B58, wsol_vault='W', config=CFG, b3=b3) for p in names]


def run_engine(tmp_path, txs, *, until, every=30, delay=1, variant='A', name='j', b3=2, since=START):
    """Receipts every `every` s from START: the transactions with block time <= receipt - delay, receipt slot = 2 x t."""
    journal = J.Journal(tmp_path / ('%s.jsonl' % name))
    eng = E.Engine(pools(list(txs), b3=b3), start=START, seed_sha=SEED, variant=variant, journal=journal,
                   store=tmp_path / ('%s_store' % name))
    sent = {p: set() for p in txs}
    for t in range(START + every, until + 1, every):
        batch = {}
        for p, d in txs.items():
            new = [r for s, r in d.items() if s not in sent[p] and since <= r['blockTime'] <= t - delay]
            sent[p].update(r['transaction']['signatures'][0] for r in new)
            batch[p] = new
        eng.step(receipt_slot=2 * t, receipt_time=t, batch=batch, wall=float(t), mono_ns=t * 10 ** 9)
    return eng, journal


# -- fill: the live anchor ------------------------------------------------------------------------------------------
def test_on_the_trigger_the_live_anchor_is_the_frozen_cost():
    now = START + 2 * HOUR
    txs = raw_txs(IDS[0], market_rows(now), FEES_A)
    line = TL.build(NAMES[0], txs, base_mint=BASE_B58)
    checked = 0
    for i in range(5, len(line.swaps) - 40, 17):
        s = line.swaps[i]
        a = F.Anchor(s.key, s.slot, s.block_time)
        for kw in (dict(), dict(failures=CC.SENSITIVITY_FAILURES), dict(latency_slots=CC.SENSITIVITY_LATENCY_SLOTS),
                   dict(buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM)):
            lat = kw.get('latency_slots', CC.LATENCY_SLOTS)
            buy_f = kw.get('failures', CC.FROZEN_FAILURES).buy
            try:
                frozen_exit = R.exit_point(line, i, CFG, latency_slots=lat, buy_failures=buy_f)
            except (CC.CostError, TL.TimelineError) as exc:
                with pytest.raises(type(exc)):
                    F.exit_point(line, a, CFG, latency_slots=lat, buy_failures=buy_f)
                continue
            assert F.exit_point(line, a, CFG, latency_slots=lat, buy_failures=buy_f) == frozen_exit
            es, et = frozen_exit
            try:
                frozen = CC.position(line, i, CFG, exit_slot=es, exit_time=et, **kw)
            except (CC.CostError, TL.TimelineError) as exc:
                with pytest.raises(type(exc), match=str(exc)):
                    F.position(line, a, CFG, exit_slot=es, exit_time=et, **kw)
                continue
            live = F.position(line, a, CFG, exit_slot=es, exit_time=et, **kw)
            assert live.pop('anchor_key') == list(s.key) and live.pop('receipt_time') == s.block_time
            assert live == frozen
            checked += 1
    assert checked >= 20


def test_the_live_anchor_moves_the_landing_the_clock_and_the_guard_state():
    now = START + 2 * HOUR
    line = TL.build(NAMES[0], raw_txs(IDS[0], market_rows(now), FEES_A), base_mint=BASE_B58)
    i = 40
    s, last = line.swaps[i], line.swaps[i + 3]
    later = F.Anchor(last.key, last.slot + 50, last.block_time + 25)
    es, et = F.exit_point(line, later, CFG)
    row = F.position(line, later, CFG, exit_slot=es, exit_time=et)
    assert row['decision_index'] == i + 3 and row['decision_slot'] == last.slot + 50
    if row['status'] == 'entered':
        assert row['buy_landing_slot'] == last.slot + 50 + CC.LATENCY_SLOTS
    if et is not None:
        assert et == last.block_time + 25 + R.CLOCK_S + R.hrr.clock_exit_latency_s(CC.LATENCY_SLOTS)
    assert F.exit_point(line, F.Anchor(s.key, s.slot, s.block_time), CFG) == R.exit_point(line, i, CFG)
    with pytest.raises(CC.CostError, match='anchor_swap_not_in_the_line'):
        F.position(line, F.Anchor((1, 2, 3), 9, 9), CFG, exit_time=10 ** 10)


# -- journal ----------------------------------------------------------------------------------------------------------
def test_the_journal_is_a_hash_chain_written_one_step_at_a_time(tmp_path):
    j = J.Journal(tmp_path / 'j.jsonl')
    a = j.append('START', x=1)
    assert a['prev'] == J.ZERO and a['seq'] == 0 and not (tmp_path / 'j.jsonl').exists()   # buffered
    b = j.append('STEP', step=0, wall=1.5)
    assert b['prev'] == a['sha'] and j.head == b['sha']
    j.commit()
    lines = (tmp_path / 'j.jsonl').read_text().splitlines()
    assert len(lines) == 2 and J.verify_records(J.read(tmp_path / 'j.jsonl')) == b['sha']
    with pytest.raises(J.JournalError, match='existing_journal_needs_replay_mode'):
        J.Journal(tmp_path / 'j.jsonl')
    with pytest.raises(J.JournalError, match='unknown_kind'):
        j.append('BUY')
    with pytest.raises(J.JournalError, match='reserved_field'):
        j.append('STEP', sha='x')
    tampered = [json.loads(x) for x in lines]
    tampered[0]['x'] = 2
    (tmp_path / 't.jsonl').write_text(''.join(J.canonical(r) + '\n' for r in tampered))
    with pytest.raises(J.JournalError, match='chain_broken_at:0'):
        J.Journal(tmp_path / 't.jsonl', replay=True)
    (tmp_path / 'u.jsonl').write_text(lines[0] + '\n' + lines[1][:20])
    with pytest.raises(J.JournalError, match='unreadable_line:1'):
        J.read(tmp_path / 'u.jsonl')
    r = J.Journal(tmp_path / 'j.jsonl', replay=True)
    assert r.append('START', x=1)['sha'] == a['sha'] and r.append('STEP', step=0, wall=99.0)['sha'] == b['sha']
    r2 = J.Journal(tmp_path / 'j.jsonl', replay=True)
    with pytest.raises(J.JournalError, match='replay_differs_at:0'):
        r2.append('START', x=2)


# -- the loop -----------------------------------------------------------------------------------------------------------
def test_the_loop_decides_orders_lands_and_exits_without_any_later_datum(tmp_path):
    until = START + 3 * HOUR
    eng, j = run_engine(tmp_path, feed(until), until=until)
    rec = j.records
    assert rec[0]['kind'] == 'START' and rec[0]['label'] == 'PAPER_LIVE_DEMO' and rec[0]['code_sha256'] == E.code_sha256()
    prim = [r for r in rec if r['kind'] == 'DECISION' and r['series'] == 'primary']
    plac = [r for r in rec if r['kind'] == 'DECISION' and r['series'] == 'placebo']
    exits = {r['id']: r for r in rec if r['kind'] == 'EXIT'}
    assert len(prim) >= 3 and plac
    received = {}
    for r in rec:
        if r['kind'] == 'RECEIVED':
            received[r['signature']] = r
            assert r['slot'] <= r['receipt_slot'] and r['block_time'] <= r['receipt_time'] - 1
    for d in prim:
        mine = [(r['slot'], r['transaction_index']) for r in rec
                if r['kind'] == 'RECEIVED' and r['pool'] == d['pool'] and r['step'] <= d['step']]
        assert d['anchor_key'][:2] == list(max(mine))           # the last swap known at the receipt
        assert d['receipt_time'] >= d['trigger_time'] and 0 <= d['delay_s'] <= 31
        assert d['trigger_received_step'] == d['step'] and received[d['trigger_signature']]['step'] <= d['step']
        assert tuple(d['anchor_key'])[0] <= d['receipt_slot'] and d['decided_after_gap'] is False
    orders = [r for r in rec if r['kind'] == 'ORDER']
    assert all(o['simulated'] is True and o['sent'] is False for o in orders) and len(orders) == len(prim) + sum(
        1 for p in plac if p['entered'])
    closed = [e for e in exits.values() if e['series'] == 'primary']
    assert closed and all(e['status'] in ('entered', 'guard_failed', 'unpriced_zero_sale') for e in closed)
    for e in exits.values():
        land = next(r for r in rec if r['kind'] == 'LANDING' and r['id'] == e['id'])
        assert land['seq'] < e['seq'] or land['step'] == e['step']
    steps = [r for r in rec if r['kind'] == 'STEP']
    assert [s['step'] for s in steps] == list(range(len(steps))) and rec[-1]['kind'] == 'STEP'
    receipt = {s['step']: s for s in steps}
    assert E.SETTLE_SLOTS == 150 and E.SETTLE_S == 60
    for r in rec:                                  # nothing is resolved before it is settled (confirmed data)
        if r['kind'] == 'LANDING':
            assert r['settled_slot'] == receipt[r['step']]['receipt_slot'] - 150 >= r['buy_landing_slot']
        if r['kind'] == 'EXIT' and r['status'] == 'entered':
            ex = r['row']['exit']
            if ex['rule'] == 'slot':
                assert ex['declared'] <= receipt[r['step']]['receipt_slot'] - 150
            else:
                assert ex['declared'] <= receipt[r['step']]['receipt_time'] - 60
    assert len({d['trigger_signature'] for d in prim}) == len(prim)
    assert rec[0]['mode'] == 'gtfa' and rec[0]['poll_s'] == 150
    marks = [r for r in rec if r['kind'] == 'MARK']
    assert marks and all(r['descriptive'] is True and r['mark_time'] % 3_600 == 0 for r in marks)
    assert all(type(r['value_lamports']) is int for r in marks if r['unpriced'] is None)
    for m in marks:                                # a mark only for a landed, still open position
        lands = [r for r in rec if r['kind'] == 'LANDING' and r['id'] == m['id']]
        exits = [r for r in rec if r['kind'] == 'EXIT' and r['id'] == m['id']]
        assert lands and lands[0]['seq'] < m['seq'] and (not exits or exits[0]['seq'] > m['seq'])
    waits = [r for r in rec if r['kind'] == 'WAIT']
    assert {tuple(w['reasons']) for w in waits if 'series' not in w} == {('no_live_swap',)}
    g0 = [r for r in rec if r['kind'] == 'G0']
    for p in NAMES[:3]:
        mine = [(r['admitted'], r['reasons']) for r in g0 if r['pool'] == p]
        assert mine and all(a != b for a, b in zip(mine, mine[1:]))           # a G0 record only on a change
    assert all(r['counts_for_operational_master'] is False for r in rec if 'counts_for_operational_master' in r)


def test_records_before_a_receipt_never_depend_on_data_received_later(tmp_path):
    until = START + 3 * HOUR
    cut = START + 2 * HOUR
    base = feed(until)
    crash = [(cut + 500 + 5 * k, 'sell', 10 ** 14, 'S%d' % k) for k in range(30)]   # a crash on an open position
    other = feed(until, extra={IDS[0]: crash})
    _e1, j1 = run_engine(tmp_path, base, until=until, name='a')
    _e2, j2 = run_engine(tmp_path, other, until=until, name='b')
    first_diff = next(k for k, (x, y) in enumerate(zip(j1.records, j2.records)) if J.stable(x) != J.stable(y))
    step = j1.records[first_diff]['step']
    receipt = next(r['receipt_time'] for r in j1.records if r['kind'] == 'STEP' and r['step'] == step)
    assert receipt > cut + 500                    # the first difference is at a receipt after the crash began
    assert [J.stable(r) for r in j1.records[:first_diff]] == [J.stable(r) for r in j2.records[:first_diff]]
    steps = {r['step']: r for r in j2.records if r['kind'] == 'STEP'}
    slot_exits = [r for r in j2.records if r['kind'] == 'EXIT' and r['status'] == 'entered'
                  and r['row']['exit']['rule'] == 'slot']
    assert slot_exits                              # the crash hits the stop loss of an open position
    assert all(r['row']['exit']['declared'] <= steps[r['step']]['receipt_slot'] - E.SETTLE_SLOTS for r in slot_exits)


def test_the_replay_reproduces_every_record_and_resumes(tmp_path):
    until = START + 2 * HOUR
    txs = feed(until)
    eng, j = run_engine(tmp_path, txs, until=until)
    again = E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'j.jsonl',
                     store=tmp_path / 'j_store')
    assert not again.journal.replaying and again.journal.head == j.head and again.n == eng.n
    assert len(again.positions) == len(eng.positions) and again.due == eng.due
    # resume then continue == one run (stable fields; the STOP of the runner is stepped over)
    half = START + HOUR
    _e, jh = run_engine(tmp_path, txs, until=half, name='h')
    jh.append('STOP', reason='planned_end_of_process', wall=0.0)
    jh.commit()
    cont = E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'h.jsonl',
                    store=tmp_path / 'h_store')
    sent = {p: {s for s, r in d.items() if START <= r['blockTime'] <= half - 1} for p, d in txs.items()}
    for t in range(half + 30, until + 1, 30):
        batch = {}
        for p, d in txs.items():
            new = [r for s, r in d.items() if s not in sent[p] and START <= r['blockTime'] <= t - 1]
            sent[p].update(r['transaction']['signatures'][0] for r in new)
            batch[p] = new
        cont.step(receipt_slot=2 * t, receipt_time=t, batch=batch, wall=float(t), mono_ns=t * 10 ** 9)
    mine = [J.stable(r) for r in cont.journal.records if r['kind'] != 'STOP']
    assert mine == [J.stable(r) for r in j.records]
    # a tampered page or record is caught
    page = next((tmp_path / 'j_store').rglob('page_*.json.gz'))
    from cpmmpilot.store import read_gz_page, write_gz_page
    doc = read_gz_page(page)
    doc['data'][0]['blockTime'] += 1
    write_gz_page(page, doc)
    with pytest.raises(E.EngineError, match='stored_transaction_differs'):
        E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'j.jsonl',
                 store=tmp_path / 'j_store')
    with pytest.raises(J.JournalError, match='replay_differs_at:0'):           # another seed: START differs
        E.resume(pools(list(txs)), start=START, seed_sha='ab' * 32, variant='A', journal_path=tmp_path / 'h.jsonl',
                 store=tmp_path / 'h_store')


def test_a_gap_is_recorded_and_its_backlog_flagged(tmp_path):
    until = START + 2 * HOUR
    txs = feed(until)
    journal = J.Journal(tmp_path / 'g.jsonl')
    eng = E.Engine(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal=journal, store=tmp_path / 'gs')
    sent = {p: set() for p in txs}
    receipts = list(range(START + 30, START + 1_800, 30)) + list(range(START + 5_400, until + 1, 30))   # 1 h down
    last = None
    for t in receipts:
        batch = {}
        for p, d in txs.items():
            new = [r for s, r in d.items() if s not in sent[p] and START <= r['blockTime'] <= t - 1]
            sent[p].update(r['transaction']['signatures'][0] for r in new)
            batch[p] = new
        gap = (float(last), float(t)) if last is not None and t - last > 60 else None
        eng.step(receipt_slot=2 * t, receipt_time=t, batch=batch, wall=float(t), mono_ns=t * 10 ** 9, gap=gap)
        last = t
    gaps = [r for r in journal.records if r['kind'] == 'GAP']
    assert len(gaps) == 1 and gaps[0]['gap_start'] == START + 1_770 and gaps[0]['gap_end'] == START + 5_400
    late = [r for r in journal.records if r['kind'] == 'DECISION' and r.get('decided_after_gap')]
    assert late and all(r['trigger_time'] < START + 5_400 and r['delay_s'] > 60 for r in late)


def test_pilot_pools_variant_and_seed_are_checked(tmp_path):
    from g23run import run as GR
    with pytest.raises(Exception):
        E.Engine(pools([GR.POOLS[0]]), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'a'),
                 store=tmp_path)
    with pytest.raises(E.EngineError, match='variant'):
        E.Engine(pools(), start=START, seed_sha=SEED, variant='C', journal=J.Journal(tmp_path / 'b'), store=tmp_path)
    with pytest.raises(E.EngineError, match='seed'):
        E.Engine(pools(), start=START, seed_sha='x', variant='A', journal=J.Journal(tmp_path / 'c'), store=tmp_path)
    eng = E.Engine(pools(), start=START, seed_sha=SEED, variant='A', journal=J.Journal(tmp_path / 'd'), store=tmp_path)
    with pytest.raises(E.EngineError, match='outside_the_universe'):
        eng.step(receipt_slot=1, receipt_time=1, batch={'zz': []}, wall=0.0, mono_ns=0)
    raw = next(iter(feed(START + HOUR)[NAMES[0]].values()))
    with pytest.raises(E.EngineError, match='after_the_receipt_slot'):
        eng.step(receipt_slot=raw['slot'] - 1, receipt_time=START + HOUR, batch={NAMES[0]: [raw]}, wall=0.0, mono_ns=0)
    assert E.placebo_delay(SEED, 'p', 's') == E.placebo_delay(SEED, 'p', 's')
    assert all(60 <= E.placebo_delay(SEED, 'p', str(k)) <= 1_800 for k in range(200))
    assert len({E.placebo_delay(SEED, 'p', str(k)) for k in range(200)}) > 150
    assert E.placebo_delay(SEED, 'p', 's') != E.placebo_delay('ab' * 32, 'p', 's')


def test_compare_matches_each_live_decision_with_the_a_posteriori_one(tmp_path):
    until = START + 3 * HOUR
    txs = feed(until)
    eng, j = run_engine(tmp_path, txs, until=until)
    doc = dict(variant='A', start=START, rows=pools(list(txs)), eligible=list(txs))
    cmp = C.compare(doc, tmp_path / 'j.jsonl', tmp_path / 'j_store', until)
    live = [r for r in j.records if r['kind'] == 'DECISION' and r['series'] == 'primary']
    assert len(cmp['matched']) + len(cmp['only_live']) == len(live) and cmp['matched']
    assert all(m['delay_s'] == 6 and m['decided_after_gap'] is False for m in cmp['matched'])
    closed = [m for m in cmp['matched'] if m['live_status'] != 'open' and m['a_posteriori_status'] == 'entered']
    assert closed and all(type(m['live_net_lamports']) is int and type(m['a_posteriori_net_lamports']) is int
                          for m in closed)
    assert cmp['decision_delay_s']['decisions'] == len(live) and cmp['processing_ms']['steps'] == eng.n
    assert cmp['journal_head'] == j.head and cmp['verdict'] is None


def test_no_decision_without_b3_before_the_start_or_twice(tmp_path):
    until = START + 2 * HOUR
    txs = feed(until)
    _e, j = run_engine(tmp_path, txs, until=until, b3=0, name='z')
    assert not [r for r in j.records if r['kind'] in ('DECISION', 'ORDER')]
    waits = [r for r in j.records if r['kind'] == 'WAIT']
    assert len(waits) == 3 and all(w['reasons'] == ['no_live_swap', 'b3_zero'] for w in waits)
    burst = [(START - 1_200 + 7 * k, 'buy', 2 * 10 ** 8, 'PRE%d' % k) for k in range(6)]
    txs = feed(until, extra={IDS[0]: burst})
    line = TL.build(NAMES[0], {k: v for k, v in txs[NAMES[0]].items() if v['blockTime'] >= START - HOUR},
                    base_mint=BASE_B58)
    from cpmmgen2 import rule as G2
    assert any(line.swaps[i].block_time < START for i in G2.decisions_g23(line, txs[NAMES[0]], 2))   # a pre-start trigger
    _e, j2 = run_engine(tmp_path, txs, until=until, since=START - HOUR, name='w')      # pre-start data delivered too
    prim = [r for r in j2.records if r['kind'] == 'DECISION' and r['series'] == 'primary']
    assert prim and all(d['trigger_time'] >= START for d in prim)
    assert any(r['kind'] == 'RECEIVED' and r['block_time'] < START for r in j2.records)


def test_variant_b_rebuilds_the_live_line_and_a_trailing_unreproduced_record_is_refused(tmp_path, monkeypatch):
    until = START + HOUR
    txs = feed(until)
    cut = dict(slot=2 * (START + 900) + 1, transactionIndex=0, blockTime=START + 900,
               meta=dict(err=None, logMessages=['Program CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C invoke [1]',
                                                'Log truncated']),
               transaction=dict(signatures=['cut'], message=dict(accountKeys=['X'], instructions=[])))
    txs[NAMES[0]]['cut'] = cut
    calls = []
    real = E.RB.rebuild
    monkeypatch.setattr(E.RB, 'rebuild', lambda line, t, **kw: calls.append((line.pool, kw['wsol_vault'])) or real(
        line, t, **kw))
    run_engine(tmp_path, txs, until=until, name='a', variant='A')
    assert calls == []
    _e, j = run_engine(tmp_path, txs, until=until, name='b', variant='B')
    assert calls and set(calls) == {(NAMES[0], 'W')}
    g0 = [r for r in j.records if r['kind'] == 'G0' and r['pool'] == NAMES[0]]
    assert any('undecoded_transactions' in r['reasons'] for r in g0)                 # kept undecoded: refused
    j.append('STOP', reason='planned_end_of_process', wall=0.0)
    j.append('GAP', step=99, gap_start=0.0, gap_end=1.0)                               # never reproduced
    j.commit()
    with pytest.raises(E.EngineError, match='did_not_reproduce'):
        E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='B', journal_path=tmp_path / 'b.jsonl',
                 store=tmp_path / 'b_store')


def test_the_way_is_frozen_in_start(tmp_path):
    until = START + HOUR
    txs = feed(until)
    journal = J.Journal(tmp_path / 'f.jsonl')
    eng = E.Engine(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal=journal, store=tmp_path / 'fs',
                   mode='gsfa_rank', poll_s=30)
    eng.step(receipt_slot=2 * (START + 30), receipt_time=START + 30, batch={}, wall=1.0, mono_ns=1)
    assert journal.records[0]['mode'] == 'gsfa_rank' and journal.records[0]['poll_s'] == 30
    with pytest.raises(J.JournalError, match='replay_differs_at:0'):
        E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'f.jsonl',
                 store=tmp_path / 'fs', mode='gtfa', poll_s=150)
    ok = E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'f.jsonl',
                  store=tmp_path / 'fs', mode='gsfa_rank', poll_s=30)
    assert ok.journal.head == journal.head


def test_the_anchor_rules_on_a_crafted_pool():
    """A cheap start then a pump (guard state), a swap AT the landing slot (H-1), a jump between the 4- and 8-slot
    landings (buy failures): the live anchor on the trigger still equals the frozen cost."""
    from cpmmgen3.tests.test_gen3 import POOL_A, line_of
    T = 1_000
    steps = [(t, 'sell' if (t // 20) % 2 else 'buy', 10 ** 12 if (t // 20) % 2 else 2 * 10 ** 8) for t in range(0, 900, 20)]
    steps += [(100 + k, 'buy', 10 * 10 ** 9) for k in range(3)]                       # early pump: cheap first state
    steps += [(T, 'buy', 2 * 10 ** 8), (T + 2, 'buy', 4 * 10 ** 8), (T + 3, 'buy', 20 * 10 ** 9)]
    steps += [(t, 'sell' if (t // 20) % 2 else 'buy', 10 ** 12 if (t // 20) % 2 else 2 * 10 ** 8)
              for t in range(T + 20, T + 3_000, 20)]
    line = line_of(POOL_A, sorted(steps))
    i = next(k for k, s in enumerate(line.swaps) if s.block_time == T)
    s = line.swaps[i]
    a = F.Anchor(s.key, s.slot, s.block_time)
    outs = {}
    for bf, failures in ((0, CC.FROZEN_FAILURES), (1, CC.SENSITIVITY_FAILURES)):
        frozen_exit = R.exit_point(line, i, CFG, buy_failures=bf)
        assert F.exit_point(line, a, CFG, buy_failures=bf) == frozen_exit
        outs[bf] = frozen_exit
        es, et = frozen_exit
        live = F.position(line, a, CFG, exit_slot=es, exit_time=et, failures=failures)
        frozen = CC.position(line, i, CFG, exit_slot=es, exit_time=et, failures=failures)
        live.pop('anchor_key'), live.pop('receipt_time')
        assert live == frozen and frozen['status'] == ('entered' if bf == 0 else 'guard_failed')   # 8 slots: after the jump
    assert outs[0] != outs[1] and outs[0][0] == s.slot + 6 + CC.LATENCY_SLOTS        # TP on the jump only at 4 slots
    assert F.entry_tokens(line, a, CFG) < F.entry_tokens(line, F.Anchor(s.key, s.slot - 2, s.block_time), CFG)
    with pytest.raises(CC.CostError, match='exit_before_the_buy_landed'):
        F.position(line, a, CFG, exit_time=s.block_time)
    later = F.Anchor(s.key, s.slot + 50, s.block_time + 25)                 # received 25 s after the anchor swap
    with pytest.raises(CC.CostError, match='exit_before_the_buy_landed'):
        F.position(line, later, CFG, exit_time=later.time)                  # a clock exit AT the receipt


def test_a_g0_refusal_stops_decisions_and_placebos_and_late_triggers_are_flagged(tmp_path, monkeypatch):
    until = START + 2 * HOUR
    txs = feed(until)
    cut = dict(slot=2 * (START + 900) + 1, transactionIndex=0, blockTime=START + 900,
               meta=dict(err=None, logMessages=['Program CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C invoke [1]',
                                                'Log truncated']),
               transaction=dict(signatures=['cut'], message=dict(accountKeys=['X'], instructions=[])))
    txs[NAMES[0]]['cut'] = cut
    monkeypatch.setattr(E, 'placebo_delay', lambda seed, pool, sig: 1_700)
    _e, j = run_engine(tmp_path, txs, until=until, name='r', variant='B')
    prim = [r for r in j.records if r['kind'] == 'DECISION' and r['series'] == 'primary']
    first = [d for d in prim if d['pool'] == NAMES[0]]
    assert first and all(d['receipt_time'] < START + 900 for d in first)              # none after the refusal
    assert [d for d in prim if d['pool'] == NAMES[1] and d['receipt_time'] > START + HOUR]
    waits = [r for r in j.records if r['kind'] == 'WAIT' and r.get('series') == 'placebo']
    assert [w['primary'] for w in waits] == [first[0]['id']]
    # a trigger received while the pool was held back is decided at the re-admission, and flagged as such
    real = E.Engine._gate
    monkeypatch.setattr(E.Engine, '_gate', lambda self, known, cfg: dict(admitted=False, reasons=['held'])
                        if self.n <= 20 else real(self, known, cfg))
    _e, k = run_engine(tmp_path, feed(START + HOUR), until=START + HOUR, name='k')
    late = [r for r in k.records if r['kind'] == 'DECISION' and r['series'] == 'primary'
            and r['trigger_received_step'] < r['step']]
    assert late and all(r['delay_s'] > 30 for r in late)


def test_nothing_lands_or_is_marked_before_it_is_settled(tmp_path, monkeypatch):
    monkeypatch.setattr(E, 'SETTLE_SLOTS', 10 ** 7)
    until = START + 3 * HOUR
    _e, j = run_engine(tmp_path, feed(until), until=until, name='s')
    kinds = {r['kind'] for r in j.records}
    assert 'ORDER' in kinds and not kinds & {'LANDING', 'EXIT', 'MARK'}


def test_a_sale_exactly_at_the_take_profit_exits_on_the_tp(monkeypatch):
    """R02 reserve 2: the TP boundary (>= +2 %): every sale is valued at exactly 102 000 000 lamports."""
    from types import SimpleNamespace
    now = START + 2 * HOUR
    line = TL.build(NAMES[0], raw_txs(IDS[0], market_rows(now), FEES_A), base_mint=BASE_B58)
    i = 40
    s = line.swaps[i]
    monkeypatch.setattr(CC, '_sell_on', lambda state, tokens, fees, on_input: SimpleNamespace(
        output_amount=CC.STAKE_LAMPORTS * 102 // 100))
    frozen = R.exit_point(line, i, CFG)
    assert frozen[0] is not None and frozen[1] is None                     # the frozen rule exits on the TP
    assert F.exit_point(line, F.Anchor(s.key, s.slot, s.block_time), CFG) == frozen


def test_a_journal_of_another_schema_is_not_resumed(tmp_path, monkeypatch):
    """R02 21:07Z (0.1.3 PASS, point a): a 0.1.2 / 0.1.3 journal cannot be resumed by this release -- START differs."""
    until = START + HOUR
    txs = feed(until)
    for old in ('livepaper-v0.1.1', 'livepaper-v0.1.3', 'livepaper-v0.1.4'):     # 0.1.2 writes 'livepaper-v0.1.1'
        with monkeypatch.context() as m:
            m.setattr(E, 'SCHEMA', old)
            run_engine(tmp_path, txs, until=until, name=old)
        assert J.read(tmp_path / ('%s.jsonl' % old))[0]['schema'] == old
        with pytest.raises(J.JournalError, match='replay_differs_at:0'):
            E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A',
                     journal_path=tmp_path / ('%s.jsonl' % old), store=tmp_path / ('%s_store' % old))
    run_engine(tmp_path, txs, until=until, name='same')
    assert E.resume(pools(list(txs)), start=START, seed_sha=SEED, variant='A', journal_path=tmp_path / 'same.jsonl',
                    store=tmp_path / 'same_store').journal.head == J.read(tmp_path / 'same.jsonl')[-1]['sha']
