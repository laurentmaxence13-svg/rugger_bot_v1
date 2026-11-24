# cpmmpilot 0.2.5 — transactions v1 (R03), HORS LIGNE

Cette version suit l'erratum R02 f2e62c72, rédigé après le diagnostic du refus −32015. Elle est construite sur la **0.2.3**, déjà auditée. La 0.2.4 (filtre par slot) est abandonnée, puisque ce filtre n'était pas la cause.

## Diagnostic

Le run A2 du 24/11 à 11:46:23Z a échoué avec `method_refused:-32015:61294f25e789`.

Ce tag est exactement `sha256(message.lower())[:12]` du message standard du RPC Agave : « Transaction version (1) is not supported by the requesting client. Please try the request again with the following configuration parameter: "maxSupportedTransactionVersion": 1 ».

La semaine récente contient des transactions v1 (Agave 4.2), alors que nos appels demandaient la version 0. Les mots « not supported » faisaient classer cette erreur, à tort, en refus de méthode.

## Changements

1. **`rpc.MAX_TX_VERSION = 1`**, utilisé dans TOUS les appels de données complètes : GTFA full de `step1.collect` et de `u2`, et `getTransaction` de `step0`. Aucune autre option de requête ne change, et le filtre blockTime de la 0.2.3 est conservé.
2. **Erreur de version.** Un message contenant « transaction version » donne `RpcError('tx_version_unsupported:<code>:<hash>')`, et jamais `MethodRefused`.
3. **Texte d'erreur (R02 (c)).** Toute erreur RPC porte `exc.error_text = redact_error_text(message)` :
   - le texte est mis en minuscules ;
   - tout segment sans espace qui contient « http », « api » ou « key », ou qui dépasse 32 caractères, est remplacé par `[masque]` ;
   - le résultat est coupé à 200 caractères.

   Le tag reste le hash seul.

4. **Garde de format (R02 caf86646 (d)).** `step1.require_tx_format(out, phase, selected)` contrôle CHAQUE transaction de CHAQUE page.
   - Champs exigés : `signatures[0]`, `slot`, `transactionIndex`, `blockTime`, et `meta.logMessages` présent ou `meta.err` non nul.
   - Au premier défaut : `TxFormatStop('STOP_TX_FORMAT:<champ>')`.
   - Sinon, la fonction renvoie `transactions_by_version` (legacy / 0 / 1) et `skipped_by_version_and_reason`.
   - Le driver A2r l'appelle après `collect` et avant les déclencheurs ; un STOP_TX_FORMAT arrête avant les fiches.

## Vérifications (hors ligne, `unshare -rn`, g1ind 0.6.1)

**Tests : 52 sur 52.** Onze sont nouveaux :
- les sources demandent la version 1, et les appels envoyés aussi ;
- la traversée v1 de bout en bout (U-2 → collect → timelines → trigger_count) donne des résultats IDENTIQUES à la version 0 ;
- le message −32015 réel donne `tx_version_unsupported:-32015:61294f25e789`, pas MethodRefused, avec un texte masqué ;
- le masquage ;
- des versions mêlées legacy/0/1, avec le compte des écartées ;
- un STOP sur chacun des 5 champs manquants ;
- un échec sans journaux accepté.

**Mutants : 73 sur 73 tués** (`MUTATIONS_cpmmpilot_v0_2_5.json`). Onze sont nouveaux :
- `max_version_0`, `collect_version_literal_0`, `u2_version_literal_0` ;
- `version_error_as_refusal` ;
- `error_text_not_recorded`, `error_text_not_redacted`, `redact_long_40`, `error_text_not_cut` ;
- `format_guard_removed`, `format_meta_unchecked`, `format_blocktime_unchecked`.

`message_echoed` a été réécrit sur le nouveau code : il était invalide au premier passage.

**Répétition :** journal 70055ab7….

## Driver A2r

`out_of_tree/cpmmpilot_run/step1_a2r.py`, sha 0ad766aa…, dérivé du driver A2 audité (21cff5e5). Seuls changent :
- `STEP1A2R_RESULT.json`, avec une seule exécution possible ;
- le contrôle du STOP −32015 précédent (58a5e547) ;
- l'absence de `collect/pre` ;
- `require_tx_format` ;
- `error_text`.
