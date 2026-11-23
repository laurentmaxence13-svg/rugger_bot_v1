# cpmmprereg 0.1 — préenregistrement de R-CP1 figé en code (tâche CPMM-2)

RUGGER 01, 23/11/2026. La fiche est `PREENREGISTREMENT_CPMM_RCP1_v0_1.md`. Les tests portent sur des pools synthétiques
seulement : aucune donnée.

- **`decisions`** : R-CP1 (chute ≥ 3 % face au dernier swap à 600 s, au moins 20 swaps sur 600 s, délai de 3 600 s).
  La règle est causale.
- **`exit_point`** : TP de +2 % ou SL de −2 % de la mise, sur la valeur de vente exacte, avec atterrissage +4 slots ;
  sinon horloge à 30 min plus la latence gelée.
- **`positions`** : le net complet par cpmmcost 0.2.
- **`placebo`** : le témoin apparié, déterministe, avec la contrainte (iii).
- **`halves`** : la scission en deux moitiés de temps.
- **Puissance** (`n_required`) : 155 au pilote (α 0,05), 221 en confirmation (α 0,05/3), avec σ = 2,5 % déclaré et
  δ = +0,5 % net.
- **`trials`** : 168 → 169, plafond 170.
- **Arrêts** (`eligibility_stop`, `power_stop`) : moins de 20 pools → STOP INCONCLUSIF sans essai ; moins de 30
  entrées attendues → décision du propriétaire.
- **Tests et mutants** : 10 tests ; mutants 16/16 (`MUTATIONS_cpmmprereg_v0_1.json`), avec la garde de base.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<cpmmx_pkg>:<cpmmcost_pkg>:<cpmmprereg_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmprereg_pkg>/cpmmprereg/tests -p no:cacheprovider -q -W error`
