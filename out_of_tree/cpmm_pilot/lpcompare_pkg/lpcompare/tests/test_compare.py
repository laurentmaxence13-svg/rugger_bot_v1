"""lpcompare 0.1 on synthetic CPMM pools only: one market written in R03's livesim layout (livesim.tests.test_sim) and
fed to the livepaper engine (the code that ran, 0.1.2) from a later start; no collected page, no network."""
import hashlib
import json

import pytest

from cpmmgen3.tests.test_gen3 import FEES_A
from cpmmpilot.store import read_gz_page, write_gz_page
from cpmmx import events
from cpmmx.tests.test_cpmmx import BASE_B58
from livepaper import engine as E, journal as J
from livesim import sim as L
from livesim.tests.test_sim import CFG_A, HOUR, IDS, START, collection, market_rows, raw_txs
from lpcompare import compare as C

LIVE0 = START + 2 * HOUR                  # the live start, two hours after livesim's
SEED = 'cd' * 32
NOW = START + 6 * HOUR + 900


def world(tmp_path, monkeypatch, *, now=NOW, drop=None, every=30, delay=6, gap_at=None, stop_after=None,
          trailing_stop=False, drop_livesim=None):
    """livesim collection of three pools and a live run from LIVE0 on the same transactions; `drop` = {pool index:
    [signature]} removed from the live feed only; returns (live view, livesim view, journal, names)."""
    specs = [(IDS[k], FEES_A, CFG_A, market_rows(now + 3 * HOUR)) for k in range(3)]
    out, list_l = collection(tmp_path, now + 3 * HOUR, specs, done_until=now + 3 * HOUR, monkeypatch=monkeypatch)
    ll = L.list_l_doc(list_l)
    elig = L.eligibility(out, ll)
    names = [events.b58encode(p) for p in IDS[:3]]
    for k, sigs in (drop_livesim or {}).items():           # removed from the livesim live pages only
        for page in sorted((out / 'collect').glob('live_*/%s/page_*.json.gz' % names[k])):
            data = read_gz_page(page)['data']
            write_gz_page(page, dict(data=[t for t in data if t['transaction']['signatures'][0] not in sigs]))
    pools = [dict(pool=n, base_mint=BASE_B58, wsol_vault='W', config=L.pool_config(ll, n),
                  b3=[r for r in elig['rows'] if r['pool'] == n][0]['b3']) for n in names]
    feed = {n: raw_txs(IDS[k], specs[k][3], FEES_A) for k, n in enumerate(names)}
    for k, sigs in (drop or {}).items():
        for s in sigs:
            feed[names[k]].pop(s)
    journal = J.Journal(tmp_path / 'J.jsonl')
    eng = E.Engine(pools, start=LIVE0, seed_sha=SEED, variant='B', journal=journal, store=tmp_path / 'PAGES')
    sent = {n: set() for n in names}
    for t in range(LIVE0 + every, now + 1, every):
        if gap_at is not None and gap_at[0] < t < gap_at[1]:
            continue
        batch = {}
        for n, d in feed.items():
            new = [r for s, r in d.items() if s not in sent[n] and LIVE0 <= r['blockTime'] <= t - delay]
            sent[n].update(r['transaction']['signatures'][0] for r in new)
            batch[n] = new
        gap = [gap_at[0], t] if gap_at is not None and t == gap_at[1] else None
        eng.step(receipt_slot=2 * t, receipt_time=t, batch=batch, wall=float(t), mono_ns=t * 10 ** 9, gap=gap)
        if stop_after is not None and t == stop_after:
            journal.append('STOP', reason='planned_end_of_process', wall=float(t))
            journal.commit()
    if trailing_stop:
        journal.append('STOP', reason='planned_end_of_process', wall=float(now + 5))
        journal.commit()
    live = C.live_view(tmp_path / 'J.jsonl', tmp_path / 'PAGES', pools)
    livesim = C.livesim_view(out, ll, elig, live['now'], window_start=live['start'])
    return live, livesim, journal, names, (out, ll, elig, feed, specs)


def sig_at(feed, pool, when):
    return [s for s, r in feed[pool].items() if r['blockTime'] == when][0]


