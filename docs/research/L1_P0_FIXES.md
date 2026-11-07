# L1 — correctifs P0 du rejeu historique (migration, frais, sorties, bras MASTER)

Préparé le 2026-11-07 par RUGGER 01 sur la branche locale `claude/r01-l1-p0-fixes`,
issue de `fe8eb51` (PR #134). GitHub est inaccessible : rien n'est poussé.

Ces correctifs ne créent aucune autorisation et ne changent ni la catégorie ni le statut des
résultats. Tout reste `HISTORICAL_REPLAY` : aucune entrée dans le registre PAPER, aucun
compte dans la porte du Master, aucun trade opérationnel du Master. Les seuils protégés de
50 cycles qualifiés et de 20 créateurs ne changent pas.

## Invariants conservés

- Aucun paramètre pré-enregistré n'est modifié : `ReplayParams` a les mêmes champs, les
  mêmes valeurs par défaut et le même `params_sha256`.
- Les quatre bundles enregistrés (`validation/historical_replay_l1/RESULTS.json`) sont
  reproduits à l'octet près. `bundle_sha256` :
  - a : `fa86f314…` ;
  - b : `8f61ad57…` ;
  - c : `86436982…` ;
  - d : `400d003c…`.

  Les nouvelles clés du bundle (`excluded_pools`, `exit_options`, `flags.migration_rule`,
  `flags.pool_exclusion_rule`) n'apparaissent que lorsqu'elles s'appliquent.
- **Constat préexistant (O3), dépendance à la version de Python.** Les empreintes
  enregistrées b, c et d ont été produites sous Python 3.12 ou plus. Sous Python 3.11 (version
  de la CI `rugger-isolated-ci.yml`), `sum()` additionne les flottants sans compensation :
  `top_holder_share` diffère alors au dernier bit, et seuls les `features_sha256` par décision
  changent. Scores, intentions, sorties et totaux sont identiques. C'est déjà le cas à
  `fe8eb51`, et les correctifs reproduisent `fe8eb51` à l'identique sous 3.11, 3.12 et 3.13.
  Le test épingle donc trois choses :
  - une empreinte structurelle, sans `features_sha256`, commune à toutes les versions ;
  - les empreintes complètes enregistrées, sous Python 3.12 ou plus ;
  - les empreintes complètes propres à Python 3.11.

  Corriger le calcul (sommation exacte) modifierait des caractéristiques du Master : cette
  décision revient au propriétaire et à RUGGER 02.
- Aucune règle n'est réglée sur les performances observées.

## 1. Migration et exclusions de pools

**Défaut.** La courbe refuse l'achat qui franchit la frontière de migration :
`check_trade` produit `curve_refused:buy_crosses_migration_boundary` et
`build_timeline` rejette l'événement. L'historique est alors incomplet, et `replay()` lève
`timeline_incomplete` : tout le rejeu échoue au lieu de traiter le pool.

**Règle** (`usable_timeline`) :
- un historique complet est utilisé tel quel ;
- un historique dont **le seul** défaut est l'achat qui franchit la frontière se termine
  juste avant cet achat. Cela suppose qu'aucun événement valide du pool ne se trouve à la
  même position `(slot, transactionIndex)` ou après. Le pool reçoit alors un enregistrement
  `migration` (règle, signatures et position de la frontière, `max_progress_ppm`). Une
  position encore ouverte à la frontière devient `migrated_unpriced` : P&L nul, valeur de
  marché dans `mark_pnl_lamports`, jamais un cycle clos ;
- tout autre historique incomplet **exclut** le pool. Il est listé dans `excluded_pools`
  avec tous ses motifs, sans jamais être rejoué partiellement. Motifs possibles :
  - `signatures_incomplete` ;
  - `transactions_missing:n` ;
  - `undecodable_transactions:n` ;
  - `timeline_gaps:…` ;
  - `rejected_events:…` ;
  - `events_after_migration_boundary` ;
  - `history_incomplete` ;
- invariant : `pools + excluded_pools == pools du MANIFEST`, sinon
  `pool_accounting_mismatch`.

**Comptabilité.** Seul un cycle `closed` a un `pnl_lamports`. Une position `open_at_end`
garde sa valeur de marché à part, dans `mark_pnl_lamports`, hors de tout total. Avant ce
correctif, une position ouverte recevait un P&L, mais elle n'entrait dans aucun total
enregistré, puisqu'aucune variante n'avait d'entrée.

Les pools engagés ne contiennent aucune migration ni aucun historique incomplet. Les tests
fabriquent donc un vrai achat plafonné : après son passage, la courbe est entièrement
vendue, et `check_trade` le refuse avec le motif exact.

## 2. Estimation causale des frais

**Défaut.** `implied_fee_rate_ppm` renvoie le **plus petit** taux compatible avec le frais
arrondi d'**un** événement. Un événement minuscule, par exemple 80 lamports avec 1 lamport
de frais, donne 1 ppm, et c'est ce taux qui était appliqué à nos propres ordres.

**Règle** (`causal_fee_rate`, `fee_rate_estimator='causal_interval'`) :
- chaque événement porteur de frais admet l'intervalle exact des taux entiers `r` tels que
  `ceil(base × r / 10⁶) = frais` ;
- on remonte depuis la décision et on intersecte ces intervalles tant que l'intersection
  reste non vide. On obtient ainsi la plus longue série **contiguë** cohérente qui se
  termine à la décision : un changement de taux plus ancien ne la pollue pas, et on ne
  saute jamais par-dessus ;
- le taux retenu est la **borne haute** de l'intersection, choix prudent sur les coûts ;
- sans aucun événement porteur de frais, le taux de l'événement de décision est conservé,
  avec une règle explicite qui le signale ;
- seuls les événements `events[:k+1]` sont lus.

La preuve est enregistrée dans `fee_rate_evidence` : règle, intervalle, événements utilisés
et ignorés. Un taux explicite (`fee_rate_ppm`) reste prioritaire. Le défaut
d'`ExecutionModel` ne change pas (`event_at_decision`) pour les autres utilisateurs ; seul
le rejeu L1 utilise `causal_interval`.

## 3. Stop suiveur et durée maximale de détention (désactivés par défaut)

`ExitOptions(trailing_stop=False, max_hold=False)`, avec les options
`--trailing-stop` et `--max-hold` de `tools/historical_research_replay.py`.

Les valeurs `trailing_stop_pct` et `hold_seconds` viennent du plan du scoreur, figé à la
décision d'entrée (`reference_exit_conditions`). La règle est celle de
`bot.master_positions.choose_frozen_position_action` :
- le stop suiveur s'arme quand le pic dépasse le prix d'entrée, et se déclenche quand
  `prix ≤ pic × (1 − pct/100)` ;
- la durée maximale se déclenche quand `âge ≥ hold_seconds` ;
- l'ordre de priorité est : stop-loss, stop suiveur, durée maximale, prise de profit, puis
  horizon de recherche `exit_horizon_ms`.

La prise de profit et le stop-loss ne peuvent pas être atteints en même temps : les sorties
par défaut sont donc inchangées. Les prix utilisés sont les cours spot des événements réels,
sans notre propre impact ; le prix d'entrée est le cours spot de l'événement derrière lequel
notre achat s'exécute.

**Limite.** `hold_seconds` du scoreur vaut 900 à 2700 s, alors que l'horizon pré-enregistré
est de 30 s. Avec les paramètres P0, `max_hold` ne peut donc jamais se déclencher. Il
n'agit qu'avec un horizon plus long, déclaré explicitement et inclus dans l'empreinte. Ce
correctif ne fait pas ce changement de paramètre.

## 4. Bras MASTER distinct : BLOQUÉ

**Constat** (`bot/p4_experiment.py:153-181`) :
- `decide_prefix` exige `base.enter` et une position de source connue pour toutes les
  stratégies ;
- `early_sniping` entre alors sans autre condition ;
- `confirmed_momentum` exige une confirmation : 15 s, un prix plus élevé et au moins
  2 acheteurs indépendants ;
- `adaptive_hybrid` exige `quick`, c'est-à-dire `prior_launches ≥ 2`, ou la même
  confirmation. Or le rejeu fixe `prior_launches = 0`, faute d'historique du créateur ;
- la réunion des intentions du scoreur Master est donc **égale** à `early_sniping` à
  chaque décision. Le test `test_master_union_of_intents_equals_early_sniping_at_every_decision`
  le vérifie sur les variantes b, c et d ;
- les sorties suivent le même plan du scoreur ; les deux bras sont donc identiques.

Le seul Master opérationnel préexistant est `MasterDecisionOrchestrator.evaluate`. Il est
déjà journalisé à chaque décision (`operational_master_action` et
`operational_master_reasons`). Sur la variante c, il répond `NO_TRADE` à 105 décisions et
`WAIT` à 8. Chacune des 113 décisions manque de cinq preuves d'admission, qui n'existent
pas hors ligne :
- santé opérationnelle ;
- capital et limites de pertes ;
- coûts additionnels ;
- preuve passée qualifiée, avec la porte 50/20 ;
- qualification identité, offre et création de la source.

Sa sortie exige en plus des cotations de sortie exactes et fraîches.

**Conclusion.** Construire un bras MASTER qui trade exigerait de fabriquer ces entrées : ce
serait une différence artificielle, que le mandat interdit. On conserve donc un seul bras de
recherche du scoreur ; le doublon `master`/`reference` est documenté et protégé par un test
d'invariant. Le supprimer ou le renommer serait une évolution versionnée du schéma
`rugger-historical-research-replay-v1` qui changerait les empreintes : cette décision
revient au propriétaire.

## Points restant ouverts

- Les événements réels rejoués sur la courbe décalée utilisent toujours leur taux minimal
  implicite (`_replay_real`). Chacun reproduit exactement l'événement d'origine, mais un
  écart d'arrondi reste possible sur la courbe décalée.
- Aucune migration réelle n'est présente dans les données engagées. La règle n'est testée
  que sur un achat plafonné synthétique, et doit être validée sur un pool réel migré
  collecté par RUGGER 03.
- O3 : la reproductibilité au bit près des variantes b à d dépend de la version de Python
  (voir « Invariants »). Il faut choisir entre figer la version de Python et passer à une
  sommation exacte des parts de détenteurs.
- Les commits de RUGGER 03 (T-0027, T-0030, T-0032 à T-0034) sont absents de cet
  environnement, et GitHub est suspendu.
