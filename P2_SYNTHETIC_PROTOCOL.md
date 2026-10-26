# Protocole P2 synthétique v1

Ce protocole teste un évaluateur, pas la rentabilité de Rugger Bot. Il ne lit
aucune donnée de marché, base utilisateur, configuration `.env`, clé ou portefeuille.
Ses rapports restent `model_eligible=false`, `paper_eligible=false` et
`economic_verdict=INSUFFICIENT DATA`, même si une fixture affiche un gain.

## Périmètre et préalable

Le point d'entrée retenu est `bot.analyser.synthetic_benchmark`. L'exécution
d'expériences attend le GO technique du périmètre synthétique défini dans le
réexamen P1 ; la réussite des tests unitaires n'accorde pas ce GO. Les anciennes
voies v25/v26, les outils historiques, le collecteur standalone et les données
réelles ne sont pas des évaluateurs certifiés par ce protocole.

Ce document et les règles du module sont à figer avant la première expérience.
Ils ne sont pas à retoucher après consultation du test final pour obtenir un gain.
Un nouveau protocole constitue une nouvelle expérience, à compter séparément.

## Jeux et hypothèses préenregistrés

Le générateur versionné utilise par défaut le seed **20261026**, **300** mints,
deux mints par transaction synthétique/timestamp et 180 secondes entre groupes.
Les mints d'un même groupe partagent un choc de rendement. Les noms synthétiques
ne désignent aucune transaction Solana réelle.

Trois mondes sont définis avant leurs résultats :

- `null` : rendement futur indépendant du momentum observé, avant coûts ; aucun
  avantage de momentum n'est programmé dans les données.
- `momentum_linked` : dépendance artificielle explicite entre momentum et rendement.
  Elle sert de témoin de sensibilité de l'évaluateur, jamais de preuve de marché.
- `adverse` : dérive défavorable et perte de 95 % de la position pour certains
  groupes prédéfinis, pour exercer les limites de capital et les pertes extrêmes.

Tous les rendements sont des **rendements en SOL** (`gross_return_sol`) et la
liquidité est exprimée en SOL. Aucun prix USD n'est transformé implicitement en
P&L SOL. Ces fixtures ne valident pas une hypothèse de change constante.

La disponibilité de cotation d'entrée est parfois absente, et le délai observé
peut être de 0, 60 ou 180 secondes. Une entrée manque ou devient périmée à la
décision : elle est refusée, jamais complétée par une cotation future. Les sorties
de positions exécutées sont garanties uniquement dans ce monde synthétique.
Une observation dont le rendement de sortie manque ou n'est pas fini invalide le
jeu : aucun rendement nul n'est fabriqué et aucun corpus incomplet n'est certifié.

## Temps et indépendance de la sélection

La cible brute est 60 % entraînement, 20 % validation, 20 % test final. Les deux
frontières utilisent `temporal_partition`, qui conserve les groupes de signature
et timestamp. Les dates de frontières sont fixées sur les événements bruts,
avant les refus de simulation. Un label train doit être connu strictement avant
la validation ; un label validation doit être connu strictement avant le test.
Les lignes purgées ne sont transférées dans aucune autre période.

Après groupement et purge, les minima sont 30 observations train, 15 validation et
15 test final. Une insuffisance produit `INSUFFICIENT DATA` ; la frontière n'est
pas déplacée pour sauver une expérience. Les labels ont leur heure effective de
sortie, y compris le retard de cotation synthétique.

Trois règles de fixture sont figées, indépendantes de la matrice de production :

1. Tous les candidats satisfaisant les contrôles communs.
2. Momentum observable strictement positif.
3. Momentum positif et liquidité observée d'au moins 50 SOL.

Le train ne calibre pas de paramètre de ces règles fixes ; il fournit les mesures
de développement et impose au moins cinq exécutions. La validation compare les
trois candidats au coût le plus défavorable enregistré : 1 000 bps de coûts et
300 bps de slippage. Le plus haut P&L net SOL est retenu avec un ordre de règles
fixe en cas d'égalité, après au moins cinq exécutions validation. Le choix est
ensuite figé. Une meilleure règle négative est signalée par
`validation_positive=false` et n'est pas assimilée à un avantage.