# -- end to end -----------------------------------------------------------------------------------------------------
def test_the_same_market_gives_the_same_signals_and_only_the_live_latency_differs(tmp_path, monkeypatch):
    live, livesim, _j, names, _ = world(tmp_path, monkeypatch)
    doc = C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))
    prim = doc['primary']
    assert prim and all(r['category'] == 'both' and r['in_a_posteriori'] for r in prim)
    assert {r['pool'] for r in prim} == set(names)
    assert all(r['shift'] == dict(seconds=0, slots=0) for r in prim)
    closed = [r for r in prim if r['live']['outcome']['status'] != 'open' and r['livesim']['outcome']['status'] != 'open']
    assert closed and all(r['live']['latency_s'] > 0 and r['live']['latency_slots'] == 2 * r['live']['latency_s']
                          for r in closed)
    assert all('latence du live (ancre à la réception)' in r['reasons'] for r in closed
               if r['live']['outcome']['landing'] != r['livesim']['outcome']['landing'])
    assert all(r['facts']['missing_in_livesim_600'] == 0 for r in prim)
    # the live has no transaction before its start: only a window reaching before it misses some
    assert all((r['facts']['missing_in_live_600'] > 0) == (r['trigger_time'] - 600 < LIVE0) for r in prim)
    assert any(r['trigger_time'] - 600 < LIVE0 for r in prim)
    assert doc['counts_for_operational_master'] is False and doc['verdict'] is None
    assert doc['economic_conclusion'] is None
    assert all(not a['rows'] for a in doc['annex'].values())


def test_segments_split_at_the_declared_instant(tmp_path, monkeypatch):
    live, livesim, _j, _n, _ = world(tmp_path, monkeypatch)
    end = LIVE0 + 2 * HOUR
    doc = C.build(live, livesim, conform_end=end, d13=('x', 0))
    for rows, key in ((doc['primary'], 'trigger_time'), (doc['placebo'], 'entry_time')):
        for r in rows:
            assert r['entry_segment'] == ('conforme' if r[key] < end else 'hors_protocole')
            assert r['segment'] == (C.SPLIT if r['exit_after_conform_end'] else r['entry_segment'])
    s = doc['summary']
    assert sum(s[g]['primary']['rows'] for g in C.SEGMENTS) == len(doc['primary'])
    assert sum(s[g]['placebo']['rows'] for g in C.SEGMENTS) == len(doc['placebo'])
    assert s['conforme']['primary']['rows'] and s['hors_protocole']['primary']['rows']
    md = C.render(doc)
    assert all(C.SEGMENT_TITLES[g] in md for g in C.SEGMENTS)
    assert md.index(C.SEGMENT_TITLES[C.SPLIT]) < md.index(C.SEGMENT_TITLES['hors_protocole'])


def test_r02_mentions_head_the_document_and_the_out_of_protocol_segment(tmp_path, monkeypatch):
    live, livesim, _j, _n, _ = world(tmp_path, monkeypatch)
    doc = C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))
    md = C.render(doc)
    head = md.split('## ')[0]
    assert C.HEADER_D15 in head and C.LIMIT_L4 in head
    assert C.HEADER_D15 == ('getSlot, hors du texte 1366025b, a été utilisé (écart D15) ; usage ratifié a posteriori '
                            'par le propriétaire le 26/11 à 07:14:54Z (événement e383a010), l\'écart restant '
                            'documenté.')
    out = md.split('## ' + C.SEGMENT_TITLES['hors_protocole'])[1].split('## ')[0]
    assert C.OUT_OF_PROTOCOL in out and 'D13' in out and 'D14' in out
    assert md.count(C.OUT_OF_PROTOCOL) == 1
    assert md.count(C.PLACEBO_NOTE) == len(C.SEGMENTS)
    assert 'Comptes à clé stricte (sans appariement décalé)' in md
    assert doc['notes']['placebo'] == 'tirage au now de la comparaison, non comparable au T+24 h'


