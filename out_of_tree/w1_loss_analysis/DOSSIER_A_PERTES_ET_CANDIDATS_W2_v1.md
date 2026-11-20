# Dossier A — Pertes W1 et candidats W2 — v1.2 (RUGGER 01, 2026-11-20)

**Audit R02 de la v1** (fc7b3a54, registre f2f86f74) : PASS SOUS RÉSERVES ; les portes sont ANCRÉES. Ses réserves sont intégrées ci-dessous (marque « R02 f2f86f74 »).

**Statut.** EXPLORATOIRE. Le dossier attend l'audit de RUGGER 02 (dossier B). Il ne modifie aucun résultat W1, ne
fige rien et ne lance rien. Il remplace la note v0.1, qui reste dans l'historique.

Cadres respectés :
- coordination de R04 du 20/11 ;
- conditions de R02 : cadre 3769fd9d (registre aa7d0d1c) et réponses w1loss 877da7b6.

**Sources chiffrées et ancrées.**
- W1 : lecture préliminaire `LECTURE_PRELIMINAIRE.json` sha ea152a32, ledger ancré 4da5fbfb (correction C1, 0
  écart), bilan vérifié par R02 (registre 62d8eae8).
- P0 développement : chiffres vérifiés par R02 (37d32c02, f583d747, ce5db0bc, de1b4bb1, 63817ac9) ; instrument
  des cohortes conforme (3b16e5f7).
- Les tableaux w1loss (T1 à T7) ne sont PAS encore produits. Leurs cases sont marquées « T1 à venir », etc.

**Compteur d'essais.** N = 159. Les ventilations w1loss compteront E = 7, à part. Aucune règle candidate n'a été
évaluée dans cette phase (`REGISTRE_ESSAIS_PHASE_W2.md`).

## 1. Décomposition de la perte, poste par poste

Les montants sont en % de la mise de 0,1 SOL, par position clôturée. W1 : MASTER, 128 positions (≡ référence
early_sniping par construction du code gelé). P0 : référence V3-01 (délai de 5 s, horloge 25 s), 124 positions.

| Poste | W1 MASTER | W1 placebo | P0 référence | Commentaire |
|---|---|---|---|---|
| Frais de courbe (achat + vente) | **3,34 %** | 4,20 % | 3,79 % | 78 % de la perte W1. Paliers causaux de P0 : 12 500, 17 500 et 37 500 ppm par transaction |
| Frais de transaction (2 × 105 000 lamports) | 0,21 % | 0,21 % | 0,21 % | Déjà au minimum : un achat, une vente |
| Tentatives échouées | 0 | 0 | 0 | Modèle gelé |
| Glissement de nos ordres | négligeable | négligeable | inclus dans le coût d'entrée | Mise faible devant la profondeur |
| Évolution du prix pendant la détention (« brut ») | **−0,72 %** | −0,19 % | −0,93 % | Aucune entrée n'a de brut positif en début de courbe, sur P0 comme sur W1 |
| **Net hors loyer** | **−4,26 %** | −4,59 % | −4,94 % | |
| Loyer du compte de token | 0 (supposé rendu, **non modélisé**) | idem | −2,05 % (modélisé) | En réel sans fermeture du compte : environ −6,3 % sur W1 |

**Le mécanisme de cohorte** a été mesuré sur P0 (instrument 3b16e5f7). Après notre achat, ceux qui vendent sont les
acteurs déjà présents : le créateur et les acheteurs des deux premiers slots au début, puis les autres acheteurs
précoces. Leur solde net est de −5 à −15 SOL à 300 s. Les nouveaux acheteurs n'absorbent pas ces ventes. Cela
explique le brut négatif d'une entrée précoce, quel que soit le signal.

**Sorties.**
- W1 : 58 arrêts de perte, 29 prises de bénéfice et 41 sorties à l'horloge ; 30,5 % de positions gagnantes.
- P0 : 7 règles de sortie causales ont été testées. Aucune n'améliore la référence, et la meilleure gagne +0,41
  point, avec un intervalle de [−1,17 ; +1,82].
- **Borne rétrospective (P0, provisoire)** : même une sortie au meilleur instant, connue d'avance, ne donnerait que
  +0,32 % en moyenne sur 61 paires, et −1,68 % avec le loyer.
- **Aucune règle de sortie ne peut rendre rentable une entrée précoce.**

**Ce qu'il faut franchir.** Le brut nécessaire vaut à peu près 2 × le taux de frais par transaction + 0,21 %. Il
est d'environ 0,71 % sur CPMM (0,25 %), environ 2,71 % au palier de 12 500 ppm, et environ 3,55 % à la moyenne W1.
Le brut actuel est de −0,72 %.

## 2. Solutions : effet estimé, avantages, limites, surajustement, critère W2

