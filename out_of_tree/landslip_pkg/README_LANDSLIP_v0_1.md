# landslip 0.1 — mesure hors ligne de N-4 / N-5 et garde de glissement (tâche P3-b)

RUGGER 01, 22/11/2026. Le plan est dans `PLAN_MESURE_N4_N5_v0_1.md`. Rien n'a été exécuté hors des fixtures publiques.

- **`landslip.measure`** compte, sur un pack collecté :
  - les achats d'autrui, par priorité déclarée et par échec ;
  - les écarts de réaction en slots.

  La sortie ne contient que des entiers. Le holdout est refusé, et le MANIFEST ancré est exigé.
- **`landslip.guard`** est la garde de glissement fixée par R02 : achat à 2 % en primaire, 5 % en sensibilité ;
  vente sans garde en primaire, 5 % avec 3 relances en sensibilité.
- **Tests** : 9 tests sur fixtures. Mutants : 21/21 (`MUTATIONS_landslip_v0_1.json`).
- **Correction faite en route** : le décodeur gelé note `side` en minuscules (`'buy'`), alors que sa docstring dit
  BUY. Un test l'a détecté.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<landslip_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <landslip_pkg>/landslip/tests -p no:cacheprovider -q -W error`

Exécution prévue, après le PASS de R02 et une seule fois :

`python -B -m landslip.measure --pack <P0 visible> --manifest-sha256 <aca7de08… ancré> --out <NOUVEAU DIR>`
