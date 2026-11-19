# Diagnostic du FAIL du ledger W1X (R02 82340a82)

Hors ligne et en lecture seule, ce paquet ne dépend que de la bibliothèque standard. Il ne fait pas partie de la chaîne :
il n'écrit rien dans la racine et ne lit que la copie gelée de `ledger/ledger.json`.

## Étape 1 : la structure des écarts (`w1diag.histogram`)

    python -B -m w1diag.histogram --ledger <copie gelée>/ledger.json --ledger-sha256 <sha ancré par R02>

Le script vérifie d'abord le sha256 ancré, puis imprime **une seule ligne**, limitée aux clés de la liste blanche
`verdict`, `mismatch_entries`, `histogram`, `pools_touched_by_trial` et `l1_plan_not_re_derived_by_trial` :

- `verdict` vaut PASS ou FAIL ; toute autre valeur est masquée.
- `mismatch_entries` est le nombre d'entrées en écart.
- `histogram` donne des lignes [essai, bras, contrôle, nombre]. Le contrôle est le préfixe avant le premier « : » ;
  un préfixe hors de `[a-z0-9_]+` devient `unrecognized_check_name`. Chaque entrée compte une fois par contrôle.
- `pools_touched_by_trial` donne le nombre de pools distincts en écart par essai, jamais leurs adresses.
- `l1_plan_not_re_derived_by_trial` donne le nombre d'entrées dont `l1_exit_plan_re_derived` est faux, par essai.

Les noms d'essai et de bras hors de `[A-Za-z0-9_.:-]+` deviennent `unrecognized`.

**Jamais imprimé** : `cycles_with_entry`, `cycles_verified` ou tout autre nombre absolu de cycles, ainsi que toute
valeur, tout pool, `pnl`, `net_return` et `comparison`.

### Lecture du résultat (d'après le code v7.4, réponse (a) à R02)

Seuls trois contrôles peuvent provenir de P1-bis : `l1_exit_plan`, `l1_plan_not_available_at_the_decision` et
`l1_plan_not_re_derived`. Tous les autres sont recalculés par v7.4 à l'assemblage, sans le cache.

## Tests

    cd <ce dossier> && PYTHONPATH=. python -B -m pytest w1diag/tests -p no:cacheprovider -q -W error

Les 6 tests portent sur un ledger synthétique dont les écarts sont connus : structure attendue, absence de toute valeur
interdite, masquage des noms, sha ancré exigé, cas PASS. Défauts volontaires : `MUTATIONS_STEP1.jsonl`.

## Étape 2

L'étape 2 est écrite après le résultat de l'étape 1 (R02).
