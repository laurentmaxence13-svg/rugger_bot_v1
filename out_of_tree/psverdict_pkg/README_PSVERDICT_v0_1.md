# psverdict 0.1 — lecture en une passe de la sortie paperstream 0.4 sur W1

Préparé pour le run W1 de R03, attendu vers 01:20Z (directive R04 du 21/11 à 18:35Z, point 3).

- **Ce que l'outil ne fait pas.** Il lit seulement, hors ligne, avec la bibliothèque standard. Il n'importe pas
  paperstream et ne modifie aucun fichier.
- **Ce que la sortie contient.** Uniquement des comptes, aucun P&L.
- **Ce que le verdict veut dire.** C'est un contrôle d'identité du moteur en flux. Ce n'est ni un essai (N reste à 168),
  ni un trade réel du MASTER. Il ne compte jamais pour les seuils de 50 cycles et 20 créateurs.

## Commande (R03 ou R02, après le run)

```
PYTHONPATH=<psverdict_pkg> python -B -m psverdict.verdict --run <RUN> --printed-sha256 <sha affiché par le run> \
       --rc <code retour du run> --manifest-sha256 <ancré> --series-file-sha256 <7458f615… complet> \
       --expect-master-closed <ancré par R02, 128 attendu>
```

## Les trois verdicts

**IDENTITY_PROVEN** : tous les contrôles passent.

**INVALID_RUN** : au moins un contrôle d'intégrité ou d'entrée échoue :
- le sha affiché ;
- le code retour ;
- le schéma 0.4 ;
- la catégorie ;
- le réseau ;
- `trials_added` ;
- `identity_check_not_a_trial` ;
- `memory_override` faux ;
- le pare-feu ;
- le MANIFEST ou la série ;
- les trois sha attendus donnés au run, qui doivent être exactement les ancres W1 (3409bf9d…, 9eb43426…, c7556f14…) ;
- l'index de checkpoint : son sha, une entrée par pool, et `mode=stream`.

**IDENTITY_FAILED** : le run est valide, mais l'un des contrôles d'identité échoue :
- fichier, JSON ou champ : la correspondance ET le sha calculé égal à l'ancre ;
- cohérence du champ interne ;
- `reconciled_cycles = closed_cycles_all_arms` ;
- `counts.master.closed_cycles` égal à l'ancre.

Chaque contrôle en échec est nommé dans `failed`.

## Preuves

- **Tests.** 20 réussis sous `-W error`, hors réseau. Ils portent sur une VRAIE sortie paperstream 0.4, produite sur les
  fixtures avec checkpoint et les trois sha attendus.
- **Ancres W1.** Les ancres W1 font échouer ce run de fixtures, comme prévu.
- **Altérations.** Chaque altération testée est nommée.
- **Mutations.** 20 sur 20 détectées (MUTATIONS_psverdict_v0_1.json).
