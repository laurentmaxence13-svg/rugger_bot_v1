# poolprof 0.1 — cProfile du rejeu gelé L1 d'UN pool W1 (demande de R02, 22:02Z), à auditer AVANT toute exécution

RUGGER 01, 22/11/2026.

- **Entrée** : le pool de RANG k par taille gz dans le MANIFEST (1 = le plus gros ; égalités départagées par le nom
  de fichier). Le rang est calculé par le script ; le sha de l'archive est vérifié contre le MANIFEST avant toute
  lecture. Le MANIFEST est vérifié AVANT la série (testé).
- **Rejeu** : l'appel gelé de `run_replay` pour ce seul pool, soit `replay_pool` avec `l1_params()`, la série ancrée,
  `collection_window`, `L1_EXIT`, `CreatorHistory.from_archives` sur TOUT le pack et le placebo.
  - Moteur EN LOT gelé : ni `--fast-analyser`, ni memo, ni paperstream.
  - La `CreatorHistory` est construite avant le profil et n'est pas profilée. Les archives sont lues une à une
    (`w1aux.lazy`).
- **Sortie `POOLPROF.json`** : la table cProfile seulement (fonction en `fichier:ligne(nom)`, avec le nom de base du
  fichier ; ncalls, tottime, cumtime), le top 30 par cumtime et le temps total. AUCUN résultat, identifiant de pool
  ni P&L.
- **Tests** : 9 sur fixtures.
  - L'enregistrement rejoué est égal à celui du `run_replay` gelé, pour les 3 rangs.
  - Même chose avec une fenêtre de collecte déclarée dans le MANIFEST.
  - La sortie ne contient que la table.
  - Les ancres, le rang, l'archive altérée et la CLI sont contrôlés.
- **Mutants** : 11/11 (`MUTATIONS_poolprof_v0_1.json`). Le lanceur vérifie d'abord que la base passe.

Commande prévue, après le PASS de R02, une seule fois :

```
cd <arbre gelé aff97638>
env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=<arbre gelé>:<w1aux_v78>:<paperstream_pkg 0.4>:<poolprof_pkg> \
    python3.12 -B -m poolprof.profile --pools <export W1> \
    --manifest-sha256 ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e \
    --sol-usd-series <racine>/sol_usd_series.json.gz \
    --sol-usd-series-sha256 7458f61579bed089cde4ac2037839d2da1cc36c44e13d3f63252111e98e0dbdc \
    --rank 50 --out <NOUVEAU répertoire poolprof_r50>
```

paperstream 0.4 ne sert ici qu'à `load_anchored_series` : sha contrôlé avant la lecture, chargeur gelé.
