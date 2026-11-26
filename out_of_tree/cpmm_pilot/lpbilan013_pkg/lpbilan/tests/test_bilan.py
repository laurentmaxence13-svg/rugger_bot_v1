"""lpbilan 0.1 -- synthetic journals only; every expected value below is computed by hand."""
import json

import pytest

from cpmmpilot import step1 as PILOT
from livepaper import journal as J
from lpbilan import bilan as B

T0 = 1_795_632_000
CUT = T0 + 6 * 3_600


def entered(pool, gross, *, rule='clock', declared=None, fixed=420_000, fees=500_000, impact=50_000):
    parts = dict(price_move=gross, trade_and_creator_fees=-fees, price_impact=-impact, transactions=-210_000,
                 wsol_close=-105_000, cleanup=-(fixed - 315_000), rent_lost=0)
    net = sum(parts.values())
    return dict(pool=pool, decision_index=3, status='entered', net_lamports=net,
                exit=dict(rule=rule, declared=declared, state_kept={}),
                decomposition_share_of_stake={k: v / 100_000_000 for k, v in parts.items()})


def guard(pool):
    return dict(pool=pool, decision_index=4, status='guard_failed', net_lamports=-105_000)


def dec(i, pool, series, *, delay=None, trigger_slot=None, slot, t):
    f = dict(id=i, pool=pool, series=series, entered=True, receipt_slot=slot, receipt_time=t, anchor_key=[1, 2])
    if series == 'primary':
        f.update(trigger_signature='sig%d' % i, trigger_slot=trigger_slot, trigger_key=[1, 1],
                 trigger_time=t - delay, delay_s=delay, trigger_received_step=0, decided_after_gap=False)
    else:
        f.update(primary=0)
    return [('DECISION', f), ('ORDER', dict(id=i, pool=pool, series=series, side='buy', stake_lamports=100_000_000,
                                           receipt_slot=slot, receipt_time=t, simulated=True, sent=False))]


def ext(i, pool, series, row):
    return [('EXIT', dict(id=i, pool=pool, series=series, status=row['status'], net_lamports=row['net_lamports'],
                          row=row))]


def land(i, pool, series, slot):
    return [('LANDING', dict(id=i, pool=pool, series=series, buy_landing_slot=slot, settled_slot=slot + 1))]


def g0(pool, t, admitted, reasons=()):
    return [('G0', dict(pool=pool, receipt_time=t, admitted=admitted, reasons=list(reasons)))]


def journal(path, steps, *, label='PAPER_LIVE_DEMO', stops=()):
    j = J.Journal(path)
    j.append('START', schema='livepaper-v0.1.1', label=label, counts_for_operational_master=False, start=T0,
             seed_sha='5' * 64, variant='B', mode='gsfa_rank', poll_s=30, settle=[150, 60], code_sha256='c' * 64,
             pools=[dict(pool='PoolAAAAAAAA', base_mint='m', wsol_vault='w', b3=2, amm_config_sha256='a' * 64),
                    dict(pool='PoolBBBBBBBB', base_mint='m', wsol_vault='w', b3=3, amm_config_sha256='b' * 64)])
    j.commit()
    for n, (t, recs) in enumerate(steps):
        slot = 1_000 + 100 * n
        for kind, f in recs:
            j.append(kind, step=n, **f)
        j.append('STEP', step=n, receipt_slot=slot, receipt_time=t, wall=t + 0.25, mono_ns=n, processing_ms=10.0 * (n + 1),
                 open_positions=0)
        j.commit()
        for after, reason, wall in stops:
            if after == n:
                j.append('STOP', reason=reason, wall=wall)
                j.commit()
    return J.read(path)


A, Bp = 'PoolAAAAAAAA', 'PoolBBBBBBBB'


