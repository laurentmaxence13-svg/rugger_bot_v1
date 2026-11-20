# w1aux v7.6 — ledger reprenable après un redémarrage (P1-bis, R02 bac856e7)

**Écrit seulement. Aucune exécution sur W1 avant l'audit de RUGGER 02 et son PASS explicite.** Le code est hors de
l'arbre gelé `aff97638`. Aucun fichier gelé n'est modifié.

## Pourquoi

Le ledger séquentiel ne garde rien avant sa fin. Deux essais sur W1 ont été perdus : coupés après 2 h, puis après
plus de 4 h 55 par un redémarrage de la plateforme. La borne haute est de 130 h de calcul d'affilée.

## Ce qui change

- **Tous les fichiers de v7.5 sont repris à l'identique**, donc ceux de v7.4 aussi (voir `MANIFEST_v76.txt`). C'est
  le cas de `ledger.py` 115f3cb5, de `ledger_parallel.py` 5c4ad5fa (audité, 07b3a3e6) et de `dayj.py`.
- **Ajouts** : `w1aux/ledger_resume.py` et `w1aux/tests/test_ledger_resume.py`.

## Principe

Le module suit le schéma de `ledger_parallel`, mais sur **un seul processus, sans fork** :

1. **PROBE** : `build_ledger` v7.4 tourne avec un enregistreur à la place de `derive_l1_plans`.
2. **COMPUTE** : dans le processus et dans l'ordre des appels, `derive_l1_plans` v7.4 calcule chaque appel absent du
   cache. Chaque résultat est écrit **dès qu'il est calculé**.
3. **ASSEMBLY** : `build_ledger` v7.4 tourne à nouveau, avec la même recherche contrôlée par rang que `ledger_parallel`.

La **clé d'un appel** est le sha256 d'une description canonique de :

- le pool et le sha256 de l'archive (archives paresseuses exigées) ;
- l'empreinte canonique de la timeline (tous ses champs) ;
- les paramètres du rejeu ;
- la série (sha256, âge maximal, confiance maximale) ;
- l'historique des créateurs (sha256, label) ;
- les index de décision triés ;
- le **rang d'occurrence** de l'appel dans le build : L1 et L1_event_horizon ont des appels identiques et ne
  partagent jamais un résultat, conformément au refus de P2 ;
- les sha256 de `ledger.py` et de ce module, et l'empreinte du code gelé.

## Règles du cache (`<racine>/ledger_resume/`, hors de `ledger/`)

Ce répertoire n'entre dans **aucun** digest d'étape (ledger compris), ni dans `SHA256SUMS_PRELIMINAIRE.json`, ni
dans le hachage de la lecture. C'est une condition de R02 (95c5e9e7), testée dans w1x 0.1.4.

- `OPENINGS.jsonl` reçoit une ligne par exécution qui ouvre le cache. Le nombre de reprises vaut ce nombre de
  lignes moins 1.
- **Liaison** : `META.json` lie le cache au digest trials de la racine et au code. Un autre lien ou un autre code est
  refusé, et un cache sans `META.json` aussi.
- **Ordre d'écriture** : d'abord la ligne d'index (clé, sha256 du contenu), avec fsync. Ensuite le fichier
  temporaire, avec fsync, puis le rename. Une interruption ne peut donc pas laisser de fichier orphelin.
- **Entrée invalide** : un fichier absent, altéré, tronqué ou portant une autre clé rend l'entrée invalide. Elle est
  rejetée, comptée, puis recalculée.
- **Dernière ligne d'index tronquée** (ajout interrompu) : elle est ignorée, et l'index est réécrit avant tout ajout.
  Toute autre ligne illisible entraîne un refus.
- **Fichiers temporaires** : les fichiers `*.tmp` et l'index en cours de réécriture laissés par une interruption sont
  supprimés et comptés.
- **Fichiers refusés** :
  - tout `*.pkl` sans ligne d'index ;
  - tout autre fichier ;
  - toute clé indexée qui n'est pas une clé de ce build (cache étranger).

## Mémoire

- Un seul processus, avec des archives paresseuses ; le ledger v7.4 actuel charge tout d'un bloc. Mesuré sur des packs
  synthétiques (×12 et ×150) : pic égal au séquentiel à +2 % près, sans économie démontrée à cette échelle.
- La garde reste celle de l'étape explore, sans dérogation. Il n'y a pas de garde workers.
- La PROBE garde les timelines des pools avec entrée. Le majorant estimé pour tout W1 est d'environ 0,85 Go.
- Mesure : voir `MESURE_MEMOIRE_v76.json`.

## Preuves

Tests hors ligne, CPython 3.12.3, `-W error`. Partout, les octets de `ledger.json`, `ledger.md` et du résumé sont
identiques au ledger v7.4 séquentiel chargé d'un bloc. Couverture :

- pack gelé, avec et sans rapport. Une seconde exécution relit les 4 résultats sans rien calculer ;
- clés distinctes pour les 4 appels, dont les deux appels identiques ;
- pools sans entrée (pack synthétique ×2), pool absent de l'export, pool migré, pool exclu ;
- SIGKILL au 3e appel puis reprise : 2 résultats repris, 2 calculés, identité ;
- entrées altérées, tronquées, absentes ou portant une autre clé : rejet puis recalcul, identité ;
- écriture interrompue (`.tmp` et dernière ligne d'index tronquée) : nettoyage, reprise, identité ;
- refus, sans fichier écrit :
  - pour le cache : `.pkl` orphelin, fichier inconnu, entrée étrangère, ligne d'index illisible au milieu, autre
    liaison, `META.json` absent, autre code ;
  - pour l'appel : divergence entre PROBE et ASSEMBLY ;
  - pour l'usage : liaison exigée, réentrance (y compris avec `ledger_parallel`), module `ledger.py` différent de v7.4.

Défauts volontaires : voir `MUTATIONS_v76.json`.