Les effets sont exploratoires. Les intervalles ne sont donnés que lorsqu'ils ont été calculés et vérifiés ; sinon,
la case le dit.

| Solution | Effet estimé sur le net (intervalle) | Avantages | Limites | Risque de surajustement | Critère W2 |
|---|---|---|---|---|---|
| **Palier de frais bas**, connu à l'entrée (veto au-delà de 15 000 ppm) | P0 (V3-07) : −3,24 % contre −4,94 % pour la référence, soit environ +1,7 point (59 positions ; intervalle non repris ici). W1 : T1 et T2 à venir | Causal, simple, effectif élevé | Net attendu toujours négatif (≈ −3,3 %) ; le palier est lié au type de lancement (biais B-3 noté par R02) | Faible : seuil fixé sur P0 le 10/11, avant W1 | GO de R02 : intervalle unilatéral > 0, supérieur au placebo et positif sur les deux moitiés. **Échec attendu** |
| **CPMM après la migration** (0,25 % par transaction) | Aucune donnée. Arithmétique seule : frais 3,34 % → 0,50 % | Seul levier qui ramène le seuil sous 1 % | Brut inconnu ; peu de pools migrent ; outils jamais exécutés sur données réelles | Faible si la règle HW1-M2 gelée est reprise telle quelle | Idem, plus le critère de couverture CPMM C-1 |
| **Changer l'entrée** : états hors début de courbe (fin de courbe, survivants, repli, purge) ou créateur non signataire | P0 : NON SIGNÉ +2,78 % [−0,13 ; +6,02] (96 positions), mais −0,91 % à 10 slots de latence et ≈ 0 sans les 5 meilleurs pools. Les autres : rejetées ou non évaluables sur P0. W1 : lecture HW1 unique après le verdict officiel | Vise la cause (le brut) | Effectifs faibles en fin de courbe ; décision sur la transaction de création pour NON SIGNÉ, ce qui n'est pas démontré en réel | **Élevé** si l'on choisit après lecture : il faut une règle de sélection écrite d'avance (§ 3) | Idem |
| Règle de sortie | ≤ +0,4 point (P0) | — | La borne rétrospective est proche de 0 | Élevé | Aucun bras proposé |
| Moins de transactions | Rien à gagner : 2 transactions par cycle, déjà le minimum | — | — | — | — |
| Loyer | Pas un gain. **Par défaut, il est PERDU** (−2,05 %, à remesurer ; R02 f2f86f74). Le mode « compte fermé » n'est admis que dans un cas : la fermeture et ses frais sont modélisés dans le simulateur AVANT le gel (déclarée et testée, comme C1), ET le code réel la prouve hors ligne et à blanc | Réalisme | La fermeture du compte en réel reste à prouver (branche `claude/r01-live-close-base-ata`) | — | Les deux mesures sont publiées ; le GO s'applique au mode gelé |
| Mise plus grande | +0,17 point au mieux (transaction) ; impact accru | — | Marginal | — | Stress seulement |

## 3. Candidats W2 (K ≤ 3), prêts à geler, avec leur règle de sélection écrite AVANT toute lecture

**Comparateurs W2** (R02) : le placebo (âge aléatoire, règle gelée), le statu quo W1 (early_sniping, ≡ MASTER W1)
et l'abstention (0).

**Règle de sélection.** Elle est écrite aujourd'hui, avant w1loss, avant la lecture HW1 et avant le pilote CPMM.
Une fois ancrée par R02, chaque porte ci-dessous s'applique telle quelle, et un candidat qui échoue à sa porte
n'est JAMAIS remplacé par une variante.

### C-A « Statu quo à palier bas »

- **Règle** : la décision W1 inchangée (scoreur, filtres, plan de sortie et horizon gelés), plus un veto si le taux
  de frais causal à la décision (`causal_fee_rate`, ledger `fee_rate_ppm`) dépasse 15 000 ppm.
- **Information** : causale, connue avant l'achat.
- **Porte (écrite d'avance)** : C-A n'entre dans W2 que si, dans T1 de w1loss, le palier 12 500 ppm du MASTER
  remplit deux conditions :
  - borne haute de l'intervalle à 95 % du net moyen ≥ 0 ;
  - n ≥ 30.
  Sinon, son emplacement reste vide.
- **Taux d'entrée** : environ 15 cycles clôturés par jour, si la part de P0 (59 sur 124) se retrouve ; à remplacer
  par la part T1.
- **Taille W2** : pour un net de +2 % : 390 cycles, soit environ 26 jours ; pour +1 % : environ 100 jours.
- **Limites** : net attendu négatif ; confondu avec le type de lancement.
- **Essais** : l'évaluation de la porte compte N + 1 (R02 f2f86f74 : c'est une décision fondée sur W1).

