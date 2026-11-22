# Protocole de vérification de paperstream 0.5.1 sur W1 (v0.1, à valider par R02)

RUGGER 01, 22/11. Cette note répond à la décision du propriétaire du 22/11 vers 14:45Z (point 3, relayé par R04) :
> « J'autorise les vérifications hors ligne sur les données déjà autorisées, après validation de R02. L'objectif est de
> prouver que le moteur accéléré reproduit exactement le résultat W1 et respecte les limites mémoire. Ne pas remplacer
> ou modifier les résultats du run 0.4. »

## 0. Ce qui ne change pas

- Le run 0.4 (out3, sha 56ff15ec) et son résultat restent tels quels : rien n'est remplacé, rien n'est relancé.
  L'échec psverdict de la 0.4 reste enregistré. Ce run 0.5.1 est une vérification de plus, pas un remplacement.
- Le code exécuté est paperstream 0.5.1, commit 35267e7, MANIFEST 389ba279, PASS de R02. Il ne bouge plus.
- `MEMO_BYTES_PER_GZ_BYTE` vaut 8,0, valeur conservée par R02 après le memo_probe du rang 1 : 6,4 octets par octet gz.
- Aucun essai n'est ajouté : N reste à 168. Ce n'est pas un trade du MASTER, et ces cycles ne comptent pas pour les
  seuils de 50 cycles et 20 créateurs.

## 1. Une exécution, une seule

Elle est faite par R03, hors ligne, sur l'export W1 déjà autorisé (MANIFEST ebe1959d). Elle a lieu après la validation
de ce protocole par R02.

```
cd <arbre gelé aff97638>
env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 \
    PYTHONPATH=<arbre gelé>:<w1aux_v78>:<paperstream_v05_pkg à 35267e7> \
    nice -n 10 python3.12 -B -m paperstream.engine run \
    --pools <export W1> --manifest-sha256 ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e \
    --sol-usd-series <racine>/sol_usd_series.json.gz \
    --sol-usd-series-sha256 7458f61579bed089cde4ac2037839d2da1cc36c44e13d3f63252111e98e0dbdc \
    --workers 4 --fast-analyser --perf-counters \
    --expect-bundle-file-sha256 3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657 \
    --expect-bundle-json-sha256 9eb4342674fdc85e002d08f4945d742800e585a50e9386a85c4bf68392a9680f \
    --expect-bundle-field-sha256 c7556f140fe8e2007ced5bd6c0a20a4202f2bfcda1a49370df1e1bbaabe62aa8 \
    --checkpoint <NOUVEAU répertoire ps051_ck1> --out <NOUVEAU répertoire ps051_W1_out1> \
    > ps051_W1_out1.stdout ; echo "rc=$?" >> ps051_W1_out1.stdout
```

**Règles d'exécution :**
- **Tout est neuf.** `--out` et `--checkpoint` sont NEUFS. Jamais out1, out2 ou out3 de la 0.4, jamais le checkpoint
  de la 0.4.
  - Même si on s'y trompait, les entrées de la 0.4 seraient refusées : la clé de checkpoint contient
    `fast_analyser=true` et le sha du code de flux, qui inclut `fast.py`. Cela donne `key_mismatch` (testé).
- **Le code 0.4 reste hors chemin.** Seul `paperstream_v05_pkg` est dans `PYTHONPATH`. Le paquet 0.4 de même nom ne doit
  pas y figurer.
- **Pas de contournement de la mémoire.** Aucun `--memory-override` et aucun `--verify-fast`. L'identité par les 3 sha
  suffit : une seule valeur mal servie par le cache changerait le bundle, donc ses sha.
- **Reprise après redémarrage.** Même commande, même `--checkpoint`, et un `--out` NEUF (out2, out3…). La reprise est
  testée : bundle identique, chemin `--out` sans effet.
  - Il faut consigner l'heure de la coupure et l'heure de la reprise.
  - Seul le dernier `--out` complet sert au verdict.
- **Arrêt sans ajustement.** Tout écart donne STOP : aucun ajustement et aucune seconde exécution sans GO du
  propriétaire.

## 2. Mesure de la mémoire (en parallèle du run, métadonnées seulement)

```
( while kill -0 <PID du run> 2>/dev/null; do
    printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$(cat /sys/fs/cgroup/memory.current)" \
                        "$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo NA)"
    sleep 60; done ) > ps051_mem.log
```

- **Ce que contient chaque ligne :** l'heure, `memory.current` et `memory.peak` du cgroup, en octets.
  - Si `memory.peak` n'existe pas, on écrit NA. Le pic retenu est alors le maximum des échantillons.
  - Le relevé par worker (VmHWM) de `ps04_monitor` peut être ajouté à part. Il est descriptif.
- **Limite.** C'est la mémoire disponible au lancement que le run consigne lui-même (`memory.available_mb`, mesurée par la
  garde de dayj). La garde exige déjà une disponibilité d'au moins 1,5 × (projection trials + marge du cache).

## 3. Critères (ps051verdict 0.1, lecture seule, en une passe)

```
PYTHONPATH=<ps051_verif> python3.12 -I -B -m ps051verdict.verdict --run <dernier --out> \
    --printed-sha256 <sha affiché par le run> --rc <rc> --mem-log ps051_mem.log
```

