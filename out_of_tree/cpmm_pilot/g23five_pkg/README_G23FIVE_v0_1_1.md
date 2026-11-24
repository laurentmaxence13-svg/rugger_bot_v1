# g23five 0.1.1 — verdict du pilote G2-3 sur pools nommés avant T0

RUGGER 01, 24/11/2026.
- Origine : décision R04-1 (24/11, 20:38Z, par délégation du propriétaire).
- Design : R02, notes 23f02580 et 835d648e ; D confirmé par c301e993.
- 0.1 : PASS TECHNIQUE R02 (MANIFEST 46167196, commit ddc578a).
- **0.1.1** : choix (a) de l'audit R02. Ajout de l'écart au témoin avec IC au même bootstrap stratifié, DESCRIPTIF et
  non décisionnel ; c'est la base de c2 en confirmation. Rien d'autre n'a changé. Soumis à l'audit de R02.

**Estimand.** « La règle G2-3 est-elle nette positive sur CES pools, nommés avant T0, dans une fenêtre future ? » Aucune
généralisation.

## Fonctions (`g23five/verdict.py`)

| Fonction | Règle |
|---|---|
| `counts_before_t0` | Déclenchements G2-3 sur [T0 − 7 j ; T0), avec le b₃ de chaque pool (`cpmmgen2.baseline_b3`, `decisions_g23`, `trigger_count`, gelés) ; données ≥ T0 refusées |
| `select` | ≥ 3 déclenchements, les 5 premiers par compte, égalités par identifiant ; moins de 3 → NON ÉVALUABLE sans essai ; liste hachée |
| `blocks`, `day_of` | Blocs pool × jour, jours alignés sur T0 ; une position hors de [T0 ; T0 + D j) est refusée |
| `stratified_bounds` | Bootstrap par blocs pool-jour STRATIFIÉ par pool : chaque pool tire ses propres jours avec remise ; bornes unilatérales à 95 % ; 10 000 tirages ; graine int(sha de la fiche[:8], 16) |
| `floors` | ≥ 30 pool-jours avec entrée ; ≥ 3 pools ; Kish (Σnₚ)² / Σnₚ² ≥ 2,5 ; aucun pool > 50 % des entrées. Entrées = positions entrées, ventes nulles comprises, refus de garde exclus |
| `difference_bounds` | 0.1.1, DESCRIPTIF : à chaque tirage, le primaire PUIS le témoin sont rééchantillonnés chacun par blocs pool-jour stratifiés par pool (tirages indépendants, un seul générateur, graine de la fiche) ; bornes unilatérales à 95 % de la différence des deux moyennes. N'entre jamais dans le mot |
| `top_pool` | Le pool qui a le plus d'entrées, égalités par identifiant |
| `report` | Voir ci-dessous |

**Décision de `report`, dans l'ordre :**
1. G-0 non passé → STOP, sans aucun chiffre.
2. Un plancher manqué → INCONCLUSIF, avant tout NO-GO (R-0.1).
3. Borne haute < 0 → NO-GO.
4. Borne basse > 0 sur l'ensemble ET sans le pool le plus fourni → GO_PILOTE.
5. Sinon → INCONCLUSIF.

**Ce que publie `report` :**
- les résultats par pool ;
- la mention « sous la cible » (155) ;
- les ventes nulles (K01) ;
- le témoin, descriptif, sans verdict, avec l'écart et ses bornes à 95 % (`placebo.difference_bounds_95`, NM sans témoin) ;
- le vocabulaire fermé, contrôlé sur tout le document.

**Code réutilisé sans modification.**
- `cpmmgen2` : règle G2-3, b₃, comptage ;
- `cpmmprereg` : `positions`, `placebo`, `n_required` ;
- `cpmmcost` : étiquettes ;
- `g1ind.report` : `counted`, ventes nulles, vocabulaire ;
- `cpmmpilot.step1` 0.1.6, via g1ind.

## Validation

- 13 tests sur fixtures. Ils couvrent :
  - la propriété de stratification : variance nulle si chaque pool est constant ;
  - l'égalité avec un calcul direct du bootstrap ;
  - chaque plancher à sa frontière, dont Kish = 2,5 exactement avec (6, 1, 1, 1, 1) et une part de 50 % exactement ;
  - la garde « sans le pool le plus fourni » ;
  - l'ordre INCONCLUSIF avant NO-GO, et STOP ;
  - K01 et les fenêtres ;
  - un bout à bout sur la règle gelée ;
  - 0.1.1 : l'égalité des bornes de l'écart avec un calcul direct, l'absence d'effet sur le mot et sur les bornes du
    primaire, et un écart centré sur 0 quand le témoin est identique au primaire.
- 40 mutants sur 40 détectés, dont 7 nouveaux sur l'écart (`MUTATIONS_g23five_v0_1_1.json`, runner `mutations_g23five_runner.py`, garde de
  référence). Un mutant ÉQUIVALENT a été écarté avant la publication (NM sur la borne basse testé par la borne
  haute : les deux sont nulles ensemble) et remplacé par « témoin = primaire ».
- Commande, cwd wt_w1, sans `-I` :
  `env -i PYTHONPATH=<chemin commun des paquets>:<plbench deps>:<cpmmgen2_pkg>:<cpmmb1_pkg>:<cpmmpilot_pkg f934bd2>:<g1ind_pkg>:<g23five_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <g23five_pkg>/g23five/tests -p no:cacheprovider -q -W error`
- Aucune donnée lue ; la fenêtre n'est pas lue.
