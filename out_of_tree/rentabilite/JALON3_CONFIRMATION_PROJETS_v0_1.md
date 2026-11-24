# Jalon 3 — PROJETS de fiches de confirmation G2-3 et N1 (v0.1)

RUGGER 01, 24/11/2026. Demande R04 du 24/11 à 22:44Z.
- **PROJET, NON ancré.** Hors ligne : aucune donnée, aucun essai, aucun crédit.
- Rien ici n'est un résultat économique.
- Ni G2-3 ni N1 ne sont des trades du Master : ils ne comptent jamais pour 50/20.

## 0. Règles communes aux deux fiches

- **Fenêtre neuve et disjointe** : [06/12/2026 10:21:26Z ; 18/12/2026 10:21:26Z), soit
  T0_c = 1 796 552 486 et D_c = 12 j. Elle suit immédiatement la fenêtre pilote, sans chevauchement.
- **Lecture conditionnelle** : la confirmation d'une hypothèse n'est LUE que si son pilote rend **GO_PILOTE**.
  - Sinon, aucune donnée de cette hypothèse n'est lue pour elle, et son essai de confirmation n'est pas consommé.
  - La collecte de la fenêtre de confirmation n'a lieu qu'après le 18/12, et seulement si au moins un pilote est
    GO_PILOTE.
- **Seuil** : α₂ = 0,025 unilatéral, avec **Holm** sur les hypothèses retenues, c'est-à-dire celles dont le pilote est
  GO_PILOTE.
  - K = 1 : seuil 0,025.
  - K = 2 : 0,0125 pour la plus petite valeur p, puis 0,025.
  - Valeur p unilatérale bootstrap = (nombre de tirages ≤ 0 + 1) / (tirages + 1). Une hypothèse INCONCLUSIF compte
    p = 1.
- **Inchangés** : mêmes coûts (cpmmcost 0.3, 105 000 lamports, pires états, garde de 20 000 ppm), mêmes planchers,
  même garde, même bootstrap stratifié, même vocabulaire.
- **Code** : g23five et n1verdict, SANS modification de leurs règles. Voir le § 3 : le seuil α y est codé en dur à
  0,05, et deux ajouts minimes sont donc nécessaires.
- **Mots de confirmation** : CONFIRMÉ, NON CONFIRMÉ, INCONCLUSIF.
  - CONFIRMÉ exige TOUS les critères de la fiche, au seuil Holm de l'hypothèse.
  - Sous les planchers : INCONCLUSIF.
- **Pas de modification** de règle, de δ ou de pools après le verdict pilote. Les seules quantités issues du pilote
  sont celles qui sont fixées ici par formule : σ_c, et donc n_c.

## A. Fiche de confirmation G2-3 (projet)

- **Pools** : les MÊMES 4 pools, liste `812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80`.
  - La règle G2-3 (`cpmmgen2.decisions_g23`) est inchangée.
  - Les b₃ restent gelés aux valeurs de la fiche pilote (2 / 1 / 6 / 1), jamais recalculés.
- **n_c** = ⌈((z₁₋α + z₀,₈) · σ_c / δ)²⌉, avec σ_c = max(σ du pilote, 2,5 %), δ = 0,5 % et une puissance de 0,80 :

| σ_c | n_c (K = 1, α = 0,025) | n_c (K = 2, premier pas α = 0,0125) |
|---|---|---|
| 2,5 % | **197** (R02) | 238 |
| 3 % | 283 | 343 |
| 4 % | 503 | 609 |
| 5 % | 785 | 951 |

- **Durée** : la fenêtre est fixée à 12 j (R04).
  - Si le pilote mesure r entrées par jour et que 12 × r < n_c, la confirmation est publiée « sous la cible ».
  - **Option, à trancher par R02** : D_c = min(30, max(12, ⌈n_c / r⌉)), fixée par formule avant le 06/12. La fin de
    fenêtre serait alors connue au verdict pilote, avant toute lecture de la fenêtre de confirmation.
