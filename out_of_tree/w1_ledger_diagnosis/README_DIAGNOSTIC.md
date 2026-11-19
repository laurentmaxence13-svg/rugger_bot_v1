# Diagnostic du FAIL du ledger W1X (R02 82340a82)

Hors ligne et en lecture seule, ce paquet ne dépend que de la bibliothèque standard. Il ne fait pas partie de la chaîne :
il n'écrit rien dans la racine et ne lit que la copie gelée de `ledger/ledger.json`.

## Étape 1 : la structure des écarts (`w1diag.histogram`)

    python -B -m w1diag.histogram --ledger <copie gelée>/ledger.json --ledger-sha256 <sha ancré par R02>

Pour la copie gelée du ledger W1X, le sha256 de `ledger.json` à passer est
`cea0175851c88e7ce85d284317927a6763387e93a5e024de2f7e90d79d9ee18a`, ancré par R02 (registre a87f54e8). La valeur
335ef4ff est l'identifiant du registre de R02, pas l'empreinte du fichier.

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

## Étape 2 : la forme des 93 écarts `tx_costs` de L1_event_horizon (`w1diag.c1_table`, R02 abb5fb04)

L'étape 1 a mis P1-bis hors de cause : FAIL, 93 entrées, `tx_costs` seulement, et seulement dans L1_event_horizon.
L'hypothèse à tester est celle de R02, vérifiée par R01 dans le code figé (voir `PROJET_C1.md`).

    python -B -m w1diag.c1_table --ledger <copie gelée>/ledger.json --ledger-sha256 cea0175851c88e7ce85d284317927a6763387e93a5e024de2f7e90d79d9ee18a \
        --bundle <racine>/run/bundles/L1_event_horizon.json.gz --bundle-sha256 <sha ancré dans run/bundles/SHA256SUMS.json>

Le script lit deux sources, et vérifie le sha256 ancré de chacune :

- `ledger.json`, uniquement pour sélectionner les entrées de L1_event_horizon en écart `tx_costs`, par (bras, pool) :
  les entrées du ledger ne portent ni `tx_costs`, ni les notes, ni `mark_pnl_lamports` ;
- le bundle, pour lire la ligne rejouée, qui porte ces champs ainsi que `exit_index`.

Sortie : une ligne, avec les clés `entries` et `table`. Chaque ligne de `table` donne : bras, issue, multiple entier de
`tx_costs / (base + priority)`, présence de `mark_pnl_lamports`, note `exit_after_migration`, présence d'`exit_index`,
et le nombre. Aucun montant, aucun pool.

Tests : 4 tests. Défauts volontaires : `MUTATIONS_STEP2.jsonl` (10/10).
