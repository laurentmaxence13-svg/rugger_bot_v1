# paperstream 0.2 — moteur PAPER EN FLUX du MASTER gelé, hors ligne (décision R02 06181c21)

La 0.1 (README_PAPERSTREAM_v0_1.md, commit e987e33d) reste valable pour le principe et les 7 conditions de R02. Cette
note ne décrit que ce qui change.

## Pourquoi une 0.2

Le run de R03 sur P0 visible donnait 0 entrée : 20 868 décisions sur 20 887 étaient bloquées par
`sol_usd_rate_unavailable`. Deux écarts de la 0.1 :
1. aucune entrée SOL/USD n'était passée à l'observateur ;
2. la 0.1 bouclait elle-même sur `replay_pool`, sans fenêtre de collecte, sans historique créateur et sans bras placebo.
   Elle n'aurait donc pas reproduit le L1 W1.

## Ce qui change (points 1 à 6 de R02)

1. **Série SOL/USD obligatoire.**
   - On fournit `--sol-usd-series` et `--sol-usd-series-sha256`.
   - Le sha256 du fichier est vérifié AVANT sa lecture.
   - Le chargeur est `sus.load_series`, celui de `w1_run.run_trials`. La garde est la même : COLLECTED, avec
     l'acceptation mesurée.
   - La série est passée identiquement au lot et au flux.
2. **Aucun taux déclaré.**
   - Aucune option ne permet d'en donner un.
   - `l1_params().sol_usd` doit être None, sinon `declared_sol_usd_rate_refused`.
3. **`StreamTrade` et `stream_replay` sont inchangés.** Le sha256 de leur source est testé égal à celui de la 0.1.
4. **L'appel gelé du bundle L1 W1.**
   - `records()` appelle `hrr.run_replay(pools, w1_run.l1_params(), série, w1_run.L1_EXIT,
     hrr.CreatorHistory.from_archives(..., 'manifest'), placebo_arm=True)`, comme `w1_run.run_trials`.
   - Le flux fait le même appel dans `streaming_engine()`.
   - `--expect-bundle-sha256` compare au bundle L1 W1 ancré.
   - Identité exigée : `bundle_sha256` gelé ET sha256 du JSON canonique entier, lot contre flux, sans tolérance.
5. **P0 visible n'est pas rejoué.** Le paquet ne le traite pas.
6. **Test sans remplacer `observe()`.**
   - Avec la série synthétique du selfcheck dayj : décisions > 0 et aucun `sol_usd_rate_unavailable`.
   - Contrôle : sans série, le frozen `run_replay` bloque 100 % des décisions par ce motif. C'est le blocage de la 0.1, qui
     ne peut donc plus passer inaperçu.

## Grands packs (W1)

- `--workers W` exécute dans `w1aux.lazy.lazy_archives()` et `w1aux.parallel.parallel_replays(W)`, comme l'étape trials.
- Les workers forkés héritent du moteur échangé.
- **Il n'y a PAS de checkpoint** : aucun résultat du lot ne peut être servi au flux.
- Chaque journal PAPER est écrit par pool, dans `journals/`, par le processus qui a rejoué la pool. Il est rapproché
  ensuite (reçu − dépensé − tx − échecs = P&L, résidu nul).
- Le lot et le flux sont testés identiques avec 1 et 2 workers.

## Usage (pour R03, sur W1 seulement, après PASS de R02)

```
python -B -m paperstream.engine reference --pools <export W1 ebe1959d> --manifest-sha256 <ancré> \
       --sol-usd-series <racine>/sol_usd_series.json.gz --sol-usd-series-sha256 7458f615… --workers <W> --out <REF>
python -B -m paperstream.engine run --pools <idem> --manifest-sha256 <ancré> \
       --sol-usd-series <idem> --sol-usd-series-sha256 7458f615… --workers <W> \
       --reference <REF>/REFERENCE.json --reference-sha256 <ancré par R02> \
       --expect-bundle-sha256 <bundle_sha256 L1 W1 ancré> --out <RUN>
```

- Le code retour est 0 seulement si trois conditions tiennent :
  - le flux est identique à la référence ;
  - le flux est égal au bundle attendu ;
  - les cycles rapprochés sont égaux aux cycles clos.
- REFERENCE.json et PAPERSTREAM.json ne donnent que des COMPTES par bras (décisions, entrées, issues, cycles clos,
  motifs), sans P&L.
- `counts.master.closed_cycles` doit être cohérent avec 128.
- `BUNDLE.json.gz` est le bundle complet, dont le sha est consigné.
- Si l'identité échoue : STOP. On n'ajuste pas `StreamTrade`.

## Preuves

- Tests : 21 réussis, sous `-W error` et hors réseau.
- Mutations : 27 sur 27 détectées (MUTATIONS_paperstream_v0_2.json), soit 15 de la 0.1 et 12 nouvelles :
  - sha de la série non vérifié ;
  - garde de la série retirée ;
  - série optionnelle ;
  - série non passée au flux ;
  - placebo retiré ;
  - historique créateur retiré ;
  - taux déclaré accepté ;
  - journal resté en mémoire ;
  - manifest non vérifié ;
  - bundle attendu ignoré ;
  - P&L dans les comptes ;
  - `replay_pool` non restauré.
- Ce paquet n'ajoute aucun essai. N reste 168 hors HW1.
