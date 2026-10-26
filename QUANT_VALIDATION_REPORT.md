# Validation quantitative — premier protocole synthétique

26 octobre 2026. **Avantage économique réel : INSUFFICIENT DATA.**
**P3 / trading réel : NO-GO.**

Sources exécutées : `f1a1345f3a7c1871ef497c9d2ec1eb219c652a8a`.
Protocole figé avant expérience : `8530f2b982e657fe7cb3fe82c3d0ad5028edeffd`,
`rugger_synthetic_sol_v1`. Aucun paramètre ni critère n'a été modifié après
consultation des résultats finaux.

## Ce qui a été exécuté

Trois mondes entièrement inventés, avec seed 20261026 et 300 mints chacun :
null, momentum_linked, adverse. Ils partagent les mêmes tirages de base et sont
des contrefactuels appariés, pas trois marchés ou échantillons indépendants.
Trois règles fixes comparées sur développement par monde, soit **neuf candidats
de développement**, puis neuf sensibilités coûts/slippage du seul candidat figé
sur chaque test final, soit **27 évaluations finales préenregistrées**.

Chaque expérience a été rejouée une fois avec les mêmes arguments : fichiers
JSON identiques octet par octet. Ces trois relectures de répétabilité ne sont pas
de nouveaux essais de sélection ; aucun nouveau seed n'a été essayé pour améliorer
le résultat. Les tests unitaires du protocole sont consignés séparément.

Après groupement et purge : **169 train / 50 validation / 60 test final** dans
chaque monde. Le candidat retenu est cautious_momentum dans les trois cas.
Son P&L de validation au stress préenregistré est négatif dans les trois mondes :
−1,724606 / −1,134843 / −2,324606 SOL. Donc
**validation_positive=false partout**. Il est publié pour diagnostiquer
l'évaluateur, sans devenir une recommandation de trade.

## Résultats du test final

Budget initial 10 SOL, positions all-in fixes de 1 SOL, maximum trois positions.
Les rendements générés et les liquidités sont natifs SOL ; aucun prix USD réel
n'est converti implicitement. Ces règles de fixture diffèrent de l'allocation
dynamique du ledger de production.

| Monde synthétique | Exécutions / opportunités | P&L, coût 200 bps, slippage 0 | Rendement capital | DD réalisé | P&L, coût 1 000 bps + slippage 300 bps |
|---|---:|---:|---:|---:|---:|
| null, aucun lien programmé momentum/rendement | 18 / 60 | −0,054187 SOL | −0,5419 % | 2,3938 % | −2,034187 SOL |
| momentum_linked, lien artificiel programmé | 18 / 60 | +1,051327 SOL | +10,5133 % | 0,7796 % | −0,928673 SOL |
| adverse, dérive négative et chocs de fixture | 18 / 60 | −1,134187 SOL | −11,3419 % | 11,3470 % | −3,114187 SOL |

Le témoin sans trading reste à 10 SOL et zéro P&L. Le résultat positif du monde
momentum_linked à faible coût provient d'un lien introduit par construction ;
il ne démontre aucun avantage de Rugger sur un marché. Il ne permet pas non plus
de remplacer après coup le coût de sélection de 1 000 + 300 bps par le coût
plus favorable affiché dans le tableau.

À 200 bps sans slippage additionnel :

| Mesure conditionnelle aux trades exécutés | null | momentum_linked | adverse |
|---|---:|---:|---:|
| Espérance observée par trade, SOL | −0,003010 | +0,058407 | −0,063010 |
| Profit factor | 0,8978 | 8,2138 | 0,0668 |
| Taux gagnant | 44,44 % | 72,22 % | 22,22 % |
| Gain moyen, SOL | +0,059525 | +0,092082 | +0,020300 |
| Perte moyenne, SOL | −0,053039 | −0,029148 | −0,086813 |
| Pire trade, SOL | −0,136301 | −0,077957 | −0,196301 |
| P05 des P&L par rang le plus proche, SOL | −0,136301 | −0,077957 | −0,196301 |
| Médiane par rang, SOL | −0,017720 | +0,039113 | −0,077720 |
| P95 par rang, SOL | +0,108987 | +0,175269 | +0,048987 |