- **Critères (CONFIRMÉ = tous)**, repris de la fiche pilote :
  - c1 : borne basse du net > 0, au seuil Holm, avec le même bootstrap stratifié par pool-jour (blocs d'1 jour) ;
  - c2 : borne basse de l'écart au témoin > 0, au même seuil et au même bootstrap (`difference_bounds`) ;
  - c3 : les deux moitiés > 0 (`cpmmprereg.halves`) ;
  - c4 : ventes nulles comptées (K01) ;
  - c5 : net > 0 avec une latence de 10 slots, et sans le pool le plus fourni ;
  - A1 : net > 0 avec 1 échec par transaction.
- **Crédits** :
  - estimation = crédits MESURÉS de la collecte pilote × D_c / 12 ;
  - plafond 33 000 (celui du pilote, R04-1) ;
  - un dépassement donne STOP, en conservant les pages déjà écrites ;
  - la mesure du pilote est NM jusqu'à sa collecte (après le 06/12).

## B. Fiche de confirmation N1 (projet)

- **Pools** : les MÊMES 3 pools (AEZjoU, G8kgi7, GdxFyc), liste
  `c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da`.
  - La rotation n'est PAS remesurée : la liste est figée par la fiche pilote.
- **Position** : la même configuration R04-6.
  - 0,5 % de la réserve WSOL lue à l'ouverture (T0_c).
  - Ouverture au début du jour 0, fermeture à la fin du jour 11.
  - Le mot porte sur l'écart à la détention, net de tous les coûts (C1), avec les coûts / 12 (C2).
  - Blocs de 2 jours ; garde K-1.
- **n_c** : même formule que pour G2-3, en unités de la mise par pool-jour.
  - **δ_N1 = 0,05 % de la mise par jour, À FIXER par R02.** Cela fait 0,6 % sur 12 jours, l'ordre des coûts d'un
    aller-retour à prix constant (0,56 à 0,61 % de la mise, n1rot).
  - **σ_c = max(σ du pilote par pool-jour, plancher)**. Le plancher est À FIXER par R02 ; aucun σ de N1 n'a jamais
    été mesuré.

| σ_c (par pool-jour, en part de la mise) | n_c (K = 1, α = 0,025) | n_c (K = 2, α = 0,0125) |
|---|---|---|
| 0,10 % | 32 | 39 |
| 0,25 % | 197 | 238 |
| 0,50 % | 785 | 951 |
| 1,00 % | 3 140 | 3 803 |

- **Limite structurelle, déclarée d'avance** : une fenêtre de 12 j sur 3 pools donne **au plus 36 pool-jours**,
  dans 18 blocs de 2 jours. La cible n'est atteignable que si σ_c ≤ 0,1 % environ par pool-jour (K = 1).
  - Au-delà, la confirmation N1 est publiée « sous la cible ».
  - Allonger la fenêtre changerait la configuration, puisque la position serait tenue plus longtemps. Ce n'est donc
    PAS proposé.
- **Critères (CONFIRMÉ = tous)** :
  - c1 : borne basse de l'écart > 0, au seuil Holm (n1verdict, blocs de 2 jours) ;
  - c2 : la même chose sans le pool qui porte le résultat (K-1) ;
  - c3 : les deux moitiés > 0, c'est-à-dire les jours 0 à 5 et les jours 6 à 11 ;
  - c4 : positions non valorisables comptées en perte totale ;
  - A1 : écart > 0 avec 1 échec par transaction.
  - Il n'y a pas de témoin pour N1 : la comparaison à la détention est déjà dans le mot.
- **Crédits** :
  - si la confirmation G2-3 est aussi collectée : **0 crédit de plus**, car les 3 pools font partie des 4 ;
  - si N1 est seul retenu : collecte des 3 pools seulement, estimée aux crédits MESURÉS de ces 3 pools au pilote ;
    plafond à fixer par R04, au plus 33 000.

## 3. Ce que « code sans modification » ne couvre pas (à faire auditer AVANT l'ancrage)

- `g23five` (0.1.1 et 0.2) a **ALPHA = 0,05 codé en dur** dans les bornes. Une confirmation à 0,025 ou 0,0125 exige :
  - un paramètre `alpha`, avec 0,05 par défaut, qui redonne exactement 0.1.1 / 0.2 (test d'identité comme pour
    block_days) ;
  - une valeur p bootstrap pour Holm ;
  - les moitiés (c3).
  Ce serait g23five 0.3. Les règles ne changent pas.
- `n1verdict` 0.2.2 : il faut lui faire passer `alpha` et produire les moitiés et la valeur p (n1verdict 0.3).
- **c5 de G2-3 (10 slots) et A1** : des positions recalculées par le code de R03 (cpmmpilot) avec une latence de
  10 slots et (1, 1, 1) échec. À confirmer par R03.
- Aucun de ces codes n'est écrit : j'attends l'accord de R04 et de R02 (règle « aucun code nouveau sans le dire »).

## 4. Essais

- Confirmation G2-3 : un nouvel essai ; confirmation N1 : un nouvel essai.
- Les numéros sont À ALLOUER par R04 (170 est l'essai N1 pilote).
- Chacun n'est consommé que si son pilote est GO_PILOTE ET si sa confirmation est lue.

## 5. QUESTION CLÉ pour R02 : ancrer AVANT le 06/12 ?

**Ma recommandation : OUI.** Ancrer les deux fiches de confirmation, et leur code, avant le **06/12/2026 10:21:26Z**
(début de leur fenêtre), donc avant de connaître les verdicts pilotes.
1. **La fenêtre est publique au fil de l'eau** : les données de la chaîne sont visibles par tous. Ancrer après le
   06/12 laisserait possible, même sans le vouloir, un choix de δ, de durée ou de critères influencé par les débuts de
   la fenêtre.
2. **Le verdict pilote ne doit rien changer d'autre que ce que la fiche fixe par formule** (σ_c → n_c, et D_c si
   l'option est retenue). Ancrer après le verdict permettrait d'ajuster la confirmation au résultat pilote, ce qui est
   interdit (« aucune modification de règle après avoir vu les résultats »).
3. **Le coût est nul si aucun pilote n'est GO** : rien n'est lu, aucun essai n'est consommé, aucun crédit n'est
   dépensé.
4. **Ce que cela demande** : g23five 0.3 et n1verdict 0.3 (§ 3) écrits, testés, mutés et audités avant le 06/12, et
   les essais alloués par R04. C'est faisable en 12 jours.

**Alternative admissible mais plus faible** : ancrer après le verdict pilote, mais avant toute lecture de la fenêtre
de confirmation. Elle protège les données, pas la conception.

**Points à trancher par R02** :
- l'ancrage avant le 06/12 ;
- δ_N1 et le plancher σ de N1 ;
- l'option D_c de G2-3 ;
- l'accord pour g23five 0.3 et n1verdict 0.3 ;
- la valeur p bootstrap pour Holm.
