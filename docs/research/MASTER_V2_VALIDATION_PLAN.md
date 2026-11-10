# D — Plan de validation quantitative MASTER V2

Préparé le 2026-11-07 par RUGGER 01. Statut : **proposition**, à auditer par RUGGER 02. Ce plan ne crée aucune autorisation : aucune collecte, aucun achat, aucun trade sans accord explicite du propriétaire.

## 1. Principes non négociables

1. **Causalité.** Une décision prise à l'événement `k` ne lit que `events[:k+1]`, jamais une transaction postérieure. C'est le contrat du rejeu L1, déjà audité, et de `bot/master_v2`.
2. **Coûts réels.** Le modèle d'exécution est celui audité :
   - frais du pool estimés causalement ;
   - frais de base et de priorité ;
   - latence en slots ;
   - impact propre sur la courbe ;
   - tentatives échouées, comme paramètre explicite.
3. **Comptabilité stricte.** Seul un cycle clos a un P&L. Les positions ouvertes, migrées ou invalorisables sont publiées par issue et jamais traitées comme neutres.
4. **Pré-enregistrement.** Avant toute lecture d'un segment d'évaluation, la politique, sa règle de sortie et les paramètres de rejeu sont figés par une empreinte (`preregistration`). Cette empreinte lie aussi le code, les données et la fenêtre de collecte.
5. **Tout essai compte.** Chaque configuration est inscrite au registre chaîné **avant** son exécution. `evaluate` exige tous les essais inscrits sur les mêmes données, et le DSR porte sur tous ces essais, pas sur le meilleur seul. La tête du registre est ancrée hors de l'outil.
6. **Fenêtre de collecte et embargo.** Aucune entrée après la coupure. Un cycle n'est clos que si sa sortie tombe dans la fenêtre. L'embargo entre segments couvre la plus longue détention bornée.
7. **Indépendance.** RUGGER 02 audite le code avant toute exécution sur données, puis chaque résultat avant toute promotion.

## 2. Données et segments

| Jeu | Contenu | Rôle autorisé |
|---|---|---|
| **P0** | 514 pools rejouables, slots 466 226 737 à 466 442 736 (216 000 slots : environ 12,8 h à 213 ms par slot, durée réelle à confirmer par les `block_time` de RUGGER 03) : 363 pools à créateur vérifié, 266 créateurs. Code de collecte `6fdd183`, export MANIFEST `e5d3c0f7…`. | **Exploration seulement.** Ce jeu a déjà servi au diagnostic (test s090) et ne peut plus valider quoi que ce soit. |
| **W1** (futur) | Fenêtre collectée **après** le gel des règles, contiguë, chronologique. | Entraînement et validation, découpage chronologique avec embargo et créateurs disjoints. |
| **W2** (futur) | Fenêtre postérieure à W1, jamais lue. | **Holdout final** : un seul descellement par politique pré-enregistrée. |

Chaque nouvelle fenêtre exige l'accord du propriétaire : volume, crédits, fournisseur. Sur P0, `chronological_split` découpe en quatre segments (exploration, entraînement, validation, holdout). Mais le « holdout » de P0 reste de l'exploration, puisque P0 a déjà été lu.

## 3. Taille d'échantillon

Le s090 donne une moyenne de −16,2 % par cycle, avec un intervalle à 95 % de [−21,2 % ; −11,2 %] sur 33 cycles. L'erreur type est donc d'environ 2,55 points, et l'écart-type d'environ 14,7 points. Une politique gagnante aura une queue droite plus épaisse, donc une dispersion plus grande.

Nombre de cycles nécessaires pour détecter un avantage net moyen δ (test unilatéral, α = 5 %, puissance 80 %) :

| δ | σ = 15 points | σ = 30 points | σ = 60 points |
|---|---|---|---|
| +2 % | 348 | 1 392 | 5 565 |
| +5 % | 56 | 223 | 891 |
| +10 % | 14 | 56 | 223 |

Le regroupement par créateur multiplie ces tailles par un facteur `1 + (m − 1)ρ`, de 1,05 à 1,6 selon le nombre moyen de cycles par créateur (m) et la corrélation intra-créateur (ρ).

**Conséquence.** La porte protégée de 50 cycles et 20 créateurs est un **minimum** nécessaire, pas une preuve suffisante d'un petit avantage. Une promotion exige la taille calculée pour l'avantage revendiqué.

## 4. Mesures

Toutes les mesures portent sur les cycles clos, coûts inclus. Par politique et par segment :
- P&L net ;
- espérance par cycle ;
- médiane ;
- taux de réussite ;
- profit factor ;
- drawdown maximal (dans l'ordre des sorties) ;
- moyenne des 10 % pires et des 10 % meilleurs cycles ;
- issues non closes.

Incertitude :
- intervalle à 95 % par rééchantillonnage en grappes de créateurs ;
- PSR contre zéro ;
- DSR contre l'espérance du maximum des essais.

## 5. Critères de décision

Une politique passe de **CHALLENGER** à **CANDIDATE** seulement si, sur le holdout W2 descellé une fois :

1. la borne basse de l'intervalle par créateurs de l'espérance nette est **strictement positive** ;
2. son **DSR est d'au moins 0,95**, tous essais comptés ;
3. elle bat, avec un écart significatif sur les mêmes pools :
   - l'abstention ;
   - l'entrée aléatoire à moments comparables ;
   - le sniping immédiat ;
4. elle reste positive sous stress :
   - frais de pool +25 % ;
   - frais de priorité ×5 ;
   - latence portée de 2 à 4 slots ;
   - tentatives échouées au taux observé dans la fenêtre ;
5. elle reste stable sur au moins deux sous-périodes, sans dépendre d'un seul créateur ni d'un seul pool : aucun ne pèse plus de 20 % du P&L ;
6. elle reçoit un PASS de RUGGER 02 sur le code, les données et le calcul.

Le passage au Master opérationnel suppose en plus les seuils protégés de 50 cycles économiques qualifiés et 20 créateurs indépendants. Ils restent **inchangés**.

## 6. Optimisation

- Uniquement sur les segments d'exploration et d'entraînement, avec de petites grilles pré-enregistrées, avancées pas à pas dans le temps (walk-forward).
- Choisir des **plateaux** de paramètres stables plutôt qu'un maximum isolé.
- Une configuration choisie sur un segment ne peut plus servir de preuve sur ce même segment.

## 7. Ordre des expériences sur P0 (exploration)

1. Cycle de vie des 514 pools, sans aucune politique.
2. Courbe du moment d'entrée : délais fixes de 0, 5, 15, 30, 60 et 120 s, une seule sortie fixée à l'avance.
3. Placebos : abstention, entrée aléatoire.
4. Familles : sniping immédiat filtré, confirmation différée, dynamique de remplissage de la courbe.
5. Décomposition du résultat : coûts certains (frais et transactions, 2,2 à 3,7 % par aller-retour), mouvement de prix pendant la détention, glissement des stops dû à la latence.

Ces résultats ne servent qu'à **formuler** des règles. Les règles retenues sont ensuite figées, puis jugées sur W1, puis sur W2.
