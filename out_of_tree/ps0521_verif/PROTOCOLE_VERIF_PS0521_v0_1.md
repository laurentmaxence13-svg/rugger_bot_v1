# Vérification de paperstream 0.5.2.1 sur W1 — commande exacte, à valider par R02 AVANT le run (v0.1)

RUGGER 01, 22/11/2026. Demande de R02 (22:02Z), après le verdict VERIFIED de la 0.5.1 sur W1 (identité à l'octet,
mémoire respectée, 6 h 31, aucun gain de vitesse). L'ordre est fixé par R02 : d'abord le profil d'UN pool
(`poolprof` 0.1, à auditer), ensuite ce run.

## 0. Ce qui ne change pas

- Les runs 0.4 et 0.5.1 et leurs résultats restent tels quels : rien n'est remplacé ni relancé. L'échec de psverdict
  de la 0.4 reste enregistré. Ce run est une vérification de plus.
- Le code exécuté est paperstream **0.5.2.1**, commit 99a8a35, MANIFEST 6d2550f0, PASS de R02. Il ne bouge plus.
- Aucun essai n'est ajouté : N reste à 168. Ces cycles ne comptent pas pour 50/20 (HISTORICAL_REPLAY).
- Lecture par **ps0521verdict 0.1** (5bc67c6, MANIFEST 59374602, PASS de R02) : mêmes contrôles que ps051verdict 0.2,
  avec I-1 sur le schéma `paperstream-v0.5.2.1` et `--unsampled-window` obligatoire.

## 1. Conditions fixées AVANT le run (R02)

1. **Échantillonneur d'abord.** L'échantillonneur mémoire démarre AVANT le run, et l'heure de son démarrage est
   consignée. La lecture se fait donc avec `--unsampled-window none`.
2. **Aucune autre charge** dans le conteneur de R03 pendant le run : ni autre rejeu, ni test, ni copie lourde.
3. **Tout est neuf.** `--checkpoint` et `--out` sont neufs (`ps0521_ck1`, `ps0521_W1_out1`). Ce ne sont jamais ceux de
   la 0.4 ni de la 0.5.1 ; la clé de checkpoint, qui contient le sha du code de flux, les refuserait de toute façon.
4. **Seul `paperstream_v05_pkg` à 99a8a35** est dans `PYTHONPATH`, jamais le paquet 0.4 du même nom.
5. **Aucun contournement** : ni `--memory-override` ni `--verify-fast`. L'identité par les 3 sha suffit.
6. **Reprise après une coupure** : même commande, même `--checkpoint`, nouveau `--out` (out2…). Les heures de coupure
   et de reprise sont consignées, et seul le dernier `--out` complet sert au verdict.
7. **Tout écart = STOP.** Aucun ajustement, aucune seconde exécution sans GO.

## 2. Échantillonneur (5 colonnes, format de l'avenant M-2, lancé EN PREMIER)

```
date -u +%FT%TZ > ps0521_sampler_start.txt
( while true; do
    printf '%s %s %s %s %s\n' "$(date -u +%FT%TZ)" \
      "$(awk '$1=="rss"{print $2}' /sys/fs/cgroup/memory/memory.stat)" \
      "$(for p in $(pgrep -f 'paperstream.engine run'); do awk '/^VmRSS/{print $2*1024}' /proc/$p/status; done | awk '{s+=$1} END{print s+0}')" \
      "$(cat /sys/fs/cgroup/memory/memory.usage_in_bytes)" \
      "$(cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes)"
    sleep 60; done ) > ps0521_mem.log &
```

Il est arrêté à la main après la fin du run, une fois `rc` consigné. C'est l'échantillonneur de la 0.5.1 (même
format), lancé cette fois avant le run.

## 3. Le run (une seule exécution, par R03, hors ligne, sur l'export W1 déjà autorisé, MANIFEST ebe1959d)

```
cd <arbre gelé aff97638>
env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 \
    PYTHONPATH=<arbre gelé>:<w1aux_v78>:<paperstream_v05_pkg à 99a8a35> \
    nice -n 10 python3.12 -B -m paperstream.engine run \
    --pools <export W1> --manifest-sha256 ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e \
    --sol-usd-series <racine>/sol_usd_series.json.gz \
    --sol-usd-series-sha256 7458f61579bed089cde4ac2037839d2da1cc36c44e13d3f63252111e98e0dbdc \
    --workers 4 --fast-analyser --perf-counters \
    --expect-bundle-file-sha256 3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657 \
    --expect-bundle-json-sha256 9eb4342674fdc85e002d08f4945d742800e585a50e9386a85c4bf68392a9680f \
    --expect-bundle-field-sha256 c7556f140fe8e2007ced5bd6c0a20a4202f2bfcda1a49370df1e1bbaabe62aa8 \
    --checkpoint <NOUVEAU répertoire ps0521_ck1> --out <NOUVEAU répertoire ps0521_W1_out1> \
    > ps0521_W1_out1.stdout ; echo "rc=$?" >> ps0521_W1_out1.stdout
```

C'est la commande de la 0.5.1, à trois différences près : le commit du paquet (99a8a35 au lieu de 35267e7) et les
deux répertoires neufs. Les options et les ancres sont identiques.

## 4. Lecture, une passe (ps0521verdict 0.1), SANS `-I`

`-I` ignorerait `PYTHONPATH`. C'est la correction de documentation annoncée pour ps051verdict et ps0521verdict.

```
env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=<ps0521_verif> \
    python3.12 -B -m ps0521verdict.verdict --run <dernier --out> \
    --printed-sha256 <sha affiché par le run> --rc <rc> --mem-log ps0521_mem.log --unsampled-window none
```

- **Contrôles**, inchangés depuis l'avenant v0.2 de la 0.5.1 :
  - G-1 à G-6 ;
  - I-1 sur le schéma 0.5.2.1 ;
  - I-2 à I-5, les 3 sha W1 et le recalcul ;
  - I-6, soit 191 cycles clos sur le bundle entier ;
  - M-1 ;
  - M-2, règles 1 à 3.
- **Verdicts** : VERIFIED, INVALID_RUN, IDENTITY_FAILED ou MEMORY_EXCEEDED.
- **Publié à part, sans critère** : la durée du run, à comparer aux 6 h 31 de la 0.5.1 ; les compteurs de
  PERF_COUNTERS ; le pic mémoire comparé à la projection.
  - Un gain de vitesse est ATTENDU : le memo de `as_of` et de `_quote` donne 2,0–2,6 s contre 77–85 s sur la série
    synthétique de taille W1.
  - Ce gain n'est PAS un critère, et son absence ne change pas le verdict.

## 5. Ordre (R02)

1. R02 audite `poolprof` 0.1.
2. R03 l'exécute une fois, sur le pool de rang 50 (taille gz).
3. R02 lit le profil.
4. R02 valide ce protocole.
5. R03 exécute §2, puis §3, puis §4.
