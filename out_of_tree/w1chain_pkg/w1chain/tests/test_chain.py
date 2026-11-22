"""w1chain: plan, row checks, frozen HW1 verdicts (same bytes as the frozen CLI), the C-B rule, the W2 C-B plan.
Fixtures only: synthetic rows and the three public LaunchLab pools moved into the W1 range; no W1 or W2 file."""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from statelab import hypotheses as H
from statelab.tests.test_hypotheses import _export, _position
from w1chain import chain as C
from w2arms import cb as CB
from w2arms import ce as W

OFFICIAL_BYTES = b'{"verdict": "anchored official W1 verdict (fixture)"}\n'
OFFICIAL = hashlib.sha256(OFFICIAL_BYTES).hexdigest()
MANIFEST = 'ab' * 32
LOW, HIGH = C.EVALUATION_W1


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _plan(tmp_path, n_before=168, manifest=MANIFEST):
    official = tmp_path / 'official.json'
    if not official.exists():
        official.write_bytes(OFFICIAL_BYTES)
    return C.plan(official, OFFICIAL, manifest, n_before)


def _rows_doc(rows, latency_slots=4, **over):
    doc = dict(schema=H.SCHEMA, status='EXPLORATORY', hypotheses=[dict(h) for h in H.HYPOTHESES],
               hypotheses_sha256=C.FROZEN['hypotheses_fingerprint'], latency_slots=latency_slots, source='export',
               pools_read=len({r['pool'] for r in rows}), missing={}, counts=H.counts(rows), rows=rows,
               flags=dict(holdout_read=False, promotion_allowed=False, financial_order_submitted=False),
               pack_manifest_sha256=MANIFEST, segments=['export'], evaluation=[LOW, HIGH],
               official_verdict_sha256=OFFICIAL, w1_data_read=True, skipped_by_the_export=0)
    doc['rows_sha256'] = _sha(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())
    doc.update(over)
    return doc


def _family(n=60, value=125_000_000):
    rows = []
    for i in range(n):
        name = 'p%03d' % i
        rows.append(_position(name, 'HW1-5', value, slot=LOW + i, creator='k%02d' % (i % 30)))
        rows.append(_position(name, H.PLACEBO, 96_000_000, slot=LOW + i, creator='k%02d' % (i % 30)))
    return rows


def _census(rows):
    pools = sorted({r['pool'] for r in rows})
    return dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[],
                rows=[dict(pool=p, class_='spl', our_account_rent_lamports=2_039_280) for p in pools])


def _raw(doc):
    return (json.dumps(doc, sort_keys=True, indent=1) + '\n').encode()


# --- frozen pieces and trial count ------------------------------------------------------------------------------

def test_the_frozen_code_and_the_dossier_b_constants_are_checked(monkeypatch):
    found = C.frozen_check()
    assert found == C.FROZEN
    assert C.DOSSIER_B == dict(k_candidates=3, alpha_one_sided=0.05 / 3, draws=10_000, n_min=414)
    assert round(100 * (1 - C.DOSSIER_B['alpha_one_sided']), 2) == 98.33
    assert C.CB_ORDER == ('HW1-5', 'HW1-1', 'HW1-2', 'HW1-4', 'HW1-3')
    for module, name, value in ((W, 'N_MIN', 400), (W, 'DRAWS', 1_000), (W, 'ALPHA_ONE_SIDED', 0.05)):
        with monkeypatch.context() as m:
            m.setattr(module, name, value)
            with pytest.raises(C.ChainError, match='dossier_b_constants_differ'):
                C.frozen_check()
    with monkeypatch.context() as m:
        m.setattr(CB, 'FROZEN_HYPOTHESES_SHA256', '0' * 64)
        with pytest.raises(C.ChainError, match='cb_fingerprint'):
            C.frozen_check()
    with monkeypatch.context() as m:
        m.setattr(H, 'fingerprint', lambda: '1' * 64)
        with pytest.raises(C.ChainError, match='frozen_code_differs:hypotheses_fingerprint'):
            C.frozen_check()
    with monkeypatch.context() as m:
        m.setitem(C.FROZEN, 'w2arms_cb_py', '2' * 64)
        with pytest.raises(C.ChainError, match='frozen_code_differs:w2arms_cb_py'):
            C.frozen_check()
    with monkeypatch.context() as m:
        m.setattr(C, 'EVALUATION_W1', (LOW, HIGH + 1))
        with pytest.raises(C.ChainError, match='w1_evaluation_range_differs'):
            C.frozen_check()


