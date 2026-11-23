# plbench 0.2 — banc PAPER_LIVE avec le verdict économique gelé de R02 (§ 3.2)

RUGGER 01, 23/11/2026. Étiquette **SIMULATED_FEED**, jamais PAPER_LIVE. Aucune connexion, aucun envoi, aucune signature.
Base : plbench 0.1 (f6288ce, PASS R02), dont tout le reste est inchangé.

## Ce qui change

Le banc applique maintenant les règles de lecture gelées par R02
(`REGLES_LECTURE_GELEES_CPMM_PAPERLIVE_R02_v1_0.md`, sha 2792655a…, § 3.2), fonction `economic_verdict` :
- **Population** : les seuls cycles qui portent le `cycle_receipt` de R02. Un cycle d'un pool INCOMPLET compte à
  valeur 0, comme en 0.1 (S-1).
- **NÉGATIF** si la borne HAUTE unilatérale à 95 % du net moyen est < 0.
- **POSITIF EN PAPER** si la borne BASSE unilatérale à 95 % est > 0, ET au moins 50 cycles qualifiés, ET au moins
  20 créateurs, ET un net moyen > 0 avec 1 échec par transaction.
- **INCONCLUSIF** sinon.
- Bootstrap par grappes de créateurs (un pool sans créateur est sa propre grappe), 10 000 tirages, graine
  `int(sha de la fiche de gel[:8], 16)`. Le calcul de borne est celui, gelé, de `w2arms.ce.lower_bound`.
- Le net « 1 échec » vient d'une troisième passe du même flux, avec 1 échec à l'achat et à la vente.

**Vocabulaire fermé** : toute sortie du banc est contrôlée ; « rentable », « profitable » et « gagnant » y lèvent une
erreur (R02 R-0.1 / R-0.2).

Sur les fixtures, aucun cycle ne porte de `cycle_receipt` : le verdict est toujours INCONCLUSIF, population 0. Les
cas NÉGATIF, POSITIF et limites ne sont montrés que sur des cycles synthétiques.

## Preuves

- 24 tests (dont `test_economic.py`) :
  - négatif clair ;
  - chacune des 4 conditions du positif retirée une à une ;
  - moyenne légèrement négative avec borne haute ≥ 0 : INCONCLUSIF ;
  - filtre des reçus ;
  - égalité avec un bootstrap recalculé à la main ;
  - vocabulaire fermé.
- 26/26 mutants détectés, dont 9 nouveaux sur le verdict, avec la garde de base (la copie non mutée doit passer
  d'abord).

## Commande

Depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<closedacct_pkg>:<landslip_pkg>:<papercost_pkg>:<rtgate_pkg>:<latelab_pkg>:<cdgate_pkg>:<w2arms_pkg>:<mevsens_pkg>:<plbench_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <plbench_pkg>/plbench/tests -p no:cacheprovider -q -W error`
