# Diagnostic G-0 : variante A (cpmmcost 0.3.1) et variante B (+ cpmmrecon 0.1)

RUGGER 01, 25/11/2026. Demande de R04 (13:58Z).
- DIAGNOSTIC à 0 crédit, hors réseau (`unshare -rn`). Ce n'est pas un ELIGIBLE ancré : le recalcul officiel revient à
  R03, puis l'ancrage à R02.
- Données lues : seulement les pages PRÉ-DÉPART de la démonstration (LIVESIM_20261125T113851Z, `collect/pre`,
  SHA256SUMS_PRE_PAGES `951b8479…` vérifié) et les pages PRÉ-T0 des pilotes (STEP1A2R_20261124T164909Z/pre_pages,
  sommes vérifiées). Aucune page live ni de fenêtre n'est lue, et aucun rendement n'est calculé.
- Code :
  - livesim 0.3.2 (`livesim032_pkg`, 6a98206) : `pre_pair`, `pool_config`, `pool_wsol_vault`, `rebuilt` ;
  - `cpmmcost.pool_gate` 0.3.1 (f635684c), inchangé ;
  - b₃ : `cpmmgen2.baseline_b3`.
- Fenêtre de la démonstration : les 7 jours avant t_start (1795606731), comme livesim. Pilotes : toutes les pages
  pré-T0, configuration U2.
- Commandes :
  - `diag.py <LIVESIM_dir> <LIST_L.json> <pre_pages> <U2.json>` → `DIAG_G0_AB.json` ;
  - `b3.py <LIVESIM_dir> <LIST_L.json>` → `B3_AB.json`.
