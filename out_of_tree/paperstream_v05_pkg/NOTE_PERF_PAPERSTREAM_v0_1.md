# paperstream : analyse de performance sur les gros pools et brouillon 0.5 (v0.1)

RUGGER 01, 21/11. Cette note répond à la directive du propriétaire relayée par R04 (18:50Z), points 1 et 2.

- **Ce qui n'est pas touché.** Le run W1 en cours, le code paperstream 0.4 audité et le code gelé.
- **Où vit la 0.5.** C'est un brouillon séparé, dans `out_of_tree/paperstream_v05_pkg`. Il est non audité et n'est pas
  destiné au run W1 en cours.

## 1. Où passe le temps (mesuré sur les fixtures, arbre gelé aff97638, CPython 3.12.3)

Rejeu L1 gelé : `run_replay`, avec la série du selfcheck, l'historique créateur et le placebo. Profil cProfile :

| Poste | Part du temps |
|---|---|
| `bot.market.replay.replay` et la machine d'états (lot) ; `StreamTrade` (flux) | **≈ 0 %** |
| `_PoolObserver._evaluate` (observateur MASTER gelé, mis en cache par indice et partagé par les 3 bras) | **≈ 100 %** |
| … dont `build_features` → `wallet_graph_snapshot`, `classify_creator_behavior`, `_contains_mint`, `json.dumps(tx)` | ≈ 65 % |
| … dont `MasterDecisionOrchestrator.evaluate` (`_safe`, récursif) | ≈ 25 % |
| … dont `_past_prices` (as-of SOL/USD par événement passé) | ≈ 7 % |

**Le terme quadratique.**
- **Mécanisme.** À CHAQUE décision k, le code gelé reparcourt TOUTES les transactions passées du pool. Il reconstruit
  aussi l'historique (`tuple(history)`, `inputs`, `sorted(signatures)`). Il recalcule enfin, pour chaque transaction, des
  fonctions qui ne dépendent que de cette transaction : `str(tx)`, `str(tx).lower()`, `json.dumps(tx)` et les soldes.
  Le coût d'une décision est donc ≈ a·k, et celui d'un pool de n événements ≈ a·n²/2.
