# latelab 0.1 — spécification à faire valider par R02 AVANT d'écrire le code (X3 du plan v0.1)

**But.** Mesurer sur W1 (données de développement, déjà lues) si des entrées TARDIVES ont un rendement net positif,
avec une grille fixée ici, avant tout calcul.
- Une piste retenue n'est qu'une HYPOTHÈSE.
- Elle se confirme sur W2 seulement, après un gel.

## Réemploi, sans modification

L'outil s'appuie sur des modules existants, sans les modifier :
- `statelab.study.probe` : valorisation `v4sim` en mode M-P ; sortie à l'horloge avec la latence de vente gelée ;
  latence de 4 slots à l'achat ; taux de frais causal à la décision ; meilleure et pire valeur (MFE, MAE) jusqu'à la
  vente ; une position migrée compte −1 ;
- `statelab.points.decision_points` ;
- `statelab.study.cluster_key` ;
- `hrr.usable_timeline` ;
- `w1aux.lazy`, qui ne garde qu'une archive en mémoire à la fois.

**Loyer** : compté comme PERDU par défaut (R02 f2f86f74). Le rendement « compte fermé » est publié à part.

## Population et pare-feu HW1

- **Population** : les pools W1 exportés, créés dans [467 678 545 ; 469 291 345), et rejouables.
- **Grappe** : la clé `cluster_key`.
- **Labels gardés** : seulement `age:120` et `age:300`, c'est-à-dire le premier événement entier d'âge ≥ A,
  avec au plus 30 s de retard (grille statelab existante). Ces âges sont < 600 s, donc hors HW1-4.
- **Labels exclus** : aucun label `progress` (HW1-3) ; pas de déclencheur de repli, de purge ou de créateur non
  signataire.
- **Signaux** : aucun signal réserve, progression ou signataire n'est lu. Le taux de frais causal à la décision est
  la seule variable de sélection de la v0.1.
- **Placebo** : le label `placebo:0` de statelab (âge aléatoire ≤ 120 s), comme comparateur.

## Grille de découverte, fixée ici : 4 cellules au plus

La découverte se fait sur la moitié 1 de W1 : pools créés dans la première moitié chronologique de la plage.

| Cellule | Entrée | Sélection | Sortie |
|---|---|---|---|
| L1 | `age:120` | tous les paliers | horloge 60 s |
| L2 | `age:120` | palier causal ≤ 2 500 ppm | horloge 60 s |
| L3 | `age:300` | tous les paliers | horloge 60 s |
| L4 | `age:300` | palier causal ≤ 2 500 ppm | horloge 60 s |

- **Par cellule** :
  - n et nombre de grappes ;
  - net moyen et IC à 95 % par grappes (graine 20261120, 2 000 tirages) ;
  - médiane, gagnantes, part des 5 meilleurs pools ;
  - écart non apparié au placebo ;
  - quantiles du MFE et du MAE (descriptifs) ;
  - part de migrées ;
  - sensibilité à 10 slots de latence (déclarée, sans effet sur un verdict).
- **Planchers** : 30 positions et 20 grappes, sinon la cellule est « non interprétable ».
- **Règle de sélection, fixée ici** : on retient la cellule qui a la plus haute borne basse d'IC parmi celles qui ont
  passé les planchers.
- **Crible** : cette seule cellule est rejouée sur la moitié 2 (1 essai).
- **Comptage** : N + 4 pour la découverte, N + 1 pour le crible.

## Question bloquante pour R02 : la propreté de C-D

Les cellules L2 et L4 ÉVALUENT sur W1 la conjonction « tardif × palier bas », c'est-à-dire C-D. Ta condition 1 de
3cd2ffa2 l'interdisait, pour garder C-D propre pour W2. Trois options :

- **(i)** Garder C-D propre. latelab se limite à L1 et L3 ; C-D reste testé seulement sur W2.
- **(ii)** Évaluer L2 et L4 sur W1, et déclarer C-D « sélectionné après évaluation W1 ». W2 reste l'unique épreuve ;
  c'est le statut d'une hypothèse de développement ordinaire.
- **(iii)** N'évaluer que L1 et L3, et figer C-D AVANT de lire L1 et L3.

**Ma recommandation : (iii).** C-D reste propre. latelab dit si le « tardif » seul a un net positif sur W1, ce qui
est l'information utile pour choisir la durée et le rythme de W2.

## Question 2 pour R02 : la liquidité (axe B)

Faut-il interdire `real_quote` comme signal de sélection avant la lecture HW1 ? C'est une variable d'état de HW1-1.
Si oui, la v0.2 se limitera à des signaux de flux : nombre et diversité des acheteurs et des vendeurs, volume
échangé, pente du prix d'exécution.