def test_a_transaction_missing_from_the_live_excludes_its_pool_and_is_tagged(tmp_path, monkeypatch):
    specs_rows = market_rows(NOW + 3 * HOUR)
    when = [r[0] for r in specs_rows if LIVE0 + 1800 < r[0] < LIVE0 + 2400][0]
    raws = raw_txs(IDS[0], specs_rows, FEES_A)
    lost = sig_at({'p': raws}, 'p', when)
    live, livesim, _j, names, _ = world(tmp_path, monkeypatch, drop={0: [lost]})
    slot = raws[lost]['slot']
    doc = C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=(names[0], slot))
    a = doc['annex'][names[0]]['rows']
    assert [(r['sig'], r['side'], r['d13']) for r in a] == [(lost, 'absent_live', True)]
    after = [r for r in doc['primary'] if r['pool'] == names[0] and r['trigger_time'] > when]
    assert after and all(r['category'] == 'livesim_only' for r in after)
    assert all(r['reasons'][0].startswith('exclusion G-0 live (') and 'reserves_chain_broken' in r['reasons'][0]
               for r in after)
    others = [r for r in doc['primary'] if r['pool'] != names[0]]
    assert others and all(r['category'] == 'both' for r in others)


def test_truncation_shows_open_on_one_side_only(tmp_path, monkeypatch):
    live, livesim, _j, _n, _ = world(tmp_path, monkeypatch)
    rows = [r for r in C.build(live, livesim, conform_end=LIVE0, d13=('x', 0))['primary'] if r['category'] == 'both']
    for r in rows:
        lo, so = r['live']['outcome'], r['livesim']['outcome']
        if (lo['status'] == 'open') != (so['status'] == 'open'):
            assert r['reasons'][0].startswith('troncature (')
        if lo['status'] == 'open':
            assert lo['net'] is None and lo['exit_time'] is None
    assert any(r['live']['outcome']['status'] == 'open' for r in rows)       # the last signal is open at now


def test_the_witness_is_listed_apart_and_never_matched_on_time_alone(tmp_path, monkeypatch):
    live, livesim, _j, _n, _ = world(tmp_path, monkeypatch)
    doc = C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))
    w = doc['placebo']
    assert w and {r['category'] for r in w} <= {'both', 'live_only', 'livesim_only'}
    assert len([r for r in w if r['live']]) == len(live['L_placebo'])
    assert len([r for r in w if r['livesim']]) == len(livesim['S_placebo'])
    for r in w:
        if r['category'] == 'both':
            assert r['live']['entry_key'] == r['livesim']['entry_key']
        else:
            assert r['reasons'] == ['mécanismes de témoin différents par construction']


def test_nothing_after_now_is_read(tmp_path, monkeypatch):
    live, livesim, _j, _n, _ = world(tmp_path, monkeypatch)
    now = live['now']
    for side in (live, livesim):
        for p in side['pools'].values():
            assert all(v[1] <= now for v in p['sigs'].values())
            assert all(s.block_time <= now for s in p['known'].swaps)
    assert all(v['trigger_time'] >= live['start'] for v in livesim['S'].values())


def test_t24_rows_must_agree_with_the_rows_at_now(tmp_path, monkeypatch):
    live, livesim, _j, _n, (out, ll, elig, _f, _s) = world(tmp_path, monkeypatch)
    later = L.bilan(out, ll, elig, START + 8 * HOUR)
    t24 = C.t24_rows(json.loads(json.dumps(later, default=str)))
    doc = C.build(live, livesim, conform_end=LIVE0, d13=('x', 0), t24=t24)
    assert all(r.get('livesim_t24') for r in doc['primary'] if r['livesim'])
    k = next(iter(t24))
    bad = dict(t24)
    bad[k] = dict(t24[k], decision_slot=(t24[k]['decision_slot'] or 0) + 1)
    if k in {(r['pool'], r['livesim']['decision_index']) for r in doc['primary'] if r['livesim']}:
        with pytest.raises(C.CompareError, match='t24_row_missing_or_other'):
            C.build(live, livesim, conform_end=LIVE0, d13=('x', 0), t24=bad)
    with pytest.raises(C.CompareError, match='t24_row_missing_or_other'):
        C.build(live, livesim, conform_end=LIVE0, d13=('x', 0), t24={})


