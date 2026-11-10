# v3lab 0.3 — exécution chez RUGGER 03 (hors ligne, après ancrage par RUGGER 02)

Prérequis : CPython 3.12.3 ; un checkout propre de l'arbre gelé `aff97638` ; `PYTHONPATH=<ce répertoire>` **seul**
(jamais w1aux, jamais le répertoire dayj) ; `RUGGER_NO_DOTENV=1` ; aucun réseau (`unshare -rn`).

```bash
cd <checkout aff97638>
export RUGGER_NO_DOTENV=1 PYTHONPATH=<v3lab_pkg>
# 0. tests (25 attendus)
unshare -rn python3.12 -B -m pytest -q -p no:cacheprovider -W error <v3lab_pkg>/v3lab/tests
# 1. plan : plan_sha256 91e831e0…, v3lab_sha256 b6c78c25…, embargo requis 6018
unshare -rn python3.12 -B -m v3lab plan | tail -5
# 2. pack visible : --table-from-bundle est OBLIGATOIRE (R02 P-1) ; les fichiers du holdout ne sont ni ouverts ni copiés
unshare -rn python3.12 -B -m v3lab pack --source v2_p0/p0_export_ro --out v3/p0_visible \
    --table-from-bundle v2_p3/out/phase3/T16.json      # sha256 75f51dcd… (ancré par R02)
#    -> envoyer manifest_sha256, counts, segments_sha256, sealed_sha256 à R02 ; ATTENDRE son ancrage
# 3. essais (identifiants seulement, aucun résultat affiché)
unshare -rn python3.12 -B -m v3lab run --pack v3/p0_visible --expect-manifest-sha <sha ancré> \
    --registry v3/v3_trials.jsonl --out v3/runs
#    -> envoyer la tête du registre et les 8 bundle_sha256 à R02
# 4. évaluation (une seule fois)
unshare -rn python3.12 -B -m v3lab evaluate --bundles v3/runs --registry v3/v3_trials.jsonl --out v3/report.json
```

Le registre V3 est un fichier NOUVEAU et VIDE au départ (`v3/v3_trials.jsonl`) : ne jamais donner le registre P0 ou W1 (refusé).
Un seul pack (R02 P-3) : tout autre pack exige l'ancrage de R02, et ses essais s'ajoutent à N (le code compte toutes les entrées du registre).
Exécution depuis une worktree propre de l'arbre `aff97638`, `PYTHONPATH=<v3lab_pkg>` seul (R02 P-4).
