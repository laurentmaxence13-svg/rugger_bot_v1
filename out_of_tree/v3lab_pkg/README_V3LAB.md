# v3lab 0.1 — exécution chez RUGGER 03 (hors ligne, après ancrage par RUGGER 02)

Prérequis : CPython 3.12.3 ; un checkout propre de l'arbre gelé `aff97638` ; `PYTHONPATH=<ce répertoire>` **seul**
(jamais w1aux, jamais le répertoire dayj) ; `RUGGER_NO_DOTENV=1` ; aucun réseau (`unshare -rn`).

```bash
cd <checkout aff97638>
export RUGGER_NO_DOTENV=1 PYTHONPATH=<v3lab_pkg>
# 0. tests (25 attendus)
unshare -rn python3.12 -B -m pytest -q -p no:cacheprovider -W error <v3lab_pkg>/v3lab/tests
# 1. plan : plan_sha256 91e831e0…, v3lab_sha256 880c99be…, embargo requis 6018
unshare -rn python3.12 -B -m v3lab plan | tail -5
# 2. pack visible (le holdout n'est jamais copié ; avec --table-from-bundle ses fichiers ne sont jamais ouverts)
unshare -rn python3.12 -B -m v3lab pack --source v2_p0/p0_export_ro --out v3/p0_visible \
    --table-from-bundle <un bundle P0 enregistré, par exemple T16>
#    -> envoyer manifest_sha256, counts, segments_sha256, sealed_sha256 à R02 ; ATTENDRE son ancrage
# 3. essais (identifiants seulement, aucun résultat affiché)
unshare -rn python3.12 -B -m v3lab run --pack v3/p0_visible --expect-manifest-sha <sha ancré> \
    --registry v3/v3_trials.jsonl --out v3/runs
#    -> envoyer la tête du registre et les 8 bundle_sha256 à R02
# 4. évaluation (une seule fois)
unshare -rn python3.12 -B -m v3lab evaluate --bundles v3/runs --registry v3/v3_trials.jsonl --out v3/report.json
```

Le registre V3 est un fichier NOUVEAU (`v3/v3_trials.jsonl`) : ne jamais donner le registre P0 ou W1 (refusé).