def scenario(tmp_path, **kw):
    steps = [
        (T0 + 30, g0(A, T0 + 30, True) + g0(Bp, T0 + 30, True)
         + dec(0, A, 'primary', delay=5, trigger_slot=990, slot=1_000, t=T0 + 30)),
        (T0 + 90, g0(A, T0 + 90, False, ['no_live_swap']) + land(0, A, 'primary', 1_004)),
        (T0 + 1_900, g0(A, T0 + 1_900, True) + ext(0, A, 'primary', entered(A, 600_000, declared=T0 + 1_830))
         + dec(1, A, 'placebo', slot=1_200, t=T0 + 1_900) + land(1, A, 'placebo', 1_204)),
        (T0 + 3_700, ext(1, A, 'placebo', entered(A, 1_500_000, rule='slot', declared=1_250))
         + [('GAP', dict(gap_start=T0 + 1_900.25, gap_end=T0 + 3_700.25))] + g0(Bp, T0 + 3_700, False, ['reserves_chain_broken'])
         + dec(2, Bp, 'primary', delay=7, trigger_slot=1_290, slot=1_300, t=T0 + 3_700)),
        (T0 + 7_300, g0(Bp, T0 + 7_300, False, ['reserves_chain_broken', 'b3_zero']) + land(2, Bp, 'primary', 1_304) + ext(2, Bp, 'primary', guard(Bp))
         + dec(3, A, 'primary', delay=3, trigger_slot=1_395, slot=1_400, t=T0 + 7_300) + land(3, A, 'primary', 1_408)
         + [('MARK', dict(id=3, pool=A, series='primary', mark_time=T0 + 7_200, value_lamports=99_000_000,
                          stake_lamports=100_000_000, unpriced=None, descriptive=True))]),
        (CUT, dec(4, Bp, 'primary', delay=11, trigger_slot=1_480, slot=1_500, t=CUT)
         + [('MARK', dict(id=3, pool=A, series='primary', mark_time=CUT, value_lamports=98_000_000,
                          stake_lamports=100_000_000, unpriced=None, descriptive=True))]),
        (CUT + 30, ext(3, A, 'primary', entered(A, 9_000_000, declared=CUT - 10))
         + dec(5, Bp, 'primary', delay=2, trigger_slot=1_590, slot=1_600, t=CUT + 30)),
    ]
    return journal(tmp_path / 'J.jsonl', steps, **kw)


# -- C1: the cut ------------------------------------------------------------------------------------------------------
def test_the_step_at_the_cut_is_in_and_everything_after_it_is_out(tmp_path):
    recs = scenario(tmp_path)
    pre = B.cut_prefix(recs, CUT)
    assert pre[-1]['kind'] == 'STEP' and pre[-1]['receipt_time'] == CUT
    assert {r['id'] for r in pre if r['kind'] == 'DECISION'} == {0, 1, 2, 3, 4}
    assert pre[-1]['sha'] == B.bilan(recs, CUT)['journal']['head_at_cut']
    assert B.cut_prefix(recs, CUT - 1)[-1]['receipt_time'] == T0 + 7_300


def test_a_journal_that_does_not_cover_the_cut_or_starts_after_it_is_refused(tmp_path):
    recs = scenario(tmp_path)
    with pytest.raises(B.BilanError, match='journal_does_not_cover_the_cut'):
        B.cut_prefix(recs, CUT + 30)
    with pytest.raises(B.BilanError, match='no_step_before_the_cut'):
        B.cut_prefix(recs, T0 + 29)


def test_a_broken_chain_a_foreign_label_and_decreasing_steps_are_refused(tmp_path):
    recs = scenario(tmp_path)
    bad = [dict(r) for r in recs]
    bad[5]['receipt_time'] += 1
    with pytest.raises(J.JournalError):
        B.cut_prefix(bad, CUT)
    with pytest.raises(B.BilanError, match='not_a_paper_live_demo_journal'):
        B.cut_prefix(scenario(tmp_path / 'x', label='MASTER'), CUT)
    back = journal(tmp_path / 'b.jsonl', [(T0 + 60, []), (T0 + 30, []), (CUT + 1, [])])
    with pytest.raises(B.BilanError, match='step_times_decrease'):
        B.cut_prefix(back, CUT)


def test_stop_records_follow_the_cut_by_their_wall(tmp_path):
    recs = scenario(tmp_path / 'a', stops=[(5, 'planned_end', CUT)])
    assert B.cut_prefix(recs, CUT)[-1]['kind'] == 'STOP'
    assert B.bilan(recs, CUT)['interruptions']['stops'] == [dict(reason='planned_end', wall=CUT)]
    late = scenario(tmp_path / 'b', stops=[(5, 'planned_end', CUT + 1)])
    assert B.cut_prefix(late, CUT)[-1]['kind'] == 'STEP'


