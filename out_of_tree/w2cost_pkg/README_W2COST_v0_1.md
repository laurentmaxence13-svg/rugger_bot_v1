# w2cost 0.1 — proposition de moteur W2 « coûts complets » (tâche P4) — NON ADOPTÉE

RUGGER 01, 22/11/2026. L'adoption est une décision du propriétaire. La note est
`NOTE_P4_MOTEUR_W2_COUTS_COMPLETS_v0_1.md`.

- `PARAMETERS` : le paramétrage unique déclaré (sha c5e99089…), avec `adopted: False`.
- `n_min` : la formule du Dossier B § 6.1 (414). `n_min_full_cost` : l'effet est réduit du surcoût, avec le plancher
  protégé de 414.
- `complete_or_excluded` : rtgate 0.2, COMPLETE exigé.
- `fixture_impact` : gelé contre proposition, sur les 3 pools publics seulement (`estimate_for_w2: False`).
- 5 tests ; 10/10 mutants (`MUTATIONS_w2cost_v0_1.json`). Le lanceur vérifie d'abord que la base passe.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<closedacct_pkg>:<landslip_pkg>:<papercost_pkg>:<rtgate_pkg>:<mevsens_pkg>:<w2cost_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <w2cost_pkg>/w2cost/tests -p no:cacheprovider -q -W error`