def test_journal_checks(tmp_path, monkeypatch):
    live, _ls, _j, names, (_o, ll, elig, _f, _s) = world(tmp_path, monkeypatch)
    pools = [dict(pool=n, base_mint=BASE_B58, wsol_vault='W', config=L.pool_config(ll, n),
                  b3=[r for r in elig['rows'] if r['pool'] == n][0]['b3']) for n in names]
    with pytest.raises(C.CompareError, match='pools_differ_from_start'):
        C.live_view(tmp_path / 'J.jsonl', tmp_path / 'PAGES', pools[::-1])
    with pytest.raises(C.CompareError, match='pool_row_differs_from_start'):
        C.live_view(tmp_path / 'J.jsonl', tmp_path / 'PAGES', [dict(pools[0], b3=pools[0]['b3'] + 1)] + pools[1:])
    with pytest.raises(C.CompareError, match='journal_of_another_variant'):
        C.live_view(tmp_path / 'J.jsonl', tmp_path / 'PAGES', pools, variant='A')
    lines = (tmp_path / 'J.jsonl').read_text().split('\n')
    rec = json.loads(lines[5])
    rec['receipt_time'] = rec.get('receipt_time', 0) + 1
    lines[5] = json.dumps(rec)
    (tmp_path / 'K.jsonl').write_text('\n'.join(lines))
    with pytest.raises(J.JournalError):
        C.live_view(tmp_path / 'K.jsonl', tmp_path / 'PAGES', pools)


# -- the declared reason trees on crafted views -----------------------------------------------------------------------
def _views(**kw):
    pool = 'P'
    lp = dict(sigs={'a': (10, 100), 'b': (20, 200)}, admission=[(150, True, []), (250, True, [])], chain=[], b3=1,
              known=None, txs={})
    sp = dict(sigs={'a': (10, 100), 'b': (20, 200), 'c': (30, 300)}, eligible=True, gate_reasons=[], chain=[], b3=1,
              known=None, txs={})
    lp.update(kw.get('lp', {}))
    sp.update(kw.get('sp', {}))
    live = dict(pools={pool: lp}, P=kw.get('P', {}), gaps=kw.get('gaps', []), resumptions=kw.get('resumptions', []))
    livesim = dict(pools={pool: sp})
    return live, livesim


def test_livesim_only_tree_in_order():
    live, ls = _views(lp=dict(admission=[(150, True, []), (250, False, ['reserves_chain_broken'])]))
    assert C.reasons_livesim_only('P', 'b', 200, live, ls, ('P', 20)) == \
        ['exclusion G-0 live (reserves_chain_broken)']
    live, ls = _views(lp=dict(admission=[(150, True, [])]))
    assert C.reasons_livesim_only('P', 'b', 200, live, ls, ('P', 20)) == \
        ['exclusion G-0 live (aucune réception après t)']
    live, ls = _views()
    assert C.reasons_livesim_only('P', 'c', 240, live, ls, ('P', 30)) == ['transaction absente des pages live (D13)']
    assert C.reasons_livesim_only('P', 'c', 240, live, ls, ('P', 31)) == ['transaction absente des pages live']
    assert C.reasons_livesim_only('P', 'c', 240, live, ls, ('Q', 30)) == ['transaction absente des pages live']
    live, ls = _views(P={('P', 'b'): {}}, gaps=[[190, 200]], resumptions=[[200, 230]])
    assert C.reasons_livesim_only('P', 'b', 200, live, ls, ('x', 0)) == \
        ['décidable a posteriori, non décidé en direct', 'trou d\'observation GAP couvrant t', 'reprise couvrant t']
    live, ls = _views(P={('P', 'b'): {}}, gaps=[[201, 210]], resumptions=[[100, 199]])
    assert C.reasons_livesim_only('P', 'b', 200, live, ls, ('x', 0)) == ['décidable a posteriori, non décidé en direct']
    live, ls = _views()
    assert C.reasons_livesim_only('P', 'b', 200, live, ls, ('x', 0)) == ['chaîne de signaux différente']


def test_an_admission_at_the_trigger_time_counts():
    live, ls = _views(lp=dict(admission=[(150, False, ['x']), (200, True, []), (250, False, ['y'])]))
    assert C.reasons_livesim_only('P', 'b', 200, live, ls, ('x', 0)) == ['chaîne de signaux différente']
    assert C.admission_at([(150, False, ['x']), (200, True, [])], 200) == (True, [], 200)
    assert C.admission_at([(150, False, ['x'])], 151) is None


