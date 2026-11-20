# Note courte — entrées tardives : résultats latelab, 3 hypothèses de sélection, CPMM sans collecte — v0.1

RUGGER 01, 20/11/2026, pour R02 (audit) et R04 (suivi).
- **Statut** : EXPLORATOIRE. Aucune dépense, aucune collecte, aucune donnée protégée.
- **Compteur d'essais** : N = 163 après la découverte latelab (161 + 2). Le crible latelab porterait N à 164.

## 1. latelab 0.4, découverte sur la moitié 1 de W1 — sortie ANCRÉE par R02 (7351512d, lue par R02 en premier)

Les trois cellules ont : sortie à l'horloge de 60 s, 0,1 SOL, latence de 4 slots, loyer perdu, aucune sélection. Les
trois lignes sont interprétables. N = 163.

| Cellule | n (grappes) | Net moyen [IC 95 %] | Médiane | Gagnantes | Part des 5 meilleurs dans les gains | Net, loyer récupéré |
|---|---|---|---|---|---|---|
| **L1** `age:120` | 178 (174) | **−5,14 %** [−7,42 ; −2,90] | −4,15 % | 11 % | 56 % | −3,21 % |
| **L3** `age:300` | 82 (77) | **−7,81 %** [−10,77 ; −4,76] | −5,12 % | 12 % | 82 % | −5,94 % |
| Placebo (âge ≤ 120 s), descriptif | 270 (254) | −5,67 % [−7,54 ; −3,75] | −4,63 % | 13 % | 53 % | −3,75 % |

- **top1 = L1.** Son crible sur la moitié 2 a été calculé par R03 (sha 20aba3f5) ; il attend l'ancrage de R02, et rien
  n'en est lu. Avec lui, N = 164. Une réussite est très improbable.
- **Lecture.**
  - Sans sélection, une entrée tardive perd autant que le placebo.
  - Loyer récupéré, le net est de −3,2 %, soit à peu près l'aller-retour de frais (≈ 3,5 %) : **le brut d'une entrée
    tardive non sélectionnée est ≈ 0**.
  - Le « +2,90 % » de la ventilation T4 portait sur les positions du MASTER (déjà sélectionnées, autre sortie). Il
    NE se généralise PAS à tous les pools tardifs.
- **Conséquence.**
  - Le seuil à battre n'est plus de +0,75 point. **Il faut ≈ +3,5 points de brut** (≈ +5,5 avec le loyer perdu)
    pour qu'une sélection tardive devienne positive au palier moyen.
  - L'argument arithmétique de C-D (§ 11 du Dossier A) s'appuyait sur ce +2,90 %. Il est **affaibli**. Au palier de
    2 500 ppm, l'aller-retour coûte ≈ 0,7 %. Il faut y ajouter 2,05 % de loyer si le compte de jetons n'est pas fermé.
    C-D reste le seul cas où un brut ≈ 0 n'est pas loin de l'équilibre, À CONDITION de fermer le compte.
  - C-D n'est pas évalué ici. Il reste figé pour W2.
  - T1 et T3p restent figés tels quels (R02 8ce50be9) : ce résultat ne les redéfinit pas.

## 2. Trois hypothèses de sélection tardive : 1 essai chacune, sur la moitié 2 uniquement

> **Mise à jour du 20/11 (audit R02).** T2 est retiré. T3 devient **T3p**, qui utilise `top5_holder_share` calculée sur les seuls montants des échanges (créateur exclu). `top5_token_share` est interdite : son dénominateur est real_base. **T1 et T3p sont figés**, avant toute sortie latelab. Outil : latesel 0.1. Compteur hors HW1 : au plus 168.

**Règles communes.**
- **Entrée** : le point de la cellule tardive, `age:120`, ou `age:300` pour T3. On ajoute un seul filtre causal, calculé
  sur l'historique jusqu'à l'événement de décision. Ce filtre vient des `FEATURES` existantes de `statelab.signals`.
- **Exécution** :
  - 0,1 SOL ; latence de 4 slots ;
  - sortie à l'horloge de 60 s ;
  - loyer perdu ; une position migrée compte −1.
- **Seuil** : un quantile de POPULATION, fixé avant tout calcul sur la moitié 1. C'est un comptage, sans aucun
  rendement.
- **Test** : un seul essai par hypothèse, sur la moitié 2, avec les planchers n ≥ 30 et 20 grappes.
- **Pare-feu HW1** : ni `progress`, ni `quote_raised` (real_quote), ni réserves, ni ratio à un prix passé ou à un
  maximum, ni déclencheur sur une vente, ni âge ≥ 600 s.

