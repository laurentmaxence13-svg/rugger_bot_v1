# cpmmpilot 0.2.8.1 — autorisation G2-3 du propriétaire (R03), HORS LIGNE

Cette version suit la 0.2.8 (MANIFEST 7251d4fe, commit 8c4a022). Elle n'ajoute **que** l'autorisation. La logique de collecte et K01 sont inchangés : `budget.py` et `step1.py` sont identiques à 0.2.8.

## Changements depuis 0.2.8

- `rpc.AUTHORIZED_TEXT_SHA256` reçoit le texte G2-3 du propriétaire :
  - écrit dans la session de R03, le 24/11 à 22:29:08Z (événement b7b839b2) ;
  - vérifié à la source et ancré par R02 (a5e8f770) ;
  - sha 3d6999ec, 1 257 octets, sans saut de ligne final.
- `AUTORISATION_G23.txt` est livré dans le paquet.
- `tests` : le test d'autorisation couvre les 4 textes, et vérifie la taille et la clause « au plus 33 000 crédits ».
- `mutations_cpmmpilot_runner.py` : un nouveau mutant, `g23_text_not_authorized` ; schéma `cpmmpilot-mutations-v0.2.8.1`.

## Vérifications (hors ligne, `unshare -rn`)

- Tests : 56 sur 56.
- Mutants : garde de base PASS ; 79 sur 79 tués (`MUTATIONS_cpmmpilot_v0_2_8_1.json`).

## Driver associé

`out_of_tree/cpmmpilot_run/g23_collect.py`.
- `G23_TEXT_SHA256 = 3d6999ec`.
- Tests : 20 sur 20. Mutants : 32 sur 32.
- **NON exécuté** : refus avant le 06/12/2026 10:21:26Z, et collecte seulement après le GO de R02.
