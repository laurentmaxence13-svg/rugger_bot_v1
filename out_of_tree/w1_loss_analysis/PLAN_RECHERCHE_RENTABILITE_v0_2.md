# Plan de recherche de rentabilité — v0.2 (RUGGER 01, 20/11/2026 ; audit R02 53ae2cae intégré, coordination R04)

Ce plan répond aux directives du propriétaire du 20/11 (« Mission priorité absolue : rentabilité », puis « Ne bloquez
pas les recherches stratégiques en attendant le verdict officiel W1 »). Il porte uniquement sur des analyses hors
ligne : aucune collecte, aucune dépense, aucun ordre. Compteur d'essais au départ : N = 161 ; ventilations : E = 7.

## 1. État des recherches : démontré, prometteur, hypothétique, rejeté

| Statut | Constat | Source |
|---|---|---|
| **Établi (exploratoire)** | Un aller-retour coûte de **3,96 à 7,53 %** selon le palier, plus 2,05 % de loyer si le compte n'est pas fermé | P0, coûts `cost_decomposition` 7d2d544b (ancrage R02 du 09/11) ; W1 ancré |
| **Établi (exploratoire)** | Après une entrée précoce, ce sont les détenteurs déjà présents qui vendent ; le brut est négatif dans tous les états de début de courbe | P0, cohortes : instrument jugé conforme par R02 le 11/11 (3b16e5f7, suivi L v3), **chiffres non recalculés** ; 50 cellules f583d747 |
| **Établi (exploratoire)** | Aucun des 34 signaux et aucune des 7 règles de sortie ne rend une entrée précoce rentable. Même une sortie idéale, connue d'avance, ne donne que +0,32 % (chiffre provisoire) | P0 ce5db0bc, f583d747 |
| **Établi (exploratoire)** | Le MASTER W1 (≡ early_sniping) fait −4,26 % net, contre −4,59 % pour le placebo. L'écart apparié est de +1,23 % [−2,23 ; +4,82], non significatif | W1 ancré ea152a32 et da1e5758 |
| **Rejeté** | Palier de 12 500 ppm seul : −5,45 % [−10,89 ; −0,55] (C-A) ; détention longue (H2) ; fin de courbe sur P0 (V3-08) ; REPLI et PURGE sur P0 | W1 da1e5758 ; P0 |
| **Prometteur (cellule choisie APRÈS regard parmi E = 7, IC non corrigé)** | **Entrées tardives (≥ 450 slots, environ 97 s)** : brut **+2,90 % [+0,90 ; +5,22]**. C'est le seul brut positif établi. Le net reste à −0,75 %, à cause des frais | W1 da1e5758, ventilation T4 |
| **Prometteur (cellule choisie APRÈS regard parmi E = 7, IC non corrigé)** | **Palier LaunchLab de 2 500 ppm** (0,25 % par transaction) : placebo +0,16 % [−1,48 ; +1,71], la seule moyenne nette non négative | W1 da1e5758, ventilation T1 |
| Fragile | Créateur non signataire (HW1-5) : +2,78 % [−0,13 ; +6,02] sur P0, mais il disparaît à 10 slots de latence et sans les 5 meilleurs pools | P0 de1b4bb1 |
| Hypothétique | CPMM après migration (seuil de brut ≈ 0,7 %) ; survivants ; reprises après correction ; stabilisation après pression vendeuse ; fin de courbe | jamais mesuré, ou gelé dans HW1 |

**Lecture.** L'avantage, s'il existe, n'est PAS au début de la courbe. Les deux seuls signaux positifs portent sur le
MOMENT (tardif) et sur le COÛT (palier bas). Ils sont indépendants et n'ont jamais été combinés.

## 2. Contrainte de méthode : le pare-feu HW1

Plusieurs axes demandés recoupent les cinq hypothèses gelées avant W1 :
- les reprises après correction recoupent HW1-1 REPLI ;
- la stabilisation après pression vendeuse recoupe HW1-2 PURGE ;
- les survivants recoupent HW1-4 ;
- la fin de courbe recoupe HW1-3.

