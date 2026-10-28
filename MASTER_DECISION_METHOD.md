# Master Trader : propositions PAPER en shadow

`bot/master_decision.py` et `bot/master_positions.py` sont des fonctions de
proposition déterministes au-dessus des trois adaptateurs P4 existants. Elles
n'effectuent aucun accès réseau, aucune signature et aucun règlement financier.
Le moteur PAPER, son inventaire natif et ses protections restent l'autorité de
règlement. Le statut de politique est toujours
`EXPERIMENTAL_SHADOW_NOT_PROMOTED`; une sortie de ces fonctions n'active rien.

## Core

`MasterDecisionOrchestrator().evaluate(frame, history=(), inventory=None,
health=None, capital=None)` renvoie une décision sérialisable : `ENTER`, `WAIT`
ou `NO_TRADE`, une stratégie sélectionnée, douze questions documentées, les
alternatives et quatre tailles au plus. Les variantes sont `early_sniping`,
`confirmed_momentum` et `adaptive_hybrid`. Une priorité de régime figée choisit
entre variantes admissibles; il n'y a pas de maximisation du gain affiché ni
d'appel à un modèle de langage dans cette boucle. L'historique contient au plus
32 observations et seuls des préfixes disponibles, de même identité et aux
features qualifiées à leur date, influencent le régime.

Une proposition d'entrée exige le veto existant levé, des états de santé et de
capital récents (5 secondes au plus), les limites financières connues, une bank
admissible et ses preuves déclarées d'identité/création/supply, les frais
additionnels connus, des quotes fraîches de quantité exacte et une référence de
recherche passée associée au hash de politique. Cette dernière exige au moins
50 cycles et 20 groupes de créateurs indépendants. Ce sont des seuils de
recherche expérimentaux, pas une certification de rentabilité. Une référence
fournie par l'appelant n'est pas authentifiée par cette fonction. Une fixture
synthétique ne peut être réétiquetée comme observation de marché.

Les coûts de courbe viennent de `assess_curve_costs` et du modèle entier
achat/revente sur un même état cohérent de réserves. Les devis externes restent
des devis indicatifs conservés, de quantité exacte; aucune règle de trois ne
produit un devis de taille différente. Les inconnues restent explicites. La
comparaison précoce contre attente demeure `UNKNOWN` sans preuve causale.

## Positions

`evaluate_position_plan(frame, inventory, health=None)` réutilise l'inventaire
atomique et `qualify_inventory_exit`, avec les frais et l'allocation cumulée
exacte du coût de revient. Actions : `HOLD`, `REDUCE`, `TAKE_PROFIT`, `EXIT`,
`EMERGENCY_EXIT`, `WAIT_FOR_DATA`. Les seuils TP/SL/trailing/durée viennent du plan
figé d'entrée et ne sont pas réécrits. Une détérioration du momentum et des flux
propose la plus grande quantité partielle déjà cotée, jamais une fraction
fabriquée d'un devis entier. Un objectif USD atteint ne suffit pas à déclarer un
bénéfice net en SOL.

L'urgence, le stop, le trailing et la durée maximale sont évalués avant le veto
aux nouvelles entrées. Une santé dégradée ne supprime donc pas une intention de
protection. Un devis manquant conserve l'intention `EXIT`/`EMERGENCY_EXIT` et ses
refus sans créditer des produits. `conditional_quote_qualified` et l'alias
`executable_quote_qualified` signifient seulement que les preuves du devis ont
passé cette qualification : financement, version d'inventaire, déduplication et
persistance atomique doivent encore passer dans le ledger existant. Aucun fill
ni règlement n'est garanti ou enregistré ici.

## Reproduire les tests ciblés

```sh
python -B tools/offline_check.py -q tests/test_master_decision.py tests/test_master_positions.py -p no:cacheprovider -W error
```

Les fixtures positives testent des branches fonctionnelles avec une preuve
historique explicitement synthétique; elles ne constituent pas des cycles P3.
P3 reste ouvert, aucun cycle économique de marché strictement qualifié n'est
ajouté par ces composants et aucune politique active n'est promue.
