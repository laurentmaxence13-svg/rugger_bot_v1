# cpmmpilot 0.2.9.1 — autorisation « GO RUGGER » du propriétaire (R03), HORS LIGNE

Cette version suit la 0.2.9 (MANIFEST f6027a28, commit a5a9942). Elle n'ajoute **que** l'autorisation. `budget.py`, `step1.py`, `store.py` et `u2.py` sont identiques à 0.2.9.

## Changements depuis 0.2.9

- `rpc.AUTHORIZED_TEXT_SHA256` reçoit le texte « GO RUGGER » du propriétaire :
  - écrit dans la session de R03, le 25/11 à 10:35:25Z (événement e73505b1, client ios) ;
  - vérifié à la source et ancré par R02 (10:37Z) ;
  - sha eba73e3f, 1 261 octets, sans saut de ligne final.
- `AUTORISATION_LIVESIM_GO.txt` est livré dans le paquet.
- `tests` : le test d'autorisation couvre les 5 textes, et vérifie la taille et la clause « dépassement du quota gratuit ».
- `mutations_cpmmpilot_runner.py` : un nouveau mutant, `livesim_text_not_authorized` ; le motif de `g23_text_not_authorized` est adapté ; schéma `cpmmpilot-mutations-v0.2.9.1`.

## Portée de ce texte (R02, 10:37Z)

Il ne couvre que la démonstration livesim, avec ces bornes :
- P = 16 500 crédits, arrêt dur à 16 170 ;
- univers 5c4fefb6, collecté par blocs de 2 h ;
- au moins 3 pools éligibles ;
- une seule relecture d'une réponse tronquée.

Il ne couvre ni la collecte de confirmation, ni aucune autre collecte, ni une hausse de P. Le pilote du 06/12 utilise l'extraction du commit 7ce025c.

## Vérifications (hors ligne, `unshare -rn`)

- Tests : 57 sur 57.
- Mutants : garde de base PASS ; 82 sur 82 tués (`MUTATIONS_cpmmpilot_v0_2_9_1.json`).

## Driver associé

`out_of_tree/cpmmpilot_run/livesim_collect.py` :
- `LIVESIM_TEXT_SHA256 = eba73e3f` ;
- tests : 27 sur 27 ; mutants : 40 sur 40.