| # | Règle causale (un filtre) | Raison économique | Effectif attendu, moitié 2 | Net attendu | Coût du test |
|---|---|---|---|---|---|
| **T1** | `age:120` et `unique_buyers` ≥ tercile haut (moitié 1) | Largeur de la demande : un pool encore acheté par beaucoup d'adresses à 2 min est moins un pool « mort » | ≈ 1/3 des entrées L1, soit ≈ 100 à 130 | inconnu ; faut battre +0,75 pt | 1 essai ; code ≈ 2 h + audit R02 ; 0 $ |
| **T2** | `age:120` et `buyers_10s` ≥ 2 | Arrivée récente d'acheteurs nouveaux : un flux vivant au moment de l'achat, et non un prix figé | ≈ 30 à 50 % des entrées L1 (à compter sur la moitié 1) | idem | 1 essai |
| **T3** | `age:300` et `top5_token_share` ≤ médiane (moitié 1) | Fait démontré sur P0 (3b16e5f7) : ce sont les détenteurs déjà présents qui vendent. Moins de concentration, c'est moins d'offre latente qui s'écoule pendant la détention | ≈ 1/2 des entrées L3 | idem ; c'est la plus argumentée | 1 essai |

**Budget.**
- Avec T1 à T3, N passe de 164 à **167** : au-dessus de 166, mais sous le plafond de 170 du plan v0.3.1, PASS R02.
- Pour tenir N ≤ 166, je propose **T3 puis T1**, et T2 en réserve.
- Un résultat positif reste une HYPOTHÈSE à confirmer sur W2.
- **À trancher par R02** : `top5_token_share` (des parts détenues, et non des réserves) est-il hors HW1 ?

## 2 bis. Résultats sur la moitié 2 de W1 (ancrés et lus par R02 ; N = 166) — AUCUN ne passe : l'emplacement L est VIDE

Sortie à l'horloge de 60 s, 0,1 SOL, latence de 4 slots, loyer perdu. Seuils de population de la moitié 1, ancrés
avant la moitié 2 : unique_buyers ≥ 26 ; top5_holder_share ≤ 0,770.

| Règle | n (grappes) | Net moyen [IC 95 %] | Médiane | Gagnantes | Part des 5 meilleurs | Net, loyer récupéré | Verdict |
|---|---|---|---|---|---|---|---|
| L1, crible (`age:120`, tous) | 106 (83) | **−10,29 %** [−13,81 ; −6,35] | −7,80 % | 11 % | 73 % | −8,47 % | échoue |
| **T1** (`age:120`, unique_buyers ≥ 26) | 34 (34) | **−5,59 %** [−11,17 ; −0,09] | −6,37 % | **32 %** | 76 % | −3,67 % | échoue |
| T3p (`age:300`, top5_holder_share ≤ 0,770) | 23 (23) | −10,62 % [−18,03 ; −4,18] | −9,70 % | 22 % | 100 % | −8,80 % | échoue (n < 30) |
| Placebo, descriptif | 200 (164) | −10,41 % [−13,02 ; −7,36] | −6,61 % | 10 % | 62 % | −8,59 % | — |

- **Lecture.** La moitié 2 est nettement plus défavorable que la moitié 1 : le placebo y fait −10,4 %, contre −5,7 %.
  - T1 fait mieux que L1 (+4,7 points, gagnantes 32 % contre 11 %), mais le net reste NÉGATIF, avec un IC sous zéro.
    C'est un indice descriptif que la largeur de la demande compte. Ce n'est pas une stratégie : aucune règle
    positive n'existe.
  - Aucune modification de T1 ni de T3p n'est permise après cette lecture (R02).
- **Piste 4 (sorties).** Aucun crible n'est positif. Selon ma recommandation, E1 et E2 ne sont donc PAS jouées, et le
  compteur reste à 166, plus 1 pour la porte C-D.
- **Ce qui reste** : la porte C-D (cdgate 0.1, en audit chez R02). C'est le seul candidat où un brut ≈ 0 n'est pas
  loin de l'équilibre, à condition de fermer le compte de jetons.

## 2 ter. Porte de non-réfutation de C-D sur W1 (cdgate 0.2 ; sortie ancrée et lue par R02, 2b173f10 ; N = 167) — C-D RETIRÉ

Règle figée : 1ᵉʳ événement entier à 450 slots ou plus, palier causal ≤ 2 500 ppm, 0,1 SOL, latence de 4 slots,
TP +7 % ou SL −5 %, sinon horloge à 30 s ; loyer perdu. Population : toute la plage d'évaluation W1.

