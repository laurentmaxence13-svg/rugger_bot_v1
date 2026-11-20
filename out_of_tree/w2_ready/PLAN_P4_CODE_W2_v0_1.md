# P-4 — plan du code W2 (C1 intégré, mode compte fermé pour C-E) — v0.1, AVANT tout code (RUGGER 01, 21/11)

**Principe.** Aucun nouveau calcul de rendement n'est écrit pour le MASTER ni pour C-B : tout réemploie le code gelé
ou audité. Le code neuf se limite à l'orchestration par fenêtre et au bras C-E.

| Bras W2 (Dossier B) | Calcul | Code | Nouveau ? |
|---|---|---|---|
| A0 statu quo (MASTER) et A1 placebo | Chaîne gelée export → series → trials → evaluate → ledger → dossier, paramétrée par `--s0` de la fenêtre W2 | `w1aux.dayj` v7.8 (inchangé) + `w1aux.dayj_c1p1` pour le ledger (C1 + P1), c'est-à-dire le paquet A2 b2e83b39 | NON : seuls `s0` et le registre W2 changent |
| C-B (une hypothèse HW1, choisie par la règle du Dossier A § 11 après la lecture HW1) | Positions et verdicts gelés de l'hypothèse retenue | `statelab.hypotheses export` (empreinte 1e5fb31a), avec `--evaluation-min/max` de W2 et `--official-verdict-sha256` du verdict W1 ; filtre sur l'id retenu | NON |
| C-E (option non recommandée) | Placebo gelé au palier ≤ 2 500 ppm, TP 7 / SL 5 / 30 s ; net en mode fermé (closedacct 0.2) ET ouvert (sensibilité) | Nouveau module `w2arms.ce` : réemploie `cdgate` 0.2 (décision placebo, palier, `run_rule`, décomposition, glissement) et `closedacct` 0.2 ; plage d'évaluation en paramètre | OUI (petit) |

## Module `w2arms` 0.1 (à écrire après ton accord)

- **`w2arms.ce rows`** : sur un export W2, avec la plage d'évaluation et le sha du MANIFEST ancré, une ligne par
  pool éligible. La ligne contient la grappe et l'outcome `run_rule` : reçu, coût, jetons, raison de sortie, taux,
  glissement, latence à 10 slots. Le rendement n'est calculé ni affiché ; seuls les effectifs sont affichés, comme
  `statelab.hypotheses export`.
- **`w2arms.ce verdict`** : sur des lignes ancrées par R02. Il calcule le net sur la mise, en mode fermé (échecs = 0)
  et en mode ouvert, avec la sensibilité échecs = 1 et celle à 10 slots, puis applique les critères GO du Dossier B,
  à recopier mot pour mot. J'ai besoin du texte exact des § 4 et 6 du Dossier B (v1.3 ou v1.4) : je ne l'ai pas.
- **Lot hebdomadaire.** Les lignes d'une semaine sont un fichier ; le verdict lit la liste des fichiers ancrés, sans
  regard intermédiaire. S'il faut un regard intermédiaire, la règle d'arrêt « palier disparu » du Dossier B est
  calculée sur des comptes de POPULATION seulement (pools éligibles par jour), jamais sur des rendements.
- **Pare-feu.** Les âges sont ≤ 120 s ; seul le palier est lu ; aucune variable HW1 ; aucune lecture d'état sauf le
  glissement descriptif (admis par R02).
- **Tests prévus.**
  - (i) Mêmes lignes que la partie placebo de cdgate sur le pack gelé, à plage égale.
  - (ii) Mode fermé = closedacct ; écart ouvert − fermé = (loyer − frais) / mise.
  - (iii) Les lignes ne contiennent aucun rendement.
  - (iv) Le verdict refuse des lignes non ancrées ou des hypothèses différentes.
  - (v) Plage hors fenêtre : rien n'est lu.
  - Défauts volontaires.

## Orchestration W2 (A0, A1)

- **Ce qui ne change pas.** `dayj` est paramétré par `--s0`. La fenêtre W2 se calcule par `w1_run.plan(s0)`
  (EVALUATION_SLOTS gelé).
- **Changements nécessaires, sans toucher au code gelé.**
  - (1) Un registre d'essais W2 neuf : `other_runs` = P0 + W1 + W2 précédents, comme le D-2 de R02.
  - (2) La correction C1 est toujours active, via `dayj_c1p1` (déjà dans le paquet A2).
  - (3) Une identité de selfcheck inchangée (4aee76a3).
- Je n'écris rien ici tant que R03 n'a pas livré le paquet de collecte W2 paramétré par fenêtre.

## Lecture HW1

Voir `RUNBOOK_LECTURE_HW1_v3.md` : prête, non exécutée. Vérifications du 21/11 sans donnée W1 : hypotheses.py
81f19725 et empreinte 1e5fb31a, toutes deux conformes.