# -- C2 / C3: positions and metrics -------------------------------------------------------------------------------------
def test_metrics_at_the_cut_by_hand(tmp_path):
    doc = B.bilan(scenario(tmp_path), CUT)
    p, q = doc['series']['primary'], doc['series']['placebo']
    # primary: decisions 0, 2, 3, 4; closed 0 (-370 000) and 2 (guard, -105 000); 3 exits AFTER the cut -> open
    assert (p['signals'], p['entries'], p['exits'], p['open_positions'], p['guard_refusals']) == (4, 1, 2, 2, 1)
    assert p['wins'] == 0 and p['win_rate'] == 0
    assert p['net_pnl_sol'] == pytest.approx(-0.000475) and p['gross_pnl_sol'] == pytest.approx(0.0006)
    assert p['costs_sol'] == pytest.approx(0.001075)
    assert p['max_drawdown_sol'] == pytest.approx(0.000475)
    assert p['net_return_per_position'] == pytest.approx(-475_000 / 200_000_000)
    assert [round(h['capital_sol'], 9) for h in p['capital_by_hour']] == [-0.00037, -0.00037] + [-0.000475] * 4
    assert [h['time'] for h in p['capital_by_hour']] == [T0 + k * 3_600 for k in range(1, 7)]
    # placebo: one closed, net +530 000, never merged
    assert (q['signals'], q['exits'], q['wins'], q['win_rate']) == (1, 1, 1, 1.0)
    assert q['net_pnl_sol'] == pytest.approx(0.00053) and doc['placebo_merged'] is False
    assert doc['series']['primary']['n_insufficient'] and doc['verdict'] is None
    assert doc['counts_for_operational_master'] is False


def test_an_open_position_is_never_valued_and_keeps_its_last_mark_apart(tmp_path):
    doc = B.bilan(scenario(tmp_path), CUT)
    opened = {p['id']: p for p in doc['positions'] if not p['closed']}
    assert set(opened) == {3, 4}
    assert opened[3]['landed'] and opened[3]['last_mark']['value_lamports'] == 98_000_000    # the LAST mark
    assert not opened[4]['landed'] and opened[4]['last_mark'] is None
    assert 'net_lamports' not in opened[3]


def test_a_net_of_zero_is_not_counted_above_zero(tmp_path):
    zero = entered(A, 970_000)                     # 970 000 - 500 000 - 50 000 - 420 000 = 0
    assert zero['net_lamports'] == 0
    recs = journal(tmp_path / 'J.jsonl', [(T0 + 30, dec(0, A, 'primary', delay=1, trigger_slot=1, slot=1_000, t=T0 + 30)),
                                          (T0 + 90, ext(0, A, 'primary', zero)), (CUT + 1, [])])
    assert B.bilan(recs, CUT)['series']['primary']['wins'] == 0


# -- C4 / C5 / C6 --------------------------------------------------------------------------------------------------------
def test_latencies_intervals_and_credits(tmp_path):
    doc = B.bilan(scenario(tmp_path), CUT, ledger=dict(credits=1234, requests=56, by_method={'getSlot': 7},
                                                     ceiling=25_000, hard_stop=24_500),
                  calls_lines=[dict(credits_after=10), dict(credits_after=1234)])
    lat, it = doc['latency'], doc['interruptions']
    assert lat['delay_s'] == dict(n=4, p50=7, p95=11, p99=11, max=11, mean=6.5)
    assert lat['latency_slots']['n'] == 4 and lat['latency_slots']['max'] == 8 and lat['latency_slots']['p50'] == 4
    assert lat['trigger_to_landing_slots']['n'] == 3 and lat['trigger_to_landing_slots']['p50'] == 14
    assert lat['processing_ms']['n'] == 6 and lat['processing_ms']['max'] == 60.0
    assert lat['fetch_ms'] == B.NM
    # intervals 60 (exactly 2 x poll: counted), 1 810, 1 800, 3 600, 14 300
    assert it['intervals_at_least_2_polls'] == 5 and it['max_interval_s'] == 14_300 and it['steps'] == 6
    assert it['gaps'] == [dict(start=T0 + 1_900.25, end=T0 + 3_700.25, seconds=1_800.0)]
    c = doc['credits']
    assert c['at_cut'] == B.NM and c['at_snapshot']['credits'] == 1234 and c['calls_log_last_credits_after'] == 1234