Ces quantiles décrivent seulement 18 trades par monde, dont 16 groupes de
signatures exécutées ; ils n'estiment pas les pertes extrêmes de marché.
Les chocs de −95 % existent dans le générateur adverse, mais aucun trade
exécuté de ce test final ne les subit : ce run ne valide pas une sortie lors
d'un tel choc. La faillite sans emprunt et la perte maximale du budget all-in
sont exercées par les tests dédiés, sous leurs hypothèses de fixture.

Les neuf coûts/slippages complets, cohortes et métriques sont conservés dans
les JSON. Dans ce run, les trois mondes ont le même ensemble de 18 exécutions
aux neuf sensibilités ; les différences de coûts ne changent donc pas la cohorte.
Exposition réservée maximale : 3 SOL. Disponible minimal au scénario faible coût :
6,817330 / 7,000000 / 6,018620 SOL. Aucune position n'emprunte.

La couverture de cotation d'entrée est 56/60, soit 93,33 %, mais seulement 18/60
opportunités sont exécutées après les filtres et limites. Les compteurs de refus
sont identiques ici : politique 33, quote absente 1, quote périmée 5,
exposition 3, solde 0. Les catégories suivent l'ordre des contrôles ; elles ne
mesurent pas des causes indépendantes ou la couverture du marché.

## Incertitude et limites

Le bootstrap descriptif par blocs de cinq signatures, 200 rééchantillonnages,
donne les intervalles conditionnels de moyenne SOL/trade suivants au faible coût :
null [−0,021654 ; +0,012382], momentum_linked [+0,039098 ; +0,075603],
adverse [−0,081654 ; −0,047618]. Il conditionne sur les exécutions déjà retenues.
Ce n'est pas un intervalle de rentabilité de marché, de drawdown ou de risque
de ruine ; les dépendances de sélection/exposition restent une limite.

Les sorties sont garanties par le générateur, les frais d'échec supposés nuls,
le slippage imposé et les pertes bornées au budget all-in. Il n'existe ici ni
carnet/pool rejoué, ni prix exécutable, ni coût réseau observé, ni perte latente
mark-to-market, ni latence réseau mesurée. Les P50/P95/P99 de réception marché,
RPC, décision et arrivée d'ordre restent inconnus et ne sont pas remplacés par
la durée de ces calculs locaux.

## Artefacts et reproduction

Les rapports complets et leur manifeste sont versionnés sous
`benchmarks/p2_synthetic_v1/`. Le manifeste contient les SHA256 de fichier et
les hashes internes des rapports. Le hash interne exclut seulement son propre
champ ; il diffère normalement du hash du fichier JSON formaté.

```sh
python -B -m bot.analyser.synthetic_benchmark --seed 20261026 --count 300 --regime null --output /tmp/rugger-null.json
python -B -m bot.analyser.synthetic_benchmark --seed 20261026 --count 300 --regime momentum_linked --output /tmp/rugger-linked.json
python -B -m bot.analyser.synthetic_benchmark --seed 20261026 --count 300 --regime adverse --output /tmp/rugger-adverse.json
```

## Décision

L'implémentation et la répétabilité du protocole synthétique sont vérifiées dans
ce périmètre. **Aucun candidat artificiel ne satisfait la validation positive au
stress fixé.** Aucun modèle n'est activable et aucune règle de production n'a été
réglée selon ces résultats. Le constat négatif est conservé.

L'avantage économique reste INSUFFICIENT DATA pour Rugger comme pour une
alternative BTC/SOL. Avant P3, il faut fixer la devise, obtenir les snapshots
point-in-time autorisés, les conversions, quotes entrée/sortie à taille effective,
coûts d'échec, historique des absences/rejets et un holdout réellement indépendant.
Aucune collecte de marché, dépense ou transaction réelle n'a été engagée.