def test_live_only_tree_in_order():
    live, ls = _views(sp=dict(sigs={'a': (10, 100)}))
    assert C.reasons_live_only('P', 'b', 200, live, ls) == ['transaction absente de la collecte livesim']
    live, ls = _views(sp=dict(eligible=False, gate_reasons=['reserves_chain_broken']))
    assert C.reasons_live_only('P', 'b', 200, live, ls) == ['pool non éligible dans livesim au now (reserves_chain_broken)']
    live, ls = _views(sp=dict(eligible=False, gate_reasons=[]))
    assert C.reasons_live_only('P', 'b', 200, live, ls) == ['pool non éligible dans livesim au now (b3_zero)']
    live, ls = _views()
    assert C.reasons_live_only('P', 'b', 200, live, ls) == \
        ['décision live non confirmée a posteriori sur ses propres pages']
    live, ls = _views(P={('P', 'b'): {}})
    assert C.reasons_live_only('P', 'b', 200, live, ls) == ['chaîne de signaux différente']


def _o(**kw):
    base = dict(status='entered', landing=10, tokens=5, rule='slot', declared=20, exit_time=300, net=-1)
    base.update(kw)
    return base


def test_both_tree():
    assert C.reasons_both(_o(), _o()) == ['aucun écart']
    assert C.reasons_both(_o(status='open'), _o()) == ['troncature (live ouvert à now ; règlement du live 150 slots / '
                                                       '60 s)']
    assert C.reasons_both(_o(), _o(status='open'))[0].startswith('troncature (livesim ouvert')
    assert C.reasons_both(_o(status='open'), _o(status='open')) == ['ouvert des deux côtés à now']
    assert C.reasons_both(_o(landing=11), _o()) == ['latence du live (ancre à la réception)']
    assert C.reasons_both(_o(landing=11, rule='clock'), _o()) == ['latence du live (ancre à la réception)',
                                                                   'règle de sortie (clock / slot)']
    assert C.reasons_both(_o(declared=21), _o()) == ['point de sortie différent, même règle']
    assert C.reasons_both(_o(status='guard_failed', rule=None), _o())[0].startswith('statut différent (guard_failed')


def test_missing_window_bounds_and_prior_window():
    a = {'x': (1, 100), 'y': (2, 160), 'z': (3, 159)}
    assert C.missing(a, {}, 100, 159) == [('z', 3, 159)]              # low exclusive, high inclusive
    assert C.missing(a, {'z': (3, 159)}, 99, 160) == [('x', 1, 100), ('y', 2, 160)]
    chain = [(0, 'a'), (1, 'b'), (3600, 'c'), (3601, 'd')]
    assert C.prior(chain, 3600) == [[1, 'b']]                          # (t - 3600 ; t): both bounds excluded
    assert C.inside([[10, 20]], 10) and C.inside([[10, 20]], 20) and not C.inside([[10, 20]], 21)


def _row(cat, pool, t, slot, sig):
    side = dict(trigger_time=t, trigger_slot=slot)
    return dict(category=cat, pool=pool, sig=sig, live=side if cat == 'live_only' else None,
                livesim=side if cat == 'livesim_only' else None)


def test_shifted_pairs_nearest_first_and_strictly_under_the_cooldown():
    rows = [_row('live_only', 'P', 1000, 1, 'l1'), _row('livesim_only', 'P', 1000 + 3600, 2, 's_far'),
            _row('livesim_only', 'P', 1500, 3, 's_near'), _row('livesim_only', 'P', 700, 4, 's_mid'),
            _row('livesim_only', 'Q', 1001, 5, 's_other_pool')]
    pairs = C._pair(rows, 3600)
    assert [(a['sig'], b['sig']) for a, b in pairs] == [('l1', 's_mid')]
    rows = [_row('live_only', 'P', 1000, 1, 'l1'), _row('livesim_only', 'P', 4600, 2, 's')]
    assert C._pair(rows, 3600) == []
    rows = [_row('live_only', 'P', 1000, 1, 'l1'), _row('live_only', 'P', 1100, 1, 'l2'),
            _row('livesim_only', 'P', 1050, 2, 's')]
    assert [(a['sig'], b['sig']) for a, b in C._pair(rows, 3600)] == [('l1', 's')]
    rows = [_row('live_only', 'P', 1000, 1, 'l1'), _row('livesim_only', 'P', 900, 2, 's1'),
            _row('livesim_only', 'P', 1100, 3, 's2')]
    assert [(a['sig'], b['sig']) for a, b in C._pair(rows, 3600)] == [('l1', 's1')]   # tie: the earlier


def _side(status='entered', exit_time=150):
    return dict(outcome=dict(status=status, exit_time=exit_time))


