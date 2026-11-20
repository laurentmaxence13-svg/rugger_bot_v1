# w1migr 0.1 — liste des pools W1 migrés (population du pilote CPMM et de HW1-M2)

Lecture admise avant le verdict officiel W1 par RUGGER 02 (f5ad8d36). C'est un fait de population, sans aucune
valeur, et il ne compte pas dans N. **Écrit, non exécuté** : R02 audite le script, puis R03 l'exécute, puis R02
ancre la liste AVANT toute requête CPMM.

## Ce que fait le script

- **Entrée** : le bundle L1, avec son sha256 (celui que le ledger ancré a enregistré).
- **Champs lus**, seuls autorisés (vérifié par un espion dans les tests) : l'identifiant du pool ; le slot et
  l'indice de transaction de la frontière de migration ; l'identifiant et les motifs des pools exclus.
- **Règle d'appartenance** (brouillon de collecte v0.3) : le slot de la frontière de migration est dans
  [467 678 395 ; 469 291 345).
- **Pools migrés sans slot** : ce sont les pools exclus du rejeu seulement parce que des événements suivent leur
  frontière. Ils sont listés à part, comptés, et jamais sélectionnés.
- **Sélection du pilote**, fixée avant tout regard : les 10 premiers membres, triés par slot de frontière, puis
  indice de transaction, puis pool.
- **Sortie** : `MIGRATION_LIST.json`, qui contient la règle, les comptes, les membres (pool, slot, indice), le
  pilote et les migrés sans slot. Elle ne contient aucune valeur, aucun bras et aucune progression.

## Commande (R03, après le PASS de R02)

    PYTHONPATH=<w1_migration_list> python -B -m w1migr.migration_list --l1-bundle <run/bundles/L1.json.gz> \
        --bundle-sha256 <sha enregistré par le ledger> --out <OUT>

## Preuves

- 4 tests sous CPython 3.12.3 avec `-W error`.
- Défauts volontaires : 9 détectés sur 9 (`MUTATIONS_w1migr_v0_1.json`).
