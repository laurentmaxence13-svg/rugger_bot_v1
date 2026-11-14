# OPTION NON APPLIQUÉE — export W1 « en flux » (voie A), 2026-11-14

**Statut : option à la décision du propriétaire. Rien ici n'est branché dans la chaîne W1, rien n'a été exécuté
sur des données W1.** RUGGER 02 (avis b98ce7e5, registre 6ff071be) classe cette voie comme un AMENDEMENT DU
PROTOCOLE v2.6.2 et non comme un correctif d'outillage : la règle R10 dit « export only through
w1_collection.export », et `backfill_export.py` fait partie de `collector_code` 9c69e482 ancré par le protocole.
RUGGER 02 recommande la voie B (machine à grande mémoire qui exécute le code gelé tel quel).

## Pourquoi cette option existe

Le 14/11 à 22:16Z, l'étape `export` de la chaîne officielle a été tuée par manque de mémoire (rc=137) :
`export_pools` gelé charge les 2 236 619 transactions de la fenêtre (environ 78 Go en mémoire, mesure de
RUGGER 03, pour 13,35 Gio disponibles).

## Ce que contient ce dossier

Le paquet w1aux v7.4 (commit 009de70e, inchangé : `dayj.py` de975525 n'appelle PAS ce module) plus deux fichiers :

- `w1aux/stream_export.py` : `export_pools` en trois passes (une transaction à la fois, puis un paquet de pools à
  la fois), qui appelle les fonctions gelées (`verify`, `compiled_launchlab_creations`, `extract_trade_events`,
  `account_keys`, `_signature_row`, `creation_quote_mint`) et écrit les mêmes archives, le même gzip et le même
  MANIFEST ; `streaming_export()` remplace `backfill_export.export_pools` le temps d'un bloc.
- `w1aux/tests/test_stream_export.py` : 10 tests, tous verts sur l'arbre gelé aff97638 (CPython 3.12.3, hors
  réseau). Chacun exécute l'export GELÉ et l'export en flux sur la même fenêtre vérifiée et compare tous les
  fichiers, le MANIFEST et la valeur renvoyée, octet pour octet : les trois pools certifiés (173 signatures dont
  59 échecs), ordre de lecture mélangé sur quatre segments, pool créé avant la fenêtre, quote non SOL, doublons de
  signature (copie exacte, copie modifiée lue avant ou après l'original, doublon de création), transaction
  étrangère avant la création, pool de plus de 3 000 transactions (plusieurs blocs gzip), mêmes refus que le gelé,
  référence de série SOL/USD, nombre de paquets et de processus variés ; un test vérifie qu'aucune transaction
  n'est conservée pendant la lecture.

## Ce qui manquerait avant toute application (si le propriétaire choisissait cet amendement)

- Décision explicite du propriétaire et amendement du protocole rédigé et ancré par RUGGER 02.
- Preuves de RUGGER 02 : pilote W1, pack P0 ouvert, cas adverses, sous-ensemble de W1 exporté par le gelé ET par
  le flux, invariants, mutations, mémoire mesurée.
- Le même traitement pour l'étape `series` (`w1_run.pyth_entries` charge les 718 183 transactions SOL/USD,
  environ 26 Go) : non écrit.
- Branchement dans dayj (nouvelle version, nouvel auto-contrôle, porte rejouée) : non fait.
- Cette option ne règle pas la mémoire de `trials`, `evaluate` et `ledger`, qui dépend du nombre de signatures
  exportées (règle D1 de RUGGER 02).
