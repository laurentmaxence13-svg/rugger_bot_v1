# cpmmpilot 0.2.7 — réponses tronquées, comptes par pool, textes T2 (R03), HORS LIGNE

Cette version fait suite au STOP de T2 (24/11 à 18:22:22Z). La réponse HTTP avait été tronquée (`IncompleteRead`), et aucun compte n'avait été conservé.

## Changements depuis 0.2.5

**0.2.6**
- `rpc.AUTHORIZED_TEXT_SHA256` reçoit le texte T1/T2 du propriétaire (b75e657a), et `AUTORISATION_T1_T2.txt` est ajouté au paquet.
- `budget` : stage `t2` et `T2_CAP = 1 470`.

**0.2.7**
- `rpc` : toute `http.client.HTTPException` (IncompleteRead, RemoteDisconnected, BadStatusLine) donne `RpcError('response_truncated')`, sans message ni cause.
- `step1.count_24h(..., checkpoint=None)` : les comptes sont écrits APRÈS chaque pool (`per_pool`, `pools_done`, `pools_total`, `t0_time`). Aucune signature n'est écrite.
- Le texte T2 bis du propriétaire (option (b), 24/11 à 18:56:59Z, sha cae25a3c) est ajouté à `AUTHORIZED_TEXT_SHA256`, et `AUTORISATION_T2_BIS.txt` est livré dans le paquet.

## Vérifications (hors ligne, `unshare -rn`)

- Tests : 55 sur 55.
- Mutants : 76 sur 76 tués (`MUTATIONS_cpmmpilot_v0_2_7.json`). La liste complète couvre aussi les lignes de 0.2.6, dont le passage propre n'avait pas été mené à terme. Nouveaux mutants : `t2_cap_1500`, `http_exception_uncaught`, `checkpoint_not_written`.

## Driver associé

`out_of_tree/cpmmpilot_run/activity_l2.py`, sha 9b2c0487.
- LiveRpc s'ouvre avec `AUTORISATION_T2_BIS.txt`.
- `RETRY_ON_TRUNCATED = 1`.
- Le plafond est cumulé : 1 470 − 186 = 1 284.
- En cas de STOP, le partiel est publié.
- Tests : 13 sur 13. Mutants : 23 sur 23.