Ces hypothèses se lisent UNE seule fois, après le verdict officiel W1. C'est la seule épreuve CONFIRMATOIRE
disponible sans nouvelle donnée.

Tant que cette lecture n'a pas eu lieu, mes outils W1 n'utilisent ni leurs déclencheurs, ni leurs variables
(real_base, real_quote, progress, créateur non signataire, âge ≥ 600 s). **Conséquence : le verdict officiel W1
(dépense A2, ≤ 66 $) ouvre la meilleure source de preuve rapide sur les axes C et D.** Il n'empêche pas d'avancer
sur le reste.

## 3. Classement argumenté des cinq pistes

| Rang | Piste (axes) | Argument économique | Données | Ce qui manque | Budget d'essais |
|---|---|---|---|---|---|
| **1** | **Entrée tardive à palier bas** (C + E), candidat C-D | Le brut tardif (+2,9 %) dépasse le seuil du palier de 2 500 ppm (≈ 0,71 %). Une entrée tardive est aussi moins exposée à la course de latence des snipers | W1 (déjà lu), P0 | Q3 : le palier baisse-t-il avec l'âge (feeage sur P0, autorisé) ? Q4 : taux d'entrée (feeage sur W1) | 1 (déjà compté) |
| **2** | **Sélection parmi les entrées tardives** (B ; signaux ADMIS par R02 53ae2cae : acheteurs et vendeurs distincts, nombre de transactions, volumes en SOL, flux net comme niveau sur une fenêtre fixe, palier, historique du créateur ; INTERDITS avant HW1 : real_quote, tout rapport à un prix passé ou à un maximum, toute entrée sur une vente, « pression puis stabilisation ») | Classer les pools tardifs par des signaux connus à la décision : flux net acheteurs − vendeurs, diversité des acheteurs, pente de prix, palier, historique du créateur. On cherche le tiers à brut ≥ +3 % | W1, moitié 1 pour la découverte, moitié 2 pour le crible | Outil `latelab`, à écrire, sous pare-feu HW1 (âge ∈ [450 slots ; 600 s)) | ≤ 6 (grille fixée d'avance) |
| **3** | **Hypothèses HW1 gelées** (C, D) | Déjà préenregistrées : REPLI, PURGE, SURVIVANT, FIN DE COURBE, NON SIGNÉ. Ce sont les seules qui peuvent devenir « confirmées sur W1 » | W1, une seule passe | Le verdict officiel W1 (B1 : accord de dépense A2) | 5 (prévus, N = 164 puis +) |
| **4** | **Sortie adaptée aux entrées tardives** (D) | Sur P0, les sorties n'aidaient pas parce que l'entrée était mauvaise. Avec un brut positif, capter le MFE (sortie sur retournement de flux, stop suiveur) peut compter. Sonde MFE/MAE d'abord, sans compter de règle | W1 | Sonde MFE/MAE des entrées tardives (`latelab --probe`), puis ≤ 2 règles | ≤ 2 |
| **5** | **CPMM après migration** (A) | Meilleure économie (0,25 % par transaction) | **Insuffisantes** : 12 pools migrés sur W1, soit environ 3 par jour. Le décodeur n'est pas certifié (C-1 non évaluable) | Une collecte CPMM de TOUTES les migrations LaunchLab, y compris les pools créés avant la fenêtre : réseau et crédits, donc accord du propriétaire | 0 avant les données |

**Si aucune piste ne tient** : le même travail sur des lieux voisins à frais bas (pools CPMM établis, autres
plateformes de lancement à 0,25 %) demanderait de nouvelles données. Ce serait à proposer au propriétaire avec un
chiffrage.

## 4. Plan d'expériences priorisé (hors ligne ; chaque résultat ancré par R02 avant lecture)

| # | Expérience | Qui | Autorisation | Délai |
|---|---|---|---|---|
| X1 | feeage 0.2 sur P0 visible (Q3) | R03 | **Accordée** (20/11, point 2) | immédiat |
| X2 | feeage 0.2 sur W1, plage d'évaluation (Q4 : taux C-D) | R03 | point 1, après PASS R02 | après X1 |
| X3 | Écrire `latelab` 0.1 : déclencheurs tardifs, signaux de sélection, sonde MFE/MAE ; liste fermée ; pare-feu HW1 | **R01** | aucune requise (code) | 24 h |
| X4 | latelab : découverte sur la moitié 1 de W1 (≤ 6 cellules), puis crible sur la moitié 2 (≤ 2 cellules) | R03 exécute, R02 ancre | point 1, après PASS R02 | après X3 |
| X5 | Décider C-D : règle unique ou conjonction (Q3) ; taille W2 (Q4, σ du bras) | R01, puis R02 | — | après X1 et X2 |
| X6 | Protocole W2 : K ≤ 3 parmi C-B (HW1 retenue), C-D et le meilleur latelab | **R02** | point 3 | en continu |
| X7 | Paquet A2 : audit et tarif | R02, R03 | lancement : accord du propriétaire | en cours |
| X8 | Proposition de collecte CPMM chiffrée (toutes les migrations, pilote, plafond) | R03, puis R01 | décision du propriétaire | 48 h |

**Budget (choix après R02 53ae2cae)** : découverte latelab ≤ **4** cellules, crible 2, sorties 2, donc N ≤ 161 + 4 + 2 + 2 = **169 ≤ 170**, hors HW1. La sonde MFE/MAE est descriptive, hors N. Toute cellule examinée compte. Les
ventilations descriptives restent hors N.

## 5. Attribution

- **R01** :
  - X3 (latelab) et X5 ;
  - règles des candidats : sélection, achat, vente ;
  - le tableau des « 3 meilleurs » demandé par le propriétaire, avec pour chaque candidat la sélection, l'achat, la
    vente, la rentabilité attendue, le risque, l'exécution et la validation.
- **R02** :
  - audit de ce plan, du budget d'essais et du pare-feu ;
  - ancrage de chaque résultat ;
  - protocole W2 (X6) ;
  - audit du paquet A2.
- **R03** : X1 maintenant, puis X2 et X4 ; relecture du tarif A2 ; X8 (chiffrage de la collecte CPMM) ; reprise de
  la sauvegarde.
- **R04** :
  - suivi ;
  - présentation au propriétaire des décisions B1 (dépense A2, qui débloque HW1) et X8 (collecte CPMM) ;
  - rapport « démontré / prometteur / hypothétique / rejeté » à chaque jalon.

## 6. Conditions de R02 pour latelab (53ae2cae), appliquées

1. Grille et signaux fermés dans le code, puis ancrés. La non-équivalence avec HW1 est déclarée signal par signal.
2. Moitiés de W1 par slot de création. Coupe à **468 484 945**, fixée dans le code.
3. Découverte :
   - critère : net moyen avec loyer PERDU, sortie **TP 7 % / SL 5 %** (celle du statu quo) ;
   - classement : par borne basse de l'IC à 95 %, bootstrap par créateur ;
   - n < 30 : la cellule est « non interprétable ».
4. Crible : les 2 cellules de tête seulement. Une cellule passe si net > 0 et n ≥ 30. Le crible n'est jamais une
   preuve.
5. Au plus 1 cellule en W2, sans repêchage. Il y a un emplacement « L » dans le dossier B v1.1 (K = 3, fixé avant
   tout résultat).
6. Chaque sortie est ancrée par R02 avant lecture.
7. Si la meilleure cellule est C-D, il n'y a pas de 2ᵉ emplacement. J'applique donc l'option (ii) de la
   spécification : L2 et L4 évaluent la conjonction, et C-D devient « sélectionné après évaluation W1 ». Sauf avis
   contraire de R02.
8. PASS de R02 sur le code de latelab (tests et défauts volontaires) avant toute exécution.
