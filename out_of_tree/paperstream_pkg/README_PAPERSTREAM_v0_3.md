# paperstream 0.3 — exigences de R02 (15:51Z, 15:52Z, 15:52:53Z) sur la 0.2

Pour le reste, la 0.2 (README_PAPERSTREAM_v0_2.md) reste valable. Ce qui suit ne décrit que les changements.

1. **W1 : le flux SEUL, comparé au sha ancré.**
   - `run` accepte `--expect-bundle-sha256` sans `--reference`. Sur W1, la valeur est
     3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657, ancrée par R02.
   - Cette valeur vient de la ligne de commande. Elle n'est jamais lue dans un fichier produit par le run.
   - `run` refuse un appel sans aucune comparaison (`nothing_to_compare_with`).
   - Le lot = flux, avec 1 et 2 workers, reste testé sur les fixtures.
2. **Point 3 de R02 : assertion exacte.**
   - Le run utilise la série synthétique du selfcheck, sans remplacer `observe()`.
   - Pour chaque bras, le compte de `sol_usd_rate_unavailable` est le même en lot, en flux et dans le moteur gelé direct
     (il vaut 0).
   - Les décisions sont égales et en nombre non nul, et le placebo entre au moins une fois.
   - Contrôle : sans série, le moteur gelé bloque 100 % des décisions.
3. **Zéro résidu, défini dans le code** (`RECONCILED`, `residual`). Pour chaque cycle clos, on vérifie :
   - `SELL.received − BUY.spent − (BUY.tx_cost + SELL.tx_cost) − row.failed_attempt_costs − row.pnl_lamports = 0` ;
   - `BUY.spent = row.spent`, `SELL.received = row.received` et `BUY.tx_cost + SELL.tx_cost = row.tx_costs`.

   Il faut exactement un BUY et un SELL par cycle, et un seul journal par pool et par bras. Six tests injectent un résidu,
   un par champ, et chacun échoue comme attendu.
4. **Pare-feu.**
   - PAPERSTREAM.json, REFERENCE.json et CHECKPOINT_INDEX.json ne contiennent que les identités, les cycles clos et les
     comptes de motifs. Testé : ni `pnl`, ni `return`, ni `HW`, ni `hypothes`, ni `mark_`.
   - Le bundle n'est plus écrit (la 0.2 écrivait BUNDLE.json.gz).
   - `identity_check_not_a_trial` vaut true et `trials_added` vaut 0 : N reste 168.
5. **Checkpoint, en flux seulement** (`--checkpoint DIR`, en dehors de `--out`).
   - Chaque pool a son entrée en JSON canonique, `<pool>.json` : la clé, le record ou l'exclusion, les journaux PAPER.
   - Son sha est dans `<pool>.sha256`, écrit après l'entrée complète.
   - Pas de pickle, et jamais le checkpoint de trials.
   - **Clé** : `mode = "stream"`, sha du code de flux, sha de la série, MANIFEST, sha de `l1_params` et `L1_EXIT`, pool.
     - Le sha du code de flux couvre le source de StreamTrade, stream_replay, streaming_engine, du wrapper et du
       Checkpoint, ainsi que `harness.code_fingerprint()`.
   - Une entrée est réutilisée seulement si sa clé ET le sha du fichier concordent. Sinon, la pool est recalculée et le
     motif est consigné (`absent`, `sha_mismatch` ou `key_mismatch`).
   - Les records du code gelé sont du JSON pur : `_canonical` sans `default`, `allow_nan=False`. Le bundle reconstitué est
     donc identique à l'octet, ce qui est testé.
   - `CHECKPOINT_INDEX.json` (clé → sha, dernier état par pool, comptes de reprise) est publié avec la sortie. Son sha est
     dans PAPERSTREAM.json.
   - `records(..., streaming=False, checkpoint_dir=…)` est refusé.
   - Tests :
     - (a) coupure simulée après 2 pools puis reprise : bundle et journaux identiques à l'octet à un run sans coupure,
       comptes `{absent: 1, reused: 2}`, puis `{reused: 3}` ;
     - (b) une entrée en mode `batch`, ou avec une autre série, un autre code ou une autre pool, est refusée
       (`key_mismatch`) et recalculée ;
     - (c) une entrée altérée est refusée (`sha_mismatch`) et recalculée ;
     - le checkpoint fonctionne aussi avec 2 workers forkés.
6. **StreamTrade inchangé** : le sha de son source est bc9227869d42c78523b76da78620ddaa5d03f9bd27fb780394bb6d5598625299,
   identique à la 0.1, et le test le vérifie.

## Usage sur W1 (R03, après PASS de R02 seulement)

```
python -B -m paperstream.engine run --pools <export W1 ebe1959d> --manifest-sha256 <ancré> \
       --sol-usd-series <racine>/sol_usd_series.json.gz --sol-usd-series-sha256 7458f615… --workers 4 \
       --expect-bundle-sha256 3409bf9d58a1c9f53e7d891b16531cb2626fb5bc25ea89d32d84170f93b36657 \
       --checkpoint <répertoire paperstream, hors --out> --out <RUN>
```

- **Durée.** R02 l'estime à environ 7 h 40 avec 4 workers.
- **Après une interruption.** Relancer la même commande avec un nouveau `--out` et le même `--checkpoint`.
- **Code retour.** Il vaut 0 seulement si le bundle du flux est égal au sha ancré ET si les cycles rapprochés sont égaux
  aux cycles clos.
- **Attendu.** `counts.master.closed_cycles` doit être cohérent avec 128.
- **En cas d'échec.** STOP, sans aucun ajustement.

## Ajouts demandés par R02 à 16:00Z et 16:06Z

7. **Le sha rapporté est celui du code gelé.** Le bundle n'est plus écrit. La sortie donne donc :
   - `bundle_sha256`, le champ du bundle gelé ;
   - `bundle_sha256_recomputed`, c'est-à-dire `hrr._sha` sur le bundle sans son propre champ sha. C'est le JSON canonique
     de `hrr._canonical` (`sort_keys`, séparateurs compacts, `allow_nan=False`), celui de `run_replay`, donc de
     `w1_run.run_trials` ;
   - le verdict `matches_expected_bundle` et/ou `identical_to_reference`.

   Un test vérifie que les deux sha sont égaux à celui de l'appel gelé direct.
8. **Garde mémoire.**
   - C'est `w1aux.dayj.memory_guard('trials', <pools>)`, la projection depuis le MANIFEST (signatures × Ko par signature
     de l'étape trials), avec la marge de dayj.
   - Elle s'applique AVANT toute écriture. Un refus donne `memory_projection_exceeds_available_owner_decision_needed`.
   - La projection et `memory_override` sont consignés dans la sortie.
   - **`--memory-override` n'est PAS utilisable par R03 sans l'accord écrit de R02.**

## Preuves (0.3)

- **Tests.** 39 réussis sous `-W error`, hors réseau.
- **Mutations.** 36 sur 36 détectées (MUTATIONS_paperstream_v0_3.json) :
  - le run complet n°2 en détectait 35 sur 36 ; `residual_tx_costs_dropped` survivait, faute d'injection côté ligne de
    trade ;
  - j'ai ajouté 3 cas de résidu côté ligne (`spent`, `received`, `tx_costs`), sans rien retirer d'autre ;
  - les 3 mutants de résidu et de rapprochement, relancés sur les tests finaux, sont tous détectés.
- **StreamTrade.** Le sha de son source est inchangé depuis la 0.1 (bc922786…).
- **N.** Inchangé, 168 hors HW1 : c'est un contrôle d'identité, pas un essai.