def test_place_puts_a_conforming_entry_with_a_late_exit_apart():
    assert C.segment(99, 100) == 'conforme' and C.segment(100, 100) == 'hors_protocole'
    assert C.place({}, 50, (_side(exit_time=99), _side(exit_time=80)), 100)['segment'] == 'conforme'
    r = C.place({}, 50, (_side(exit_time=99), _side(exit_time=100)), 100)      # one side at the instant
    assert r['segment'] == C.SPLIT and r['entry_segment'] == 'conforme' and r['exit_after_conform_end'] is True
    assert C.place({}, 50, (None, _side(exit_time=101)), 100)['segment'] == C.SPLIT
    assert C.place({}, 50, (_side(status='open', exit_time=None), None), 100)['segment'] == C.SPLIT
    assert C.place({}, 50, (_side(status='guard_failed', exit_time=None), None), 100)['segment'] == 'conforme'
    r = C.place({}, 100, (_side(exit_time=300), None), 100)
    assert r['segment'] == 'hors_protocole' and r['exit_after_conform_end'] is False


def test_the_apart_rows_are_never_added_to_the_conforming_sums(tmp_path, monkeypatch):
    live, livesim, _j, _n, _ = world(tmp_path, monkeypatch)
    first = min((r for r in C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))['primary']),
                key=lambda r: r['trigger_time'])
    end = first['live']['outcome']['exit_time']
    doc = C.build(live, livesim, conform_end=end, d13=('x', 0))
    moved = [r for r in doc['primary'] if r['sig'] == first['sig']]
    assert moved and all(r['segment'] == C.SPLIT for r in moved)
    conf = [r for r in doc['primary'] if r['segment'] == 'conforme']
    s = doc['summary']
    assert s['conforme']['primary']['live']['net_lamports_closed_sum'] == sum(
        r['live']['outcome']['net'] for r in conf if r['live'] and r['live']['outcome']['status'] != 'open')
    assert s[C.SPLIT]['primary']['rows'] == len([r for r in doc['primary'] if r['segment'] == C.SPLIT]) >= 1


def test_gaps_resumptions_and_a_trailing_stop(tmp_path, monkeypatch):
    stop = LIVE0 + HOUR + 300
    live, _ls, _j, _n, _ = world(tmp_path, monkeypatch, gap_at=(LIVE0 + 3000, LIVE0 + 3300), stop_after=stop,
                                  trailing_stop=True)
    assert live['gaps'] == [[LIVE0 + 3000, LIVE0 + 3300]]
    assert live['resumptions'] == [[stop, stop + 30]]                  # the trailing STOP has no next STEP
    assert live['now'] == NOW - (NOW - LIVE0) % 30 and live['records'] == live['records_total'] - 1
    pool = live['order'][0]
    adm = live['pools'][pool]['admission']
    assert [a[0] for a in adm] == [t for t in range(LIVE0 + 30, NOW + 1, 30) if not LIVE0 + 3000 < t < LIVE0 + 3300]


def test_summary_counts_and_sums_by_side():
    o = dict(status='entered', net=-3, exit_time=1, landing=1, tokens=1, rule='slot', declared=1)
    op = dict(o, status='open', net=None)
    prim = [dict(segment='conforme', category='both', reasons=['x'], live=dict(outcome=o), livesim=dict(outcome=op)),
            dict(segment='conforme', category='livesim_only', reasons=['x', 'y'], live=None,
                 livesim=dict(outcome=dict(o, net=-5)), shifted_with='a'),
            dict(segment='hors_protocole', category='live_only', reasons=['y'], live=dict(outcome=dict(o, net=7)),
                 livesim=None, shifted_with='b')]
    s = C.summary(prim, [])
    assert s['conforme']['primary']['live'] == dict(positions=1, closed=1, open=0, net_lamports_closed_sum=-3)
    assert s['conforme']['primary']['livesim'] == dict(positions=2, closed=1, open=1, net_lamports_closed_sum=-5)
    assert s['conforme']['primary']['reasons'] == {'x': 2, 'y': 1}
    assert s['conforme']['primary']['strict_key_categories'] == {'both': 1, 'livesim_only': 1}
    assert s['conforme']['primary']['shifted_rows'] == 1 and s['hors_protocole']['primary']['shifted_rows'] == 1
    assert s['hors_protocole']['primary']['live']['net_lamports_closed_sum'] == 7
    assert s['conforme']['descriptive'] is True


