# R — Évaluation économique préliminaire du bot : complément détaillé (v0.2, 2026-11-15)

Complément détaillé du rapport court de RUGGER 03 (Phase 0), corrigé selon le contrôle de RUGGER 02.

**Ce document n'est PAS le verdict officiel W1.** Il ne lit aucune donnée de W1. Il ne modifie ni
n'évalue les cinq hypothèses gelées. C'est une compilation, sans aucun calcul nouveau, de résultats
déjà obtenus et déjà contrôlés par RUGGER 02 sur les données de développement (« P0 visible »,
collectées avant W1). Simulation hors ligne : aucun ordre réel, aucun fonds.

## 1. Réponse courte

**Aucune stratégie rentable n'est démontrée.** Sur les données de développement, les stratégies
essayées perdent en moyenne, après frais, entre 2,7 % et 30 % du capital engagé par opération. Une
seule moyenne est positive (+2,78 %) et elle n'est pas significative (§ 5). La stratégie de référence perd 4,94 % par opération hors loyer du compte de token, 6,85 %
avec ce loyer, et 9,42 % dans la configuration exécutable aujourd'hui.

## 2. Performances estimées après frais

Mise de 0,1 SOL, latence de 4 slots à l'achat et à la vente, rejeu exact de la courbe. Rendement net
moyen = gain ou perte divisé par le capital engagé, sur les cycles achat-vente complets.

| Stratégie | Rendement net moyen par opération | Opérations (cycles clos) | Perte cumulée |
|---|---|---|---|
| Référence : achat 5 s après la création, vente à 25 s | −4,94 % hors loyer ; −6,85 % avec loyer ; −9,42 % exécutable aujourd'hui (63 opérations) | 125 (124) | 0,6133 SOL, soit 6,1 mises |
| Témoin : achat à un âge tiré au hasard | −4,40 % | 45 | 0,1983 SOL |
| Détention de 120 / 300 / 900 s avec stops | −6,62 % / −6,98 % / −6,78 % | 125 (117 / 113 / 109) | 0,7756 / 0,7906 / 0,7402 SOL |
| Détention de 900 s sans stop (descriptif) | −8,17 % | 125 (111) | 0,9086 SOL |
| Pools à frais faibles (≤ 1,5 % par côté) | −3,24 % | 59 | 0,1916 SOL |
| « Course vers la migration » | −30,24 % | 8 | 0,2424 SOL |
| 25 essais antérieurs (achat immédiat, délais de 0 à 120 s, confirmation, filtres) | de −2,7 % à −16,3 % selon l'essai | 4 à 159 par essai | — |
| Étude d'états : 6 moments d'achat × 5 durées de détention (30 cas) | de −24,86 % à −7,22 % ; aucun cas retenu | 33 à 89 par moment d'achat | — |
| Étude d'états élargie à tous les pools : 10 × 5 (50 cas) | de −20,5 % à −4,1 % ; aucun cas retenu | 32 à 185 | — |
| Tri par 34 signaux à l'achat | meilleur tiers : −3,92 % ; aucun tiers positif | 154 pools | — |
| 7 règles de vente sur les mêmes achats | de −7,88 % à −5,91 % ; aucune rentable | 154 positions | — |
| Répétition, sur ces données, des hypothèses gelées pour W1 (ne préjuge pas du résultat sur W1) | « repli » −9,05 % ; « purge » −4,47 % ; « créateur non signé » +2,78 % (intervalle [−0,13 ; 6,02], non significatif, −0,91 % avec 10 slots de latence) ; deux hypothèses non évaluables (2 et 25 positions) | 39 / 102 / 96 / 2 / 25 | — |

La référence ne fait pas mieux que le témoin tiré au hasard.

## 3. Positions ouvertes et clôturées (référence)

- 125 achats simulés, 124 cycles clos.
- 1 position a migré vers un autre marché : elle n'est pas valorisée (ni gain ni perte crédités),
  faute de données sur ce marché.
- Dans l'ensemble des essais de cette série, 50 des 51 positions non closes sont des artefacts du
  rejeu, pas des pertes réelles (contrôle R02).
- Aucune position réelle n'a jamais été ouverte : tout est simulé.

## 4. Gains, pertes et principaux facteurs d'échec

Décomposition exacte de la référence (124 cycles, vérifiée au lamport près par R02), en part du
capital engagé :

| Poste | Part du capital |
|---|---|
| Frais de la courbe à l'achat | −1,92 % |
| Frais de la courbe à la vente | −1,87 % |
| Frais de transaction | −0,21 % |
| **Coût d'un aller-retour immédiat** | **−4,00 %** |
| Évolution du prix pendant la détention | −0,93 % |
| **Résultat hors loyer** | **−4,94 %** |
| Loyer du compte de token, perdu par la chaîne actuelle | −2,05 % |
| **Résultat avec loyer** | **−6,85 %** |

Facteurs d'échec, par ordre d'importance :

1. **Le coût d'entrée.** Un aller-retour coûte 4 % à 5,4 % du capital, plus 2,05 % de loyer, payés
   dès l'achat. Il faudrait une hausse de 2,3 % à 8 % après notre achat pour seulement l'annuler ;
   12,5 % des achats la voient.
