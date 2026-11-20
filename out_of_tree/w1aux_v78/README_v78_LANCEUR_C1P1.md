# w1aux v7.8 — lanceur de l'étape ledger officielle avec C1 + P1 (option A2, paquet cloud v2.6.4)

**PRÉPARÉ, NON AUDITÉ, NON EXÉCUTÉ SUR W1** (décision du propriétaire du 20/11, point 4 : préparer l'option A2
« sans lancement ni engagement financier »).

Avant tout usage, il faut :
- le PASS de RUGGER 02 sur ce paquet ;
- l'accord EXPLICITE du propriétaire sur l'amendement C1 et sur la dépense.

## Changements

- Tous les fichiers de v7.7 sont repris à l'identique.
- Ajout de `w1aux/dayj_c1p1.py` : l'étape `ledger` de `dayj`, INCHANGÉE, exécutée dans `ledger_c1.c1_rule()` et
  `ledger_parallel.parallel_ledger(N)`. La trace est écrite HORS du dossier dayj, de sorte qu'aucun digest dayj ne
  change. Toute autre étape est refusée.
- Ajout de `w1aux/tests/test_dayj_c1p1.py`, 9 tests :
  - C1 + P1 (1 et 3 processus) donnent des fichiers identiques octet pour octet à C1 seul, avec et sans lignes
    réétiquetées (ce sont les 93 cas W1 reproduits) ;
  - sur la chaîne dayj du pack gelé, le lanceur donne le même digest et les mêmes fichiers `ledger/` que l'étape
    nue ;
  - le lanceur refuse les autres étapes et une trace existante ;
  - les modules sont restaurés après une erreur.