| Mesure | **C-D** | Placebo à palier bas (descriptif) | MASTER W1 (cité) |
|---|---|---|---|
| Trades (grappes) | 46 (41) | 35 (34) | — |
| Net moyen [IC 95 %] | **−4,59 %** [−7,40 ; **−2,42**] | −1,82 % [−3,29 ; −0,33] | −4,26 % |
| Net médian | −2,69 % | −2,69 % | — |
| Gagnantes | 8,7 % | 20 % | — |
| Meilleur / pire trade | +9,6 % / −47,7 % | — | — |
| Brut (part de la mise) | −1,94 % | +0,89 % | — |
| Frais de courbe | 0,49 % | 0,50 % | — |
| Transactions | 0,21 % | 0,21 % | — |
| Loyer (perdu) | 2,04 % | 2,04 % | — |
| Net, loyer récupéré | −2,64 % | **+0,17 %** | — |
| Net à 10 slots de latence | −4,70 % | — | — |
| Glissement à l'achat | −3,5 % (prix en baisse avant l'atterrissage) | +0,5 % | — |
| Sorties | horloge 39, SL 5, TP 2 | horloge 28, SL 1, TP 6 | — |

**Cycles.** 771 pools tardifs, 53 éligibles (= Q4), 46 clôturés. 7 entrées à 600 s ou plus ont été comptées, mais
pas lues (13 %). Aucun achat refusé.

**Verdict.** La porte n'est pas passée : la borne haute de l'IC vaut −2,42 %, sous 0. C-D est retiré de W2, sans
variante ni repêchage (R02).

**Exécutabilité.** La règle est simple : palier lu à la décision, aucune course de latence. Mais même avec des frais
de 0,5 %, le brut est négatif (−1,9 %).

**Lecture.**
- Entrer tard ne crée pas d'avantage, même à frais bas.
- Le placebo à palier bas (entrée aléatoire à 120 s ou moins, même sortie) est le SEUL chiffre proche de l'équilibre :
  +0,17 % loyer récupéré, n = 35, 20 % de gagnantes.
- C'est une observation faite après regard, sur un comparateur. Ce n'est pas une règle.
- **Hypothèse nouvelle, pour des données NEUVES seulement** : « entrée précoce sur un pool à palier ≤ 2 500 ppm, avec
  fermeture du compte de jetons ». Elle n'est testable ni sur W1 ni sur P0 visible (aucun palier bas sur P0).

**Bilan des candidats W2.**
- C-A retiré ; C-C vide ; C-D retiré ; L vide.
- Il reste C-B : une hypothèse HW1 gelée, lisible seulement après le verdict officiel W1, donc après la dépense A2
  (B1).

## 3. CPMM après migration : ce qu'on apprend SANS collecte

- **Fréquence** : 12 pools migrés sur 2 273 exportés dans W1, soit ≈ 0,5 %, ≈ 2 à 3 par jour. La donnée existante
  (courbe LaunchLab) s'arrête à la migration. Il n'y a AUCUN échange CPMM dans W1, donc aucun rendement CPMM
  mesurable. C-C reste vide.
- **Descriptif possible, sans essai** : pour les 12 pools, l'âge à la migration et le nombre d'acheteurs uniques
  avant. Il faut aussi savoir combien de positions tardives latelab migrent avant la sortie à 60 s : chacune y compte
  −1, ce qui est prudent, mais faux en vrai (les jetons passent sur CPMM).
- **Hypothèse, si une collecte est autorisée plus tard** :
  - **C-M** : achat au premier swap CPMM à 60 s ou plus après la migration ; vente à l'horloge de 10 min.
  - **Frais** : 0,25 % par transaction, soit ≈ 0,5 % l'aller-retour, contre ≈ 3,6 % sur la courbe.
  - **Données** : il faut TOUTES les migrations du programme LaunchLab, y compris celles des pools créés avant la
    fenêtre.
  - **Puissance** : à ≈ 3 migrations par jour, 414 cycles demandent ≈ 140 jours. C'est infaisable sans élargir
    l'univers à d'autres plateformes à 0,25 % ou à des pools établis.
  - **Coût** : à chiffrer par R03 (X8). Il n'est pas prioritaire.

**Prochaine action.**
1. Remplir le § 1 dès la sortie ancrée.
2. Si R02 l'accepte, écrire `latesel` : latelab avec un filtre, T3 puis T1.
3. Faire auditer, puis faire exécuter par R03 sur la moitié 2.
