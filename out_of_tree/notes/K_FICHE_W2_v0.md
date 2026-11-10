# W2 — fiche de pré-enregistrement, version 0 (projet)

RUGGER 01, 2026-11-10. **Projet : rien n'est gelé, rien n'est collecté.** À auditer par RUGGER 02
(critères économiques v1, sha 4e42b108…) puis à soumettre au propriétaire. W1 n'est pas touchée.

## 1. Rôle de W2
Fenêtre neuve de **confirmation** des stratégies V3 retenues, jugée avec les critères v1 de R02
(recevabilité R-1 à R-3, positif P-1 à P-6, stress pré-déclarés). Un positif sur W2 doit encore être
confirmé sur une autre fenêtre neuve avant tout réel.

## 2. Enchaînement proposé (aucune étape n'ouvre de données avant son gel)
1. ≈ 14/11 : clôture de W1, collecte et verdict W1 par le protocole gelé (rien ne change).
2. Après le verdict W1 de R02 : les données W1 deviennent des données de **développement** V3
   (≈ 4 800 à 10 100 pools, contre 360 visibles sur P0), valorisées par v4sim en mode M-P. Chaque
   essai compte dans N.
3. Gel de la liste des stratégies W2 (au plus 5, référence et placebo compris), ancrage R02.
4. Collecte de W2, une seule fois, puis évaluation par les critères v1.

## 3. Fenêtre
Fixée d'avance en slots, strictement après la fenêtre W1 plus un intervalle au moins égal au plus
grand horizon de résultat : début = 469 295 858 + intervalle ; longueur = 2 020 113 slots (≈ 5 jours).
La fenêtre peut s'écouler pendant l'étape 2 : seules ses données restent fermées jusqu'au gel.

## 4. Effectifs attendus contre R-1 (≥ 200 positions closes, ≥ 100 créateurs indépendants)
Densités mesurées : P0 = 514 pools en 12,85 h (40 pools/h) ; pilote W1 ≈ 2,1 fois plus.

| Stratégie | Taux d'entrée mesuré sur P0 visible | Entrées attendues sur 5 jours | R-1 |
|---|---|---|---|
| Référence (délai 5 s, horloge 25 s) | 125 / 360 | 1 667 à 3 513 | tenu |
| Placebo (entrée aléatoire) | 45 / 360 | 600 à 1 265 | tenu |
| H1 (palier de frais bas) | 59 / 360 | 787 à 1 658 | tenu |
| H3 (course vers la migration) | 8 / 360 | 107 à 225 | **non garanti** : tenu seulement à la densité haute |

Règle proposée : la fenêtre n'est jamais allongée après coup ; une stratégie sous R-1 est NON
CONCLUANTE. Pour garantir H3 à la densité P0, il faudrait ≈ 225 h (9,4 jours) : à décider avant le gel.

## 5. Données et couverture
- LaunchLab : même collecteur et mêmes contrôles de couverture que W1.
- SOL/USD : même série que W1.
- CPMM (pools migrés) : **non couvert aujourd'hui**. Requis par le protocole CPMM v1 (transactions du
  pool, création, AmmConfig). Coût non mesuré : un pilote sur 2 ou 3 pools (≤ 2 000 crédits) le fixe.
  Sans CPMM, les positions migrées restent non valorisées et R-2 (au plus 10 % de migrées) s'applique.

## 6. Budget de crédits Helius (ordres de grandeur de R03)
| Poste | Bas (densité P0) | Haut (densité pilote) |
|---|---|---|
| LaunchLab | 278 000 | 586 000 |
| SOL/USD | 58 651 | 75 134 |
| CPMM | non mesuré (hypothèse 5 000 à 300 000) | |
| Total hors CPMM | 336 651 | 661 134 |

Reste gratuit attendu après la collecte W1 : ≈ 275 000 (pire cas 59 252) ; remise à zéro le 07/12.
Donc : une W2 de 5 jours ne tient pas sur le plan gratuit avant le 07/12 ; elle tient après, ou tout
de suite avec un plan payant (décision du propriétaire, voir le compte rendu).

## 7. Critères et arrêt
Ceux de R02 v1, sans assouplissement. Tableau obligatoire par stratégie (outil `v3lab/tables.py`).
Arrêt sans évaluation si la couverture échoue, si un plafond de crédits est atteint, ou si le
registre n'est pas ancré avant la collecte.

## 8. Ouvert (à trancher avant le gel)
Longueur de fenêtre (5 ou ≈ 10 jours) ; liste finale des stratégies ; valeur X de la dégradation MEV
(stress de R02) ; couverture CPMM oui / non ; plan Helius.