Un témoin « ne rien faire » conserve 10 SOL, avec zéro P&L et zéro drawdown.
Les résultats des trois candidats train/validation sont publiés ; seuls ceux du
candidat déjà figé sont calculés sur le test final. Le coût et le slippage ne
sont pas choisis d'après le test. Les neuf combinaisons 200/500/1 000 bps de coûts
et 0/100/300 bps de slippage sont toutes publiées, avec les cohortes exécutées.

Compteur d'essais : **3 candidats** par monde, pas neuf stratégies gagnantes.
Les neuf coûts sont une analyse de sensibilité préenregistrée. Si les trois mondes
sont exécutés, le journal doit annoncer trois expériences et neuf candidats de
développement, y compris les résultats défavorables. Changer de seed, règle,
générateur ou protocole doit être ajouté au nombre total d'expériences ; aucun
seed n'est sélectionné d'après le résultat final.

## Ledger et exécution de fixture

Le capital initial est de **10 SOL**. Chaque position engage un budget all-in
fixe de **1 SOL**, soit 10 % du capital initial, avec trois positions simultanées
au maximum. Ce budget ne compose pas les pourcentages de trades comme s'ils
concernaient tout le portefeuille. Les fonds engagés sont retirés du disponible ;
aucun emprunt, solde négatif ou nouvelle entrée sans solde suffisant n'est admis.

L'entrée cible signal +300 s et la sortie signal +900 s, augmentées du délai de
cotation. Une cotation retardée de plus de 120 s ou une liquidité observable
inférieure à 20 fois le budget de position est refusée. Ce seuil est une
hypothèse de fixture, pas une preuve de profondeur ou de prix exécutable.

Les coûts et le slippage aller-retour sont retranchés des produits de sortie,
planchés à zéro ; la perte maximale est donc le budget all-in. Les frais d'une
soumission échouée sont supposés nuls et aucune soumission réseau n'a lieu.
Ce choix simplifie la comptabilité et doit être remplacé par des observations
avant une étude économique réelle. Il ne reproduit pas les frais réellement
payables lorsque la revente d'un token est impossible.

Au même timestamp, les sorties sont agrégées puis les entrées sont traitées dans
un ordre déterministe. C'est une convention du monde synthétique, sans garantie
sur l'ordre d'événements réseau réels. Le drawdown utilise l'equity réalisée SOL,
agrégée par date de sortie ; il ne mesure pas une perte latente ou exécutable.

## Mesures et limites

Le rapport contient P&L, rendement du capital, drawdown réalisé, espérance de P&L
SOL par trade, taux de réussite, gains/pertes moyens, pire perte, profit factor,
nombre de trades, exposition, disponible minimal, couverture des cotations,
refus et coûts/slippage. Sans perte observée, le profit factor est `null` avec
`no_losses` ; aucun infini JSON ou ratio fabriqué n'est publié.

L'incertitude de la moyenne par trade utilise un bootstrap descriptif conditionnel
par blocs de cinq groupes consécutifs de signatures, 200 rééchantillonnages et un
seed fixe. Moins de dix groupes exécutés donne `insufficient_groups`. Cette
procédure conditionne sur les cohortes déjà exécutées : elle ne certifie ni la
rentabilité de marché, ni le drawdown, ni le risque de ruine. Aucune incertitude
statistique ne transforme le générateur en données historiques.

Les hashes du jeu complet, des seules observations de sélection et du rapport
normalisé permettent de vérifier la répétabilité. Les tests perturbent les
rendements du test final et imposent que le choix de règle et le hash de sélection
restent identiques. Le fichier JSON final est publié par remplacement atomique.

## Commandes après GO technique

Depuis la racine du dépôt et sans accès réseau :

```sh
python -B -m bot.analyser.synthetic_benchmark --seed 20261026 --count 300 --regime null --output /tmp/rugger-null.json
python -B -m bot.analyser.synthetic_benchmark --seed 20261026 --count 300 --regime momentum_linked --output /tmp/rugger-linked.json
python -B -m bot.analyser.synthetic_benchmark --seed 20261026 --count 300 --regime adverse --output /tmp/rugger-adverse.json
```

Ces commandes doivent être accompagnées du commit exact, de la version Python,
des hashes et de l'ensemble des résultats. Le présent fichier ne prétend pas que
ces expériences ont déjà été exécutées. Les tests unitaires sont des validations
d'implémentation du protocole ; ils n'accordent aucun GO économique, P3 ou réel.
