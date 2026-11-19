# w1aux v7.5 — ledger parallèle par pool (option P1, R02 0c51450f)

**Écrit seulement. Aucune exécution sur W1 avant l'audit de RUGGER 02 et son PASS explicite.** Hors de l'arbre gelé
`aff97638` ; aucun fichier gelé n'est modifié.

## Ce qui change par rapport à v7.4

- **Tous les fichiers de v7.4 sont repris à l'identique, octet pour octet** (voir `MANIFEST_v75.txt` : mêmes sha256
  que `MANIFEST_v74.txt`), dont `w1aux/ledger.py` (115f3cb5), `w1aux/parallel.py`, `w1aux/lazy.py` et `w1aux/dayj.py`.
  Les identités vérifiées par dayj et par w1x restent donc les mêmes.
- **Ajouts** : `w1aux/ledger_parallel.py` et `w1aux/tests/test_ledger_parallel.py`.

## Principe (le même que `w1aux.parallel`, déjà audité pour les trials)

`ledger.build_ledger` passe presque tout son temps dans `derive_l1_plans`. Cette fonction est pure : elle ne dépend
que de ses arguments (archive, timeline utilisable, paramètres, série SOL/USD, historique des créateurs, index de
décision). `build_ledger` l'appelle par son nom. Dans `parallel_ledger(workers)`, chaque appel de
`ledger.build_ledger` (et donc de `ledger.main`, inchangé) se fait en trois temps :

1. **PROBE** : le `build_ledger` d'origine, avec `derive_l1_plans` remplacé par un enregistreur. Celui-ci garde les
   arguments exacts de chaque appel et répond `{}`. Ce ledger-sonde est jeté. Les arguments sont donc calculés par le
   code v7.4 lui-même.
2. **COMPUTE** : le `derive_l1_plans` d'origine sur chaque appel enregistré, dans `workers` processus forkés
   (ProcessPoolExecutor en fork, gc.freeze avant le fork). Le plus gros pool passe d'abord, selon T² (T = nombre de
   transactions du pool). Le moindre échec (exception, processus tué) annule le reste et lève une erreur. Aucun
   résultat partiel n'est gardé, et aucun fichier n'est écrit : `main` n'écrit qu'après le retour de `build_ledger`.
3. **ASSEMBLY** : le `build_ledger` d'origine à nouveau, avec `derive_l1_plans` remplacé par une recherche. Elle
   vérifie que chaque appel, à son rang, a les mêmes arguments que l'appel enregistré : archive par pool et sha256,
   timeline par égalité de dataclass, paramètres par égalité, série par identité, historique des créateurs par
   sha256 et label, index par égalité. Elle exige aussi que tous les résultats soient utilisés. Le ledger est donc
   assemblé par la boucle v7.4, dans son ordre.

Il y a toujours un appel par pool et par bundle L1, comme en v7.4. Aucune passe n'est partagée entre bundles :
l'option P2 a été refusée par R02.

Les archives sont chargées paresseusement (`w1aux.lazy`, déjà prouvé équivalent pour le ledger), donc le parent
n'en garde aucune. En revanche, les timelines enregistrées des pools avec entrée restent en mémoire jusqu'à
l'assemblage. Il y a deux passes de lecture de plus que le séquentiel (PROBE et ASSEMBLY), sans observateur.

## Preuves (tests hors ligne, CPython 3.12.3, `-W error`)

Dans tous les cas, `ledger.json`, `ledger.md` et la ligne de résumé de `ledger.main` sont identiques octet pour
octet au ledger v7.4 séquentiel et chargé d'un bloc (ce que lance aujourd'hui l'étape exploratoire). Cas couverts :

- pack gelé (PASS, 9 cycles), avec 1, 2 et 4 processus, avec et sans rapport ;
- plusieurs bundles L1 entrés sur un même pool : 4 appels sur DVP426, dérivés séparément ;
- pool absent de l'export ;
- pool exclu ;
- pool migré ;
- pools sans aucune entrée (pack synthétique ×2), avec 1, 2 et 4 processus.

Autres vérifications :

- les erreurs d'entrée de v7.4 restent les mêmes (`bundle_file_changed`, `bundle_internal_hash_mismatch`,
  `series_is_not_the_one_replayed`), sans fichier écrit ;
- un processus qui lève une exception, et un processus tué par SIGKILL : échec complet, sans fichier ;
- une divergence entre PROBE et ASSEMBLY, et des résultats non utilisés, sont refusés ;
- garde-fous : nombre de processus, réentrance, module `ledger.py` différent de v7.4, archives paresseuses ;
- ordonnancement : chaque résultat est rendu au rang de son appel, quel que soit le nombre de processus.

- comparaison des arguments nommés et refus d'un appel sans résultat (tests unitaires) ;
- relevés : nombre d'événements des timelines gardées par la PROBE, pic du parent après la PROBE, pic de chaque
  processus de calcul (`STATS`).

Défauts volontaires : voir `MUTATIONS_v75.json`.

## Usage

Dans du code : `with ledger_parallel.parallel_ledger(4): ledger.main([...])`. Pour l'étape exploratoire,
utiliser le lanceur de w1x 0.1.3 (`python -B -m w1x.ledger_par step --ledger-workers N -- <arguments d'explore>`),
qui ajoute une garde mémoire pour les processus de calcul, sans dérogation possible.
