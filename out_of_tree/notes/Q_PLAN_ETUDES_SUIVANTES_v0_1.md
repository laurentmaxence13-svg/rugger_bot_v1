# Q — Études suivantes : fin de courbe, survivants, migration LaunchLab → CPMM, mesure conjointe (v0.1, 2026-11-11)

Point de départ (vérifié, N = 159) : sur le début de la courbe, ni la sélection par les 34 signaux
disponibles, ni le moment d'achat, ni la règle de sortie ne donnent un rendement net positif. Les
états où un avantage reste possible sont ceux que P0 ne contient presque pas.

## 1. Ce que chaque étude demande

| Étude | Question | Données nécessaires | Disponibles ? | Outil | État de l'outil |
|---|---|---|---|---|---|
| Fin de courbe | Entrer à 65 % ou 80 % de progression et sortir avant l'achèvement rapporte-t-il ? | transactions LaunchLab des pools qui vont loin | W1 après verdict (quelques dizaines de pools attendus) | statelab (étiquettes progress:650000 / 800000, règles de sortie) | prêt, gelé pour HW1-3 |
| Survivants | Un pool encore actif après 10 minutes a-t-il une dérive différente ? | idem, pools à longue vie | W1 après verdict | statelab (age:600 à 3600) | prêt, gelé pour HW1-4 |
| Traversée de la migration | Tenir une position à travers la migration et vendre sur le pool CPMM | transactions CPMM des pools migrés (première heure) | NON : aucune collecte autorisée | cpmmx 0.1 + pont v4cpmm 0.1 (protocole v1.2 ancré) | décodeur exact sur 280 swaps réels ; critère C-1 non évaluable faute d'échantillon |
| Après migration | Acheter sur le pool CPMM après son ouverture (frais 0,25 % au lieu de 1 à 3,75 %) | idem | NON | à écrire : sonde d'achat-vente sur chronologie CPMM | à construire hors ligne (§ 3) |

## 2. Données manquantes et coût

- Seule donnée manquante : les transactions CPMM des pools W1 qui auront migré. Estimation de R03
  (hors ligne, non mesurée) : environ 7 500 crédits Helius gratuits au point central pour 50 à 100
  pools sur 60 minutes (fourchette 500 à 60 000), par `getTransactionsForAddress` ; reste attendu après
  W1 : 257 000 à 281 000 crédits (pire cas 58 500) ; remise à zéro le 07/12. Aucun abonnement, aucun achat.
- Conditions techniques : liste des pools migrés tirée de W1 (donc après le verdict ancré) ; plafond
  de crédits fixé d'avance et arrêt à 98 % ; règle de collecte ancrée par R02 ; accord explicite du
  propriétaire. Rien n'est lancé d'ici là.

## 3. Outils à préparer hors ligne (aucune collecte)

1. Sonde après migration (`v4cpmm.probe`, à écrire) : sur une chronologie CPMM reconstruite par cpmmx,
   achat de 0,1 SOL à un instant causal (N secondes après le premier swap), vente à l'horloge,
   arithmétique exacte du pool (frais lus sur la chaîne), loyer du compte, latence d'ordre ; tests sur
   chronologies synthétiques à résultat connu et sur les 5 pools publics déjà décodés (280 swaps).
2. Règle de collecte CPMM révisée (R03) : population = pools W1 migrés ; fenêtre = 60 minutes ;
   plafond par pool et global ; critères de couverture (C-1) ; à faire auditer par R02.
3. Lecteur « traversée » : déjà présent dans le pont v4cpmm (règles at_open / strategy_clock) ; à
   brancher sur les positions HW1-3 une fois les données là.

## 4. Mesure conjointe sélection × achat × vente

Principe : un plan factoriel à trois facteurs, mesuré sur les MÊMES pools et valorisé par le même
moteur, pour séparer les contributions avant de les combiner.

- Sélection S : un prédicat sur les signaux connus à la décision (aucun, frais bas, courbe peu
  montée, beaucoup d'acheteurs aux deux premiers slots, créateur non signataire).
- Achat A : un déclencheur (référence age:5 ; les cinq déclencheurs gelés).
- Vente V : une règle de sortie (horloge ; première vente d'un tiers ; flux négatif).
- Pour chaque cellule (S, A, V) : rendement net moyen, intervalle par créateurs, médiane, part de
  gagnants, gain et perte moyens, drawdown de la suite chronologique, effectif.
- Contributions : effet de S à A et V fixés (écart apparié aux mêmes entrées non filtrées) ; effet de
  A à S et V fixés (écart au placebo) ; effet de V à S et A fixés (écart apparié à l'horloge) ; puis
  interaction = résultat combiné moins somme des effets.
- Discipline : la grille (S, A, V) est écrite dans le code avant lecture ; chaque cellule calculée
  compte dans N ; planchers 30 positions et 20 créateurs ; correction de multiplicité sur la grille ;
  découverte sur la première moitié chronologique de W1 (après son verdict et la passe gelée, W1
  devient donnée de développement), crible sur la seconde moitié, confirmation sur W2.
- Les briques existent : `statelab.signals` (S), `statelab.hypotheses` (A), `statelab.exits` (V). Reste à
  écrire le module qui les croise (`statelab.joint`) et ses tests ; il ne sera exécuté sur aucune
  donnée avant l'audit de R02.

## 5. Ce qui ne sera pas refait

Les 159 essais conclus : référence et variantes, 80 cellules d'états, 34 signaux, 7 règles de sortie,
répétition des cinq hypothèses. Aucune relance sur P0.