def test_the_trial_count_is_168_plus_5_and_the_cap_170_outside_hw1_is_enforced():
    t = C.trials(168)
    assert (t['n_outside_hw1'], t['cap_outside_hw1'], t['hw1_reading'], t['n_with_hw1']) == (168, 170, 5, 173)
    assert C.trials(170)['n_with_hw1'] == 175
    with pytest.raises(C.ChainError, match='trial_cap_exceeded:171>170'):
        C.trials(171)
    for bad in (-1, 168.0, '168', True, None):
        with pytest.raises(C.ChainError, match='n_before_must_be_a_non_negative_integer'):
            C.trials(bad)


# --- plan -------------------------------------------------------------------------------------------------------

def test_the_plan_needs_the_anchored_official_verdict_and_lists_the_runbook_commands(tmp_path):
    doc = _plan(tmp_path)
    assert doc['evaluation'] == [467_678_545, 469_291_345] and doc['s0_w1'] == 467_275_745
    assert doc['trials']['n_with_hw1'] == 173 and doc['flags']['data_read'] is False
    step3 = next(s for s in doc['steps'] if s['step'] == '3')['commands']
    assert len(step3) == 2 and all('--evaluation-min 467678545 --evaluation-max 469291345' in c for c in step3)
    assert all('--official-verdict-sha256 ' + OFFICIAL in c and '--expect-manifest-sha ' + MANIFEST in c for c in step3)
    assert '--latency-slots' not in step3[0] and '--latency-slots 10' in step3[1]
    assert all(' -I ' not in c for s in doc['steps'] for c in s.get('commands', []))
    (tmp_path / 'other.json').write_bytes(OFFICIAL_BYTES + b' ')
    with pytest.raises(C.ChainError, match='official_verdict_is_not_the_anchored_file'):
        C.plan(tmp_path / 'other.json', OFFICIAL, MANIFEST, 168)
    for bad in ('x' * 64, 'AB' * 32, None):
        with pytest.raises(C.ChainError, match='must_be_a_sha256'):
            C.plan(tmp_path / 'official.json', OFFICIAL, bad, 168)
    with pytest.raises(C.ChainError, match='trial_cap_exceeded'):
        _plan(tmp_path, n_before=171)


def test_the_plan_cli_writes_once_and_load_plan_checks_its_sha(tmp_path, capsys):
    (tmp_path / 'official.json').write_bytes(OFFICIAL_BYTES)
    args = ['plan', '--official-verdict', str(tmp_path / 'official.json'), '--official-verdict-sha256', OFFICIAL,
            '--export-manifest-sha256', MANIFEST, '--n-before', '168', '--out', str(tmp_path / 'plan.json')]
    assert C.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    raw = (tmp_path / 'plan.json').read_bytes()
    assert printed['plan_sha256'] == _sha(raw) and printed['trials']['n_with_hw1'] == 173
    assert C.load_plan(tmp_path / 'plan.json', _sha(raw))['export_manifest_sha256'] == MANIFEST
    with pytest.raises(C.ChainError, match='plan_is_not_the_anchored_file'):
        C.load_plan(tmp_path / 'plan.json', '0' * 64)
    with pytest.raises(C.ChainError, match='output_exists'):
        C.main(args)


# --- rows (step 4) ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('over, error', [
    (dict(schema='x'), 'rows_not_a_statelab_export_document'),
    (dict(source='p0_visible'), 'rows_not_a_statelab_export_document'),
    (dict(hypotheses_sha256='0' * 64), 'rows_not_from_the_frozen_hypotheses'),
    (dict(latency_slots=10), 'rows_not_the_4_slot_run'),
    (dict(pack_manifest_sha256='cd' * 32), 'rows_not_from_the_anchored_export'),
    (dict(evaluation=[LOW, HIGH + 1]), 'rows_not_on_the_w1_evaluation_range'),
    (dict(evaluation=None), 'rows_not_on_the_w1_evaluation_range'),
    (dict(official_verdict_sha256='ef' * 32), 'rows_not_after_the_anchored_official_verdict'),
    (dict(w1_data_read=False), 'rows_do_not_come_from_w1'),
    (dict(rows_sha256='0' * 64), 'rows_sha256_differs'),
    (dict(counts={'m': 9}), 'counts_differ'),
])
def test_each_row_check_stops_the_chain(tmp_path, over, error):
    the_plan = _plan(tmp_path)
    assert C.check_rows_document(_rows_doc(_family()), the_plan, 4)
    with pytest.raises(C.ChainError, match=error):
        C.check_rows_document(_rows_doc(_family(), **over), the_plan, 4)


