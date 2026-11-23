# cpmmprereg 0.2 — R-CP1 figé en code, avec l'amendement A1 de R02

RUGGER 01, 23/11/2026. La fiche est `PREENREGISTREMENT_CPMM_RCP1_v0_2.md`. Base : 0.1 (7e60f0b, PASS R02) ; la
règle, les sorties, le témoin, la scission, la puissance du pilote, les essais et les arrêts sont inchangés. Les tests
portent sur des pools synthétiques seulement : aucune donnée.

## Ajouts de A1

- **(c) Garde ACTIVE.** `positions` appelle cpmmcost 0.3 avec la garde de 20 000 ppm par défaut. Les sensibilités
  sont déclarées :
  - garde à 50 000 ppm ;
  - `failures=Failures(1, 1, 0)` ;
  - `latency_slots=10`, qui décale aussi le point de sortie (TP/SL et horloge) dans `exit_point`.
  Chaque ligne porte `decision_time`, qui sert à la scission.
- **(b) Nombre attendu d'entrées.**
  - `trigger_count` compte les seuls DÉCLENCHEURS de R-CP1 sur [T0 − 7 j ; T0), pour chaque pool de U-2.
  - Une donnée à T0 ou après est REFUSÉE, jamais filtrée, et aucun résultat n'est calculé (`outcomes_computed=False`).
  - `expected_entries` = ⌊ déclencheurs × D / 7 ⌋ ; cette mise à l'échelle est **à valider par R02**.
  - Ensuite `power_stop`, inchangé.
- **(a) Confirmation.**
  - `sigma_of_pilot` : écart-type des nets valorisés du pilote.
  - `confirmation_n` : σ_c = max(σ du pilote, 2,5 %), α = 0,05/3, ce qui donne 221 à 2,5 %.
  - `confirmation_verdict` donne CONFIRMÉ, NON CONFIRMÉ ou INCONCLUSIF, à partir de :
    - c1 à c5 du Dossier B, adaptés aux grappes par pool ;
    - net > 0 avec 1 échec ;
    - net > 0 à 10 slots (dans c5) ;
    - différence ponctuelle au témoin > 0.
  - n = les entrées seulement ; les refus de la garde sont exclus.
  - `counts_for_operational_master` vaut toujours False.

## Points déclarés, à valider par R02

1. La mise à l'échelle D/7 de l'attendu, et le fait que l'attendu soit optimiste, puisque les refus de la garde sont
   inconnus sans résultat.
2. c4 : une position non valorisée (par exemple des données qui s'arrêtent avant la sortie) fait échouer c4. Elle
   n'est pas écartée.
3. c5 reprend la section 3 du Dossier B : 10 slots ET sans les 5 meilleures.
4. c2 : borne basse de (moyenne R-CP1 − moyenne témoin) sur les mêmes tirages de pools.

## Preuves

- 21 tests, dont 11 nouveaux.
- **43/43 mutants détectés** (27 nouveaux), avec la garde de base (`MUTATIONS_cpmmprereg_v0_2.json`).

## Commande

Depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<cpmmx_pkg>:<cpmmcost_pkg>:<cpmmprereg_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmprereg_pkg>/cpmmprereg/tests -p no:cacheprovider -q -W error`
