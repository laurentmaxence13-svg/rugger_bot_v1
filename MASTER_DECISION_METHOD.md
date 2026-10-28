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

## Régimes explicables et données de comparaison

La décision expose désormais `regime_assessment`, séparé du champ historique
`regime` et de sa priorité figée. Neuf situations peuvent coexister : activité
indépendante croissante sur lancement précoce, confirmation de momentum,
sur-extension, liquidité insuffisante, volatilité élevée, manipulation possible,
perte de momentum, coûts économiquement défavorables et données insuffisantes.
Chacune conserve `OBSERVED`, `NOT_OBSERVED` ou `UNKNOWN`, ses motifs, métriques,
identifiants source et date de disponibilité. `OBSERVED` veut dire que la
condition descriptive publiée est satisfaite; il ne confirme ni manipulation,
retournement, sortie future ou avantage économique.

`classification_policy_sha256` identifie les seuils descriptifs versionnés,
distincts de la politique de sélection. `classification_controls_entry` reste
false : cette extension ne modifie ni les priorités, ni les paramètres actifs,
ni l'identité des preuves de recherche de la politique. Les seuils sont des
hypothèses expérimentales à comparer sur des données indépendantes.

L'activité précoce demande deux observations causales, un lancement âgé au plus
120s, une augmentation du nombre déclaré d'acheteurs indépendants et du momentum
positif. Un nombre de transactions d'achat ne remplace jamais ce nombre de
participants indépendants. La confirmation réutilise l'adaptateur P4 existant.
La sur-extension reprend le seuil de momentum60s supérieur à30%; la volatilité
décrit une variation absolue adjacente supérieure à20%, pas un estimateur
statistique calibré. L'absence d'indicateur de coordination n'est décrite comme
non observée que si des données comportementales, de holders et de graphe
existent; elle ne prouve jamais une absence de manipulation.

La liquidité reste la capacité conditionnelle du modèle de courbe ou un veto
explicite du scorer. Une bank indisponible ne devient pas une preuve d'absence
de liquidité. Le caractère économiquement défavorable exige des frais connus et
une référence passée qualifiée : la comparaison de coûts seule ne fabrique pas
un rendement futur. Toutes les inconnues et les situations simultanées restent
consultables, même lorsqu'un régime principal est affiché.

`decision_evidence` fournit score, risques, stratégies admissibles, priorité
figée, frais inconnus, conditions TP/SL/trailing/durée du scorer et motifs
d'admission. `reference_score_intent` est explicitement l'intention du scorer,
avant contrôles opérationnels et ledger, pas l'ordre ou la décision complète du
moteur de référence. Les positions conservent leur plan d'entrée séparé et figé.

Les features futures ou invalides du frame courant ne peuvent plus influencer
la mesure de volatilité. Leur prix est exclu, comme les préfixes futurs ou
d'identité différente. Le hash du contexte fourni demeure une empreinte de
l'entrée, pas une attestation de validité de chaque donnée reçue.

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