def test_check_rows_prints_sizes_and_shas_only(tmp_path):
    the_plan = _plan(tmp_path)
    rows = _family()
    (tmp_path / 'l4.json').write_bytes(_raw(_rows_doc(rows)))
    (tmp_path / 'l10.json').write_bytes(_raw(_rows_doc(rows, latency_slots=10)))
    out = C.check_rows(the_plan, tmp_path / 'l4.json', tmp_path / 'l10.json')
    assert set(out) == {'lat4', 'lat10'}
    for block in out.values():
        assert set(block) == {'file_sha256', 'rows_sha256', 'pools_read', 'missing', 'counts'}
        assert set(block['counts']['HW1-5']) == {'positions', 'clusters', 'distinct_payers', 'migrated',
                                                 'migrated_share', 'evaluable'}
    assert out['lat4']['file_sha256'] == _sha((tmp_path / 'l4.json').read_bytes())
    (tmp_path / 'l10b.json').write_bytes(_raw(_rows_doc(rows[:-2], latency_slots=10, pools_read=59)))
    with pytest.raises(C.ChainError, match='lat4_and_lat10_did_not_read_the_same_pools'):
        C.check_rows(the_plan, tmp_path / 'l4.json', tmp_path / 'l10b.json')
    with pytest.raises(C.ChainError, match='rows_not_the_10_slot_run'):
        C.check_rows(the_plan, tmp_path / 'l4.json', tmp_path / 'l4.json')


# --- verdicts (step 5) ------------------------------------------------------------------------------------------

def test_the_verdicts_are_byte_identical_to_the_frozen_cli(tmp_path, capsys):
    rows = _family()
    lat4, lat10 = _raw(_rows_doc(rows)), _raw(_rows_doc(rows, latency_slots=10))
    census = _raw(_census(rows))
    for name, raw in (('l4.json', lat4), ('l10.json', lat10), ('census.json', census)):
        (tmp_path / name).write_bytes(raw)
    document = C.hw1_verdicts(_plan(tmp_path), lat4, lat10, census, 1)
    assert H.main(['verdicts', str(tmp_path / 'l4.json'), '--declared-m', '1', '--census', str(tmp_path / 'census.json'),
                   '--latency10', str(tmp_path / 'l10.json')]) == 0
    assert C.frozen_cli_bytes(document) == capsys.readouterr().out.encode()
    assert document['hypotheses']['HW1-5']['verdict'] == C.CODE_POSITIVE['exploratory']
    assert document['trials_added_to_n'] == 5 and document['rows_file_sha256'] == _sha(lat4)
    with pytest.raises(ValueError, match='declared_m_is_not_the_number_of_evaluable_hypotheses'):
        C.hw1_verdicts(_plan(tmp_path), lat4, lat10, census, 2)
    with pytest.raises(C.ChainError, match='rows_not_the_10_slot_run'):
        C.hw1_verdicts(_plan(tmp_path), lat4, lat4, census, 1)


