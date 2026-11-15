"""render_synthese: every figure comes from the reading with its key; fixed wording; forbidden wording refused."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import render_synthese as RS                                # noqa: E402
from w1x import reading as R                                # noqa: E402
from w1x.tests import test_reading as tr                    # noqa: E402


def _reading(tmp_path, empty=False):
    if empty:
        ledger, bundle = tr._documents(tmp_path, [tr._pool('a', tr.START, 'A')], [])
    else:
        ledger, bundle = tr._case(tmp_path)
    R.run(ledger, bundle, tmp_path / 'out', evaluation_min=tr.START, evaluation_max=tr.END)
    path = tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.json'
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _keys(doc, prefix=''):
    for key, value in doc.items():
        if isinstance(value, dict):
            yield from _keys(value, prefix + key + '.')
        else:
            yield prefix + key


def test_every_figure_is_the_reading_s_with_its_key(tmp_path):
    path, sha = _reading(tmp_path)
    assert RS.main(['--reading', str(path), '--reading-sha256', sha, '--n-trials', '159', '--chain-hours', '21', '--out', str(tmp_path / 's.md')]) == 0
    text = (tmp_path / 's.md').read_text(encoding='utf-8')
    doc = json.loads(path.read_text(encoding='utf-8'))
    assert text.startswith('# EXPLORATOIRE — NON OFFICIEL — pas le verdict W1 — pas une preuve de rentabilité future')
    assert sha in text and "option A" in text and 'cinq hypothèses gelées ne sont pas lues' in text.replace('\n', ' ')
    known = set(_keys(doc))
    cited = {k for k in re.findall(r'`([A-Za-z0-9_.]+)`', text) if '.' in k} - {'LECTURE_PRELIMINAIRE.json'}
    assert len(cited) > 45 and cited <= known, cited - known             # every cited key exists in the reading
    # a few figures, in the unit of the document
    assert '+0,005000 SOL (`master.Q7_unit.net_sum_sol`)' in text and '+0,50 % (`master.Q2_result_lamports.net_return_mean`)' in text
    assert '40,0 % (`master.Q2_result_lamports.win_rate`)' in text and '1,21 (`master.Q2_result_lamports.profit_factor`)' in text
    assert '-0,008000 SOL (`master.Q3_distribution_lamports.minimum`)' in text
    assert '15 (`master.Q1_positions.opened`)' in text and '10 (`master.Q1_positions.closed`)' in text
    assert '`stop_loss` : 3 (`master.Q4_failure_factors.exit_reasons.stop_loss`)' in text
    assert '-0,003000 SOL (`others.reference.mean_net_pnl_lamports`)' in text and '+12,00 % (`others.placebo_random.mean_net_return`)' in text
    assert "L'intervalle contient zéro : le signe du résultat n'est pas établi." in text
    assert ('les cinq plus présents détiennent 90,0 % (`master.Q5_creators.share_of_the_5_largest`) des cycles clôturés '
            '(en nombre de cycles, non en résultat).') in text
    assert ("(159 essais exploratoires comptés sur les données de développement, en plus des essais préenregistrés du "
            "protocole W1 ; chiffre donné par RUGGER 02)") in text
    assert ("- Durée du calcul : environ 21 heures (chiffre donné par RUGGER 02 à partir des durées enregistrées). Le temps "
            "du rejeu gelé croît à peu près comme le carré du nombre d'événements d'un pool tant que le MASTER n'est pas "
            "entré : c'est une limite pratique de l'outil, sans effet sur les résultats.") in text
    assert [line for line in text.splitlines() if line.startswith('## ')] == [
        '## 1. Réponse courte', '## 2. Positions', '## 3. Résultat après frais et distribution (cycles clôturés)',
        "## 4. Où part l'argent", '## 5. MASTER contre référence et contre hasard (totaux seulement)', '## 6. Fiabilité',
        "## 7. Pistes d'amélioration", '## 8. Suite']
    short = text.split('## 1. Réponse courte')[1].split('## 2.')[0]
    assert len(re.findall(r'[.!?](?:\s|$)', short.replace('95 %', '95'))) <= 4
    # no figure of the document is absent from the reading: every number printed next to a key is that key's value
    checked = 0
    for value, unit, key in re.findall(r'([+-]?\d+,\d+) (SOL|%) \(`([A-Za-z0-9_.]+)`\)', text):
        raw, shown = RS._get(doc, key), float(value.replace(',', '.'))
        if unit == '%':                                    # a ratio of the reading, shown in per cent, rounded
            assert abs(shown - raw * 100) <= 0.051, (key, value, raw)
        else:                                              # lamports (or SOL for Q7) of the reading, shown in SOL
            assert abs(shown - (raw if key.endswith('_sol') else raw / 1e9)) <= 5.1e-7, (key, value, raw)
        checked += 1
    assert checked > 40


def test_no_closed_cycle_and_interval_sentences(tmp_path):
    path, sha = _reading(tmp_path, empty=True)
    RS.main(['--reading', str(path), '--reading-sha256', sha, '--n-trials', '159', '--chain-hours', '21', '--out', str(tmp_path / 's.md')])
    text = (tmp_path / 's.md').read_text(encoding='utf-8')
    assert "n'en a clôturé aucune : il n'y a pas de résultat à lire" in text and 'Aucun cycle clôturé : pas de décomposition.' in text
    assert 'non calculé (`master.Q2_result_lamports.net_sum`)' in text
    assert RS._interval_sentence(0.01, 0.03).endswith('positif sur cette période, non démontré.')
    assert RS._interval_sentence(-0.03, -0.01).endswith('négatif sur cette période.')
    assert RS._interval_sentence(-0.01, 0.0).startswith("L'intervalle contient zéro")
    assert RS._interval_sentence(None, None) == "L'intervalle de confiance n'est pas calculable."


def test_guards_anchored_sha_stamp_forbidden_wording(tmp_path, monkeypatch):
    path, sha = _reading(tmp_path)
    with pytest.raises(RS.SyntheseError, match='reading_is_not_the_anchored_one'):
        RS.main(['--reading', str(path), '--reading-sha256', '0' * 64, '--n-trials', '159', '--chain-hours', '21', '--out', str(tmp_path / 's.md')])
    (tmp_path / 's.md').write_text('x')
    with pytest.raises(RS.SyntheseError, match='output_exists'):
        RS.main(['--reading', str(path), '--reading-sha256', sha, '--n-trials', '159', '--chain-hours', '21', '--out', str(tmp_path / 's.md')])
    doc = json.loads(path.read_text(encoding='utf-8'))
    with pytest.raises(RS.SyntheseError, match='not_the_preliminary_reading'):
        RS.render(dict(doc, stamp='autre', _sha256=sha), 159, 21)
    with pytest.raises(RS.SyntheseError, match='n_trials_must_be_given_by_r02'):
        RS.render(dict(doc, _sha256=sha), None, 21)
    for bad in (None, 0, -3, 2.5, '21'):
        with pytest.raises(RS.SyntheseError, match='chain_hours_must_be_given_by_r02'):
            RS.render(dict(doc, _sha256=sha), 159, bad)
    with pytest.raises(SystemExit):                                             # the argument is required
        RS.main(['--reading', str(path), '--reading-sha256', sha, '--n-trials', '159', '--out', str(tmp_path / 'z.md')])
    for word in ('rentable', 'prouvé', 'démontré', 'significatif', 'confirme', 'valide', 'par mois', 'annuel'):
        monkeypatch.setattr(RS, 'HEADER', RS.HEADER + ' ' + word)
        with pytest.raises(RS.SyntheseError, match='forbidden_wording'):
            RS.render(dict(doc, _sha256=sha), 159, 21)
        monkeypatch.undo()
    text = RS.render(dict(doc, _sha256=sha), 159, 21)                               # the fixed text itself passes
    for phrase in RS.ALLOWED:                                                   # outside the allowed quotations: nothing
        text = text.replace(phrase, '')
    assert not RS.FORBIDDEN.search(text)
    assert not re.search(r'rentable|prouv|démontr|significati|confirm|valid', text, re.I)


def test_an_absent_key_is_shown_as_not_computed_never_guessed(tmp_path):
    path, sha = _reading(tmp_path)
    doc = json.loads(path.read_text(encoding='utf-8'))
    del doc['master']['Q2_result_lamports']['net_median'], doc['master']['Q3_distribution_lamports']
    del doc['master']['Q4_failure_factors']['exit_reasons'], doc['others']['reference'], doc['master']['Q1_positions']['not_closed']
    del doc['population']['evaluation_max'], doc['master']['Q6_interval_95_of_the_mean_net_return']['low']
    text = RS.render(dict(doc, _sha256=sha), 159, 21)
    for key in ('master.Q2_result_lamports.net_median', 'master.Q3_distribution_lamports.p10', 'master.Q4_failure_factors.exit_reasons',
                'others.reference.closed_cycles', 'others.reference.decomposition_lamports.net', 'master.Q1_positions.not_closed',
                'master.Q6_interval_95_of_the_mean_net_return.low'):
        assert f'non calculé (`{key}`)' in text, key
    assert "plage d'évaluation de non calculé slots" in text and "L'intervalle de confiance n'est pas calculable." in text


def test_no_result_figure_is_written_in_the_script_and_the_fixed_wording_is_r02_s():
    import ast
    import inspect
    source = inspect.getsource(RS)
    numbers = {node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant)
               and type(node.value) in (int, float)}
    assert numbers <= {0, 1, 100, 1_000_000_000}, numbers                       # units and comparisons only
    text_only = re.sub(r'`[^`]*`', '', source)
    assert not re.search(r'\d+[,.]\d+ ?(SOL|%)', text_only)
    assert "de l'ordre de 4 jours (durée exacte non mesurée dans cette lecture)" in source
    assert 'collecte soumise à votre accord' in source and 'HYPOTHÈSES, à tester sur des données futures (W2), jamais sur W1' in source
    assert 'préfigure, sans les remplacer, les tests officiels' in source
    assert 'des cycles clôturés (en nombre de cycles, non en résultat).' in source
    assert 'plus des essais préenregistrés du protocole W1 ; chiffre donné par RUGGER 02' in source
    assert RS.HEADER == 'EXPLORATOIRE — NON OFFICIEL — pas le verdict W1 — pas une preuve de rentabilité future'
