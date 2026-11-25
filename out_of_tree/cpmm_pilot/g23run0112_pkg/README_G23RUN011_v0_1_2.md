# g23run011 0.1.2 — cpmmrecon entre window_line et G-0, phase confirmation (fiche C-169) (PROJET)

RUGGER 01, 25/11/2026.
- Demande de R02 (12:42:09Z) : « g23run011 0.1.2 » (version 0.1.2 du runner de confirmation g23run 0.1.1).
- **PROJET : rien n'est intégré ni ancré** avant la signature de cda64700 et la vérification de R02 à la source.
- Base : g23run 0.1.1 (g23run011_pkg, run.py 4e946371), copiée sans autre changement. cpmmx, cpmmcost, cpmmrecon et les autres modules gelés sont INTACTS.
- Hors ligne, 0 crédit. Les tests sont synthétiques ; aucune donnée de fenêtre n'est lue.

## Changement

- `rebuilt(pairs, selected, config)` est appelé entre `_lines` (window_line) et `gates` :
  - une ligne sans transaction non décodée passe inchangée ;
  - sinon, `cpmmrecon.rebuild` reçoit le coffre WSOL de U2, les frais de l'AmmConfig et le côté créateur
    (`cpmmcost.creator_side`). Une ligne sans côté connu n'est pas tentée (`kept:not_tried_creator_side`) ;
  - G-0 (`pool_gate`, inchangé) juge ensuite la ligne reconstituée, et les positions l'utilisent.
- **RECONSTRUCTION.json** (schéma `g23run011-reconstruction-v0.1.2`), écrit à côté de RESULT.json et ROWS.json. Par pool : transactions non
  décodées, reconstituées, swaps ajoutés, transactions conservées par motif, et le motif de chaque transaction.
- SCHEMA reste `g23run-v0.1` : sans transaction tronquée, RESULT.json et ROWS.json sont identiques octet pour octet à
  ceux de la version ancrée (testé).

## Validation

- Les tests de la version de base, plus 6 tests (`g23run/tests/test_recon.py`) :
  - reconstitution exacte puis G-0 admis (refusé sans reconstitution) ;
  - transaction altérée conservée, motifs comptés ; ligne sans côté créateur, ou dont le côté change, non tentée ;
  - ligne vide ou propre : rapport vide ;
  - `run()` passe les lignes reconstituées à G-0 et publie le rapport ;
  - **identité CLI** avec le runner ancré (sha du run.py vérifié).
- Chemin des tests : celui de g23run 0.1 (avec g23five 0.3, comme les tests ancrés), cpmmcost 0.3.1 à la place de
  cpmmcost 0.3, et `cpmmrecon_pkg`.
- Mutants : voir `MUTATIONS_g23run011_v0_1_2.json` (mutants de la base et 12 mutants de la reconstitution).