def test_fetch_ms_is_summarised_when_the_steps_carry_it(tmp_path):
    j = J.Journal(tmp_path / 'J.jsonl')
    j.append('START', schema='livepaper-v0.1.3', label='PAPER_LIVE_DEMO', counts_for_operational_master=False, start=T0,
             seed_sha='5' * 64, variant='B', mode='gsfa_rank', poll_s=30, settle=[150, 60], code_sha256='c' * 64,
             pools=[])
    for n, t in enumerate((T0 + 30, CUT + 1)):
        j.append('STEP', step=n, receipt_slot=n, receipt_time=t, wall=t, mono_ns=0, processing_ms=1.0, fetch_ms=250.0 * (n + 1),
                 open_positions=0)
    j.commit()
    assert B.bilan(J.read(tmp_path / 'J.jsonl'), CUT)['latency']['fetch_ms']['max'] == 250.0


# -- C7: decomposition -------------------------------------------------------------------------------------------------
def test_the_decomposition_must_sum_to_the_net(tmp_path):
    row = entered(A, 600_000)
    d = B.decomposition(row)
    assert d['fixed'] == pytest.approx(-0.0042) and d['gross'] == pytest.approx(0.006)
    assert B.decomposition(dict(row, net_lamports=row['net_lamports'] + 1)) is not None
    with pytest.raises(B.BilanError, match='decomposition_differs_from_net'):
        B.decomposition(dict(row, net_lamports=row['net_lamports'] + 2))
    with pytest.raises(B.BilanError, match='entered_row_without_decomposition'):
        B.decomposition({k: v for k, v in row.items() if k != 'decomposition_share_of_stake'})
    assert B.decomposition(guard(A)) is None
    extra = dict(row, decomposition_share_of_stake=dict(row['decomposition_share_of_stake'], unknown=0.0))
    with pytest.raises(B.BilanError, match='unexpected_decomposition_keys'):
        B.decomposition(extra)


def test_an_exit_record_that_differs_from_its_row_is_refused(tmp_path):
    row = entered(A, 600_000)
    bad = [('EXIT', dict(id=0, pool=A, series='primary', status='entered', net_lamports=row['net_lamports'] + 1,
                         row=row))]
    recs = journal(tmp_path / 'J.jsonl', [(T0 + 30, dec(0, A, 'primary', delay=1, trigger_slot=1, slot=1_000, t=T0 + 30)),
                                          (T0 + 90, bad), (CUT + 1, [])])
    with pytest.raises(B.BilanError, match='exit_record_differs_from_its_row'):
        B.bilan(recs, CUT)


# -- C8 and the command --------------------------------------------------------------------------------------------------
def test_documents_are_rendered_in_the_closed_vocabulary_and_the_command_is_deterministic(tmp_path):
    recs = scenario(tmp_path)
    (tmp_path / 'ledger.json').write_text(json.dumps(dict(credits=1, requests=1, by_method={}, ceiling=25_000,
                                                          hard_stop=24_500)))
    outs = []
    for k in range(2):
        B.main(['--journal', str(tmp_path / 'J.jsonl'), '--cut', str(CUT), '--ledger', str(tmp_path / 'ledger.json'),
                '--out', str(tmp_path / ('o%d' % k))])
        outs.append({n: (tmp_path / ('o%d' % k) / n).read_bytes() for n in ('BILAN.json', 'BILAN.md', 'DECOMPOSITION.md')})
    assert outs[0] == outs[1]
    md, dm = outs[0]['BILAN.md'].decode(), outs[0]['DECOMPOSITION.md'].decode()
    assert 'fetch_ms : NON MESURÉ' in md and 'Positions ouvertes au cut' in md
    assert '| G2-3 (n insuffisant : 2 < 30) | 4 | 1 | 2 | 2 | 1 | 0.00 % |' in md
    assert '## G2-3 : 2 positions fermées (+ 2 ouverte(s), non valorisée(s))' in dm
    assert '| 1 | PoolAA | 18:40:30Z | horloge (1800 s), écrite 19:11:40Z | entered | +0.6000 % | -0.5000 % | -0.0500 % | -0.4200 % | -0.3700 % | -370000 |' in dm
    assert 'slot 1250' in dm and '| guard_failed | — | — | — | — | -0.1050 % | -105000 |' in dm
    for word in ('rentable', 'profitable', 'gagnant'):
        assert word not in md.lower() and word not in dm.lower()
    assert recs == J.read(tmp_path / 'J.jsonl')


