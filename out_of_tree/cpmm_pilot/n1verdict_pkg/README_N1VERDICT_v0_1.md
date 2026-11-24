# n1verdict 0.1 — verdict du pilote N1 (essai 170) par g23five, sans modification

RUGGER 01, 24/11/2026.
- Base : R02 a jugé N1 RECEVABLE (notes 0b64abd6 et 2f2e0707), lpcost 0.1 a reçu le PASS TECHNIQUE, et g23five
  0.1.1 le PASS.
- Code hors ligne. Il ne lit aucune donnée et ne s'exécute qu'après l'ancrage de la fiche N1.

## Ce que fait le code (`n1verdict/verdict.py`)

| Fonction | Règle |
|---|---|
| `pool_days` | Jour k = 0 … D − 1 : départ à T0 + k × 86 400 s, fin au début du jour k + 1. Position calculée par `lpcost.lp_position`, avec la latence gelée et les pires états. La ligne doit contenir l'état du pool AVANT T0 (pages pré-T0 + pages de la fenêtre), sinon `pre_t0_state_missing` |
| `total_loss_lamports` | Pool-jour non valorisable (R02 (4)) = −(mise + transactions + loyers perdus). Aux échecs gelés : −100 630 000 lamports |
| `UNPRICED` | Les seules causes « non valorisable », chacune avec son type d'erreur : événement LP au point d'atterrissage, état de sortie vide, pool vidé par un retrait, événement LP sur coffre vide, type d'événement LP inconnu, aucun état au point d'atterrissage. Toute autre erreur ARRÊTE le verdict : c'est un défaut de code ou d'entrée, jamais un résultat |
| `positions` | Les lignes doivent être exactement les pools nommés, dans l'ordre de la fiche |
| `word` | Les règles de G2-3 par les fonctions de g23five : planchers (INCONCLUSIF avant NO-GO) ; NO-GO si la borne haute est < 0 ; GO_PILOTE si la borne basse est > 0 sur l'ensemble ET sans le pool le plus fourni ; sinon INCONCLUSIF |
| `report` | G-0 non passé → STOP sans chiffre. Graine int(sha de la fiche N1[:8], 16). Critère : le NET en SOL, exposition au prix comprise (L3) |

**Ce que publie `report` :**
- les résultats par pool, avec le nombre de pool-jours non valorisables et de refus de garde ;
- les pool-jours non valorisables (nombre, valeur, causes) ;
- des éléments DESCRIPTIFS, sans verdict :
  - `hold_pnl` et `lp_vs_hold`, avec leurs bornes au même bootstrap ;
  - les frais perçus et la perte d'inventaire estimés ;
- les sensibilités, sans verdict : (1, 1, 1) échec, garde à 50 000 ppm, loyers perdus ;
- les limites L1 à L3 ;
- la multiplicité ;
- le sens restreint d'un GO_PILOTE ;
- « sous la cible » (155) ;
- le vocabulaire fermé, contrôlé sur tout le document.

**Code réutilisé sans modification :**
- `lpcost` 0.1 ;
- `cpmmcost` 0.3 ;
- `cpmmx` ;
- `g23five` 0.1.1 : `stratified_bounds`, `blocks`, `floors`, `entries`, `top_pool`, `_check_sheet` ;
- `g1ind`, via g23five : vocabulaire et mention « sous la cible ».

## Validation

- 7 tests :
  - la valeur de la perte totale ;
  - les pool-jours alignés sur T0 et égaux à `lp_position` sur un pool synthétique réel ;
  - un événement LP au point d'atterrissage qui donne 2 pool-jours en perte totale (sortie du jour 1, entrée du
    jour 2), y compris sous la sensibilité ;
  - une autre erreur qui arrête le verdict ;
  - l'état pré-T0 exigé ;
  - GO, NO-GO et « sans le pool le plus fourni » sur des nets contrôlés ;
  - les bornes égales à `stratified_bounds` avec la graine de la fiche ;
  - les sensibilités ;
  - STOP et les entrées ;
  - le vocabulaire.
- 26 mutants sur 26 détectés (`MUTATIONS_n1verdict_v0_1.json`, runner `mutations_n1verdict_runner.py`).
- Commande, cwd wt_w1 : chemin de n1rot + `<g23five_pkg>:<cpmmgen3_pkg>:<barmap_pkg>:<n1verdict_pkg>`,
  `python3.12 -B -m pytest <n1verdict_pkg>/n1verdict/tests -p no:cacheprovider -q -W error`.
