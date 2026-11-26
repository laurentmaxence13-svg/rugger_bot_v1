# g23b 0.1 — script B de la règle de recommandation du 06/12

RUGGER 01, 26/11/2026. Demandé par R04 (pré-mortem, état 23aedd3 ; note R02 9ed6de75). Les conventions ont été
déclarées à R02 avant toute lecture. Le script est hors ligne, sans crédit et ne lit aucune donnée de la fenêtre.
g23five 0.1.1 est importé sans modification.

## Ce que calcule le script

- **B** : la moyenne du brut `price_move` (avant tout coût), avec ses bornes unilatérales à 95 %.
  - Mêmes lignes que le verdict : `G1.counted` de ROWS.json.
  - Mêmes blocs : `V.blocks`, avec t0 et d_days lus dans RESULT.json.
  - Même graine, contrôlée égale à RESULT. Même nombre de tirages. Même fonction : `V.stratified_bounds`.
  - Brut d'une ligne : son `price_move` si elle est entrée ; 0 pour un refus de garde ou une vente nulle K01 (toute
    la perte est alors comptée en coût). Le nombre de lignes de chaque statut est publié.
- **Contrôle** : l'outil applique d'abord le même calcul au net. Il doit retrouver exactement `lower/upper_bound_95`
  de RESULT.json, sinon il s'arrête (STOP).
- **Coût** : la moyenne de (brut − net), avec la décomposition gelée moyenne des positions entrées.
- **P4**, sensibilité descriptive qui n'entre jamais dans le mot :
  - bootstrap par jour calendaire commun à tous les pools, avec la même graine ;
  - calculé pour le net et pour B.

## Commande

```
python -B -m g23b.b --rows ROWS.json --result RESULT.json --sheet-sha <fiche> --out B.json
```

## Vérification

- Tests : 8/8 avec `-W error`. Ils couvrent une réécriture indépendante des deux bootstraps, et un passage de bout en
  bout sur les positions gelées de cpmmprereg.
- Mutants : 23/23 (`MUTATIONS_g23b_v0_1.json`).
- Jamais une transaction du Master, jamais compté pour 50/20, aucun verdict propre.