def test_a_forbidden_word_stops_the_rendering_and_an_unknown_series_is_refused(tmp_path):
    word = 'gagnant' + 'X'
    recs = journal(tmp_path / 'J.jsonl', [(T0 + 30, dec(0, word, 'primary', delay=1, trigger_slot=1, slot=1_000,
                                                          t=T0 + 30)), (CUT + 1, [])])
    doc = B.bilan(recs, CUT)
    with pytest.raises(PILOT.Step1Stop, match='forbidden_word_in_output'):
        B.render(doc)
    odd = dec(0, A, 'primary', delay=1, trigger_slot=1, slot=1_000, t=T0 + 30)
    odd[0][1]['series'] = 'other'
    recs = journal(tmp_path / 'K.jsonl', [(T0 + 30, odd), (CUT + 1, [])])
    with pytest.raises(B.BilanError, match='unknown_series'):
        B.bilan(recs, CUT)


# -- C9 ---------------------------------------------------------------------------------------------------------------
def test_g0_at_the_cut_reports_the_trailing_run_of_refusals_and_a_readmission(tmp_path):
    doc = B.bilan(scenario(tmp_path), CUT, notes=['D13 : GaPTvX exclu par G-0 depuis 20:11:03Z (transaction manquée).'])
    g = {x['pool']: x for x in doc['g0_at_cut']}
    assert g[A] == dict(pool=A, admitted=True, reasons=[], since=None, changes=3)       # refused at +90, readmitted
    assert g[Bp] == dict(pool=Bp, admitted=False, reasons=['reserves_chain_broken', 'b3_zero'], since=T0 + 3_700,
                         changes=3)                                                     # since the FIRST refusal of the run
    md = B.render(doc)
    assert '| PoolBBBB | non | reserves_chain_broken, b3_zero | 19:41:40Z | 3 |' in md
    assert '- D13 : GaPTvX exclu par G-0 depuis 20:11:03Z (transaction manquée).' in md
    assert B.cut_prefix(scenario(tmp_path / 'z'), CUT)[0]['kind'] == 'START'


def test_a_pool_without_g0_record_is_not_measured_and_no_note_reads_none(tmp_path):
    recs = journal(tmp_path / 'J.jsonl', [(T0 + 30, []), (CUT + 1, [])])
    doc = B.bilan(recs, CUT)
    assert [x['admitted'] for x in doc['g0_at_cut']] == [B.NM, B.NM] and doc['declared_defects'] == []
    md = B.render(doc)
    assert '| PoolAAAA | NON MESURÉ | — | — | 0 |' in md and '## Défauts déclarés (C9)\n\nAucun.' in md


def test_a_note_with_a_forbidden_word_is_refused(tmp_path):
    doc = B.bilan(journal(tmp_path / 'J.jsonl', [(T0 + 30, []), (CUT + 1, [])]), CUT, notes=['position ' + 'gagn' + 'ante'])
    with pytest.raises(PILOT.Step1Stop):
        B.render(doc)


def test_the_command_reads_the_notes_file(tmp_path):
    scenario(tmp_path)
    (tmp_path / 'notes.txt').write_text('D13 : premier défaut.\n\n  \nD14 : second.\n')
    B.main(['--journal', str(tmp_path / 'J.jsonl'), '--cut', str(CUT), '--notes', str(tmp_path / 'notes.txt'),
            '--out', str(tmp_path / 'o')])
    doc = json.loads((tmp_path / 'o' / 'BILAN.json').read_text())
    assert doc['declared_defects'] == ['D13 : premier défaut.', 'D14 : second.']


