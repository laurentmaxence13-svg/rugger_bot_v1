# latelab 0.4 — correction d'écriture (R02 0d0ffd06), rien d'autre

**Le défaut (0.3).**
- `statelab.exits.run_rule` donne `reason=None` pour une position migrée.
- `summary()` indexait `exit_reasons` par cette raison. La clé `None`, mêlée à des chaînes, empêchait
  `json.dumps(sort_keys=True)` d'écrire `LATELAB.json`.
- Le calcul de R03 s'est terminé sans rien écrire. Rien n'a été lu.

**Correction (0.4).** La clé est désormais `'migrated' if o['migrated'] else o['reason']`, comme statelab l. 231.
Aucune autre modification de calcul, de grille, de règle ni de sortie. `SCHEMA` reste `latelab-v0.3`, et l'usage est
celui de `README_LATELAB_v0_3.md`.

**Preuves.**
- Tests : 11 réussites. C'est la suite de la 0.3, plus un test avec deux positions migrées : l'écriture réussit et
  `exit_reasons` vaut `{'clock': 1, 'migrated': 2}`.
- Défauts volontaires : 15 sur 15 détectés. Ce sont les 14 défauts de la 0.3, plus `migrated_key_none`, qui remet
  `o['reason']` (`MUTATIONS_latelab_v0_4.json`).
- Comptage, selon R02 : la relance n'est pas un second regard ; le compteur reste à N + 2 pour la découverte.
  R03 relance dans un dossier NEUF, après le PASS de R02.
