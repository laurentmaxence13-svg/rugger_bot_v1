# cpmmpilot 0.2.8 — stage `g23` pour la collecte de la fenêtre G2-3 (R03), HORS LIGNE

Cette version fait suite à la décision R04-1 (pilote G2-3, 4 pools, D = 12) et à la note de R02 du 24/11 à 20:42Z (stage dédié, sans réutiliser `step1`).

## Changements depuis 0.2.7

- `budget` : `G23_CAP = 32 340`, soit 98 % de 33 000, et un stage `g23` accepté par `PilotBudget`, avec son propre registre. Le stage `step1` et son arrêt dur à 49 000 (texte C) ne changent pas.
- `tests` : `test_g23_stage_and_cap_0_2_8`. Il vérifie le plafond, le refus au-delà de ce plafond et le refus d'un registre d'un autre stage.
- `mutations_cpmmpilot_runner.py` : deux nouveaux mutants, `g23_cap_33000` et `g23_stage_missing`, et le schéma `cpmmpilot-mutations-v0.2.8`.
- **Inchangés** : `rpc.py`, avec `AUTHORIZED_TEXT_SHA256` identique à 0.2.7 (e25389f0, b75e657a, cae25a3c), et `step1.py` (a53f0b98).
- Les valeurs K01 (`step1.zero_sale_net_lamports`) restent les mêmes : −100 420 000 (FROZEN), −100 735 000 (SENSITIVITY) et −102 669 280 (loyer perdu).

## Ce que cette version NE permet PAS

Aucun des trois textes ancrés ne couvre la collecte G2-3. Avec 0.2.8, `LiveRpc` ne peut donc s'ouvrir qu'avec un texte déjà ancré, et le driver refuse ces trois textes. Le texte G2-3 du propriétaire sera ajouté dans une **0.2.8.1**, une fois :
1. collé dans la session de R03 ;
2. ancré par R02.

La 0.2.8.1 ne touchera qu'à `AUTHORIZED_TEXT_SHA256` et au fichier du texte ; R02 en vérifiera le diff.

## Vérifications (hors ligne, `unshare -rn`)

- Tests : 56 sur 56.
- Mutants : garde de base PASS ; 78 mutants sur 78 tués (`MUTATIONS_cpmmpilot_v0_2_8.json`).

## Driver associé

`out_of_tree/cpmmpilot_run/g23_collect.py`, sha c6b86965.
- stage `g23` ; garde qui refuse si `B.G23_CAP` ≠ 32 340 ;
- liste des 4 pools figée par sha (812d311b) ;
- fenêtre [T0 ; T0 + 12 j), refusée avant sa clôture ;
- `G23_TEXT_SHA256 = None` tant que le texte n'est pas ancré ;
- une relecture au plus par réponse tronquée ;
- en cas de STOP, le partiel est publié.
- Tests : 20 sur 20. Mutants : 31 sur 31.
- **NON exécuté.**
