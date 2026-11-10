# MASTER V3 — fiche de pré-enregistrement V3-P0-EXPLO-1

RUGGER 01, 2026-11-10. À ancrer par RUGGER 02 **avant le premier rejeu**.

- **Plan (source unique, lisible par la machine)** : `v3lab/plan.py`, `plan_sha256` = `91e831e0bbb5e278cc3e5f27e29049283624a874e3183c8605d7d627c83e66d2`.
- **Code V3 qui choisit les données, décide et construit un bundle** : `v3lab_sha256` = `880c99bee21680e9d72443e6e644535bfd2891bcabeb6c14b28242f2cbe7ddda`.
- **Moteur d'exécution et de comptabilité** : celui de l'arbre gelé `aff97638`, appelé sans modification.
- **Statut de tout résultat** : EXPLORATOIRE. P0 a déjà servi à 25 essais. Rien n'est promu. Un succès donne seulement droit à un pré-enregistrement sur une fenêtre fraîche (W2).

## 1. Ce que l'on sait déjà (faits établis sur P0, sans nouveau calcul)

| Fait | Valeur | Source |
|---|---|---|
| Frais de courbe par côté | 1,25 % à 3,75 % | `cost_decomposition.json` 7d2d544b, script PASS R02 |
| Frais aller-retour, en part du coût | 3,7 % à 7,3 % ; seuil de rentabilité 3,96 % à 7,53 % | idem |
| Impact propre (entrée de 0,1 SOL) | < 0,3 % | idem |
| Coûts fixes de transaction | 0,21 % | idem |
| Rendement moyen des cycles clos, sortie à 25 s | −3 % à −13 % selon le bras et le segment ; négatif dans les 30 croisements | livrable G |
| Meilleur bras | le placebo aléatoire, ou à égalité avec lui | livrable G |
| Filtres d'entrée testés (confirmation, remplissage, veto initiés, sac du créateur) | aucun effet significatif | livrable G |

**Lecture.** La perte moyenne d'une entrée quelconque est de l'ordre du coût de traverser la courbe deux fois. Ce qui reste à mesurer : la part exacte coût / dérive par cycle, l'effet du palier de frais, l'effet de la durée de détention, et la fréquence des trajectoires qui dépassent le coût.

**Non mesurable sur P0** : le min_out (non modélisé), les échecs de transaction réels (stress descriptif seulement), la sortie après migration (aucune migration parmi les pools visibles), l'effet du régime de marché (12,85 h).

## 2. Données

- **Autorisées** : les pools P0 visibles (exploration, train, validation), dans un pack « visible seulement » construit par `v3lab pack` et ancré par R02.
- **Interdites, refusées par le code** :
  - tout slot ≥ 467 275 745 (W1) ;
  - le holdout P0 : ses fichiers ne sont jamais copiés dans le pack ; leur sha256 figure dans `SEALED_SHA256.txt` et tout fichier de cette liste est refusé ;
  - un export brut (P0 ou W1) : refusé, faute du bloc `v3_visible` ;
  - un pack dont le sha du MANIFEST n'est pas celui ancré.
