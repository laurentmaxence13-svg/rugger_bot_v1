# paperstream 0.5.2 — le terme dominant sur W1 : as_of de la série SOL/USD (BROUILLON, plan validé par R02 à 17:15Z)

La 0.4 reste la seule version du run W1 et de son contrôle. Le run 0.5.1 en cours n'est pas touché : son verdict
(identité et mémoire) sera rendu tel quel.

## Constat

- **Aucun gain de la 0.5.1 sur les géants W1.** R03, à 17:10Z : après 1 h 40, la 0.5.1 en était exactement au même point
  que la 0.4 au même moment.
- **Cause, établie dans le code.**
  - `_PoolObserver._evaluate` appelle `_past_prices(history[:-1], sol)` (historical_research_replay.py:475).
  - Cette fonction appelle `SolUsdSeries.as_of` pour CHAQUE événement passé (l. 416-427), à chaque décision complète.
  - `as_of` parcourt les points LINÉAIREMENT (sol_usd_series.py:158-170). Sur W1, il y en a 21 937.
- **Mon erreur de méthode.** Le banc d'essai de la 0.5 et de la 0.5.1 utilisait la série du selfcheck, qui n'a QU'UN
  point : ce terme y était invisible.

## Ce que fait la 0.5.2

Elle ajoute deux fonctions pures au cache par pool (`fast.py`), avec les mêmes règles qu'en 0.5 : clé sur l'identité de
l'objet avec une référence forte, mode verify, fonctions restaurées.

- **`SolUsdSeries.as_of(slot, transaction_index, decision_ms)`.**
  - C'est une méthode d'un dataclass gelé. Son résultat ne dépend que de ses arguments et des champs gelés.
  - Dans `_past_prices`, les arguments sont ceux de l'événement PASSÉ : son slot, son indice et
    `block_time * 1000 + receipt_latency_ms`. Ils sont constants d'une décision à l'autre, donc la clé se répète.
  - Le point rendu est le dict de la série lui-même, c'est-à-dire le même objet que celui du code gelé.
  - Ce n'est donc pas une réimplémentation : vérifié dans le code, comme R02 l'avait demandé (condition 2).
- **`_PoolObserver._quote(event, sol)`.** Il rend deux floats, avec une clé (événement, observateur, taux).

## Mesures (fixtures, CPython 3.12.3, série synthétique `bigseries`)

| Points de la série | Gelé | Avec cache 0.5.2 | Rapport | Identique |
|---|---|---|---|---|
| 1 (selfcheck) | 2,33 s | 0,45 s | ×5,2 | oui |
| 2 000 | 8,07 s | 0,50 s | ×16 | oui |
| 21 937 (taille W1) | 76,9 s (80,8 s dans le test) | 1,99 s (2,5 s) | ×38 (×32) | oui |

- Dans le code gelé, le temps passe de 2,3 s à 77 s quand la série grandit : `as_of` domine.
- **Aucune promesse sur W1.** Ces mesures portent sur 3 pools de fixtures. Le gain réel sur W1 se mesure seulement sur
  le GO de R02, par la vérification des 3 sha.
- Avec le cache, il reste un parcours par événement distinct, soit O(k · m). Un `bisect` le supprimerait, mais ce serait
  une réimplémentation : elle demanderait des tests d'équivalence exhaustifs et n'est pas proposée ici.

## Preuves

- **69 tests** sous `-W error`. Les tests de la 0.5.2 portent sur les points suivants.
  - **Identité octet pour octet :** bundle_sha256 et JSON strict.
    - Avec une série de 2 000 points, contre le rejeu gelé direct : en lot, en flux, et en flux lent, avec 1 et 2 workers,
      et des journaux identiques.
    - Avec une série de 21 937 points, en lot.
  - **Mode verify** avec une série de 1 000 points.
  - **as_of :** il rend le même objet point, il est installé puis restauré, et un `decision_ms` différent à la même
    position donne `sol_usd_stale` (rien n'est servi à tort).
  - **_quote :** un même événement à deux taux donne deux résultats (verify).
- **Mutations : 4/4** sur les ajouts (MUTATIONS_paperstream_v052.json) :
  - caches non installés ;
  - caches non restaurés ;
  - `decision_ms` absent de la clé ;
  - taux absent de la clé.
- Les mutants de la 0.5 et de la 0.5.1 portent sur du code inchangé.
- `bigseries` ne sert qu'aux tests : ce n'est jamais une entrée d'un run W1 ou P0.

## 0.5.2.1 (réserve mineure de R02, 18:03Z)

- **La réserve.** La clé de `_quote`, (id(observateur), taux), ne gardait PAS de référence forte à l'observateur.
- **La correction.** `Memo.get(..., owner=...)` garde maintenant l'objet `owner` dans l'entrée. L'entrée n'est servie que
  si l'événement ET l'observateur sont exactement ceux de l'appel. `_quote` passe `owner=self`. Le schéma devient
  `paperstream-v0.5.2.1`.
- **Le test.** Il force la réutilisation de l'identifiant : une entrée dont la clé porte les mêmes id, mais qui contient
  un autre observateur, est refusée, recalculée, puis remplacée.
- **Preuves.**
  - 70 tests sous `-W error`.
  - Mutations : 7 sur 7 (MUTATIONS_paperstream_v0521.json). Ce sont les 4 de la 0.5.2, plus le propriétaire non vérifié,
    le propriétaire non gardé (l'ancienne clé `id(self)`), et l'objet non vérifié.
  - L'ancre du mutant `memo_object_unchecked` du runner de la 0.5 a été mise à jour (la ligne a changé).