| Contrôle | Condition |
|---|---|
| G-1 | le sha affiché est égal au sha de PAPERSTREAM.json |
| G-2 | rc = 0 |
| G-3 | entrées : MANIFEST ebe1959d et fichier de série 7458f615 |
| G-4 | network false, trials_added 0, identity_check_not_a_trial, HISTORICAL_REPLAY |
| G-5 | les 3 sha attendus donnés au run sont exactement les ancres W1 |
| G-6 | INDEX du checkpoint : sha, une entrée par pool, mode `stream`, `fast_analyser` vrai, aucun `sha_mismatch` ni `key_mismatch` |
| **I-1** | schéma paperstream-v0.5.1, `fast_analyser` vrai, `verify_fast` faux |
| **I-2** | sha du FICHIER L1 recalculé par `w1_run._write_json` = 3409bf9d (et correspondance vraie) |
| **I-3** | sha du JSON canonique décompressé = 9eb43426 |
| **I-4** | champ interne `bundle_sha256` = c7556f14 |
| **I-5** | champ interne = son recalcul `hrr._sha` |
| **I-6** | `reconciled_cycles` = `closed_cycles_all_arms` > 0, et `counts.master.closed_cycles` = **191**. C'est le compte du bundle ENTIER, documenté par R02 : ce n'est pas le 128 de la plage d'évaluation, qui était l'erreur de définition de psverdict 0.2. |
| **M-1** | garde dayj passée SANS `--memory-override`, avec la marge du cache (`fast_memo_mb` consigné) |
| **M-2** | pic mesuré (max des échantillons et du `memory.peak` du cgroup) ≤ `memory.available_mb` consigné au lancement |

**Verdicts possibles :**
- **VERIFIED** : tout passe.
- **INVALID_RUN** : un contrôle G échoue.
- **IDENTITY_FAILED** : un contrôle I échoue sur un run valide.
- **MEMORY_EXCEEDED** : un contrôle M échoue.

**Ce qui est aussi publié**, à titre descriptif et sans critère :
- le pic, la projection avec cache et leur rapport (calibrage) ;
- `checkpoint_counts` ;
- le sha de PERF_COUNTERS.json : évaluations complètes, attentes courtes et secondes par rang de taille, sans
  identifiant ni résultat.

On n'utilise PAS psverdict 0.2 : son schéma attendu est la 0.4, et son critère de 128 cycles porte sur une autre
population.

## 4. Preuves de l'outil de lecture

- **ps051verdict 0.1 :** 16 tests sous `-W error`, sur une VRAIE sortie paperstream 0.5.1 `--fast-analyser` produite
  sur les fixtures (2 workers, checkpoint, compteurs).
- **Résultat VERIFIED avec les ancres de fixtures.** Avec les ancres W1, le même run donne INVALID_RUN, comme prévu.
- **Chaque altération est nommée :**
  - moteur lent ;
  - schéma 0.4 ;
  - verify ;
  - chacun des 3 sha ;
  - cohérence ;
  - cycles ;
  - override ;
  - marge absente ;
  - réseau ;
  - attendus ≠ ancres ;
  - index ;
  - pic > disponible ;
  - journal vide ;
  - rc ;
  - sha affiché.

## 5. Durée attendue

- La 0.4 a mis environ 5 h 20 à 6 h sur les plus gros pools, avec 4 workers.
- Avec le cache, on mesure ×3,1 sur les fixtures. Sur W1, le gain est à mesurer, car les grosses transactions pèsent
  davantage.
- Le compteur technique donnera la répartition par rang.

## 6. Avenant v0.2 (R02, 22/11 15:32Z et 15:33Z, fixé avant tout résultat) : M-2 et ps051verdict 0.2

**Pourquoi.** Sur cgroup v1, `usage_in_bytes` et `max_usage_in_bytes` comprennent le cache de pages : la lecture des
données suffit à les faire grimper. De plus, `max_usage_in_bytes` court depuis le démarrage du conteneur.

**L'échantillonneur de R03**, lancé à 15:32:51Z, en lecture seule. Il écrit une ligne par minute :
`<iso> <rss de memory.stat> <somme des VmRSS des processus du run> <usage_in_bytes> <max_usage_in_bytes>`, en octets.
Le §2 ci-dessus est remplacé par ce format.

**La règle M-2.** Elle compare à la mémoire disponible consignée par le run au lancement (`memory.available_mb`) :
1. si max(max_usage_in_bytes) ≤ disponible, c'est PASS ;
2. sinon, si max(somme VmRSS) ≤ disponible ET max(rss) ≤ disponible, c'est PASS, avec la mention « unsampled window
   15:29:53-15:32:51Z » ;
3. sinon, c'est MEMORY_EXCEEDED.

Les pics de chaque colonne et le numéro de la règle appliquée sont publiés.

**Format du journal.** Il est exact : 5 colonnes, des entiers. Une ligne malformée est refusée et donne
`memory_log_malformed_line:<n>`, de même qu'un journal sans échantillon.

**Décisions de R02 enregistrées :**
- I-6 = 191 est confirmé.
- Il n'y a pas de verify sur P0 visible, faute de série COLLECTED. La condition 3 est remplacée par l'identité W1
  (3 sha) et par les tests de verify.
- G-6 refuse tout `key_mismatch` et tout `sha_mismatch`. C'est accepté avant le run.

**Preuves de ps051verdict 0.2 : 22 tests**, dont :
- la règle 1 ;
- la règle 2, avec un cache élevé et une mémoire anonyme basse, qui donne VERIFIED avec la mention ;
- la règle 3, une fois par la somme des VmRSS et une fois par le rss de memory.stat ;
- les pics par colonne ;
- 5 journaux refusés : vide, lignes vides, 4 colonnes (format v0.1), 6 colonnes, valeur non numérique.
