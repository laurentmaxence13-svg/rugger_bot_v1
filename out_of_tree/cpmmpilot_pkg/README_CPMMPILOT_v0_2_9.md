# cpmmpilot 0.2.9 — stage `livesim` pour la simulation PAPER en temps réel (R03), HORS LIGNE

Cette version suit la 0.2.8.1 (MANIFEST ba38eba3) et répond à la décision R04-10 (simulation PAPER sur un univers distinct, directive du propriétaire du 25/11 à 08:39:28Z).

## Changements depuis 0.2.8.1

- `budget` : un tuple `STAGES = ('step0', 'u2', 'step1', 't2', 'g23', 'livesim')` remplace la liste écrite en dur. Le stage `livesim` a son propre registre, et son plafond est le P du texte du propriétaire, passé en `max_credits`.
- `tests` : `test_livesim_stage_0_2_9`.
- `mutations_cpmmpilot_runner.py` : `livesim_stage_missing` et `stage_not_checked` sont ajoutés, et `g23_stage_missing` est adapté à `STAGES` ; schéma `cpmmpilot-mutations-v0.2.9`.
- **Inchangés** : `rpc.py` (avec `AUTHORIZED_TEXT_SHA256` identique à 0.2.8.1), `step1.py`, `store.py`, `u2.py`. La logique de collecte et K01 ne changent pas.

## Vérifications (hors ligne, `unshare -rn`)

- Tests : 57 sur 57.
- Mutants : garde de base PASS ; 81 sur 81 tués (`MUTATIONS_cpmmpilot_v0_2_9.json`).

## Driver associé

`out_of_tree/cpmmpilot_run/livesim_collect.py` : `LIVESIM_TEXT_SHA256 = None`, **NON exécuté**. Le texte du propriétaire pour la simulation sera ajouté dans une 0.2.9.1 qui ne touche qu'à l'autorisation.
