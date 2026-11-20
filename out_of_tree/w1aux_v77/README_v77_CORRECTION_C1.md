# w1aux v7.7 — correction C1 du contrôle du ledger (décision du propriétaire du 20/11 : C1-b + D2)

**Changement DÉCLARÉ d'une seule règle de contrôle.** Le code est écrit et testé, mais rien n'est exécuté sur W1 avant
l'audit de RUGGER 02 et son PASS. Tout reste hors de l'arbre gelé `aff97638` : ni les simulations W1, ni les règles de
trading, ni `w1aux/ledger.py` v7.4 (115f3cb5) ne sont modifiés.

## Ce qui change par rapport à v7.6

- **Fichiers repris à l'identique.** Tous les fichiers de v7.6 sont repris octet pour octet (voir `MANIFEST_v77.txt`).
  C'est le cas en particulier de `ledger.py`, `ledger_parallel.py`, `ledger_resume.py` et `dayj.py`. Les identités de
  la chaîne et les clés du cache de reprise ne changent donc pas.
- **Ajouts** : `w1aux/ledger_c1.py` et `w1aux/tests/test_ledger_c1.py`.

## Le défaut corrigé (confirmé sur W1 par le diagnostic, R02 3708a816)

- **Le rejeu gelé** compte 2 × `tx_costs` et, via `priced`, 2 × `failed_attempt_costs` pour toute position valorisée
  (vente ou marquage). hrr réétiquette ensuite certaines de ces lignes sans toucher à ces coûts :
  - `_apply_window` : passage en `open_at_window_end` ;
  - `_migrated` : passage de `open_at_end` à `migrated_unpriced`, sans note ;
  - `_exit_after_migration` : passage de `closed` à `migrated_unpriced`, avec la note `exit_after_migration`.
- **Le ledger v7.4** attend 1 × pour toute issue autre que `closed` et `open_at_end`. Sur W1, cela donne 93 écarts
  `tx_costs` dans L1_event_horizon :
  - 91 lignes passées par `_apply_window` ;
  - 2 lignes passées par `_migrated`.
- Le rejeu est exact ; c'est l'attendu du contrôle qui est faux.

## La règle C1 (C1-b, recalcul indépendant)

Elle s'applique seulement aux issues `open_at_window_end` et `migrated_unpriced`, quand une règle de sortie est
connue. Le ledger rejoue lui-même la détention avec sa propre boucle `derive_hold` (copie indépendante v7.4), à partir
de l'entrée du bundle :

- **Issue re-dérivée valorisée** (`closed` ou `open_at_end`). Les contrôles sont :
  - `tx_costs` = 2 × (base + priority) ;
  - `failed_attempt_costs` = 2 × le frais d'échec ;
  - `exit_index` re-dérivé égal à celui du bundle ;
  - `c1_relabel_consistent` : un `migrated_unpriced` AVEC la note doit venir d'un `closed`, et SANS la note d'un
    `open_at_end`. Un `open_at_window_end` peut venir de l'un ou de l'autre.
- **Issue re-dérivée non valorisée.** L'attendu reste 1 × (la règle v7.4), et le contrôle `outcome` exige que l'issue
  re-dérivée soit égale à celle du bundle.
- **Ce qui ne change pas** :
  - le scope reste `entry_only` : aucun P&L n'est vérifié ni compté pour ces lignes, qui n'en ont pas ;
  - toute autre issue garde EXACTEMENT le résultat v7.4 (testé) ;
  - toute ligne dont les contrôles v7.4 s'arrêtent avant les coûts (indices, taux de frais, achat refusé) le garde
    aussi.

La règle est appliquée par `ledger_c1.c1_rule()`. Ce bloc remplace `ledger.verify_cycle`, que `_entry_for` appelle par
son nom. Il vérifie que `ledger.py` est bien la v7.4 et il est non réentrant. Il rend la déclaration `RULE`, enrichie
du module et de son sha256, pour la trace.

## Preuves (tests hors ligne, CPython 3.12.3, `-W error`)

- **Pack gelé** (sans ligne réétiquetée) : `ledger.json` et `ledger.md` sont identiques octet pour octet avec et sans
  C1.
- **Réétiquetages reproduits** en réécrivant une ligne de bundle exactement comme le fait hrr (fenêtre depuis
  `open_at_end` et depuis `closed` ; `_migrated` ; `_exit_after_migration`) : v7.4 donne FAIL avec exactement
  `tx_costs:ledger=105000:bundle=210000`, et C1 donne PASS. Les autres entrées sont identiques à v7.4.
- **Réétiquetages incohérents ou falsifiés** : C1 donne FAIL dans chaque cas.
  - Un `closed` réétiqueté sans note, ou un `open_at_end` réétiqueté avec la note, échoue sur `c1_relabel_consistent`.
  - Une falsification de `tx_costs`, d'`exit_index` ou de `failed_attempt_costs` échoue sur le contrôle
    correspondant.
- **Re-dérivation non valorisée** : à 1 × et avec la même issue, il n'y a pas d'écart. À 2 ×, l'écart porte sur
  `tx_costs` ; avec une autre issue, sur `outcome`.
- **Toutes les autres issues**, ainsi que les arrêts précoces (avec ou sans règle de sortie) : le résultat est
  identique à v7.4.
- **Réutilisation du cache** : on fait d'abord un ledger reprenable v7.4 (FAIL), puis le même cache avec C1. Les 4
  appels sont repris, 0 sont recalculés, et le résultat est PASS, identique octet pour octet à C1 sans cache.
- **Garde-fous** : réentrance, double remplacement, `ledger.py` différent de v7.4, restauration.

Défauts volontaires : voir `MUTATIONS_v77.json`.
