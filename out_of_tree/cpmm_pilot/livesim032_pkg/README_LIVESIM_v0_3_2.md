# livesim 0.3.2 — variante (B) : cpmmcost 0.3.1 + cpmmrecon 0.1 (PROJET)

RUGGER 01, 25/11/2026. Demande de R04 (12:47Z), après l'avis de R02 sur R04-15.
- **Deux variantes.**
  - (A) cpmmcost 0.3.1 seul : c'est **livesim 0.3.1** (`livesim_pkg`, commit 55466dd, MANIFEST `a5d8ae4e`). Je n'ai pas
    créé de version supplémentaire, faute de nécessité démontrée.
  - (B) cpmmcost 0.3.1 + cpmmrecon 0.1 : ce paquet (`livesim032_pkg`).
- Seule la variante retenue par le propriétaire (texte cda64700) sera auditée.
- Démonstration descriptive, comme la 0.3 : aucun essai, aucun verdict, jamais un trade du Master, jamais compté pour
  50/20. Les 7 limites de R02 sont inchangées.
- Hors ligne, 0 crédit. Les tests sont synthétiques.

## Changement par rapport à la 0.3.1

- `rebuilt(line, txs, wsol_vault, config)` : la même règle que g23run 0.1.2 et n1verdict 0.2.3.
  - Une ligne sans transaction non décodée passe inchangée.
  - Sinon, `cpmmrecon.rebuild` reçoit le coffre WSOL du pool (LIST_L, `pool_wsol_vault`), les frais de SA config et le
    côté créateur (`cpmmcost.creator_side`). Une ligne sans côté connu n'est pas tentée.
  - Chaque transaction est reconstituée en entier ou pas du tout.
- **Où** :
  - `eligible` : sur la ligne pré-départ, AVANT b₃ et G-0 ;
  - `bilan` : sur la ligne pré-départ (b₃ et N1, qui doivent égaler ceux d'ELIGIBLE.json) et sur la ligne live, AVANT
    G-0 à « now » et les positions.
- **Publication** : `reconstruction` dans ELIGIBLE.json (`pre`) et dans LIVESIM.json (`pre`, `live`). Par pool :
  transactions non décodées, reconstituées, swaps ajoutés, conservées par motif, et le motif de chaque transaction.
- `FROZEN` contrôle aussi cpmmrecon 0.1 (MANIFEST `bfeae9a3`, PASS R02).
- `SCHEMA` vaut `livesim-v0.3.2`.
- G-0 (`pool_gate`) est inchangé : une transaction qui reste non décodée fait toujours refuser le pool.

## Validation

- 28 tests : les 24 de la 0.3.1 (l'ensemble `FROZEN` contient cpmmrecon) et 4 nouveaux (`tests/test_recon.py`) :
  - **identité** : sans transaction tronquée, ELIGIBLE.json, LIVESIM.json et le rendu sont égaux à ceux de la 0.3.1
    (sha de `sim.py` `128143ec` vérifié), au champ `schema` et au champ `reconstruction` près ;
  - transactions tronquées non reconstituables : elles sont conservées et G-0 refuse le pool ; motifs comptés ;
  - lignes reconstituées (rebuild simulé) : cpmmrecon est appelé avec le coffre WSOL et les frais du pool. Les lignes
    reconstituées servent à b₃, à G-0 et aux positions, et le rapport est publié ;
  - règle `rebuilt` : ligne propre, côté créateur inconnu, ligne sans swap ; `pool_wsol_vault`.
- Mutants : 111/111 détectés (`MUTATIONS_livesim_v0_3_2.json`) : les 96 de la 0.3.1 et 15 de la reconstitution. Une
  première campagne laissait survivre `bilan_pre_not_rebuilt` (110/111) ; le test vérifie maintenant les lignes reçues
  par `simulate`.
