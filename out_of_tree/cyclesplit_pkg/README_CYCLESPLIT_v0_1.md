# cyclesplit 0.1 — réconciliation 191 / 128 des cycles MASTER clos de W1 (demande de R02, 22/11)

C'est un outil en lecture seule et hors ligne. Il n'est **pas exécuté** avant le PASS de R02.

## Entrée

- Le fichier `run/bundles/L1.json.gz`. Son sha256 (3409bf9d…) est vérifié AVANT toute lecture.
- `--s0`, qui vaut 467 275 745 pour W1. C'est le s0 de la chaîne dayj et de la chaîne exploratoire w1x (explore.py:148).

## Règles, reprises du code sans les réimplémenter

- **Bornes.** `w1_collection.bounds(s0)['evaluation']` (w1_collection.py:31-43 ; fenêtre décrite l. 9-11). Pour W1,
  la plage est [467 678 545 ; 469 291 345) (testé).
- **Population.** On reprend la règle de w1x 0.1.5, reading.py:146 :
  `evaluation_min <= pool['creation_slot'] < evaluation_max`.
- **Cycle clos.** Il faut `outcome == 'closed'` (reading.py:121-122), lu sur la ligne master du bundle. C'est la ligne
  que la lecture compare au ledger (reading.py:155-163).
- **Contrôle du total.** Avant · dedans · après = le total du code gelé, `totals.master.closed_cycles`
  (historical_research_replay.py:767). Sinon l'outil lève une erreur, sans aucune sortie.

## Sortie

- La provenance : schéma, sha du fichier, s0, plage, règle.
- Exactement 4 entiers : `master_closed_before`, `master_closed_inside`, `master_closed_after`,
  `master_closed_total`.
- Les clés suivent une liste blanche. Il n'y a ni P&L, ni pool, ni autre chiffre (testé).

## Commande (R03, après le PASS de R02)

```
cd <arbre gelé aff97638>
env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=<arbre gelé>:<cyclesplit_pkg> \
    python3.12 -B -m cyclesplit.split --bundle <run/bundles/L1.json.gz> \
    --bundle-sha256 3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657 --s0 467275745
```

Valeurs attendues (diagnostic de R02) : un total de 191, dont 128 dedans. On attend aussi 63 avant : ce sont les pools
créés pendant l'échauffement [467 275 745 ; 467 678 545).

## Preuves

- **Tests.** 4 tests sous `-W error`, hors réseau.
  - Bornes exactes : min dedans, max après, min − 1 avant.
  - Seul le bras master est compté.
  - Refus de quatre cas : sha faux, total qui ne s'additionne pas, slot de création absent, et l'écriture du bundle par
    `w1_run._write_json` lui-même.
  - Test sur un VRAI bundle L1 gelé des fixtures, observateur forcé à ENTER, avec trois s0 : tout avant, tout dedans,
    tout après.
- **Mutations.** 8 sur 8 détectées (MUTATIONS_cyclesplit_v0_1.json) :
  - bornes inclusives à tort, une de chaque côté ;
  - mauvais bras ;
  - tous les résultats comptés ;
  - sha non vérifié ;
  - total gelé non vérifié ;
  - slot manquant accepté ;
  - bornes non gelées.
- **Mémoire.** Le bundle W1 fait 395 Mo de JSON, chargé en entier comme le fait la lecture. Prévoir quelques Go.