### C-B « Entrée hors début de courbe » (une seule hypothèse HW1, choisie par une règle fixe)

- **Règle** : la PREMIÈRE, dans l'ordre HW1-5, HW1-1, HW1-2, HW1-4, HW1-3, des hypothèses dont la lecture W1 unique
  donne le verdict « EXPLORATOIRE POSITIVE » ou « CONFIRMÉE SUR W1 ».
  - Le verdict doit inclure, pour HW1-5, les conditions obligatoires (i) à (viii) de R02 (d70251db).
  - La règle est reprise telle que figée le 11/11 (fiche N v0.2, code 47ec8826) : déclencheur, horizon et latence
    sans aucun changement.
  - Si aucune hypothèse n'a ce verdict, l'emplacement reste vide.
- **Information** : causale, par construction gelée.
- **Taux d'entrée** :
  - HW1-5 : environ 40 % des pools (P0), soit environ 125 positions par jour au rythme W1 (environ 310 pools par
    jour) ;
  - HW1-1 et HW1-4 : quelques dizaines par jour ;
  - HW1-3 : quelques-unes par jour.
- **Taille W2** : HW1-5, environ 3 jours pour +2 % et environ 12 jours pour +1 % ; les autres, plus long.
- **Limites** :
  - HW1-5 décide sur la transaction de création, ce qui n'est pas démontré en réel ;
  - HW1-5 est sensible à la latence ;
  - une hypothèse HW1 dont plus de 10 % des positions migrent est non évaluable sans CPMM.
- **Dépend de** B1 (verdict officiel W1, puis lecture HW1 : N = 164).
- **Ajouts obligatoires (R02 f2f86f74)** :
  - (i) un seul candidat, sans cumul ;
  - (ii) pour HW1-5, le GO W2 exige en plus deux choses, qui sont ses faiblesses connues sur P0 :
    - la robustesse à 10 slots de latence : un net moyen > 0 à 10 slots ;
    - un net moyen > 0 sans les 5 meilleurs pools ;
  - (iii) limite déclarée : rien ne démontre aujourd'hui qu'une décision prise sur la transaction de création soit
    réalisable en réel (détecter, décider et atterrir en 4 slots).

### C-C « CPMM après la migration »

- **Règle** : HW1-M2, telle que figée le 11/11. Achat de 0,1 SOL sur le pool CPMM 60 s après son premier swap,
  vente 300 s plus tard ; frais du pool lus sur la chaîne ; loyer compris.
