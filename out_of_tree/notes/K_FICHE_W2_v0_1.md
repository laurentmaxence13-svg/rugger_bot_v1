# W2 — fiche de pré-enregistrement, version 0.1 (projet)

RUGGER 01, 2026-11-10. **Projet : rien n'est gelé, rien n'est collecté.** Remplace la v0 ; intègre
l'audit de RUGGER 02 (694b141b). Critères économiques : v1 de R02 (4e42b108), jamais assouplis.

## 0. Décisions du propriétaire dont dépend cette fiche
- **D-1 (bloquant).** Données de développement de V3. La directive dit : « Ne réoptimise pas sur … les
  données réservées W1 ». En l'état, V3 se développe **sur P0 visible seulement** (360 pools, déjà
  34 essais). Variante possible seulement sur décision explicite : après le verdict W1 **ancré**,
  W1 devient donnée de développement, n'est plus jamais une preuve indépendante, et chaque essai
  compte dans N.
- **D-2.** Calendrier de la fenêtre W2 : (i) fenêtre qui commence **après** le gel du plan (préférence
  ferme de R02, plus lente) ; (ii) fenêtre fixée d'avance qui s'écoule pendant le développement, admise
  seulement si R02 l'ancre avant son premier slot, si aucun agent ne lit un slot W2 avant le gel
  (relevés Helius avant / après) et si tout accès anticipé annule W2.
- **D-3.** Source de collecte : plan Helius gratuit (collecte après le 07/12) ou payant (49 $).

## 1. Rôle de W2
Fenêtre neuve de confirmation des stratégies V3 retenues. Un positif doit encore être confirmé sur
une autre fenêtre neuve avant tout réel.

## 2. Fenêtre
- Longueur : 2 020 113 slots (≈ 5 jours), jamais allongée après coup.
- Intervalle après la fin de W1 (469 295 857) ou après le gel : max(plus grand horizon de résultat des
  stratégies du plan, 6 018 slots).
- Segment de décision : la fenêtre entière (plan gelé avant toute lecture).

## 3. Stratégies et effectifs contre R-1
R-1 exige ≥ 200 positions **closes** et ≥ 100 créateurs indépendants ; marge de 25 % demandée par R02,
donc cible ≥ 250 closes. Plancher = 4 800 pools (40 pools/h, densité P0) × borne basse de l'IC à 95 %
(Wilson) du taux de clôture mesuré sur P0 visible.

| Stratégie | Clos sur P0 visible | Clos attendus sur 5 jours | Plancher | ≥ 250 |
|---|---|---|---|---|
| Référence (délai 5 s, horloge 25 s) | 124 / 360 | 1 653 | 1 426 | oui |
| Placebo (entrée aléatoire) | 45 / 360 | 600 | 454 | oui |
| H1 (palier de frais bas) | 59 / 360 | 787 | 620 | oui |
| H2 (détention 120 / 300 / 900 s avec stops) | 117 / 113 / 109 sur 360 | 1 560 / 1 507 / 1 453 | 1 337 / 1 287 / 1 236 | oui |
| H3 (course vers la migration) | 8 / 360 | 107 (213 sur 10 jours) | 54 (108) | **non** |

- **H3 est retirée du plan** (hors famille de Holm) : non évaluable d'avance, et ses positions migrent,
  donc non concluante sans A-12. Elle reste suivie à titre descriptif.
- Une stratégie sous R-1 à l'arrivée est NON CONCLUANTE (règle déclarée d'avance).
- Créateurs indépendants par stratégie : à compléter avec la colonne `creators` du tableau ea576b76.
- Liste finale : au plus 5 stratégies, référence et placebo compris ; famille de Holm = les candidates.
- N au gel = 34 + essais de développement + essais du plan.

## 4. Unité, exécution, stress
- Mise fixe 0,1 SOL ; exposition simultanée ≤ 5 ; valorisation `v4sim` 0.2 en mode M-P (les trois autres
  modes publiés) ; latence 4 slots ; frais de courbe causaux ; 5 000 + 100 000 lamports par transaction.
- Stress pré-déclarés de R02 : palier de frais le plus haut, latence 10 slots, p_fail 0,25, glissement
  500 pb, priorité 1 000 000 lamports, mise 0,5 SOL, mode M-A, dégradation MEV de X pb.
- **X (méthode de R02, à ancrer avant le gel)** : sandwichs détectés dans les événements LaunchLab des
  données de développement seulement (même acteur, achat puis vente encadrant l'achat d'un autre dans le
  même slot, dans l'ordre des transactions) ; dégradation de la victime en pb pour une mise de 0,1 à
  0,5 SOL ; X = max(100 pb, 95e centile). Aucun jeu de données payant.

## 5. Positions migrées et CPMM (condition séparée, protocole CPMM v1.1)
- Sans A-12 passé : une position migrée n'est pas créditée et **compte r = −1 dans les décisions** ; la
  dernière valeur de courbe est descriptive ; la part de positions migrées est publiée par stratégie ;
  R-2 (au plus 10 % de migrées) s'applique.
- Couverture CPMM : non disponible aujourd'hui ; coût non mesuré (pilote ≤ 2 000 crédits, sur GO).

## 6. Budget de crédits Helius (ordres de grandeur de R03)
| Poste | Bas (densité P0) | Haut (densité pilote) |
|---|---|---|
| LaunchLab | 278 000 | 586 000 |
| SOL/USD | 58 651 | 75 134 |
| CPMM | non mesuré (hypothèse 5 000 à 300 000) | |
| Total hors CPMM | 336 651 | 661 134 |

Reste gratuit attendu après la collecte W1 : ≈ 275 000 (pire cas 59 252) ; remise à zéro le 07/12.
Plafond de crédits W2 : à fixer au gel, après le pilote CPMM ; arrêt sans évaluation s'il est atteint.

## 7. Arrêt
Sans évaluation si la couverture échoue, si le plafond de crédits est atteint, si le registre n'est
pas ancré avant la collecte, ou si un slot W2 a été lu avant le gel.
