# g23run 0.1 — runner G2-3 (pilote et confirmation), fonctions gelées seulement

RUGGER 01, 24/11/2026.
- Demandé par R03 (23:09Z) : la collecte reste chez R03, le code de verdict chez R01, audité par R02.
- Statut fixé par R02 (23:18:54Z, registre b1a0d629) : **code d'exécution**, audité puis ancré comme complément de la
  fiche G2-3 v0.6, AVANT toute lecture. Ce n'est pas un erratum de la fiche, puisqu'il n'ajoute aucune règle.
- Rien n'est exécuté. Aucune donnée de fenêtre n'est lue.

## Phase pilote (fiche G2-3 v0.6, graine 3807920413, g23five 0.1.1)

1. **Lignes de fenêtre SEULES** : `<racine>/<pool>/page_*.json.gz`, avec toute transaction dans [T0 ; T0 + 12 j),
   sinon STOP (`window_line`). C'est la méthode de cpmmpilot.step1.g1 pour R-CP1/B1.
2. **G-0 (R02)** : `cpmmcost.pool_gate` sur chacun des 4 pools.
   - `g0_passed` vaut True si le contrôle a été évalué sans erreur d'intégrité ; une exception donne False, puis STOP.
   - Les pools non admis sont exclus et publiés avec leur motif. Les planchers jugent ensuite (2 pools admis :
     INCONCLUSIF, pas STOP).
3. **Décisions** : `cpmmgen2.decisions_g23`, avec les b₃ GELÉS 2 / 1 / 6 / 1.
4. **Positions** : `cpmmprereg.positions` et `cpmmprereg.placebo`, avec la graine de la fiche ancrée.
   - Elles sont appelées décision par décision (`positions_each`).
   - Constat déclaré : la fonction gelée laisse remonter une CostError de son propre `exit_point`, par exemple un
     événement LP entre la décision et l'atterrissage, ce qui arrêterait tout le pool. Cette erreur devient la même
     ligne brute « non valorisée » que `positions` aurait produite.
   - Sans erreur, les lignes sont identiques à `positions` ; c'est testé.
5. **K01** : toute ligne non valorisée devient une vente nulle de SA série d'échecs (`cpmmpilot.step1.zero_sale`,
   comme `step1._converted`).
6. **Rapport** : `g23five.report`. Les lignes (ROWS.json) et le rapport (RESULT.json) sont écrits avec leur sha.
7. **ERRATUM C-169** (08b14a6b, R04-9), publié au pilote pour K = 1 et K = 2 :
   - c_j = crédits du registre g23 / 12 ;
   - σ, r, n_c et D_c* ;
   - P = ⌈1,25 × c_j × D_c*⌉ ;
   - D_c33 = min(D_c*, ⌊32 340 / (1,25 × c_j)⌋).

## Phase confirmation (fiche C-169, g23five 0.3)

- Elle n'est lancée que si le pilote est GO_PILOTE (lu dans RESULT.json du pilote).
- Fenêtre [T0_C ; T0_C + D_c j), avec D_c fourni explicitement. Seuls D_c* et D_c33 du K retenu sont acceptés, et
  D_c doit être ≥ 7.
- D_c* = min(30, max(12, ⌈n_c / r⌉)) :
  - σ_c = max(écart type d'échantillon des net_return comptés du pilote, 2,5 %) ;
  - n_c au premier pas de Holm, α₂/K (ACCEPTÉ par R02) ;
  - r = entrées du pilote / 12.
- Mêmes calculs que le pilote, plus **c5** (latence de 10 slots) et **A1** (échecs (1, 1, 1)) sur les MÊMES décisions,
  par la fonction gelée.
- Critères c1 à A1 au seuil α. INCONCLUSIF si un plancher manque.
- Le mot avant Holm est « CRITÈRES REMPLIS » ou « NON CONFIRMÉ ». `final_words` applique Holm avec N1 : CONFIRMÉ
  exige les critères ET le rejet ; une hypothèse qui manque ses critères compte p = 1.

## Limites déclarées

- **L-FIN** (R02, option (i)) : la règle est le comportement de fait du code gelé. Sans TP ni SL parmi les swaps
  collectés, la vente est valorisée sur l'état qui suit le dernier swap collecté avant T0 + D, statut entered, comme
  R-CP1.
  - Publication descriptive, par pool : le nombre de décisions dont la sortie horloge dépasse T0 + D.
  - La même règle vaut pour C-169, C-170 et N1 (N1 garde L4).
  - Un test fixe ce comportement : décision à T0 + D − 600 s, vente sur le dernier swap, statut entered.
- **Lignes de fenêtre seules** : les 600 premières secondes voient un historique d'acheteurs tronqué, et le délai de
  3 600 s repart au début de la fenêtre. R02 juge l'effet négligeable.
- **Slot T1** : inutile. L'AmmConfig est celle de U2 (slot 473309024) et n'est pas relue (R02).

## Validation

- 13 tests sur des pools synthétiques écrits en pages GTFA (couche cpmmpilot.store). Ils couvrent :
  - les bornes de fenêtre ;
  - les fonctions gelées (décisions, positions, placebo, K01, c5, A1) ;
  - la ligne non valorisée de `exit_point` ;
  - L-FIN, avec une décision à T0 + D − 600 s ;
  - G-0 : 2 pools admis donnent INCONCLUSIF, une erreur d’intégrité donne STOP ;
  - les formules de l’erratum (c_j, P, D_c33) et D_c* ;
  - les critères, Holm et le nombre de placebos ;
  - c5 et A1 calculés sur leurs propres lignes ;
  - les deux phases de bout en bout, et le CLI.
- 52 mutants sur 52 détectés (`MUTATIONS_g23run_v0_1.json`, runner `mutations_g23run_runner.py`).

## Exécution (R03, UNE fois par phase, après l'audit et l'ancrage de R02)

```
python -B -m g23run.run --phase pilot --u2 U2.json --root OUT_G23/window/collect/window --t0-slot 473309024 --sheet-sha <G2-3 v0.6> --g23-credits <crédits du registre g23> --out OUT_G23RUN
python -B -m g23run.run --phase confirmation --alpha <0,025 ou 0,0125> --u2 U2.json --root OUT_CONF/window/collect/window --t0-slot 473309024 --sheet-sha <C-169> --pilot-dir OUT_G23RUN --kept <K> --d-c <D_c* ou D_c33> --g23-credits <…> --out OUT_C169RUN
```

- Chemin Python :
  - pilote : g23five 0.1.1 (`g23five_pkg`) ;
  - confirmation : g23five 0.3 (`g23five03_pkg`).
  - Une version de g23five qui ne correspond pas à la phase est refusée.
- Un dossier de sortie existant, ou un T0 de U2 différent, est refusé.