# -- C10 (0.1.1): the runner records of a livepaper 0.1.4 journal ---------------------------------------------------------
def test_error_and_catchup_records_are_published_and_never_change_the_metrics(tmp_path):
    base = B.bilan(scenario(tmp_path / 'a'), CUT)
    j = J.Journal(tmp_path / 'b.jsonl')
    for r in scenario(tmp_path / 'c'):
        f = {k: v for k, v in r.items() if k not in ('seq', 'prev', 'sha', 'kind')}
        if r['kind'] == 'STEP' and r['step'] == 3:                    # a catch-up before the 4th step
            j.append('CATCHUP', pool=A, outcome='found', receipt_slot=1_300, signatures=['sigX'], wall=T0 + 3_700.5)
            j.append('RECEIVED', step=3, pool=A, signature='sigX', slot=1_250, block_time=T0 + 3_600,
                     transaction_index=0, index_source='gsfa_rank_catchup', raw_sha256='0' * 64, page='p',
                     receipt_slot=1_300, receipt_time=T0 + 3_700, wall=T0 + 3_700.25, mono_ns=0)
        j.append(r['kind'], **f)
        if r['kind'] == 'STEP' and r['step'] == 5:                    # an incident right after the step at the cut
            j.append('ERROR', error_type='RpcError', message='http_503', wall=CUT)
            j.append('STOP', reason='incident:RpcError', wall=CUT)
        if r['kind'] == 'STEP' and r['step'] == 6:                    # and one after the cut: never in the prefix
            j.append('ERROR', error_type='RpcError', message='network_error', wall=CUT + 31)
        j.commit()
    recs = J.read(tmp_path / 'b.jsonl')
    doc = B.bilan(recs, CUT)
    assert doc['series'] == base['series'] and doc['positions'] == base['positions'] and doc['latency'] == base['latency']
    it = doc['interruptions']
    assert it['errors'] == [dict(error_type='RpcError', message='http_503', wall=CUT)]
    assert it['stops'] == [dict(reason='incident:RpcError', wall=CUT)]
    assert it['catchups'] == [dict(pool=A, outcome='found', signatures=['sigX'], receipt_slot=1_300, wall=T0 + 3_700.5)]
    assert it['caught_up_received'] == 1
    pre = B.cut_prefix(recs, CUT)
    assert [r['kind'] for r in pre[-2:]] == ['ERROR', 'STOP']
    md = B.render(doc)
    assert '- Incidents (ERROR) : 1.\n  - RpcError : http_503 à 00:40:00Z.' in md
    assert '- Rattrapages (CATCHUP) : 1 ; transactions rattrapées reçues : 1.' in md
    assert '  - PoolAAAA : found, 1 signature(s), slot de réception 1300 à 19:41:40Z.' in md
    assert doc['schema'] == 'lpbilan-v0.1.3'


def test_a_journal_without_runner_records_reads_none(tmp_path):
    doc = B.bilan(scenario(tmp_path), CUT)
    it = doc['interruptions']
    assert it['errors'] == [] and it['catchups'] == [] and it['caught_up_received'] == 0
    md = B.render(doc)
    assert '- Incidents (ERROR) : 0.' in md and '- Rattrapages (CATCHUP) : 0 ; transactions rattrapées reçues : 0.' in md


