# cpmmpilot 0.1.5 — intégration de g1ind 0.3 (R03), HORS LIGNE uniquement

Demandes : R02 (intégration de g1ind 0.3 après son PASS) et R01 (forme de l'appel `G1.report`). Aucun appel réseau : `rpc.LiveRpc` lève toujours une erreur.

## Changements

1. `step1.g1(out, selected, *, t0_slot, sheets, g0_passed, cut_time)` appelle `g1ind.report.report` (R01, commit 31ecf7f, MANIFEST a5480537) pour chaque hypothèse. Il lui passe :
   - les lignes primaires et témoin APRÈS `zero_sale` ;
   - les 4 sensibilités, calculées sur les MÊMES décisions (`idx`), sous les clés exactes de `g1ind.report.SUPPLIED` :
     - `latency_10_slots` : `latency_slots = CC.SENSITIVITY_LATENCY_SLOTS` ;
     - `one_failure_per_tx` : `failures = CC.SENSITIVITY_FAILURES`, soit (1,1,1) ;
     - `rent_lost_vs_closed_account` : `failures = CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS)`, soit (0,0,3) ;
     - `guard_5_percent` : `buy_guard_ppm = CC.BUY_GUARD_SENSITIVITY_PPM`.
   - `cut_time`, lu dans la fiche de gel ;
   - `lines`, les timelines des pools admis (pour le drawdown).
2. Chaque série est convertie par `zero_sale` avec SES échecs. Exemple : une vente nulle de `one_failure_per_tx` vaut −100 735 000 lamports.
3. `G1_INPUTS_<H>.json` contient `{primary, placebo, sensitivities}` déjà convertis. Le fichier ne contient aucune ligne brute non valorisée.
4. Les fiches de gel portent `cut_time = t0_time + int(D × 86 400) // 2` (milieu de la fenêtre, un int).
5. cpmmpilot ne publie plus aucun chiffre ni phrase qui lui soit propre :
   - `SHEET_SENTENCE` est supprimée : la source est `g1ind.SHEET_MEANING` ;
   - `assert_closed_vocabulary` reste un second contrôle sur G1.json.

## Points à trancher par R02

- **(P1) `decision_slot` des lignes non valorisées.** La ligne non valorisée de la règle gelée (`cpmmprereg.positions`) ne porte que `pool`, `decision_index`, `unpriced` et `decision_time`. Or g1ind trie le drawdown sur `decision_slot`, ce qui provoquait une KeyError dès qu'une ligne était à vente nulle.
  - Correction : le runner copie `decision_slot = line.swaps[decision_index].slot` depuis la timeline avant `zero_sale`.
  - C'est un identifiant, jamais une valeur. Il est couvert par un test et par le mutant `decision_slot_missing`.
  - Alternative : R01 ajoute un repli dans g1ind.
- **(P2) Choix de `cut_time` au milieu de la fenêtre.** À ancrer via la fiche de gel.

## Vérifications (hors ligne, `unshare -rn`)

- 27 tests passent.
- 33 mutants sur 33 sont tués (`MUTATIONS_cpmmpilot_v0_1_5.json`). Sept mutants nouveaux : `sensitivity_failures_ignored`, `placebo_not_converted`, `sensitivities_not_passed`, `cut_time_not_passed`, `sheet_cut_not_middle`, `decision_slot_missing`, `latency_sensitivity_4_slots`.
- Répétition sur la chaîne SYNTHÉTIQUE : journal 2a6aba96…, 27,6 s.
  - 24 pools admis sur 24 ;
  - les quatre sensibilités sont toutes fournies ;
  - exercices d'arrêt inchangés.
  - Les décisions synthétiques sont sans portée : données fabriquées.
- PYTHONPATH = celui de 0.1.4, avec `g1ind03/out_of_tree/cpmm_pilot/g1ind_pkg` ajouté avant `cpmmpilot_pkg`.
