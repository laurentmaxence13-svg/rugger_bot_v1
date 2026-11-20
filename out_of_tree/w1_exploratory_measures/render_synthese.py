"""Owner synthesis of the PRELIMINARY W1 reading, rendered from the anchored LECTURE_PRELIMINAIRE.json only.

Plan, sources and forbidden wordings fixed by RUGGER 02 BEFORE any reading (additif 5, 2026-11-15). This script
adds no figure: every number is read in the JSON and printed with its key; the only arithmetic is the change of
unit (lamports to SOL, ratio to per cent) and the length of the evaluation range in slots. The text around the
figures is fixed here, before the reading; no result figure is written in this file. A key absent from the reading
is shown as "non calculé", never guessed. The number of trials counted so far and the duration of the computation
(hours, from the recorded step durations) are given by RUGGER 02 on the command line. Standard library only.

    python -B render_synthese.py --reading LECTURE_PRELIMINAIRE.json --reading-sha256 <sha anchored by R02> \
        --n-trials <N counted by R02> --chain-hours <H given by R02> --out FILE.md
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

LAMPORTS_PER_SOL = 1_000_000_000
STAMP = 'PRÉLIMINAIRE — PAS LE VERDICT OFFICIEL W1'
HEADER = 'EXPLORATOIRE — NON OFFICIEL — pas le verdict W1 — pas une preuve de rentabilité future'
ALLOWED = ('pas une preuve de rentabilité future', 'positif sur cette période, non démontré')
FORBIDDEN = re.compile(r'rentable|prouv|démontr|significati|confirm|valid|par mois|par an|mensuel|annuel', re.I)


class SyntheseError(RuntimeError):
    pass


def _get(doc, key):
    """The value at the dotted key, or None when any part of the path is absent (shown as "non calculé")."""
    value = doc
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class Figures:
    """Reads a figure by its JSON key and formats it, always followed by the key."""

    def __init__(self, doc):
        self.doc = doc

    def raw(self, key):
        return _get(self.doc, key)

    def count(self, key):
        value = self.raw(key)
        return f'{value} (`{key}`)' if value is not None else f'non calculé (`{key}`)'

    def sol(self, key):
        value = self.raw(key)
        if value is None:
            return f'non calculé (`{key}`)'
        return f'{value / LAMPORTS_PER_SOL:+.6f}'.replace('.', ',') + f' SOL (`{key}`)'

    def sol_given(self, key):                              # a figure the JSON already gives in SOL
        value = self.raw(key)
        return f'non calculé (`{key}`)' if value is None else f'{value:+.6f}'.replace('.', ',') + f' SOL (`{key}`)'

    def cost(self, key):                                   # a cost: its magnitude, never a sign (R02, 20/11)
        value = self.raw(key)
        if value is None:
            return f'non calculé (`{key}`)'
        text = f'{abs(value) / LAMPORTS_PER_SOL:.6f}'.replace('.', ',') + f' SOL (`{key}`)'
        return text if value >= 0 else 'coût négatif, gain de ' + text

    def percent(self, key, signed=True):
        value = self.raw(key)
        if value is None:
            return f'non calculé (`{key}`)'
        return (f'{value * 100:+.2f} %' if signed else f'{value * 100:.1f} %').replace('.', ',') + f' (`{key}`)'

    def number(self, key):
        value = self.raw(key)
        return f'non calculé (`{key}`)' if value is None else f'{value:.2f}'.replace('.', ',') + f' (`{key}`)'


def _interval_sentence(low, high):
    if low is None or high is None:
        return "L'intervalle de confiance n'est pas calculable."
    if low > 0:
        return "L'intervalle est entièrement au-dessus de zéro : positif sur cette période, non démontré."
    if high < 0:
        return "L'intervalle est entièrement au-dessous de zéro : négatif sur cette période."
    return "L'intervalle contient zéro : le signe du résultat n'est pas établi."


def render(doc, n_trials, chain_hours, evaluation_hours=None):
    if evaluation_hours is not None and (type(evaluation_hours) is not int or evaluation_hours < 1):
        raise SyntheseError('evaluation_hours_must_be_given_by_r02')
    if type(n_trials) is not int or n_trials < 1:
        raise SyntheseError('n_trials_must_be_given_by_r02')
    if type(chain_hours) is not int or chain_hours < 1:
        raise SyntheseError('chain_hours_must_be_given_by_r02')
    if doc.get('stamp') != STAMP or doc.get('schema') != 'rugger-w1-preliminary-reading-v1':
        raise SyntheseError('not_the_preliminary_reading')
    f = Figures(doc)
    q1, q2, q3 = 'master.Q1_positions', 'master.Q2_result_lamports', 'master.Q3_distribution_lamports'
    q4, q5, q6, q7 = ('master.Q4_failure_factors', 'master.Q5_creators', 'master.Q6_interval_95_of_the_mean_net_return',
                      'master.Q7_unit')
    closed = f.raw(q1 + '.closed')
    low, high = f.raw(q6 + '.low'), f.raw(q6 + '.high')
    lines = [f'# {HEADER}', '',
             '**Synthèse de la lecture préliminaire de W1 (bras MASTER gelé, simulation hors ligne).** '
             f"Document source : `LECTURE_PRELIMINAIRE.json`, sha256 `{doc['_sha256']}`, ancré par RUGGER 02. "
             'Chaque chiffre est suivi de sa clé dans ce fichier ; aucun autre calcul que le changement d\'unité.', '',
             "Rappels. Vous avez choisi l'option A : le verdict officiel W1 sera calculé plus tard, quel que soit ce "
             "résultat. W1 n'est plus une donnée « non vue » pour toute idée nouvelle. Les cinq hypothèses gelées ne "
             "sont pas lues ici. Aucun ordre réel n'a été passé : tout est simulé.", '',
             '## 1. Réponse courte', '']
    if not closed:
        lines += ["Sur la plage d'évaluation de W1, le MASTER a ouvert " + f.count(q1 + '.opened') +
                  " position(s) et n'en a clôturé aucune : il n'y a pas de résultat à lire.", '']
    else:
        lines += ["Sur la plage d'évaluation de W1, le MASTER a ouvert " + f.count(q1 + '.opened') + ' positions et en a '
                  'clôturé ' + f.count(q1 + '.closed') + '. Résultat net après tous les frais : ' +
                  f.sol_given(q7 + '.net_sum_sol') + ' au total, soit ' + f.sol_given(q7 + '.net_mean_sol') + ' et ' +
                  f.percent(q2 + '.net_return_mean') + ' du capital engagé par opération en moyenne. Intervalle de '
                  'confiance à 95 % de ce rendement moyen : de ' + f.percent(q6 + '.low') + ' à ' +
                  f.percent(q6 + '.high') + '. ' + _interval_sentence(low, high), '']
    lines += ['## 2. Positions', '',
              '| | |', '|---|---|',
              '| Pools du MANIFEST (rejoués et exclus) | ' + f.count(q1 + '.eligible_manifest_pools') + ' |',
              '| dont exclus pour défaut de données | ' + f.count(q1 + '.excluded_pools') + ' |',
              "| Pools de la plage d'évaluation | " + f.count(q1 + '.evaluation_pools') + ' |',
              "| Pools hors plage (échauffement), seulement comptés | " + f.count(q1 + '.pools_outside_the_evaluation_range') + ' |',
              '| Sans entrée | ' + f.count(q1 + '.no_entry') + ' |',
              '| Positions ouvertes | ' + f.count(q1 + '.opened') + ' |',
              '| Cycles avec achat exécuté | ' + f.count(q1 + '.cycles_with_entry') + ' |',
              '| Positions clôturées | ' + f.count(q1 + '.closed') + ' |']
    if f.raw(q1 + '.not_closed') is None:
        lines.append(f'| Non clôturées, par code | non calculé (`{q1}.not_closed`) |')
    for code, n in sorted((f.raw(q1 + '.not_closed') or {}).items()):
        lines.append(f'| Non clôturées : `{code}` | {n} (`{q1}.not_closed.{code}`) |')
    lines += ['', '## 3. Résultat après frais et distribution (cycles clôturés)', '',
              '| | |', '|---|---|',
              '| Net total | ' + f.sol(q2 + '.net_sum') + ' |',
              '| Net moyen par opération | ' + f.sol(q2 + '.net_mean') + ' |',
              '| Net médian | ' + f.sol(q2 + '.net_median') + ' |',
              '| Rendement net moyen (du capital engagé) | ' + f.percent(q2 + '.net_return_mean') + ' |',
              '| Rendement net médian | ' + f.percent(q2 + '.net_return_median') + ' |',
              '| Part des opérations gagnantes | ' + f.percent(q2 + '.win_rate', signed=False) + ' |',
              '| Somme des gains / somme des pertes | ' + f.number(q2 + '.profit_factor') + ' |',
              '| Brut total (avant glissement et frais) | ' + f.sol(q2 + '.gross_sum') + ' |',
              '| Brut moyen | ' + f.sol(q2 + '.gross_mean') + ' |',
              '| 10 % des opérations font moins que | ' + f.sol(q3 + '.p10') + ' |',
              '| Médiane | ' + f.sol(q3 + '.p50') + ' |',
              '| 90 % des opérations font moins que | ' + f.sol(q3 + '.p90') + ' |',
              '| Meilleure opération | ' + f.sol(q3 + '.maximum') + ' |',
              '| Pire opération | ' + f.sol(q3 + '.minimum') + ' |',
              '| Part des 5 meilleures dans les gains | ' + f.percent(q3 + '.share_of_the_5_best', signed=False) + ' |',
              '', "## 4. Où part l'argent", '']
    if f.raw(q4 + '.decomposition_lamports') is None:
        lines += ['Aucun cycle clôturé : pas de décomposition.', '']
    else:
        d = q4 + '.decomposition_lamports'
        lines += ['Les coûts sont donnés en montant, sans signe ; ils se retranchent du brut : '
                  'Net = Brut − somme des coûts.', '',
                  '| Poste (total des cycles clôturés) | Montant |', '|---|---|',
                  '| Brut : évolution du prix pendant la détention | ' + f.sol(d + '.market_move') + ' |',
                  '| Coût : glissement de nos propres ordres | ' + f.cost(d + '.slippage') + ' |',
                  '| Coût : frais de la courbe (achat et vente) | ' + f.cost(d + '.launchlab_fees') + ' |',
                  '| Coût : frais de transaction | ' + f.cost(d + '.tx_costs') + ' |',
                  '| Coût : tentatives échouées | ' + f.cost(d + '.failed_attempt_costs') + ' |',
                  '| Net | ' + f.sol(d + '.net') + ' |',
                  "| Résidu de cette identité (rapporté tel quel, en lamports) | " + f.count(d + '.identity_residual') + ' |', '']
    lines += ['Motifs de sortie des cycles clôturés :', '']
    reasons = f.raw(q4 + '.exit_reasons')
    if reasons is None:
        lines.append(f'- non calculé (`{q4}.exit_reasons`)')
    else:
        lines += [f'- `{code}` : {n} (`{q4}.exit_reasons.{code}`)' for code, n in sorted(reasons.items())] or ['- aucun']
    lines += ['', '## 5. MASTER contre référence et contre hasard (totaux seulement)', '',
              'Cette comparaison préfigure, sans les remplacer, les tests officiels.', '',
              _identity_sentence(f, q1, q2, q4), '',
              '| | MASTER | Référence | Hasard (placebo) |', '|---|---|---|---|',
              '| Cycles clôturés | ' + f.count(q1 + '.closed') + ' | ' + f.count('others.reference.closed_cycles') + ' | ' +
              f.count('others.placebo_random.closed_cycles') + ' |',
              '| Net moyen par opération | ' + f.sol(q2 + '.net_mean') + ' | ' + f.sol('others.reference.mean_net_pnl_lamports') +
              ' | ' + f.sol('others.placebo_random.mean_net_pnl_lamports') + ' |',
              '| Rendement net moyen | ' + f.percent(q2 + '.net_return_mean') + ' | ' + f.percent('others.reference.mean_net_return') +
              ' | ' + f.percent('others.placebo_random.mean_net_return') + ' |']
    for label, part in (('Brut', 'market_move'), ('Coût : glissement', 'slippage'),
                        ('Coût : frais de la courbe', 'launchlab_fees'), ('Coût : frais de transaction', 'tx_costs'),
                        ('Coût : tentatives échouées', 'failed_attempt_costs'), ('Net', 'net')):
        show = f.cost if label.startswith('Coût') else f.sol
        row = f'| {label} (total) | ' + (show(q4 + '.decomposition_lamports.' + part)
                                         if f.raw(q4 + '.decomposition_lamports') is not None else 'non calculé')
        for arm in ('reference', 'placebo_random'):
            row += ' | ' + show(f'others.{arm}.decomposition_lamports.{part}')
        lines.append(row + ' |')
    lines += ['', '## 6. Fiabilité', '',
              '- Intervalle de confiance à 95 % du rendement net moyen : de ' + f.percent(q6 + '.low') + ' à ' +
              f.percent(q6 + '.high') + ' ; rééchantillonnage par créateur, ' + f.count(q6 + '.draws') + ' tirages, ' +
              f.count(q6 + '.clusters') + ' créateurs ou pools distincts. ' + _interval_sentence(low, high),
              '- Concentration : ' + f.count(q5 + '.distinct_clusters') + ' créateurs ou pools distincts parmi les cycles '
              'clôturés ; les cinq plus présents détiennent ' + f.percent(q5 + '.share_of_the_5_largest', signed=False) +
              ' des cycles clôturés (en nombre de cycles, non en résultat).',
              "- Une seule période : plage d'évaluation de " + _slots(f) + " slots (`population.evaluation_max` − "
              "`population.evaluation_min`), " + (
                  "durée d'horloge non mesurée dans cette lecture." if evaluation_hours is None else
                  f"soit environ {evaluation_hours} heures d'horloge de la chaîne (block_time ; chiffre donné par "
                  "RUGGER 02)."),
              '- Coûts, latence et mise sont ceux du protocole gelé ; nos ordres simulés n\'ont pas existé : leur effet '
              'sur les autres acteurs est inconnu.',
              '- Les outils en flux utilisés pour cette lecture produisent les mêmes fichiers que la chaîne gelée sur '
              'les jeux de référence seulement (pilote, jeux de prix ouverts, jeux synthétiques), pas sur une fenêtre '
              'réelle de la taille de W1.',
              "- Ce n'est pas la décision W1 : ni le test officiel contre la référence et le hasard, ni la correction "
              f"pour le nombre d'essais ({n_trials} essais exploratoires comptés sur les données de développement, en "
              'plus des essais préenregistrés du protocole W1 ; chiffre donné par RUGGER 02) ne sont calculés ici.',
              "- Lecture non aveugle : elle a été faite avant le verdict officiel.",
              f'- Durée du calcul : environ {chain_hours} heures (chiffre donné par RUGGER 02 à partir des durées '
              "enregistrées). Le temps du rejeu gelé croît à peu près comme le carré du nombre d'événements d'un pool "
              "tant que le MASTER n'est pas entré : c'est une limite pratique de l'outil, sans effet sur les "
              'résultats.', '',
              '## 7. Pistes d\'amélioration', '',
              'Ce sont des HYPOTHÈSES, à tester sur des données futures (W2), jamais sur W1. Elles viennent de ce que '
              'les données de développement avaient déjà établi ; aucune ventilation de W1 n\'a été faite pour en '
              'chercher d\'autres.', '',
              '1. Réduire le coût d\'un aller-retour : récupérer le loyer du compte de token en fermant le compte après '
              'la vente.',
              '2. Élargir l\'univers exécutable aux tokens Token-2022 d\'une liste stricte.',
              '3. Se limiter aux pools à frais de courbe faibles.',
              '4. Mesurer la migration et le marché d\'après-migration, sur lesquels il n\'existe aucune donnée : '
              'collecte soumise à votre accord.',
              '5. Réévaluer la décision d\'entrée elle-même : sur les données de développement, la perte venait de '
              'l\'achat, pas de la règle de vente.', '',
              '## 8. Suite', '',
              '- Verdict officiel W1 : il reste à calculer (option A). La seule voie prête est Google Cloud, dans la '
              'limite de budget que vous aviez fixée, avec un paquet audité ; elle attend votre décision de dépense.',
              '- Les cinq hypothèses gelées seront lues une seule fois, après ce verdict officiel.',
              '- Aucun ordre réel, aucune activation, aucune dépense sans votre accord.', '']
    text = '\n'.join(lines)
    checked = text
    for phrase in ALLOWED:
        checked = checked.replace(phrase, '')
    found = FORBIDDEN.search(checked)
    if found:
        raise SyntheseError('forbidden_wording:' + found.group(0))
    return text


def _identity_sentence(f, q1, q2, q4):
    """The frozen code makes the MASTER arm enter exactly when early_sniping does, with the same exit plan (R02, 20/11;
    hrr l. 491, 508-513; p4_experiment l. 178). The sentence is checked against the reading, never assumed."""
    same = (f.raw(q1 + '.closed') == f.raw('others.reference.closed_cycles')
            and f.raw(q2 + '.net_mean') == f.raw('others.reference.mean_net_pnl_lamports')
            and f.raw(q4 + '.decomposition_lamports') is not None
            and all(f.raw(q4 + '.decomposition_lamports.' + part) == f.raw('others.reference.decomposition_lamports.' + part)
                    for part in ('market_move', 'slippage', 'launchlab_fees', 'tx_costs', 'failed_attempt_costs', 'net')))
    if same:
        return ("Les colonnes MASTER et Référence sont identiques, et c'est attendu : par construction du code gelé, le "
                "bras MASTER entre exactement quand la référence `early_sniping` entre, avec le même plan de sortie. "
                "Cette lecture ne compare donc pas le MASTER à une autre stratégie ; seule la colonne Hasard le fait.")
    return ("ATTENTION : les colonnes MASTER et Référence diffèrent, alors que le code gelé les rend identiques "
            "(le MASTER entre exactement quand `early_sniping` entre, avec le même plan de sortie). Écart à expliquer "
            "avant toute conclusion.")


def _slots(f):
    start, end = f.raw('population.evaluation_min'), f.raw('population.evaluation_max')
    return 'non calculé' if type(start) is not int or type(end) is not int else f'{end - start:,}'.replace(',', ' ')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--reading', type=Path, required=True)
    parser.add_argument('--reading-sha256', required=True, help='sha256 of the reading, as anchored by RUGGER 02')
    parser.add_argument('--n-trials', type=int, required=True, help='trials counted so far, as given by RUGGER 02')
    parser.add_argument('--chain-hours', type=int, required=True,
                        help='duration of the computation in hours, as given by RUGGER 02 from the recorded durations')
    parser.add_argument('--evaluation-hours', type=int, default=None,
                        help='clock duration of the evaluation range in hours (block_time), as given by RUGGER 02')
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    sha = hashlib.sha256(a.reading.read_bytes()).hexdigest()
    if sha != a.reading_sha256:
        raise SyntheseError('reading_is_not_the_anchored_one')
    if a.out.exists():
        raise SyntheseError('output_exists')
    doc = json.loads(a.reading.read_text(encoding='utf-8'))
    doc['_sha256'] = sha
    a.out.write_text(render(doc, a.n_trials, a.chain_hours, a.evaluation_hours), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