# -- C11 (0.1.2): every resumption between processes, whatever its length ------------------------------------------------
def test_every_resumption_is_listed_even_under_two_polls(tmp_path):
    recs = scenario(tmp_path, stops=[(0, 'planned_end_of_process', T0 + 30.5),       # next STEP wall T0 + 90.25
                                     (2, 'planned_end_of_process', T0 + 1_900.5),    # next STEP wall T0 + 3 700.25
                                     (5, 'planned_end_of_process', CUT)])            # next STEP after the cut
    doc = B.bilan(recs, CUT)
    rs = doc['interruptions']['resumptions']
    assert [(r['reason'], r['stop_wall'], r['next_step_wall']) for r in rs] == [
        ('planned_end_of_process', T0 + 30.5, T0 + 90.25), ('planned_end_of_process', T0 + 1_900.5, T0 + 3_700.25),
        ('planned_end_of_process', CUT, None)]
    assert rs[0]['seconds'] == pytest.approx(59.75) and rs[1]['seconds'] == pytest.approx(1_799.75)
    assert rs[2]['seconds'] == B.NM
    # 0.1.3: the real hole of observation, from the LAST STEP before the STOP to the next STEP
    assert [r['last_step_wall'] for r in rs] == [T0 + 30.25, T0 + 1_900.25, CUT + 0.25]
    assert rs[0]['observation_gap_s'] == pytest.approx(60.0) and rs[1]['observation_gap_s'] == pytest.approx(1_800.0)
    assert rs[2]['observation_gap_s'] == B.NM
    assert doc['interruptions']['gaps'] == [dict(start=T0 + 1_900.25, end=T0 + 3_700.25, seconds=1_800.0)]  # one GAP only
    md = B.render(doc)
    assert '- Reprises entre processus (toutes, quelle que soit leur durée) : 2.' in md
    assert ("  - STOP planned_end_of_process à 18:40:30Z ; dernier pas avant à 18:40:30Z ; pas suivant à 18:41:30Z : "
            "STOP → pas suivant 59.8 s ; trou d'observation (dernier pas → pas suivant) 60.0 s.") in md
    assert ("  - STOP planned_end_of_process à 00:40:00Z ; dernier pas avant à 00:40:00Z ; pas suivant à — : "
            "STOP → pas suivant — ; trou d'observation (dernier pas → pas suivant) —.") in md
    assert doc['series'] == B.bilan(scenario(tmp_path / 'z'), CUT)['series']          # never in the metrics


def test_no_stop_lists_no_resumption(tmp_path):
    doc = B.bilan(scenario(tmp_path), CUT)
    assert doc['interruptions']['resumptions'] == []
    assert '- Reprises entre processus (toutes, quelle que soit leur durée) : 0.' in B.render(doc)


def test_a_stop_of_any_reason_is_listed_with_its_reason(tmp_path):
    rs = B.bilan(scenario(tmp_path, stops=[(1, 'incident:RpcError', T0 + 90.5)]), CUT)['interruptions']['resumptions']
    assert rs == [dict(reason='incident:RpcError', stop_wall=T0 + 90.5, next_step_wall=T0 + 1_900.25,
                       seconds=pytest.approx(1_809.75), last_step_wall=T0 + 90.25,
                       observation_gap_s=pytest.approx(1_810.0))]


def test_a_missing_bound_renders_a_dash(tmp_path):
    """0.1.3: a STOP before any STEP has no last step; a STOP without wall has no STOP -> next duration."""
    j = J.Journal(tmp_path / 'J.jsonl')
    j.append('START', schema='livepaper-v0.1.4', label='PAPER_LIVE_DEMO', counts_for_operational_master=False, start=T0,
             seed_sha='5' * 64, variant='B', mode='gsfa_rank', poll_s=30, settle=[150, 60], code_sha256='c' * 64,
             pools=[])
    j.append('STOP', reason='planned_end_of_process')                         # no wall, before any STEP
    for n, t in enumerate((T0 + 30, CUT + 1)):
        j.append('STEP', step=n, receipt_slot=n, receipt_time=t, wall=t + 0.5, mono_ns=0, processing_ms=1.0,
                 open_positions=0)
    j.commit()
    doc = B.bilan(J.read(tmp_path / 'J.jsonl'), CUT)
    assert doc['interruptions']['resumptions'] == [dict(reason='planned_end_of_process', stop_wall=None,
                                                        next_step_wall=T0 + 30.5, seconds=B.NM, last_step_wall=None,
                                                        observation_gap_s=B.NM)]
    md = B.render(doc)
    assert ("  - STOP planned_end_of_process à — ; dernier pas avant à — ; pas suivant à 18:40:30Z : STOP → pas suivant — ; "
            "trou d'observation (dernier pas → pas suivant) —.") in md
