# L1 — Interpréteur de référence et bras MASTER en double

Décision du propriétaire, validée le 2026-11-07 à 16:36 UTC et transmise par RUGGER 04 :

> RUGGER 01 : figer Python 3.12 pour les résultats reproductibles. Conserver le code historique
> du bras MASTER, mais exclure son doublon du comparatif économique tant qu'aucune politique
> indépendante n'existe. Aucun résultat historique ne doit être modifié.

Mise en œuvre sur la branche locale `claude/r01-py312-arm-dedup`, issue de `e21c32c` (correctifs P0 audités PASS par RUGGER 02).

## 1. Python 3.12, interpréteur de référence

- `REFERENCE_PYTHON = (3, 12)` (`bot/p4/historical_research_replay.py`). Les empreintes de bundle reproductibles sont celles de Python 3.12, et les quatre bundles enregistrés y sont reproduits à l'octet près.
- `tools/historical_research_replay.py` affiche toujours l'interpréteur utilisé et s'il s'agit de la référence. Il refuse d'écrire un bundle (`--out`) sous une autre version, sauf avec `--allow-non-reference-python` : le résultat est alors explicitement marqué non reproductible (`reproducible=False`). La simple consultation, sans fichier écrit, reste possible sous toute version.
- Les deux suites CI hors ligne utilisent Python 3.12 (`offline-tests.yml`, auparavant en 3.13, et `rugger-isolated-ci.yml`, auparavant en 3.11). Les déclencheurs ne changent pas. Seuls les repères de texte des tests de mutation du garde-fou suivent le nouveau nom d'étape.
- Origine : l'écart O3. Sous Python 3.11, la somme des flottants n'est pas compensée, et `top_holder_share` diffère au dernier bit.

## 2. Le bras MASTER en double sort du comparatif économique

- Le code historique et le contenu du bundle ne changent pas : les deux bras `master` et `reference` y restent, et toutes les empreintes sont inchangées.
- `economic_comparison(bundle)` ne retient que les bras distincts. Un bras dont toutes les intentions journalisées et toutes les lignes de trade sont égales à celles du bras `reference` est listé dans `excluded`, avec la règle `DUPLICATE_ARM_RULE`. Dès qu'un bras diffère, il est comparé.
- L'outil en ligne de commande n'affiche plus que les bras comparés. Il nomme le bras exclu : `[master] excluded from the economic comparison: duplicate of [reference] (kept in the bundle)`.
- Tant qu'aucune politique MASTER indépendante n'existe, le comparatif ne contient qu'un seul bras, celui du scoreur.

## 3. Tests

`tests/test_l1_py312_arm_dedup.py` vérifie :
- l'exclusion du doublon sur trois variantes ;
- que le bundle n'est pas modifié et que son empreinte par défaut est inchangée ;
- qu'un bras différent, par son trade ou par son intention, entre bien dans la comparaison ;
- l'affichage en ligne de commande ;
- le refus d'écrire sous Python 3.11 ou 3.13, avec et sans dérogation, et l'écriture sous 3.12 ;
- la version figée dans les deux suites CI.