def test_the_verdicts_cli_reads_anchored_files_only_and_writes_the_trial_count(tmp_path, capsys):
    rows = _family()
    files = dict(l4=_raw(_rows_doc(rows)), l10=_raw(_rows_doc(rows, latency_slots=10)), census=_raw(_census(rows)))
    for name, raw in files.items():
        (tmp_path / name).write_bytes(raw)
    (tmp_path / 'official.json').write_bytes(OFFICIAL_BYTES)
    plan_raw = C._dump(_plan(tmp_path))
    (tmp_path / 'plan.json').write_bytes(plan_raw)

    def args(**sha):
        shas = dict(dict((k, _sha(v)) for k, v in files.items()), **sha)
        return ['verdicts', '--plan', str(tmp_path / 'plan.json'), '--plan-sha256', _sha(plan_raw),
                '--rows-lat4', str(tmp_path / 'l4'), '--rows-lat4-sha256', shas['l4'],
                '--rows-lat10', str(tmp_path / 'l10'), '--rows-lat10-sha256', shas['l10'],
                '--census', str(tmp_path / 'census'), '--census-sha256', shas['census'], '--declared-m', '1',
                '--out', str(tmp_path / 'out')]
    for key, error in (('l4', 'rows_lat4'), ('l10', 'rows_lat10'), ('census', 'census')):
        with pytest.raises(C.ChainError, match=error + '_is_not_the_anchored_file'):
            C.main(args(**{key: '0' * 64}))
    assert not (tmp_path / 'out').exists()
    assert C.main(args()) == 0
    printed = json.loads(capsys.readouterr().out)
    verdict_raw = (tmp_path / 'out' / 'HW1_VERDICTS.json').read_bytes()
    assert printed == dict(hw1_verdicts_file_sha256=_sha(verdict_raw), n_with_hw1=173)
    record = json.loads((tmp_path / 'out' / 'TRIALS.json').read_bytes())
    assert record['n_outside_hw1'] == 168 and record['n_with_hw1'] == 173 and record['declared_m'] == 1
    assert record['rows_lat4_sha256'] == _sha(files['l4']) and record['census_sha256'] == _sha(files['census'])
    assert (tmp_path / 'out' / 'HW1_VERDICTS.md').read_text(encoding='utf-8')
    with pytest.raises(C.ChainError, match='output_exists'):
        C.main(args())


# --- the C-B rule -----------------------------------------------------------------------------------------------

def _hw1(codes):
    return dict(schema='statelab-hypothesis-verdicts-v1', source='export', w1_data_read=True,
                hypotheses_sha256=C.FROZEN['hypotheses_fingerprint'], pack_manifest_sha256=MANIFEST,
                trials_added_to_n=5, hypotheses={k: dict(verdict=v) for k, v in codes.items()})


NEG = 'REJETÉE'
P, X = C.CODE_POSITIVE['primary'], C.CODE_POSITIVE['exploratory']


def _codes(**positive):
    codes = {k: NEG for k in C.CB_ORDER}
    for key, value in positive.items():
        codes[key.replace('_', '-')] = value
    return codes


def _final(words, sha='12' * 32, conditions=True):
    doc = dict(schema=C.SCHEMA_FINAL, hw1_verdicts_file_sha256=sha, final=dict(words))
    if conditions is not None:
        doc['hw1_5_conditions_r02'] = {k: conditions for k in C.HW1_5_CONDITIONS}
    return doc


def _select(tmp_path, codes, words, **kw):
    return C.select(_plan(tmp_path), _hw1(codes), '12' * 32, _final(words, **kw))


@pytest.mark.parametrize('positives, expected', [
    ({}, None),
    ({'HW1-5': X, 'HW1-1': P}, 'HW1-5'),
    ({'HW1-1': P, 'HW1-4': P}, 'HW1-1'),
    ({'HW1-3': P, 'HW1-2': P}, 'HW1-2'),
    ({'HW1-3': P, 'HW1-4': P}, 'HW1-4'),
    ({'HW1-3': P}, 'HW1-3'),
])
def test_cb_is_the_first_positive_in_the_frozen_order_else_empty(tmp_path, positives, expected):
    codes = dict(_codes(), **positives)
    words = {k: ('EXPLORATOIRE POSITIVE' if k in positives else 'REJETÉE') for k in C.CB_ORDER}
    out = _select(tmp_path, codes, words)
    assert out['cb_hypothesis'] == expected and out['status'] == ('RETENUE' if expected else 'VIDE')
    horizons = {h['id']: h['horizon'] for h in H.HYPOTHESES}
    assert out['horizon_s'] == (None if expected is None else horizons[expected])
    assert out['trials']['n_with_hw1'] == 173 and out['order'] == list(C.CB_ORDER)


