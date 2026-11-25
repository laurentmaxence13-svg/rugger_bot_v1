"""g23run 0.1 on synthetic CPMM pools written as GTFA pages (cpmmpilot.store layout): window lines, frozen decisions
and positions, K01 conversion, c5 / A1 variants, D_c, criteria, Holm, the CLI. No collected datum is read."""
import hashlib
import json
from fractions import Fraction

import pytest

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmgen3.tests.test_gen3 import CONFIG_A, FEES_A, Pool, SOL
from cpmmpilot import step1 as PILOT
from cpmmpilot.store import write_gz_page
from cpmmprereg import rule as R
from cpmmx import events
from cpmmx.tests.test_cpmmx import BASE_B58, logs, tx
from g23run import run as G

DAY = 86_400
T0 = 10 * DAY
SHEET = '13579bdf' + '02468ace' * 7
IDS = [bytes(range(k, k + 32)) for k in (1, 41, 81)]
NAMES = [events.b58encode(p) for p in IDS]


def steps(start, end, every=300, burst=None):
    """Alternating buys (distinct payers) and sales; ``burst`` adds a pump: (t0, n buys of 2 SOL)."""
    out = [(t, 'buy' if (t // every) % 2 else 'sell', 2 * 10 ** 8 if (t // every) % 2 else 10 ** 12, 'B%d' % t)
           for t in range(start, end, every)]
    if burst:
        t, n = burst
        out += [(t + 7 * k, 'buy', 2 * SOL, 'P%d_%d' % (t, k)) for k in range(n)]
    return sorted(out)


def raw_txs(pid, rows):
    sim, out = Pool(pid, 10 ** 15, 200 * SOL, FEES_A), {}
    for k, (t, side, amount, payer) in enumerate(rows):
        sig = '%s%06d' % (pid[:2].hex(), k)
        payload = sim.deposit(1, 10) if side == 'lp' else sim.swap(side, amount)
        raw = tx(t * 2, 0, logs(payload), when=t)
        raw['transaction'] = dict(signatures=[sig], message=dict(accountKeys=[payer, 'Other']))
        out[sig] = raw
    return out


def write_pages(directory, txs, per_page=200):
    rows = sorted(txs.values(), key=lambda r: r.get('blockTime', 0))
    for n in range(0, len(rows), per_page):
        write_gz_page(directory / ('page_%05d.json.gz' % (n // per_page)), dict(data=rows[n:n + per_page]))


@pytest.fixture
def small(monkeypatch):
    """3 synthetic pools, b3 = 1 each, T0 = 10 d, D = 7 d, the confirmation right after."""
    monkeypatch.setattr(G, 'POOLS', tuple(NAMES))
    monkeypatch.setattr(G, 'POOLS_SHA256', hashlib.sha256('\n'.join(NAMES).encode()).hexdigest())
    monkeypatch.setattr(G, 'B3', {n: 1 for n in NAMES})
    monkeypatch.setattr(G, 'T0', T0)
    monkeypatch.setattr(G, 'T0_C', T0 + 7 * DAY)
    monkeypatch.setattr(G, 'D_PILOT', 7)
    monkeypatch.setattr(G, 'VERSIONS', dict(pilot=G.V.SCHEMA, confirmation=G.V.SCHEMA))
    return [dict(pool=n, base_mint=BASE_B58) for n in NAMES]


def layout(root, start, days, every=150):
    for pid in IDS:
        write_pages(root / events.b58encode(pid), raw_txs(pid, steps(start, start + days * DAY, every=every)))


# -- window lines ------------------------------------------------------------------------------------------------------
def test_window_line_refuses_pages_outside_the_window(tmp_path):
    txs = raw_txs(IDS[0], steps(T0, T0 + 3_600))
    write_pages(tmp_path / 'a', txs)
    line, got = G.window_line(NAMES[0], BASE_B58, tmp_path / 'a', start=T0, end=T0 + 3_600)
    assert got == txs and len(line.swaps) == len(txs)
    for start, end in ((T0 + 1, T0 + 3_600), (T0, T0 + 3_000), (T0, T0 + 3_300)):     # 3 300 = a swap time
        with pytest.raises(G.RunError, match='outside_the_window'):
            G.window_line(NAMES[0], BASE_B58, tmp_path / 'a', start=start, end=end)
    bad = dict(next(iter(txs.values())))
    bad.pop('blockTime')
    write_pages(tmp_path / 'b', dict(bad=bad))
    with pytest.raises(G.RunError, match='block_time'):
        G.window_line(NAMES[0], BASE_B58, tmp_path / 'b', start=T0, end=T0 + 3_600)
    (tmp_path / 'c').mkdir()
    with pytest.raises(G.RunError, match='no_window_page'):
        G.window_line(NAMES[0], BASE_B58, tmp_path / 'c', start=T0, end=T0 + 3_600)


# -- rows: frozen decisions, positions, placebo, K01, variants ---------------------------------------------------------
def test_pool_rows_are_the_frozen_functions_with_k01(tmp_path):
    base = steps(T0, T0 + 2 * DAY, every=150)
    full = raw_txs(IDS[0], base)
    write_pages(tmp_path / 'full', full)
    whole, wtxs = G.window_line(NAMES[0], BASE_B58, tmp_path / 'full', start=T0, end=T0 + 2 * DAY)
    td = whole.swaps[G2.decisions_g23(whole, wtxs, 1)[3]].block_time
    # an LP event of others right after a decision swap, before its landing: that position cannot be priced
    write_pages(tmp_path / 'p', raw_txs(IDS[0], sorted(base + [(td + 1, 'lp', None, 'LP')])))
    line, txs = G.window_line(NAMES[0], BASE_B58, tmp_path / 'p', start=T0, end=T0 + 2 * DAY)
    got = G.pool_rows(line, txs, CONFIG_A, 1, SHEET, variants=True)
    idx = G2.decisions_g23(line, txs, 1)
    assert got['decisions'] == len(idx) > 10
    # the frozen positions() stops the whole pool on this decision; positions_each publishes it as unpriced
    with pytest.raises(CC.CostError, match='lp_change'):
        R.positions(line, CONFIG_A, idx)
    bad = [i for i in idx if line.swaps[i].block_time == td]
    assert len(bad) == 1
    each = G.positions_each(line, CONFIG_A, idx)
    assert [r['decision_index'] for r in each] == idx
    assert each[idx.index(bad[0])] == dict(pool=line.pool, decision_index=bad[0], unpriced='lp_change_at_the_landing_point',
                                           decision_time=td)
    rest = [i for i in idx if i != bad[0]]
    assert [r for r in each if r['decision_index'] != bad[0]] == R.positions(line, CONFIG_A, rest)   # identical
    assert got['primary'] == G.converted(line, each)
    assert got['placebo'] == G.converted(line, G.positions_each(line, CONFIG_A, R.placebo(line, len(idx), SHEET)))
    assert got['c5_10_slots'] == G.converted(line, G.positions_each(line, CONFIG_A, idx, latency_slots=10))
    assert got['a1_one_failure'] == G.converted(line, G.positions_each(line, CONFIG_A, idx,
                                                                       failures=CC.SENSITIVITY_FAILURES),
                                                CC.SENSITIVITY_FAILURES)
    assert len(got['placebo']) == len(R.placebo(line, len(idx), SHEET))
    for key, kw, f in (('c5_10_slots', dict(latency_slots=10), CC.FROZEN_FAILURES),
                       ('a1_one_failure', dict(failures=CC.SENSITIVITY_FAILURES), CC.SENSITIVITY_FAILURES)):
        frozen = G.converted(line, R.positions(line, CONFIG_A, rest, **kw), f)
        assert [r for r in got[key] if r['decision_index'] != bad[0]] == frozen
        assert frozen != [r for r in got['primary'] if r['decision_index'] != bad[0]]
    clean = G.positions_each(whole, CONFIG_A, G2.decisions_g23(whole, wtxs, 1))
    assert clean == R.positions(whole, CONFIG_A, G2.decisions_g23(whole, wtxs, 1))                  # no error: same
    # the unpriced position becomes a zero sale (K01), counted, in every series
    zero = [r for r in got['primary'] if r.get('status') == 'unpriced_zero_sale']
    assert zero and all(r['net_lamports'] == PILOT.zero_sale_net_lamports() for r in zero)
    zero_a1 = [r for r in got['a1_one_failure'] if r.get('status') == 'unpriced_zero_sale']
    assert zero_a1 and all(r['net_lamports'] == PILOT.zero_sale_net_lamports(CC.SENSITIVITY_FAILURES) for r in zero_a1)
    assert all('net_return' in r for r in got['primary'] + got['placebo'])
    assert 'c5_10_slots' not in G.pool_rows(line, txs, CONFIG_A, 1, SHEET)
    assert G.pool_rows(line, txs, CONFIG_A, 0, SHEET)['decisions'] == 0                   # b3 = 0: excluded


# -- D_c, criteria, words, Holm ----------------------------------------------------------------------------------------
def rows_of(values, entered=True):
    return [dict(pool='p', decision_time=T0 + k, net_return=v, entered=entered) for k, v in enumerate(values)]


def test_d_confirmation_formula():
    rows = rows_of([0.05, -0.05] * 60)                                       # sigma ~ 5 %, 120 entries -> r = 10 / day
    d = G.d_confirmation(rows, kept=2)
    sigma = __import__('statistics').stdev([0.05, -0.05] * 60)
    n_c = R.n_required(sigma=sigma, delta=0.005, alpha=0.0125)
    assert d['sigma_c'] == sigma and d['alpha_first_step'] == 0.0125 and d['n_c'] == n_c
    assert d['d_c'] == min(30, max(12, -(-n_c // 10))) and d['r_per_day'] == 10
    calm_ = G.d_confirmation(rows_of([0.001, 0.002] * 300), kept=1)          # sigma floor 2.5 %, r = 50 / day
    assert calm_['sigma_c'] == 0.025 and calm_['n_c'] == 197 and calm_['d_c'] == 12
    mid = G.d_confirmation(rows_of([0.001, 0.002] * 75), kept=1)             # r = 12.5 / day: 197 / 12.5 = 15.76
    assert mid['r_per_day'] == 12.5 and mid['d_c'] == 16
    none = G.d_confirmation(rows_of([0.01, 0.02], entered=False), kept=1)
    assert none['r_per_day'] == 0 and none['d_c'] == 30
    for kept in (0, 3):
        with pytest.raises(G.RunError, match='kept'):
            G.d_confirmation(rows, kept=kept)
    with pytest.raises(G.RunError, match='too_few'):
        G.d_confirmation(rows_of([0.01]), kept=1)


def report(lower=0.01, gap=0.01, halves=True, wo=0.01, mean=0.01, floors=True, decision='GO_PILOTE'):
    return dict(decision=decision, lower_bound_95=lower, placebo=dict(difference_bounds_95=dict(lower=gap)),
                halves=dict(both_positive=halves), without_top_pool=dict(lower_bound_95=wo), mean_net_return=mean,
                floors=dict(passed=floors))


def test_criteria_words_and_holm():
    good = G.criteria(report(), report(), report())
    assert good == dict(c1=True, c2=True, c3=True, c4=True, c5=True, a1=True)
    assert G.confirmation_word(report(), good) == 'CRITÈRES REMPLIS'
    for kw, key in ((dict(lower=-0.001), 'c1'), (dict(gap=G.V.NM), 'c2'), (dict(gap=0.0), 'c2'),
                    (dict(halves=False), 'c3'), (dict(wo=0.0), 'c5'), (dict(wo=None), 'c5')):
        crit = G.criteria(report(**kw), report(), report())
        assert crit[key] is False and G.confirmation_word(report(**kw), crit) == 'NON CONFIRMÉ'
    assert G.criteria(report(lower=0.0), report(), report())['c1'] is False
    assert G.criteria(report(), report(mean=0.0), report())['c5'] is False
    assert G.criteria(report(), report(mean=None), report())['c5'] is False
    assert G.criteria(report(), report(), report(mean=-0.01))['a1'] is False
    assert G.confirmation_word(report(floors=False), good) == 'INCONCLUSIF'
    assert G.confirmation_word(report(decision='STOP'), {}) == 'STOP'
    both = G.final_words(dict(g23='CRITÈRES REMPLIS', n1='CRITÈRES REMPLIS'), dict(g23=0.01, n1=0.02))
    assert both == dict(g23='CONFIRMÉ', n1='CONFIRMÉ')
    first_fails = G.final_words(dict(g23='CRITÈRES REMPLIS', n1='CRITÈRES REMPLIS'), dict(g23=0.013, n1=0.02))
    assert first_fails == dict(g23='NON CONFIRMÉ', n1='NON CONFIRMÉ')
    other_inconclusive = G.final_words(dict(g23='CRITÈRES REMPLIS', n1='INCONCLUSIF'), dict(g23=0.0125, n1=0.0))
    assert other_inconclusive == dict(g23='CONFIRMÉ', n1='INCONCLUSIF')                   # INCONCLUSIF = p 1
    assert G.final_words(dict(g23='CRITÈRES REMPLIS'), dict(g23=0.025)) == dict(g23='CONFIRMÉ')
    # a hypothesis that failed its criteria counts p = 1 in Holm, whatever its p
    failed_other = G.final_words(dict(g23='NON CONFIRMÉ', n1='CRITÈRES REMPLIS'), dict(g23=0.001, n1=0.02))
    assert failed_other == dict(g23='NON CONFIRMÉ', n1='NON CONFIRMÉ')


# -- the runs ----------------------------------------------------------------------------------------------------------
def test_pilot_then_confirmation_end_to_end(tmp_path, small):
    layout(tmp_path / 'pilot', T0, 7)
    doc, rows = G.run('pilot', selected=small, root=tmp_path / 'pilot', config=CONFIG_A, sheet_sha=SHEET,
                      credits=1_200, draws=200)
    assert doc['phase'] == 'pilot' and set(doc['decisions']) == set(NAMES) and doc['g0_passed'] is True
    assert all(g['admitted'] for g in doc['pool_gate'].values())
    assert doc['report']['n'] == len(rows['primary']) > 0 and doc['report']['d_days'] == 7
    assert rows['c5_10_slots'] == [] and rows['a1_one_failure'] == []
    assert set(doc['l_fin']['clock_exits_after_the_end']) == set(NAMES)
    for k in (1, 2):                                                          # ERRATUM C-169, published at the pilot
        e = doc['erratum_c169']['K=%d' % k]
        assert e == dict(G.d_confirmation(rows['primary'], kept=k), **G.budget(G.d_confirmation(rows['primary'],
                                                                                                   kept=k), 1_200))
    with pytest.raises(G.RunError, match='go_pilote'):
        G.run('confirmation', selected=small, root=tmp_path, config=CONFIG_A, sheet_sha=SHEET, alpha=0.025,
              pilot_rows=rows['primary'], pilot_decision='INCONCLUSIF', kept=1, d_c=12)
    design = G.d_confirmation(rows['primary'], kept=1)
    layout(tmp_path / 'conf', T0 + 7 * DAY, design['d_c'])
    kw = dict(selected=small, root=tmp_path / 'conf', config=CONFIG_A, sheet_sha=SHEET, alpha=0.025,
              pilot_rows=rows['primary'], pilot_decision='GO_PILOTE', kept=1, draws=200)
    conf, crow = G.run('confirmation', d_c=design['d_c'], **kw)
    assert conf['design']['d_c_used'] == design['d_c'] and conf['report']['t0'] == T0 + 7 * DAY
    assert conf['report']['d_days'] == design['d_c'] and conf['report']['alpha'] == 0.025
    assert crow['c5_10_slots'] and crow['a1_one_failure'] and set(conf['criteria']) == {'c1', 'c2', 'c3', 'c4', 'c5',
                                                                                          'a1'}
    # c5 and A1 are computed on their OWN rows
    assert conf['c5_10_slots']['n'] == len(crow['c5_10_slots'])
    assert conf['c5_10_slots']['mean_net_return'] == pytest.approx(
        sum(r['net_return'] for r in crow['c5_10_slots']) / len(crow['c5_10_slots']))
    assert conf['a1_one_failure']['mean_net_return'] == pytest.approx(
        sum(r['net_return'] for r in crow['a1_one_failure']) / len(crow['a1_one_failure']))
    assert conf['a1_one_failure']['mean_net_return'] < conf['report']['mean_net_return']        # more charged tx
    assert conf['word_before_holm'] in ('INCONCLUSIF', 'NON CONFIRMÉ', 'CRITÈRES REMPLIS')
    assert conf['p_value'] == conf['report']['p_value']
    with pytest.raises(G.RunError, match='d_c_star_or_d_c33'):
        G.run('confirmation', d_c=design['d_c'] + 1, **kw)


def test_budget_formulas_of_the_erratum():
    design = dict(d_c=20)
    b = G.budget(design, 2_400)                                                 # c_j = 200 credits per day
    assert b['c_j'] == 200 and b['p'] == 5_000 and b['d_c33'] == 20            # ceil(1.25 x 200 x 20); 32 340 / 250
    tight = G.budget(dict(d_c=30), 18_000)                                      # c_j = 1 500
    assert tight['p'] == 56_250 and tight['d_c33'] == 17                       # floor(32 340 / 1 875) = 17
    odd = G.budget(dict(d_c=13), 1_000)                                         # c_j = 83.33..
    assert odd['p'] == 1_355                                                    # ceil(1 354.16..)
    assert G.budget(design, None) == dict(c_j=G.V.NM, p=G.V.NM, d_c33=G.V.NM)
    for bad in (0, -5, '1'):
        with pytest.raises(G.RunError, match='credits'):
            G.budget(design, bad)
    assert G.CREDIT_CAP == 32_340 and G.CREDIT_MARGIN == 1.25


def test_l_fin_the_de_facto_frozen_behaviour_at_the_window_end(tmp_path):
    """R02 23:18:54Z (i): a decision at T0 + D - 600 s; no TP / SL among the collected swaps; the clock exit falls
    after T0 + D; the sale is valued on the state after the LAST collected swap, status entered."""
    end = T0 + DAY
    write_pages(tmp_path / 'e', raw_txs(IDS[0], steps(T0, end, every=150)))
    line, _txs = G.window_line(NAMES[0], BASE_B58, tmp_path / 'e', start=T0, end=end)
    i = max(k for k, sw in enumerate(line.swaps) if sw.block_time <= end - 600)
    assert line.swaps[i].block_time == end - 600
    slot, exit_time = R.exit_point(line, i, CONFIG_A)
    assert slot is None and exit_time > end                                    # clock exit beyond the data
    row = R.positions(line, CONFIG_A, [i])[0]
    assert row['status'] == 'entered' and 'unpriced' not in row
    # the sale value is the one of the state after the last collected swap (both H-1 limits see every swap)
    last = CC.position(line, i, CONFIG_A, exit_time=line.swaps[-1].block_time + 1)
    assert row['received'] == last['received'] and row['net_lamports'] == last['net_lamports']
    assert G.clock_exits_after(line, CONFIG_A, [i], end) == 1
    assert G.clock_exits_after(line, CONFIG_A, [i], exit_time) == 0


def test_g0_gate_two_admitted_pools_is_inconclusive_and_integrity_failure_is_stop(tmp_path, small, monkeypatch):
    layout(tmp_path / 'pilot', T0, 7)
    real = CC.pool_gate

    def two_admitted(line, config):
        return dict(admitted=False, reasons=['undecoded_transactions']) if line.pool == NAMES[2] else real(line, config)
    monkeypatch.setattr(CC, 'pool_gate', two_admitted)
    doc, rows = G.run('pilot', selected=small, root=tmp_path / 'pilot', config=CONFIG_A, sheet_sha=SHEET, draws=200)
    assert doc['g0_passed'] is True and doc['report']['decision'] == 'INCONCLUSIF'        # floors: 2 pools < 3
    assert doc['pool_gate'][NAMES[2]] == dict(admitted=False, reasons=['undecoded_transactions'])
    assert NAMES[2] not in doc['decisions'] and all(r['pool'] != NAMES[2] for r in rows['primary'])

    def broken(line, config):
        if line.pool == NAMES[1]:
            raise CC.CostError('amm_config_not_read_and_hashed')
        return real(line, config)
    monkeypatch.setattr(CC, 'pool_gate', broken)
    stop, _r = G.run('pilot', selected=small, root=tmp_path / 'pilot', config=CONFIG_A, sheet_sha=SHEET, draws=200)
    assert stop['g0_passed'] is False and stop['report']['decision'] == 'STOP'
    assert stop['pool_gate'][NAMES[1]]['reasons'][0].startswith('integrity_failure')
    assert 'erratum_c169' not in stop


def test_run_guards(tmp_path, small, monkeypatch):
    kw = dict(selected=small, root=tmp_path, config=CONFIG_A, sheet_sha=SHEET)
    with pytest.raises(G.RunError, match='pilot_alpha'):
        G.run('pilot', alpha=0.025, **kw)
    for alpha in (0.05, 0.01):
        with pytest.raises(G.RunError, match='confirmation_alpha'):
            G.run('confirmation', alpha=alpha, pilot_rows=[], pilot_decision='GO_PILOTE', kept=1, **kw)
    with pytest.raises(G.RunError, match='pilot_rows'):
        G.run('confirmation', alpha=0.025, pilot_decision='GO_PILOTE', kept=1, **kw)
    rows = rows_of([0.05, -0.05] * 2)                                          # r tiny -> D_c* = 30
    d33 = G.budget(G.d_confirmation(rows, kept=1), 60_000)['d_c33']
    assert d33 == 32_340 * G.D_PILOT // 75_000 < 7                             # floor(32 340 / (1.25 x 60 000 / D))
    with pytest.raises(G.RunError, match='minimum'):
        G.run('confirmation', alpha=0.025, pilot_rows=rows, pilot_decision='GO_PILOTE', kept=1, d_c=d33,
              credits=60_000, **kw)
    with pytest.raises(G.RunError, match='missing'):
        G.run('pilot', **dict(kw, selected=small[:2]))
    monkeypatch.setattr(G, 'POOLS_SHA256', '0' * 64)
    with pytest.raises(G.RunError, match='altered'):
        G.run('pilot', **kw)
    monkeypatch.setattr(G, 'VERSIONS', dict(pilot='g23five-v0.1.1', confirmation='g23five-v0.3'))
    with pytest.raises(G.RunError, match='version'):
        G.run('pilot' if G.V.SCHEMA != 'g23five-v0.1.1' else 'confirmation', **kw)


def test_constants_are_the_anchored_ones():
    assert hashlib.sha256('\n'.join(G.POOLS).encode()).hexdigest() == G.POOLS_SHA256 == (
        '812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80')
    assert [G.B3[p] for p in G.POOLS] == [2, 1, 6, 1]
    assert G.T0 == 1795515686 and G.T0_C == G.T0 + 12 * DAY and G.D_PILOT == 12
    assert G.VERSIONS == dict(pilot='g23five-v0.1.1', confirmation='g23five-v0.3')


def test_cli_writes_rows_and_result_once(tmp_path, small, monkeypatch, capsys):
    layout(tmp_path / 'pilot', T0, 7)
    monkeypatch.setattr(G.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0, selected=small + [dict(pool='x', base_mint='m')])))
    args = ['--phase', 'pilot', '--u2', str(tmp_path / 'u2.json'), '--root', str(tmp_path / 'pilot'), '--t0-slot',
            '5', '--sheet-sha', SHEET, '--g23-credits', '1200', '--out', str(tmp_path / 'out')]
    monkeypatch.setattr(G.V, 'DRAWS', 200)
    G.main(args)
    printed = json.loads(capsys.readouterr().out)
    for name in ('ROWS.json', 'RESULT.json'):
        assert printed[name] == hashlib.sha256((tmp_path / 'out' / name).read_bytes()).hexdigest()
    result = json.loads((tmp_path / 'out' / 'RESULT.json').read_text())
    assert result['phase'] == 'pilot' and result['erratum_c169']['K=1']['c_j'] == pytest.approx(1_200 / 7)
    with pytest.raises(G.RunError, match='out_exists'):
        G.main(args)
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0 + 1, selected=small)))
    with pytest.raises(G.RunError, match='t0'):
        G.main(args[:-1] + [str(tmp_path / 'out2')])


def test_the_placebo_count_is_the_pool_decision_count(tmp_path):
    # buyers only during the first 6 hours: few decisions, many placebo candidates (the count binds, not the supply)
    early = [r for r in steps(T0, T0 + 6 * 3_600, every=150)]
    late = [(t, 'sell', 10 ** 12, 'S%d' % t) for t in range(T0 + 6 * 3_600, T0 + 2 * DAY, 300)]
    write_pages(tmp_path / 'q', raw_txs(IDS[0], early + late))
    line, txs = G.window_line(NAMES[0], BASE_B58, tmp_path / 'q', start=T0, end=T0 + 2 * DAY)
    got = G.pool_rows(line, txs, CONFIG_A, 1, SHEET)
    assert 0 < got['decisions'] < len(R.placebo(line, got['decisions'] + 1, SHEET))
    assert len(got['placebo']) == got['decisions']


def test_c5_and_a1_reports_read_their_own_rows(tmp_path, small, monkeypatch):
    pilot = rows_of([0.001, 0.002] * 300)                                       # D_c* = 12 at K = 1
    layout(tmp_path / 'conf', T0 + 7 * DAY, 12)
    real = G.pool_rows

    def marked(*a, **kw):
        got = real(*a, **kw)
        got['c5_10_slots'] = [dict(r, net_return=r['net_return'] + 0.5) for r in got['c5_10_slots']]
        got['a1_one_failure'] = [dict(r, net_return=r['net_return'] - 0.5) for r in got['a1_one_failure']]
        return got
    monkeypatch.setattr(G, 'pool_rows', marked)
    conf, crow = G.run('confirmation', selected=small, root=tmp_path / 'conf', config=CONFIG_A, sheet_sha=SHEET,
                       alpha=0.025, pilot_rows=pilot, pilot_decision='GO_PILOTE', kept=1, d_c=12, draws=200)
    main = conf['report']['mean_net_return']
    assert conf['c5_10_slots']['mean_net_return'] == pytest.approx(main + 0.5, abs=0.2)
    assert conf['a1_one_failure']['mean_net_return'] == pytest.approx(main - 0.5, abs=0.2)