- **Porte (écrite d'avance)** : le pilote CPMM réel doit remplir le critère de couverture C-1 (protocole CPMM v1.2)
  sur au moins 20 pools migrés, et la lecture exploratoire (comptée dans N) doit donner un net moyen > 0. Sinon,
  l'emplacement reste vide.
- **Taux d'entrée** : celui des migrations, inconnu. R03 estime 50 à 100 pools sur W1, soit environ 12 à 25 par
  jour.
- **Taille W2** : pour +2 %, environ 16 à 32 jours.
- **Limites** : aucune donnée aujourd'hui ; concurrence après l'ouverture ; protocole CPMM jamais exécuté sur
  données réelles.
- **Dépend de** B2 (pilote, accord du propriétaire, crédits gratuits).

**Choix de candidat que je recommande** : C-B en priorité, car c'est le seul qui ait à la fois un effectif suffisant
pour une W2 courte et un indice, même fragile, de brut positif. C-C vient ensuite, comme seul levier de coût
crédible. C-A sert surtout de témoin de coût : la porte le retirera probablement.

## 4. Durée de W2 qu'implique la puissance (calcul à vérifier par R02)

- Hypothèses : écart-type par cycle d'environ 13,7 % (W1) et K = 3. Il faut alors environ 390 cycles par bras pour
  +2 % net, et environ 1 550 pour +1 % (R02).
- Effet détectable en W2 de 5 jours :
  - statu quo : environ 160 cycles, soit un effet d'environ +3 % ;
  - C-B (HW1-5) : environ 600 cycles, soit un effet d'environ +1,6 %.
- **Recommandation** : la durée de W2 se fixe au gel, d'après les candidats retenus par les portes.
  - Avec C-B (HW1-5) seul : 5 à 12 jours.
  - Avec C-A ou C-C : au moins 16 à 32 jours, ou les accepter comme sous-puissants (déclaré NON CONCLUANT d'avance).
- **Crédits (aligné sur le dossier C de R03)** : environ 60 000 crédits par jour de fenêtre. Une W2 de 12 jours
  demande environ 0,73 M crédits, ce qui tient dans le quota mensuel de l'offre Free. MAIS la documentation actuelle
  de Helius réserve `getTransactionsForAddress` aux offres Developer et au-delà. Si un diagnostic de 1 requête au plus
  (≤ 50 crédits, avec le solde relevé avant et après) confirme ce refus en Free, la collecte demande l'offre
  Developer : environ 59 $ TTC par mois, avec l'accord du propriétaire. Le chiffrage fait foi dans le dossier C.
- **Écart-type par bras (R02 f2f86f74)** : σ = 13,7 % est celui du MASTER. Au gel, la taille de chaque bras se
  recalcule avec le σ de P0 propre à ce bras, et l'on retient la plus grande des deux tailles.

## 5. Décisions du propriétaire (à présenter par R04)

- **B0** : exécuter w1loss sur le ledger ancré (hors ligne, quelques secondes, aucun coût). Nécessaire à la porte
  de C-A.
- **B1** : verdict officiel W1 (dépense de calcul, note voie B). Il ouvre la lecture HW1 et la porte de C-B.
- **B2** : pilote CPMM réel, nécessaire à la porte de C-C. Plafonds proposés, jugés cohérents par R03 :
  - au plus 10 pools migrés, les premiers dans l'ordre chronologique de migration ;
  - 60 minutes après le premier swap de chaque pool ;
  - 1 500 crédits par pool, soit environ 14 800 transactions ;
  - 15 000 crédits au total, avec arrêt à 98 % ;
  - le rapport donne le nombre de pools plafonnés.
  - **Diagnostic préalable** : 1 requête, 50 crédits au plus. Si la méthode est refusée en Free, le pilote demande
    l'offre Developer (≈ 59 $ TTC), donc l'accord du propriétaire.
  - **Population du pilote** : lecture de `record['migration']` ADMISE par R02 (f5ad8d36) ; outil `w1migr` 0.1.1 (PASS 45813426 pour la 0.1). **Limite déclarée** : seuls les pools exportés, donc créés dans la fenêtre collectée, y figurent ; un pool créé avant W1 et migré pendant W1 est absent.
- **B3** : durée et calendrier de W2 (§ 4), plafond de crédits, offre Helius.
- Sans B1 ni B2, W2 ne comporterait que C-A face aux comparateurs, avec un échec attendu. **Je déconseille de
  lancer W2 dans cette configuration.**

## 6. Taux d'entrée : ce qui est connu, ce qui ne l'est pas (R02 141155dd)

| Bras | Cycles clôturés par jour | Source | Statut |
|---|---|---|---|
| Statu quo (≡ MASTER W1) | ≈ 32 | W1 ancré : 128 sur ≈ 4 j (1 612 800 slots à 215 ms) | **connu** |
| Placebo | ≈ 86 | W1 ancré : 343 sur ≈ 4 j | **connu** |
| C-A palier bas | ≈ 15 | part P0 (59 sur 124) × 32 | estimé ; connu sur W1 après T1 (effectif du palier 12 500) |
| C-B (HW1-5) | ≈ 125 | P0 : 40 % des pools ; W1 : 1 250 pools d'évaluation en ≈ 4 j | estimé ; connu après la lecture HW1 |
| C-C (CPMM) | ≈ 12 à 25 | estimation de R03 (50 à 100 pools migrés sur W1) | inconnu ; connu après le pilote |

**Puissance vérifiée par R02** : n = 160 détecte environ +2,7 % (K = 1), +3,0 % (K = 2) et +3,2 % (K = 3). Le palier
bas demande environ 24 à 26 jours pour +2 %. Aujourd'hui, seuls le statu quo et le placebo ont un taux d'entrée
mesuré sur W1. Le taux de C-A le sera dès l'exécution de w1loss (B0).

## 7. Errata de la note v0.1 (audit R02 5c4e0ae8 ; chiffres de la note jugés conformes)

- a) S1, « ≈ 790 positions en 5 jours » : ce chiffre vient de la fiche K v0.1 (H1 sur P0 visible, 59 sur 360
  pools). Sa population est la référence à délai de 5 s sur TOUS les pools, pas le MASTER à créateur signé. Pour le
  MASTER, le bon chiffre est d'environ 15 par jour (§ 6), soit environ 75 en 5 jours.
- b) S3(c), `jointlab` : chaque cellule examinée compte dans N. Le pare-feu HW1 est obligatoire (ni real_base, ni
  real_quote, ni progress, ni créateur non signataire, ni âge ≥ 600 s) tant que la lecture HW1 n'a pas eu lieu.
  Sinon, S3(c) attend cette lecture. Le dossier A ne retient PAS `jointlab`.
- c) Le constat « l'écart MASTER − placebo vient des frais et non du brut » n'est pas apparié. Il reste au
  conditionnel jusqu'au tableau T6.
- d) Bras W2 : A0 = statu quo, A1 = placebo, A2 à A4 = au plus K = 3 candidats (C-A, C-B, C-C, chacun sous sa
  porte), plus l'abstention comme comparateur.