- **Mesure** (pool de 100 événements, coût marginal d'un événement sur la seconde moitié) : a ≈ 0,168 ms par événement
  de plus.
- **Conséquence.** Un pool de 6 000 à 7 000 événements coûte ≈ 0,168 ms × n²/2, soit 50 à 70 min. C'est cohérent avec
  les 3 pools au-delà de 66 min relevés par R03. Les relevés détaillés (`ps04_monitor.log`, demandés à R03 en
  métadonnées seules) permettront de caler a sur W1.
- **Le terme est le même en lot et en flux.** Il est dans le code gelé et non dans le moteur de flux. Le rejeu W1 en flux
  dure donc à peu près ce que durait le rejeu L1 de l'étape trials. La copie supplémentaire de StreamTrade
  (`tuple(self.events[:j+1])`) est négligeable devant `_evaluate`.

## 1 bis. Relevés de R03 sur le run W1 en cours (19:20Z, métadonnées seules, pools désignés par leur rang)

- La durée ne suit ni la taille, ni les signatures, ni les transactions. Elle va de 2,4 à 2 229 secondes pour 1 000
  transactions, soit un écart de ×900.
- Exemples :
  - le rang 7 (2 156 transactions) prend 80 min ;
  - le rang 3 (3 322 transactions) prend 0,3 min ;
  - les rangs 1 et 2 (7 694 et 2 858 transactions) tournaient encore après 1 h 40.
- Les 4 workers sont à 100 % du CPU, sans attente d'entrée-sortie. La mémoire de chaque worker est de 235 à 376 Mo.

**Lecture** (compatible avec le code gelé, à confirmer par un compteur technique) :
- **Ce qui rend un pool cher.** Le coût dépend du nombre de décisions qui vont jusqu'au calcul complet
  (`build_features` puis `evaluate`), et non du nombre de transactions.
  - Une décision s'arrête tôt dans trois cas, sans calcul de features : identité de création indisponible, événement
    qui n'est pas le dernier de sa transaction, ou refus de la série SOL/USD (point trop vieux, confiance insuffisante).
  - Un bras qui est entré ne réclame plus d'observation.
- **Ce qui rend un pool bon marché.** Il ne fait presque que des attentes courtes.
- **Ce qui rend un pool lent.** Il atteint n décisions complètes, chacune reparcourant ses T transactions, pour un coût
  ≈ a·n·T. Le rang 7 donne a ≈ 2 ms par événement. C'est environ 12 fois la pente des fixtures, ce qui est cohérent avec
  des transactions W1 plus grosses : `str(tx)` et `json.dumps(tx)` coûtent en proportion de leur taille.
- **Conséquence pour P-1.** Plus la sérialisation par transaction pèse lourd, plus la mémorisation rapporte. Le gain sur
  W1 devrait donc dépasser le ×3 des fixtures. C'est à mesurer, et non à supposer.
- **Compteur technique proposé pour une 0.5.1.** Il est hors identité et facultatif. Par pool, il donnerait :
  - le nombre d'évaluations complètes et d'attentes courtes ;
  - la durée ;
  - le rang de taille.

  Il serait écrit à part, sans aucun résultat. Cela permettrait de confirmer la lecture ci-dessus.

## 2. Brouillon 0.5 (préparé séparément ; StreamTrade et stream_replay inchangés)

| Id | Changement | Effet | Preuve |
|---|---|---|---|
| P-1 | `--fast-analyser`, **désactivé par défaut** : `paperstream.fast` mémorise les fonctions pures par transaction de l'analyseur gelé (`_contains_mint`, `classify_creator_behavior`, `_owner_balances`, `_is_swap`, `json.dumps(tx, separators)` de `wallet_graph_snapshot`) | **×3,1** sur les fixtures ; pente du terme quadratique de 0,168 à 0,073 ms par événement (**×2,3**), le gain grossissant avec la taille des transactions | octet pour octet : bundle_sha256 ET JSON canonique strict = rejeu gelé direct, sur les fixtures et sur un pack synthétique à 3 copies, en lot et en flux, avec 1 et 2 workers, avec checkpoint |
| P-2 | la série SOL/USD est chargée une seule fois par commande (la 0.4 la chargeait dans `main` puis dans `records`) | une lecture et une décompression de moins (environ 1,4 Mo gz) | test : `load_series` appelé exactement 1 fois |
| P-3 | `reconcile_all` : les journaux sont indexés une fois par (pool, bras), au lieu d'un parcours par cycle | O(n) au lieu de O(cycles × journaux) | test : même compte et mêmes refus (résidu, doublon) que `reconcile` |

**Sûreté de P-1.**
- **Clé du cache.** C'est (fonction, id(tx), arguments). L'entrée garde une référence forte à la transaction, et elle
  n'est servie que si `entrée.tx is tx`. Une adresse ne peut donc pas être réutilisée tant que l'entrée vit (testé).
- **Résultats mutables.** Ils sont rendus en copie (testé).
- **Le shim JSON.** Il ne mémorise QUE `dumps(dict, separators=(',', ':'))` et délègue tout le reste (testé).
- **Portée du cache.** Il y a un cache par pool (testé : 3 caches pour 3 pools), et rien n'est conservé d'un pool à
  l'autre.
- **Restauration.** Les fonctions gelées sont restaurées à la sortie (testé).
- **Mode `verify`.** Il recalcule chaque valeur servie et lève une erreur au premier écart (testé, et identique sur les
  fixtures).
- **Clé de checkpoint.** Le drapeau `fast_analyser` fait partie de la clé (une entrée sans P-1 n'est jamais servie à un
  run avec P-1, testé). Le sha du code de flux inclut le source de `fast.py`.

**Ce que P-1 ne retire pas.** Il reste dans le code gelé une part de ≈ 0,073 ms par événement : `_safe`, `_features`
de `p4_experiment` et `_past_prices`. Leurs entrées changent à chaque préfixe, donc la mémorisation ne s'y applique pas.
Pour aller plus loin, il faudrait réimplémenter l'observateur de façon incrémentale. Cela demanderait un plan à R02 et une
preuve d'identité beaucoup plus lourde. Ce n'est pas proposé ici.

**Tests et mutations.**
- 54 tests : les 42 de la 0.4, qui passent inchangés sur la 0.5, et 12 nouveaux, tous sous `-W error`.
- Mutations : 12 sur 12 détectées sur les parties nouvelles (MUTATIONS_paperstream_v05.json). Le premier run en détectait 10 ; 2 tests ont été ajoutés, puis les 2 mutants relancés sur les tests finaux sont détectés.

## 3. Usage

Rien n'est à lancer avant le PASS de R02 sur la 0.5. Une fois ce PASS obtenu, l'usage prévu est le suivant.
- **La 0.5 sert aux rejeux suivants, jamais au rejeu W1 en cours.** Exemples : P0, un W2 éventuel, un nouveau rejeu.
- **L'identité de P-1 se prouve sur des données réelles avant tout usage.** Il faut un run `--fast-analyser` dont le
  bundle est égal à un bundle gelé déjà ancré. Sur W1, ce serait 3409bf9d / 9eb43426 / c7556f14, mais seulement si R02
  et le propriétaire veulent bien une seconde passe.
- **P-2 et P-3 ne changent aucune sortie.**
