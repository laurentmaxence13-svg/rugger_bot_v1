# Réorientation si C-B échoue — étape 8 du chemin critique — v0.1 (R01, 21/11 ; 1 page ; pour R02, R04 et le propriétaire)

## Constat (chiffres ancrés de W1 ; aucun nouvel essai)

Sur la courbe LaunchLab, avec des frais standards et une mise de 0,1 SOL, notre preneur à 4 slots n'a **aucun brut
positif**.

| Mesure | Valeur | Source |
|---|---|---|
| MASTER W1, net hors loyer | **−4,26 %** (brut −0,72 %, frais de courbe 3,34 %, tx 0,21 %) | ea152a32, Dossier A § 1 |
| Tardif sans sélection (2 min / 5 min) | −5,14 % / −7,81 % ; loyer récupéré : −3,21 %, donc brut ≈ 0 | 7351512d |
| Tardif sélectionné T1 (moitié 2) | −5,59 % [−11,17 ; −0,09] ; il bat le placebo d'environ 5 points | f3c6c9e3 |
| C-D (tardif à palier ≤ 2 500 ppm) | −4,59 % [−7,40 ; −2,42] : brut −1,94 % malgré des frais de 0,49 % | 2b173f10 |
| Placebo précoce à palier bas | +0,17 % loyer récupéré (n = 35, observé après regard) : seul cas proche de l'équilibre | 2b173f10 |
| Mécanisme (P0) | Ce sont les détenteurs déjà présents qui vendent après notre achat (−5 à −15 SOL à 300 s) | 3b16e5f7 |

**Seuil à franchir** : brut ≥ 2 × taux de frais + 0,21 %, soit ≈ 3,55 % à la moyenne W1, contre ≈ 0,71 % à 0,25 %.
**Conclusion** : le levier n'est pas le signal sur la courbe, il est dans les **coûts**, ou dans un **autre lieu
d'échange**.

## Pistes encore crédibles, classées

| # | Piste | Argument chiffré | Données neuves | Coût | Essais |
|---|---|---|---|---|---|
| 1 | **Fermer le compte de jetons**, pour tout candidat | +1,89 à +1,93 point par position de 0,1 SOL (closedacct 0.2, PASS). C'est un gain de coût, pas d'avantage : le MASTER passerait de ≈ −6,3 % loyer perdu à ≈ −4,4 % | Aucune ; preuve sur la chaîne plus tard (P-1 live) | 0 $ | 0 (ce n'est pas une règle de sélection) |
| 2 | **Lieux à 0,25 %, pools CPMM ÉTABLIS** (déjà migrés, liquides), avec des stratégies hors début de courbe | Seuil 0,71 % au lieu de 3,55 %. C'est le seul univers où un brut modeste peut suffire | Collecte CPMM d'un univers de pools établis : décodeur à certifier (C-1 non évaluable aujourd'hui) | Pilote ≤ 50 000 crédits, puis à chiffrer par R03 ; au-delà de 1 M par mois, l'offre payante (décision du propriétaire) | Nouveau plan de recherche et nouveau plafond N, fixés par R02 |
| 3 | **C-E en W2** (déjà figé, non recommandé) | Espérance ≈ 0 (+0,07 % après frais de nettoyage) ; δ gelé +2 % : NO-GO ou INCONCLUSIF attendu | W2 de 48 à 64 jours | 4 à 5 mois de quota gratuit | Déjà compté (168) |
| 4 | **Sélection par la demande (indice T1)** | Elle bat le placebo d'environ 5 points, mais reste négative. Elle n'a de sens que combinée à la piste 2 ou à la piste 3 | Nouvelle fenêtre (W2 ou plus tard) ; aucune variante sur W1 | Selon la fenêtre | 1, en pré-enregistrement neuf |
| 5 | **Arrêt ordonné de la piste « courbe LaunchLab »** | Si C-B échoue, toutes les règles causales autorisées sur W1 sont négatives. Continuer sur la courbe sans nouvel argument serait du surajustement | — | 0 $ | 0 |

## Recommandation

- **Si C-B échoue** :
  1. Déclarer la courbe LaunchLab sans avantage démontré (piste 5).
  2. Garder la piste 1 dans toute exécution future.
  3. Proposer au propriétaire un pilote CPMM établi (piste 2) : ≤ 50 000 crédits gratuits, décodeur certifié d'abord,
     nouveau plan pré-enregistré par R02.
- **C-E** seulement si le propriétaire veut un essai long à faible probabilité.
- **Dans tous les cas** : aucun trading réel, et le budget N actuel n'est pas dépassé (170 hors HW1).
