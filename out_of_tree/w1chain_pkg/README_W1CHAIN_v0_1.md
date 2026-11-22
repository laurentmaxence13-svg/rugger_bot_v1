# w1chain 0.1 — chaîne hors ligne verdict W1 → lecture HW1 → choix de C-B → verdict W2 de C-B (tâche P2-a)

RUGGER 01, 22/11/2026. ÉCRIT, TESTÉ SUR FIXTURES, NON EXÉCUTÉ sur W1 ni W2. Aucune donnée W1/W2 lue.
Source des tâches : `docs/ops/ETAT_RUGGER_MASTER.md` (62c4525). Base : runbook HW1 v2 (74a74cf) et v3 (2df1b92),
inchangés ; Dossier A § 3 et § 11 (règle C-B) ; Dossier B v1.9 (critères GO de C-B).

## Ce que fait la chaîne (elle ne change aucune règle)

| Sous-commande | Étape du runbook | Rôle |
|---|---|---|
| `plan` | avant 3 | sha du verdict officiel W1 ancré (octets hachés, jamais lus) ; code gelé revérifié ; plage W1 recalculée par `w1_collection.bounds(467 275 745)` = [467 678 545 ; 469 291 345) ; compteur d'essais ; commandes exactes des étapes 3 et 5 |
| `check-rows` | 4 (R02) | les 2 fichiers de lignes sont les exports 4 et 10 slots de CE plan ; n'affiche QUE les sha et les effectifs gelés (`counts`) |
| `verdicts` | 5 (R03) | lignes, recensement et m ANCRÉS ; appelle `statelab.hypotheses.verdicts` gelé ; sortie OCTET POUR OCTET égale à la CLI gelée (testé) ; écrit `TRIALS.json` |
| `select` | après 6 | règle C-B : 1ʳᵉ de HW1-5, 1, 2, 4, 3 dont le mot FINAL de R02 est « EXPLORATOIRE POSITIVE » ou « CONFIRMÉE SUR W1 » ; sinon C-B VIDE |
| `cb-plan` | W2 | commandes W2 de l'hypothèse retenue (export statelab par fenêtre, `w2arms.cb creation-slots`, un seul `w2arms.cb verdict`) ; aucune commande si C-B est VIDE |

## Éléments gelés vérifiés à chaque commande (`frozen_check`)

- `statelab/hypotheses.py` 81f19725… ; empreinte « hypotheses » 1e5fb31a… ; `w2arms/cb.py` 0.2 a293d3f7… ; `w2arms/ce.py` a161ad49….
- Dossier B v1.9 : K = 3 ; borne unilatérale à α = 0,05/3 (98,33 %) > 0 ; 10 000 tirages par grappe de créateurs ;
  n_min = 414 ; c1 rentabilité, c2 supériorité au placebo apparié (même pool, même horizon), c3 deux moitiés
  positives (par slot de création), c4 identité de coûts à résidu nul, c5 (HW1-5 : net > 0 à 10 slots ET sans les
  5 meilleurs pools). Ces critères sont ceux de `w2arms.cb.verdict` 0.2, appelé tel quel.
- Toute différence = ARRÊT (`frozen_code_differs:*`, `dossier_b_constants_differ`, `w1_evaluation_range_differs`).

## Décompte des essais

- Entrée `--n-before` = registre de R02 hors HW1 (168 le 22/11) ; refus si > 170 (`trial_cap_exceeded`).
- Lecture HW1 : + 5 (= `trials_added_to_n` du code gelé, vérifié) → **173**, publié à part.
- Le choix de C-B est mécanique : + 0 (déclaré ; à confirmer par R02).

## Points déclarés, à valider par R02 (aucun n'est une règle nouvelle)

1. **Document final de R02 (étape 6)** : je propose le schéma `w1chain-hw1-final-v1` :
   `{"schema", "hw1_verdicts_file_sha256", "final": {HW1-1..HW1-5: mot}, "hw1_5_conditions_r02": {"i".."viii": true|false}}`.
   Mots admis : EXPLORATOIRE POSITIVE, CONFIRMÉE SUR W1 (positifs) ; NÉGATIVE, REJETÉE, NON ÉVALUABLE, NON CONCLUANT,
   EXPLORATOIRE NON CONFIRMÉE (non positifs).
2. **Lien code / R02** (règle 6 de R02, 4e03d6a6) : un mot final positif n'est accepté que si le code gelé a donné son
   mot positif (« CRITÈRE PRINCIPAL ATTEINT — … » ; pour HW1-5 « CRITÈRE PRINCIPAL ET CONDITIONS ATTEINTS — … »).
   Sinon ARRÊT (`r02_positive_where_the_frozen_code_is_not`). Un mot positif du code SANS mot positif de R02 ne
   sélectionne rien.
3. **HW1-5** : les conditions (i) à (viii) de R02 (d70251db) doivent toutes valoir `true` ; leur contenu reste celui
   de R02, la chaîne ne les recalcule pas.
4. **Nombre de fenêtres W2 (k)** et s0 de W2 : variables du propriétaire (Dossier B v1.9) ; simples entrées ici.

## Tests et mutants

- 31 tests (`w1chain/tests/test_chain.py`), dont une chaîne COMPLÈTE `plan → check-rows → verdicts → select → cb-plan`
  sur les 3 pools publics de fixture décalés dans la plage W1 (positions réelles HW1-5 et placebo ; m = 0, donc C-B
  VIDE), et l'égalité d'octets avec la CLI gelée de statelab.
- Mutants : 29/29 détectés (`MUTATIONS_w1chain_v0_1.json`, lanceur `mutations_w1chain_runner.py`).

Commande (depuis l'arbre gelé, SANS `-I`) :
`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<w1chain_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <w1chain_pkg>/w1chain/tests -p no:cacheprovider -q -W error`

## Interdits respectés

Aucune exécution sur W1 ou W2 ; aucune lecture de valeur ; holdout P0 jamais ouvert ; aucun seuil, horizon,
population ou critère modifié ; aucune seconde passe ; aucun ordre, aucune dépense, aucune collecte.