2. **Le prix baisse après notre achat.** Sur 124 cycles : 17 fois le prix monte, 74 fois personne ne
   traite, 33 fois il baisse. Dans les 30 cas de l'étude d'états, l'évolution du prix seule, sans
   aucun frais, est négative.
3. **Les vendeurs sont ceux qui étaient là avant nous** (créateur et tout premiers acheteurs) ; les
   nouveaux acheteurs n'absorbent pas leurs ventes.
4. **Ni la vitesse, ni le tri, ni la règle de vente ne corrigent une entrée précoce.** Avec 1 slot de
   latence au lieu de 4, les résultats sont plus mauvais. Tenir plus longtemps aggrave. En choisissant
   après coup le meilleur instant de vente, la moyenne reste à −1,68 % avec loyer (chiffre provisoire,
   non recalculé par R02) : le problème est l'achat, pas la vente.

## 5. Limites de fiabilité

- **Données de développement.** Ces données ont servi à concevoir et à essayer les stratégies : 159
  essais y ont été comptés. Elles peuvent écarter une idée, pas en prouver une.
- **Petit échantillon, une seule période.** 360 pools visibles sur 12,85 heures, dont 242 rejouables
  dans les segments de découverte. Toute vue de moins de 200 cycles clos est non concluante selon les critères
  de R02 ; la référence en a 124.
- **Simulation.** Rejeu exact de la courbe, mais nos ordres n'ont pas existé : leur effet sur les
  autres acteurs n'est pas connu, et les échecs d'envoi ne sont pas modélisés.
- **Zones sans données.** Presque aucun pool en fin de courbe (2 positions), une seule migration,
  aucune donnée sur le marché d'après-migration.
- **Seule moyenne positive observée** (« créateur non signé ») : elle repose sur quelques pools,
  tombe à +0,18 % sans les cinq meilleurs, et devient négative (−0,91 %) avec 10 slots de latence.

## 6. Améliorations envisageables

| Piste | Ce que l'on sait | Ce qui la tranchera |
|---|---|---|
| Récupérer le loyer en fermant le compte de token | le loyer pèse 2,04 % ; avec ce nettoyage, −4,61 % au lieu de −6,52 % ; non activé | développement hors ligne |
| Accepter les tokens Token-2022 de la liste stricte | −6,52 % sur 121 opérations au lieu de −9,42 % sur 63 ; réduit la perte, ne rend pas rentable | développement hors ligne |
| Pools à frais faibles | −3,24 % sur 59 opérations ; réduit la perte, ne la supprime pas | données futures (W2), hypothèse nouvelle |
| Migration et marché d'après-migration | aucune donnée | une collecte gratuite dans le quota (environ 7 500 crédits estimés), soumise à votre accord |

La conclusion de travail : sur le début de la courbe, ces données ne montrent aucun avantage à
prendre. Seules des données nouvelles peuvent dire s'il en existe un ailleurs.

## 7. Pour aller plus loin : deux façons d'obtenir une lecture sur W1

Ce document ne contient et ne contiendra aucun chiffre de W1. Deux options, à votre décision :

| | Voie B (Google Cloud) | Lecture préliminaire dans la session de RUGGER 03 |
|---|---|---|
| Ce qu'elle donne | le verdict officiel W1, puis les cinq hypothèses gelées | un registre des achats et ventes simulés du MASTER sur W1 : positions ouvertes et closes, gains et pertes après frais, décomposition des coûts, intervalle de confiance ; pour la référence et le témoin, des totaux seulement ; rien sur les hypothèses |
| Ce qu'elle ne donne pas | — | le verdict officiel (l'étape qui le calcule ne tient pas dans la mémoire disponible) |
| Coût | 60 USD au plus, déjà cadré ; paquet validé par R02 et prêt | aucun |
| Délai | vos commandes Cloud Shell, puis le calcul | environ une journée d'outils et d'audit, puis quelques heures de calcul (durée jamais mesurée à cette échelle) |
| Statut | conforme au protocole gelé | **écart au protocole gelé** : W1 serait lu avant son verdict officiel |

Conditions de la lecture préliminaire, fixées par R02 (conditions (1) et A-2 de sa méthode) :
1. **votre accord explicite** pour lire W1 avant le verdict officiel ;
2. **votre choix, avant toute lecture**, entre : (a) le verdict officiel sera calculé ensuite quoi que
   montre la lecture préliminaire, ou (b) la lecture préliminaire fait foi et W1 est déclaré
   exploratoire ;
3. les outils sont audités par R02 avant tout calcul, et la liste de ce qui est lu est fermée
   d'avance ; les empreintes des fichiers intermédiaires pourront être comparées plus tard à celles
   de la chaîne officielle.

## 8. Sources (toutes contrôlées par RUGGER 02, sauf mention « provisoire »)

- Table des stratégies : ea576b76 (contrôle 10702f6e) ; vues par classe de token : 3a7c36d2 (d3b1a10a).
- Décomposition des pertes : anatomy.json f56a76f7, contrôle 37d32c02.
- Acteurs vendeurs (cohortes) : instrument conforme 3b16e5f7, chiffres non recalculés par R02.
- Étude d'états : 63817ac9 ; élargie et 34 signaux : f583d747 ; règles de vente : ce5db0bc.
- Répétition des hypothèses gelées : de1b4bb1.
- Tableaux de suivi L v2 (11/11 13:45Z) et L v3 (11/11 18:45Z), dont ce document reprend les chiffres.
