# w1x 0.1.5 — étape `ledger` avec la correction C1 déclarée (décision du propriétaire du 20/11)

**Préparé, non exécuté sur W1.** RUGGER 03 ne l'exécute qu'après l'audit de RUGGER 02 et son PASS, et il n'exécute que
la correction auditée et ses contrôles. Ce n'est pas la chaîne officielle W1, et cela ne donne jamais le verdict W1.
Le paquet demande w1aux v7.7.

## Ce qui change par rapport à 0.1.4

- `explore.py` 0.1.2 (a182c148) et tous les fichiers couverts par les identités restent identiques.
- `w1x/ledger_par.py` reçoit `step --resumable --c1`.
- Ajout : `w1x/tests/test_ledger_par_c1.py`.

## Procédure pour RUGGER 03 (après le PASS de R02)

1. **Mettre à part le ledger en échec, sans le supprimer** (condition du propriétaire). Le dossier `<racine>/ledger/`
   qu'il a écrit doit être SORTI de la racine, par exemple vers `<OUT>/ledger_fail_20261119/`. Sa `ledger.json` garde
   son sha256 ancré `cea0175851c88e7ce85d284317927a6763387e93a5e024de2f7e90d79d9ee18a`.
   - Ce dossier n'entre dans aucun digest d'étape, puisque l'étape ledger n'est pas enregistrée.
   - Le cache `<racine>/ledger_resume/` reste en place.
2. **Lancer, détaché**, avec `PYTHONPATH = <checkout aff97638>:<w1aux_v77>:<w1_exploratory_v015>` :

       python -B -m w1x.ledger_par step --resumable --c1 \
           --failed-ledger <OUT>/ledger_fail_20261119/ledger.json \
           --failed-ledger-sha256 cea0175851c88e7ce85d284317927a6763387e93a5e024de2f7e90d79d9ee18a -- \
           --step ledger --out <OUT> --s0 467275745 --expect-sha <digest trials>

3. **Vérifier ce qui est attendu** :
   - les 2 344 appels sont repris et 0 sont recalculés ;
   - le cache garde son lien (`trials:<digest>`) et son code, puisque `ledger.py` et `ledger_resume.py` sont
     inchangés ;
   - la durée se limite à la PROBE, la relecture du cache et l'assemblage ;
   - l'étape explore exige un verdict **PASS**, donc **aucun écart** : sinon `ledger_verdict_not_pass`, rien n'est
     enregistré et on analyse de nouveau ;
   - `LEDGER_PARALLELE.json` déclare `c1` (module, sha256, règle remplacée, issues concernées) et
     `failed_ledger_kept` (chemin et sha256).
4. **Faire ancrer par R02**, avant toute lecture : la trace, le digest de l'étape ledger et le nouveau `ledger.json`.
   Ensuite seulement vient l'étape `reading` (explore 0.1.2, inchangée), puis son ancrage, puis la synthèse
   exploratoire.

## Refus du lanceur

- `--c1` sans `--resumable`.
- `--c1` sans le ledger en échec ou sans son sha256.
- Un ledger en échec dont le sha256 n'est pas celui ancré.
- Un dossier `ledger/` encore présent dans la racine.
- Un enregistrement déjà présent.

## Tests

En plus de ceux de 0.1.4, deux tests portent sur la chaîne complète du pack gelé :

- le ledger avec C1 donne le même état, le même digest et le même `ledger/` que le séquentiel v7.4 ;
- la trace déclare C1 et le ledger conservé, et les refus ci-dessus sont vérifiés.