def test_a_positive_code_word_alone_does_not_select_and_r02_cannot_make_positive_what_the_code_does_not(tmp_path):
    words = {k: 'REJETÉE' for k in C.CB_ORDER}
    assert _select(tmp_path, _codes(HW1_1=P), words)['cb_hypothesis'] is None          # R02 rejected it at step 6
    words['HW1-2'] = 'CONFIRMÉE SUR W1'
    with pytest.raises(C.ChainError, match='r02_positive_where_the_frozen_code_is_not:HW1-2'):
        _select(tmp_path, _codes(), words)
    words = {k: 'REJETÉE' for k in C.CB_ORDER}
    words['HW1-5'] = 'EXPLORATOIRE POSITIVE'
    with pytest.raises(C.ChainError, match='r02_positive_where_the_frozen_code_is_not:HW1-5'):
        _select(tmp_path, _codes(HW1_5=P), words)                                       # not the exploratory word
    assert _select(tmp_path, _codes(HW1_5=X), words)['cb_hypothesis'] == 'HW1-5'
    words['HW1-5'] = 'CONFIRMÉE SUR W1'
    assert _select(tmp_path, _codes(HW1_5=X), words)['cb_hypothesis'] == 'HW1-5'


def test_only_the_two_positive_final_words_select(tmp_path):
    for word in ('NÉGATIVE', 'REJETÉE', 'NON ÉVALUABLE', 'NON CONCLUANT', 'EXPLORATOIRE NON CONFIRMÉE'):
        words = dict({k: 'REJETÉE' for k in C.CB_ORDER}, **{'HW1-5': word, 'HW1-1': word})
        assert _select(tmp_path, _codes(HW1_5=X, HW1_1=P), words)['status'] == 'VIDE'
    assert C.FINAL_POSITIVE == ('EXPLORATOIRE POSITIVE', 'CONFIRMÉE SUR W1')