def test_vocabulary_is_closed(tmp_path, monkeypatch):
    live, livesim, _j, names, _ = world(tmp_path, monkeypatch)
    doc = C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))
    doc['primary'][0]['reasons'] = ['rentable']
    with pytest.raises(Exception):
        C.render(doc)
    livesim['pools'][names[0]]['gate_reasons'] = ['gagnant']
    with pytest.raises(Exception):
        C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))


def test_a_pool_not_eligible_in_livesim_leaves_its_live_signals_alone(tmp_path, monkeypatch):
    rows = market_rows(NOW + 3 * HOUR)
    raws = raw_txs(IDS[1], rows, FEES_A)
    when = [r[0] for r in rows if LIVE0 + 1800 < r[0] < LIVE0 + 2400][0]
    lost = sig_at({'p': raws}, 'p', when)
    live, livesim, _j, names, _ = world(tmp_path, monkeypatch, drop_livesim={1: [lost]})
    assert livesim['pools'][names[1]]['eligible'] is False
    assert 'reserves_chain_broken' in livesim['pools'][names[1]]['gate_reasons']
    doc = C.build(live, livesim, conform_end=LIVE0 + 2 * HOUR, d13=('x', 0))
    mine = [r for r in doc['primary'] if r['pool'] == names[1]]
    assert mine and all(r['category'] == 'live_only' for r in mine)
    assert all(r['reasons'] == ['pool non éligible dans livesim au now (%s)'
                                % ', '.join(livesim['pools'][names[1]]['gate_reasons'])] for r in mine)
    assert [(r['sig'], r['side']) for r in doc['annex'][names[1]]['rows']] == [(lost, 'absent_livesim')]
    assert doc['livesim_gate'][names[1]]['eligible'] is False


def test_cli_checks_the_anchored_files(tmp_path, monkeypatch):
    with pytest.raises(C.CompareError, match='journal_not_the_anchored_file'):
        run = tmp_path / 'RUN'
        run.mkdir()
        (run / 'J.jsonl').write_text('x')
        for f in ('E.json', 'LS.json'):
            (tmp_path / f).write_text('{}')
        C.main(['--live-dir', str(run), '--journal-sha', '0' * 64, '--collect', str(tmp_path), '--list-l',
                str(tmp_path / 'E.json'), '--eligible', str(tmp_path / 'E.json'), '--eligible-sha', '0' * 64,
                '--livesim-json', str(tmp_path / 'LS.json'), '--livesim-json-sha', '0' * 64, '--out',
                str(tmp_path / 'OUT')])
    sha = hashlib.sha256(b'x').hexdigest()
    with pytest.raises(C.CompareError, match='livesim_json_not_the_anchored_file'):
        C.main(['--live-dir', str(run), '--journal-sha', sha, '--collect', str(tmp_path), '--list-l',
                str(tmp_path / 'E.json'), '--eligible', str(tmp_path / 'E.json'), '--eligible-sha',
                hashlib.sha256(b'{}').hexdigest(), '--livesim-json', str(tmp_path / 'LS.json'),
                '--livesim-json-sha', '0' * 64, '--out', str(tmp_path / 'OUT')])
    with pytest.raises(C.CompareError, match='eligible_not_the_anchored_file'):
        C.main(['--live-dir', str(run), '--journal-sha', sha, '--collect', str(tmp_path), '--list-l',
                str(tmp_path / 'E.json'), '--eligible', str(tmp_path / 'E.json'), '--eligible-sha', '0' * 64,
                '--livesim-json', str(tmp_path / 'LS.json'), '--livesim-json-sha', '0' * 64, '--out',
                str(tmp_path / 'OUT')])