- **Découpage** : `validation.chronological_split` de l'arbre gelé (4 × 25 %, créateurs disjoints), calculé sur tous les pools de l'export source. Embargo = 6 018 slots, le plus grand horizon de résultat des essais (âge d'entrée + détention + latence).
  - Avec `--table-from-bundle`, la table (créateur, slot de création, exclusions) vient d'un bundle P0 déjà enregistré : aucun fichier de pool non visible n'est alors ouvert.
- **Usage des segments** : exploration et train servent à vérifier le signe ; la validation sert **une seule fois par hypothèse**. Tout second passage est un nouvel essai.
- La liste des fichiers lus, avec leur sha256, est écrite dans chaque bundle.

## 3. Exécution et coûts (identiques au moteur gelé)

- Entrée de 0,1 SOL ; latence de 4 slots ; frais de courbe par `causal_fee_rate` ; remplissages entiers exacts ; impact propre rejoué sur les transactions suivantes ; 5 000 + 100 000 lamports par transaction propre.
- Aucun coût n'est modifié. Référence et candidats tournent sur les mêmes pools, avec le même moteur.
- Fenêtre : coupure d'entrée = `window_slot_max` − `hold_gap_slots(règle de sortie)`, jamais après la coupure de la source ; un cycle ne compte que s'il sort avant `window_slot_max` (règle gelée M1).

## 4. Essais (8 au maximum, tous inscrits au registre V3 avant leur rejeu)

| Essai | Rôle | Entrée | Sortie |
|---|---|---|---|
| V3-01 | référence | délai fixe 5 s | horloge 25 s |
| V3-02 | placebo | âge d'entrée aléatoire (≤ 120 s) | horloge 25 s |
| V3-03 | candidat H2 | délai fixe 5 s | horloge 120 s, stop 30 %, stop suiveur 25 % |
| V3-04 | candidat H2 | délai fixe 5 s | horloge 300 s, mêmes stops |
| V3-05 | candidat H2 | délai fixe 5 s | horloge 900 s, mêmes stops |
| V3-06 | sonde (descriptive) | délai fixe 5 s | horloge 900 s, sans stop ; enregistre la valeur de liquidation exacte après chaque événement |
| V3-07 | candidat H1 | délai fixe 5 s, refusé si frais causaux > 15 000 ppm | horloge 25 s |
| V3-08 | candidat H3 | courbe entre 30 % et 80 %, gain ≥ 5 points en 60 s, top 1 ≤ 20 %, créateur n'ayant pas vendu, âge ≤ 600 s | sortie à 90 % de la courbe, stop suiveur 20 %, stop 25 %, horloge 600 s |

Les paramètres sont fixés a priori et ne sont réglés sur aucun résultat. Le seuil de 15 000 ppm isole le palier le plus bas mesuré sur P0 (12 500 ppm).

## 5. Hypothèses, tests et critères (écrits avant tout résultat)

Rendement r d'une position entrée : rendement net du cycle clos (formule gelée) ; −1 si la position n'est pas un cycle clos.

### H1 — Coût : le palier de frais bas a une espérance nette supérieure, à entrée identique
- **Mécanisme** : l'aller-retour paie deux fois le taux du pool. Si le mouvement brut ne dépend pas du palier, le palier bas garde la différence.
- **Test** : ablation exacte de V3-01 par V3-07 (même instant, lignes de trade identiques), fonction gelée `veto_partition`, 10 000 abstentions aléatoires.
- **Réussite** : en validation, gardés − retirés > 0 et p < 0,05, avec au moins 20 cycles clos gardés et 20 retirés ; même signe en exploration et en train.
- **Non évaluable** : moins de 20 cycles clos d'un côté en validation. **Échec** : tout autre cas.

### H2 — Sortie : une détention plus longue avec stops fait mieux que la sortie à 25 s, sur les mêmes entrées
- **Mécanisme** : le coût aller-retour est payé une fois, quelle que soit la durée. Une détention plus longue peut garder la queue droite, et les stops couper les lancements morts. L'inverse (le temps passé en position coûte) est aussi plausible : la lecture est bilatérale.
- **Test** : différence appariée par pool, d = r(candidat) − r(V3-01) ; moyenne de d ; bootstrap par créateur (10 000 tirages, graine 20261110) ; p unilatéral = part des moyennes ≤ 0 ; correction de Holm sur les 3 candidats.
- **Réussite** : en validation, moyenne de d > 0, p de Holm < 0,05, et CVaR 5 % du candidat pas inférieure de plus de 0,10 à celle de V3-01 ; même signe en exploration et en train.
- **Non évaluable** : moins de 20 entrées appariées en validation. **Échec** : tout autre cas.

### H3 — Sélection : acheter un remplissage rapide en milieu de courbe et vendre avant la migration a une espérance nette positive
- **Mécanisme** : sur une courbe à produit constant, le prix monte à chaque achat ; un pool au-delà de 30 % qui gagne encore 5 points par minute est dans une course réflexive vers la migration.
- **Test** : V3-08 seul ; moyenne pessimiste par position entrée ; bootstrap par créateur.
- **Réussite** : en validation, au moins 20 positions entrées, moyenne pessimiste > 0, borne basse de l'IC 95 % > 0, et moyenne supérieure à celles de V3-01 et V3-02.
- **Non évaluable** : moins de 20 positions entrées en validation. C'est l'issue attendue sur P0 (événements rares, aucune migration visible) ; l'hypothèse sera alors portée telle quelle au pré-enregistrement W2.

## 6. Sorties descriptives (aucune décision)

- Par bras et par segment : entrées, clos, non clos par motif, rendement moyen, moyenne pessimiste, taux de réussite, CVaR 5 %, IC 95 % par créateur, P&L total.
- **Décomposition de la perte** par cycle clos : `cost0` = coût instantané de l'aller-retour (achat puis vente immédiate sur l'état laissé par notre achat, coûts de transaction compris) ; `drift` = r − cost0, ce que le marché a fait pendant la détention.
- **Sonde V3-06** : meilleure et pire valeur de liquidation après l'entrée (MFE, MAE), âge du sommet, part des entrées dont le MFE dépasse 0, 10, 25, 50 et 100 %, courbe d'horizon à 10, 25, 60, 120, 300, 600 et 900 s. Latence de vente ignorée : ce n'est pas le résultat d'une règle de sortie.

## 7. Comptage

- Registre V3 séparé et chaîné ; il refuse d'écrire dans un registre qui n'est pas un registre V3.
- Chaque configuration exécutée compte pour un essai, même abandonnée. N cumulé = 25 + essais V3 (33 si les 8 tournent), utilisé pour le DSR.
- Le registre f1f26e36, N = 32 de W1 et le registre W1 ne sont pas touchés.

## 8. Après

- Aucune promotion à partir de P0, quel que soit le résultat.
- Les données W1 ne servent pas à développer V3 avant le verdict W1 de R02.
- `v3lab` ne tourne jamais dans le processus, le répertoire ou le PYTHONPATH des étapes `dayj`.