def test_hw1_5_admission_is_i_to_vii_and_the_payer_sensitivity_and_viii_is_recorded_only(tmp_path):
    assert C.HW1_5_ADMISSION == ('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'payer_cluster_sensitivity_consistent')
    assert C.HW1_5_RECORDED == ('viii',)
    words = dict({k: 'REJETÉE' for k in C.CB_ORDER}, **{'HW1-5': 'EXPLORATOIRE POSITIVE'})
    the_plan, hw1 = _plan(tmp_path), _hw1(_codes(HW1_5=X))

    def run(**change):
        final = _final(words)
        final['hw1_5_conditions_r02'].update(change)
        return C.select(the_plan, hw1, '12' * 32, final)
    out = run(viii=False)                                        # R-1 only serves the word "rentable"
    assert out['cb_hypothesis'] == 'HW1-5' and out['status'] == 'RETENUE'
    assert out['hw1_5_recorded_not_blocking'] == dict(viii=False)
    assert run()['hw1_5_recorded_not_blocking'] == dict(viii=True)
    for key in C.HW1_5_ADMISSION:
        with pytest.raises(C.ChainError, match='hw1_5_positive_without_the_admission_conditions'):
            run(**{key: False})
    with pytest.raises(C.ChainError, match='hw1_5_positive_without_the_admission_conditions'):
        run(payer_cluster_sensitivity_consistent=False, viii=True)
    for conditions in (False, None):
        with pytest.raises(C.ChainError, match='hw1_5_'):
            _select(tmp_path, _codes(HW1_5=X), words, conditions=conditions)
    for drop in ('viii', 'payer_cluster_sensitivity_consistent', 'iv'):
        final = _final(words)
        del final['hw1_5_conditions_r02'][drop]
        with pytest.raises(C.ChainError, match='hw1_5_conditions_incomplete_or_not_boolean'):
            C.select(the_plan, hw1, '12' * 32, final)
    for bad in ('yes', 1, None):
        with pytest.raises(C.ChainError, match='hw1_5_conditions_incomplete_or_not_boolean'):
            run(viii=bad)
    with pytest.raises(C.ChainError, match='hw1_5_conditions_incomplete_or_not_boolean'):
        run(ix=True)
    # a negative HW1-5 needs no condition; another hypothesis selected records nothing
    neg = {k: 'REJETÉE' for k in C.CB_ORDER}
    assert _select(tmp_path, _codes(), neg, conditions=None)['status'] == 'VIDE'
    one = dict(neg, **{'HW1-1': 'EXPLORATOIRE POSITIVE'})
    out = _select(tmp_path, _codes(HW1_1=P), one, conditions=None)
    assert out['cb_hypothesis'] == 'HW1-1' and out['hw1_5_recorded_not_blocking'] is None


def test_the_selection_inputs_are_checked(tmp_path):
    words = {k: 'REJETÉE' for k in C.CB_ORDER}
    the_plan = _plan(tmp_path)
    with pytest.raises(C.ChainError, match='r02_final_is_not_about_these_hw1_verdicts'):
        C.select(the_plan, _hw1(_codes()), '34' * 32, _final(words))
    with pytest.raises(C.ChainError, match='r02_final_is_not_about_these_hw1_verdicts'):
        C.select(the_plan, _hw1(_codes()), '12' * 32, dict(_final(words), schema='x'))
    for bad in (dict(words, **{'HW1-5': 'POSITIVE'}), {k: v for k, v in words.items() if k != 'HW1-3'},
                dict(words, **{'HW1-9': 'REJETÉE'})):
        with pytest.raises(C.ChainError, match='r02_final_words_incomplete_or_unknown'):
            C.select(the_plan, _hw1(_codes()), '12' * 32, _final(bad))
    for over, error in ((dict(source='p0_visible'), 'not_the_hw1_verdicts_of_w1'),
                        (dict(w1_data_read=False), 'not_the_hw1_verdicts_of_w1'),
                        (dict(schema='x'), 'not_the_hw1_verdicts_of_w1'),
                        (dict(hypotheses_sha256='0' * 64), 'hw1_verdicts_not_from_this_plan'),
                        (dict(pack_manifest_sha256='0' * 64), 'hw1_verdicts_not_from_this_plan'),
                        (dict(trials_added_to_n=4), 'hw1_trials_differ')):
        with pytest.raises(C.ChainError, match=error):
            C.select(the_plan, dict(_hw1(_codes()), **over), '12' * 32, _final(words))


# --- W2 C-B plan ------------------------------------------------------------------------------------------------

def test_cb_plan_lists_the_w2_commands_of_the_chosen_hypothesis_only(tmp_path):
    words = dict({k: 'REJETÉE' for k in C.CB_ORDER}, **{'HW1-4': 'EXPLORATOIRE POSITIVE'})
    selection = _select(tmp_path, _codes(HW1_4=P), words)
    s0 = 471_000_000
    doc = C.cb_plan(selection, '56' * 32, s0, 3)
    assert doc['cb_hypothesis'] == 'HW1-4' and doc['horizon_s'] == 120 and doc['windows'] == 3
    assert [w['s0'] for w in doc['per_window']] == [s0, s0 + W.WINDOW_SLOTS, s0 + 2 * W.WINDOW_SLOTS]
    assert all(w['evaluation'] == list(W.evaluation_range(w['s0'])) for w in doc['per_window'])
    for w in doc['per_window']:
        assert all('--official-verdict-sha256 ' + OFFICIAL in c for c in w['commands'][:2])
        assert '--evaluation-min %d --evaluation-max %d' % tuple(w['evaluation']) in w['commands'][0]
        assert '--latency-slots 10' in w['commands'][1] and 'w2arms.cb creation-slots' in w['commands'][2]
    v = doc['verdict_command']
    assert '--hypothesis HW1-4' in v and 'cb_rows_1.json cb_rows_2.json cb_rows_3.json' in v and '--latency10' in v
    assert doc['conditions'] == list(C.CONDITIONS_C_B) and doc['dossier_b']['n_min'] == 414


def test_an_empty_cb_gives_no_command_and_w2_must_follow_w1(tmp_path):
    empty = _select(tmp_path, _codes(), {k: 'REJETÉE' for k in C.CB_ORDER})
    doc = C.cb_plan(empty, '56' * 32, 471_000_000, 3)
    assert doc['status'] == 'VIDE' and doc['commands'] == [] and 'verdict_command' not in doc
    for s0, k in ((C.S0_W1, 3), (C.EVALUATION_W1[1], 3), (471_000_000, 0), (471_000_000, '3')):
        with pytest.raises(C.ChainError, match='invalid_w2_windows|w2_overlaps_w1'):
            C.cb_plan(empty, '56' * 32, s0, k)
    with pytest.raises(C.ChainError, match='not_a_cb_selection'):
        C.cb_plan(dict(empty, schema='x'), '56' * 32, 471_000_000, 3)


# --- the whole chain on the public fixture pools moved into the W1 range -----------------------------------------

def test_the_whole_chain_on_fixture_pools_inside_the_w1_range(tmp_path, capsys):
    base, _base_sha = _export(tmp_path)
    first = min(tx['slot'] for p in base.glob('*.json.gz')
                for tx in json.loads(gzip.decompress(p.read_bytes()))['transactions'].values())
    (tmp_path / 's').mkdir()
    pools, manifest_sha = _export(tmp_path / 's', shift=LOW + 10 - first)
    (tmp_path / 'official.json').write_bytes(OFFICIAL_BYTES)
    run = lambda *a: C.main([str(x) for x in a])                                       # noqa: E731
    assert run('plan', '--official-verdict', tmp_path / 'official.json', '--official-verdict-sha256', OFFICIAL,
               '--export-manifest-sha256', manifest_sha, '--n-before', 168, '--out', tmp_path / 'plan.json') == 0
    plan_sha = json.loads(capsys.readouterr().out)['plan_sha256']
    for slots, name in ((4, 'l4.json'), (10, 'l10.json')):
        doc = H.run_export(pools, manifest_sha, evaluation=C.EVALUATION_W1, official_verdict_sha256=OFFICIAL,
                           latency_slots=slots)
        (tmp_path / name).write_text(json.dumps(doc, sort_keys=True, indent=1) + '\n', encoding='utf-8')
    assert run('check-rows', '--plan', tmp_path / 'plan.json', '--plan-sha256', plan_sha,
               '--rows-lat4', tmp_path / 'l4.json', '--rows-lat10', tmp_path / 'l10.json') == 0
    sizes = json.loads(capsys.readouterr().out)
    assert sizes['lat4']['pools_read'] == 3 and sizes['lat4']['counts']['m'] == 0
    assert sizes['lat4']['counts']['PLACEBO']['positions'] > 0 and sizes['lat4']['counts']['HW1-5']['positions'] > 0
    census = dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[], rows=[])
    (tmp_path / 'census.json').write_bytes(_raw(census))
    sha = lambda n: _sha((tmp_path / n).read_bytes())                                   # noqa: E731
    assert run('verdicts', '--plan', tmp_path / 'plan.json', '--plan-sha256', plan_sha,
               '--rows-lat4', tmp_path / 'l4.json', '--rows-lat4-sha256', sha('l4.json'),
               '--rows-lat10', tmp_path / 'l10.json', '--rows-lat10-sha256', sha('l10.json'),
               '--census', tmp_path / 'census.json', '--census-sha256', sha('census.json'), '--declared-m', 0,
               '--out', tmp_path / 'v') == 0
    verdicts_sha = json.loads(capsys.readouterr().out)['hw1_verdicts_file_sha256']
    hw1 = json.loads((tmp_path / 'v' / 'HW1_VERDICTS.json').read_bytes())
    assert all(hw1['hypotheses'][k]['verdict'] == 'NON ÉVALUABLE' for k in C.CB_ORDER)
    final = dict(schema=C.SCHEMA_FINAL, hw1_verdicts_file_sha256=verdicts_sha,
                 final={k: 'NON ÉVALUABLE' for k in C.CB_ORDER})
    (tmp_path / 'final.json').write_bytes(_raw(final))
    assert run('select', '--plan', tmp_path / 'plan.json', '--plan-sha256', plan_sha,
               '--hw1-verdicts', tmp_path / 'v' / 'HW1_VERDICTS.json', '--hw1-verdicts-sha256', verdicts_sha,
               '--r02-final', tmp_path / 'final.json', '--r02-final-sha256', sha('final.json'),
               '--out', tmp_path / 'selection.json') == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['status'] == 'VIDE' and printed['cb_hypothesis'] is None
    assert run('cb-plan', '--selection', tmp_path / 'selection.json', '--selection-sha256', sha('selection.json'),
               '--w2-s0', 471_000_000, '--windows', 2, '--out', tmp_path / 'cb_plan.json') == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'VIDE'
    assert json.loads((tmp_path / 'cb_plan.json').read_bytes())['commands'] == []
    # the same pools OUTSIDE W1 are refused by the chain (no W1 data read)
    plain = H.run_export(base, _base_sha, evaluation=C.EVALUATION_W1, official_verdict_sha256=OFFICIAL)
    with pytest.raises(C.ChainError, match='rows_not_from_the_anchored_export|rows_do_not_come_from_w1'):
        C.check_rows_document(plain, C.load_plan(tmp_path / 'plan.json', plan_sha), 4)