def test_annex_bounds_sides_and_the_d13_tag():
    live = dict(order=['P'], pools={'P': dict(sigs={'a': (1, 99), 'b': (2, 100), 'c': (3, 200), 'd': (4, 201)})})
    ls = dict(pools={'P': dict(sigs={'a': (1, 99), 'e': (5, 100), 'f': (6, 200), 'g': (7, 201), 'h': (8, 150)})})
    got = C.annex(live, ls, start=100, now=200, conform_end=150, d13=('P', 8))['P']
    assert [(r['side'], r['sig'], r['segment'], r['d13']) for r in got['rows']] == [
        ('absent_live', 'e', 'conforme', False), ('absent_live', 'h', 'hors_protocole', True),
        ('absent_live', 'f', 'hors_protocole', False), ('absent_livesim', 'b', 'conforme', False),
        ('absent_livesim', 'c', 'hors_protocole', False)]
    assert (got['live_before_start'], got['live_in_window'], got['livesim_in_window']) == (1, 2, 3)
    got = C.annex(live, dict(pools={'P': dict(sigs={'b': (8, 100)})}), start=100, now=200, conform_end=150,
                  d13=('P', 3))['P']
    assert [(r['sig'], r['d13']) for r in got['rows']] == [('c', False)]         # D13 only for a live absence


def _w(pool, key, t):
    return dict(pool=pool, entry_key=key, entry_time=t, entry_slot=2 * t,
                outcome=dict(status='entered', exit_time=t + 10, net=-1, landing=1, rule='clock', declared=t + 10))


def test_the_witness_pairs_only_on_the_same_pool_and_entry_swap():
    live = dict(L_placebo=[_w('P', [5, 0, 0], 50), _w('P', [6, 0, 0], 60), _w('Q', [7, 0, 0], 70)])
    ls = dict(S_placebo=[_w('P', [5, 0, 0], 50), _w('Q', [6, 0, 0], 60), _w('P', [7, 0, 1], 70)])
    rows = C.placebo_rows(live, ls, conform_end=1000)
    assert [(r['pool'], r['category']) for r in rows] == [('P', 'both'), ('P', 'live_only'), ('Q', 'livesim_only'),
                                                          ('P', 'livesim_only'), ('Q', 'live_only')]
    assert rows[0]['reasons'] == ['même swap d\'entrée']


def test_outcome_of_open_guard_and_priced_rows():
    assert C.outcome(None, None) == dict(status='open', landing=None, tokens=None, rule=None, declared=None,
                                         exit_time=None, net=None)
    g = C.outcome(dict(status='guard_failed', net_lamports=-10, tokens=0), None)
    assert (g['status'], g['rule'], g['exit_time'], g['net']) == ('guard_failed', None, None, -10)
    e = C.outcome(dict(status='entered', net_lamports=-3, buy_landing_slot=9, tokens=4, exit_time=77,
                       exit=dict(rule='clock', declared=77)), None)
    assert (e['landing'], e['rule'], e['declared'], e['exit_time']) == (9, 'clock', 77, 77)
    # a published row (livesim, T+24 h) keeps ITS exit_time: no line is needed for a TP / SL exit
    s = C.outcome(dict(status='entered', net_lamports=-3, buy_landing_slot=9, tokens=4, exit_time=88,
                       exit=dict(rule='slot', declared=50)), None)
    assert (s['rule'], s['declared'], s['exit_time']) == ('slot', 50, 88)


def test_a_posteriori_only_rows_and_the_t24_control_branches(tmp_path, monkeypatch):
    live, livesim, _j, _n, (out, ll, elig, _f, _s) = world(tmp_path, monkeypatch)
    k = sorted(livesim['S'])[0]
    only_p = dict(live, L={kk: v for kk, v in live['L'].items() if kk != k})
    ls2 = dict(livesim, S={kk: v for kk, v in livesim['S'].items() if kk != k})
    row = [r for r in C.build(only_p, ls2, conform_end=LIVE0, d13=('x', 0))['primary'] if (r['pool'], r['sig']) == k]
    assert [(r['category'], r['reasons']) for r in row] == [
        ('a_posteriori_only', ['décidable sur les pages live a posteriori seulement'])]
    later = L.bilan(out, ll, elig, START + 8 * HOUR)
    t24 = C.t24_rows(json.loads(json.dumps(later, default=str)))
    closed = [kk for kk, v in livesim['S'].items() if v['outcome']['status'] != 'open']
    key = (closed[0][0], livesim['S'][closed[0]]['decision_index'])
    bad = dict(t24)
    bad[key] = dict(t24[key], outcome=dict(t24[key]['outcome'], net=t24[key]['outcome']['net'] + 1))
    with pytest.raises(C.CompareError, match='t24_row_differs_from_now'):
        C.build(live, livesim, conform_end=LIVE0, d13=('x', 0), t24=bad)
