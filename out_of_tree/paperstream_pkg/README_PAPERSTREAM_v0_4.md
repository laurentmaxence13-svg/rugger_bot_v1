# paperstream 0.4 — corrections K-1 à K-3 de l'audit R02 de la 0.3 (adfa889)

Le reste de la 0.3 est accepté par R02 et inchangé (README_PAPERSTREAM_v0_3.md).

## K-1 (bloquant) : la valeur ancrée est l'empreinte du FICHIER

La valeur W1 3409bf9d… est le sha256 du fichier `run/bundles/L1.json.gz`. Ce fichier est écrit par `w1_run._write_json` :
gzip (mtime 0) du JSON canonique strict, avec le champ `bundle_sha256` À L'INTÉRIEUR. Ce n'est donc pas ce champ. La 0.3
aurait rendu rc=1 sur W1 même avec un flux parfait. Mes tests ne le voyaient pas, car ils comparaient la même quantité des
deux côtés.

Ce que fait la 0.4 :
- `--expect-bundle-sha256` est supprimé ; ses deux remplaçants doivent être fournis ENSEMBLE :
  - `--expect-bundle-file-sha256` ;
  - `--expect-bundle-json-sha256`.
- `bundle_file_sha256` est obtenu en appelant `w1_run._write_json` lui-même, vers `<tmp>/bundles/L1.json.gz` :
  - `<tmp>` est un répertoire temporaire hors `--out`, supprimé à la sortie ;
  - un `tempfile.gettempdir()` situé sous `--out` est refusé.
- `bundle_json_sha256` est le sha256 du contenu décompressé, `_canonical_strict`, indépendant de zlib.
- `zlib_runtime_version` est publié.
- rc=0 exige les DEUX égalités.
- Tests :
  - le bundle gelé direct est écrit par `w1_run._write_json` en `run/bundles/L1.json.gz` sur les fixtures, et paperstream
    retrouve exactement son sha de fichier et son sha décompressé, en lot comme en flux seul avec checkpoint ;
  - un sha de fichier faux donne rc=1, un sha JSON faux aussi ;
  - fournir un seul des deux est refusé ;
  - l'ancienne option est refusée.

## K-2 : rc=0 exige aussi un sha interne cohérent

`bundle_sha256_consistent` = (champ `bundle_sha256` == `hrr._sha` recalculé), et rc=0 l'exige. Test : un bundle dont le
champ est altéré, avec des sha attendus calculés sur ce même bundle, donne rc=1. Le mutant correspondant est ajouté.

## K-3 : une seule sérialisation, celle de run_trials

`canonical_sha256` est remplacé par `bundle_json_sha256`, en `_canonical_strict` : pas de `default`, `allow_nan=False`.
Test : un bundle contenant NaN, ou un objet non JSON, est refusé par les deux fonctions de sha.

## Champ interne (R02 16:33Z)

`--expect-bundle-field-sha256` est un contrôle SUPPLÉMENTAIRE du champ interne `bundle_sha256`, jamais un substitut.
Sans `--expect-bundle-file-sha256` et `--expect-bundle-json-sha256`, il est refusé
(`bundle_field_sha256_is_an_extra_check_not_a_substitute`). Une valeur fausse donne rc=1 (testé).

Valeurs ancrées par R02 (lues par R03 en lecture seule, zlib 1.3) :
- fichier : 3409bf9d… ;
- JSON décompressé : 9eb43426… (394 845 032 o) ;
- champ interne : c7556f14….

## Usage sur W1 (R03, après PASS de R02 seulement)

```
python -B -m paperstream.engine run --pools <export W1 ebe1959d> --manifest-sha256 <ancré> \
       --sol-usd-series <racine>/sol_usd_series.json.gz --sol-usd-series-sha256 7458f615… --workers 4 \
       --expect-bundle-file-sha256 3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657 \
       --expect-bundle-json-sha256 9eb4342674fdc85e002d08f4945d742800e585a50e9386a85c4bf68392a9680f \
       --expect-bundle-field-sha256 c7556f140fe8e2007ced5bd6c0a20a4202f2bfcda1a49370df1e1bbaabe62aa8 \
       --checkpoint <répertoire paperstream, hors --out> --out <RUN>
```

- `--memory-override` n'est pas utilisable sans l'accord écrit de R02.
- Si l'identité échoue : STOP, sans ajustement.
- Si seule l'égalité du fichier échoue alors que le JSON est égal, c'est une différence de zlib : `zlib_runtime_version`
  est publié pour ce cas. Le verdict revient à R02.

## Mémoire en fin de run

Les trois sha (champ recalculé, JSON, fichier) resérialisent chacun le bundle, soit environ 395 Mo sur W1. Les trois calculs
sont successifs, ce qui ajoute à peu près 1 Go de pointe passagère après le rejeu. R03 en tient compte en plus du
memory_guard.

## Preuves (0.4)

- **Tests.** 42 réussis sous `-W error`, hors réseau.
- **Mutations.** 44 sur 44 détectées (MUTATIONS_paperstream_v0_4.json) :
  - le run complet n°2 en détectait 43 sur 44 : `reference_json_sha_ignored` survivait, car aucune référence n'avait le
    même champ et un autre sha JSON ;
  - j'ai ajouté 1 test, sans rien retirer d'autre ;
  - les 2 mutants de référence, relancés sur les tests finaux, sont tous les deux détectés.
- **StreamTrade.** Le sha de son source est inchangé depuis la 0.1 (bc922786…).
- **N.** Inchangé, 168 hors HW1.
