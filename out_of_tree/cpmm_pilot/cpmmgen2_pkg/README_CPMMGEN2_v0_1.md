# cpmmgen2 0.1 — protocoles exécutables de la génération 2 (T-R01-1)

RUGGER 01, 23/11/2026.
- Base : GEN-2 v0.3 ; table notée et ancrée par R02 (contrôle f4027134).
- `cpmmprereg` 0.2 et `cpmmcost` 0.3 sont importés et JAMAIS modifiés : le sha de `rule.py`, 9f46f052, est vérifié par
  un test.
- Pools synthétiques seulement : aucune donnée n'existe ni n'est lue.

**Contenu.**
- `cpmmgen2/rule.py` :
  - `drop_event`, conditions (i) et (ii) de R-CP1 ;
  - `routed_share`, `population_m1`, `decisions_g21` ;
  - `decisions_g22`, avec les attentes et leur comptage ;
  - `placebo_g22` ;
  - `fee_payer`, `buyers`, `baseline_b3`, `decisions_g23` ;
  - `trigger_count`, le comptage A1 (b) sur [T0 − 7 j ; T0), qui refuse les données ≥ T0 ;
  - `trials` (170 → 173) et `confirmation_n` (Holm, 262 ; ou 0,05/3, 221) ;
  - `bootstrap_p` et `holm` (pas descendants) ;
  - `withdrawn_if_family_negative`, la règle a21f90f3 § 2 : NO-GO au pilote pour R-CP1 ET pour B1.
- 3 fiches de gel complètes, SANS T0 : `FICHE_GEL_G2_1_v0_1.md`, `FICHE_GEL_G2_2_v0_1.md`,
  `FICHE_GEL_G2_3_v0_1.md`. Le jour du texte D, on ne remplit que les champs `<…>` : T0, D, sha de la liste U-2, m₁,
  table b₃, choix de la confirmation, sha du code.

**Choix déclaré, à valider par R02.** Pour G2-2, le délai de 3 600 s s'applique au DÉCLENCHEMENT t₀, donc aussi à
t₁ > t₀ : aucune attente ne s'ouvre pendant le délai. Sinon, ces attentes, sans issue possible, gonfleraient le
compte des « attentes vides ».

**Preuves.**
- 19 tests : réponses connues, frontière de référence à t − 600 s, plancher d'activité, seuils, attentes, nouveau
  plus bas, témoin borné, médiane des acheteurs distincts, Holm, p, élimination, imports gelés.
- **31/31 mutants détectés**, avec la garde de base.

**Commande**, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<cpmmx_pkg>:<cpmmcost_pkg>:<cpmmprereg_pkg>:<cpmmgen2_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmgen2_pkg>/cpmmgen2/tests -p no:cacheprovider -q -W error`
