# v4sim 0.2 — version d'acceptation (V4-2), RUGGER 03, 2026-11-10

- **Protocole :** V4 v2, sha256 00d9ccf97b47b16b511b80de75202da58aa1cfeec5c90ba4759793227a286533 (ancré par RUGGER 02), avec l'amendement A-4′ (v2.1, audit 08f9d440…).
- **Données utilisées :** pack de test gelé `tests/fixtures/launchlab_sol_pools` et packs SYNTHÉTIQUES uniquement. Aucune donnée réelle (P0, W1, holdout).
- **Isolation :** `v4sim` importe l'arbre gelé aff97638 en lecture seule. Il n'importe jamais `w1aux`, `v3lab` ni dayj. Le générateur `v4synth/gen_pack.py` et `tools/prep_a3.py` tournent À PART.

## Reproduire

Les commandes se lancent depuis une worktree propre de aff97638, avec CPython 3.12.3 et `RUGGER_NO_DOTENV=1`.

1. Générer les packs synthétiques, à part, avec PYTHONPATH = worktree seule. On doit retrouver les sha des MANIFEST consignés dans `MANIFEST_v4sim_020.txt` :

```bash
python -B v4synth/gen_pack.py random <packs>/random500 --pools 500 --seed 20261110
```

```bash
python -B v4synth/gen_pack.py stress <packs>/stress100 --pools 100 --seed 20261110
```

2. Lancer les tests A-1 à A-10, avec PYTHONPATH = worktree:v4sim_pkg et V4SIM_PACKS=<packs> :

```bash
python -B -m pytest -q -p no:cacheprovider -W error v4sim_pkg/v4sim/tests
```

3. Lancer A-3 par `run_trials` (environ 7 min). On le prépare d'abord à part, avec w1aux v7.3 dans le PYTHONPATH :

```bash
python -B tools/prep_a3.py <a3>
```

Puis on relance les tests avec `V4SIM_A3_DIR=<a3>` :

```bash
python -B -m pytest -q -p no:cacheprovider -W error v4sim_pkg/v4sim/tests -k a3_run_trials
```

4. Produire la sortie pour A-11, position par position, dans les quatre modes :

```bash
python -B -m v4sim.batch <packs>/stress100 out.json
```

Le sha256 attendu de la sortie est consigné dans `MANIFEST_v4sim_020.txt` (ligne `out/stress100_v020.json`).
