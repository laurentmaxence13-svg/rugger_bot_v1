# cpmmb1 0.1 — B1, miroir momentum de R-CP1, figé en code sur sa fiche séparée

RUGGER 01, 23/11/2026.
- La fiche est `PREENREGISTREMENT_CPMM_B1_v0_1.md`.
- `cpmmprereg` 0.2 est importé et jamais modifié : le sha de son `rule.py`, 9f46f052, est vérifié par un test.

Ce que fait le paquet :
- **`decisions`** : la règle R-CP1 avec le seul signe inversé, hausse ≥ +3 % au lieu d'une chute ≤ −3 %. Mêmes
  référence, activité et délai ; causale.
- **`trigger_count`** : comptage PROPRE, refus des données ≥ T0.
- **`trials`** : 169 → 170, puis plafond atteint.
- **Repris de R-CP1 à l'identique** : sorties, coûts (cpmmcost 0.3, garde active), témoin, scission, puissance (155,
  221) et confirmation.

Preuves : 7 tests, sur des pools synthétiques seulement. 13/13 mutants détectés, avec la garde de base.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<cpmmx_pkg>:<cpmmcost_pkg>:<cpmmprereg_pkg>:<cpmmb1_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmb1_pkg>/cpmmb1/tests -p no:cacheprovider -q -W error`
