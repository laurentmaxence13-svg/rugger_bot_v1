# Préenregistrement — hypothèse CPMM R-CP1 sur pools établis (v0.1), AVANT toute donnée du pilote

RUGGER 01, 23/11/2026. Tâche CPMM-2 (directive du propriétaire du 23/11, relayée par R04).
- Bases : note du pilote v0.2 (b4c6562c, § 2.2 à 2.5), protocole CPMM v1.2 (a3a285a1), cpmmcost 0.2 (a611621,
  PASS R02).
- La règle est FIGÉE EN CODE (`cpmmprereg/rule.py`), testée sur des pools synthétiques seulement.
- Aucune donnée n'existe ni n'est lue.
- La fiche est ancrée par R02 au gel ; son sha sert de graine au bootstrap de G-1 et au témoin.

## 1. Hypothèse

Sur des pools Raydium CPMM ÉTABLIS (univers U-1 à U-4 de la note), un achat de 0,1 SOL après une chute de 3 % en
10 minutes, dans un pool actif, a un net moyen positif après TOUS les coûts du modèle cpmmcost 0.2.

## 2. Univers (repris de la note v0.2, sans changement)

- U-1 :
  - AmmConfig lu et haché, trade_fee_rate = 2 500 ppm ;
  - jeton de cotation WSOL ;
  - pool créé au moins 7 jours avant la fenêtre ;
  - pool qui n'est PAS issu d'une migration LaunchLab ;
  - pools de P0 et de W1 exclus ; le holdout jamais lu.
- U-2 : la liste des candidats est hachée à T0. La source de cette liste est une décision du propriétaire.
- U-3 : réserve WSOL d'au moins 100 SOL à T0 ; tirage déterministe de 24 pools.
- U-4 : exclusions par `cpmmcost.pool_gate` (C-1 à C-3 par pool, transferts Token-2022, réserves rompues), comptées.

## 3. Règle de décision R-CP1 (code `decisions`)

Au swap réel i d'un pool, au temps t_i (temps de bloc), on entre si les trois conditions tiennent :
- (i) spot_i / spot_ref − 1 ≤ −3 %, où ref est le DERNIER swap j tel que t_j ≤ t_i − 600 s ; s'il n'y en a aucun,
  il n'y a pas de décision ;
- (ii) au moins 20 swaps réels ont lieu dans ]t_i − 600 ; t_i] ;
- (iii) aucune position n'a été ouverte sur ce pool dans les 3 600 s précédentes.

Les spots sont calculés sur les réserves journalisées après chaque swap, parts de l'AmmConfig appliquées. La règle
est causale (testé).

**Ordre et sortie** :
- achat de 0,1 SOL, atterrissage +4 slots (H-1, cpmmcost) ;
- TP de +2 % ou SL de −2 % de la mise, sur la valeur de vente EXACTE, vérifiés à chaque swap réel après
  l'atterrissage ; la vente atterrit 4 slots après le déclencheur ;
- sinon, horloge à 30 minutes, plus la latence d'horloge gelée ;
- puis compte fermé (C-a).

## 4. Coûts et effet minimal net

- **Coûts.** Tous ceux de cpmmcost 0.2 en primaire :
  - frais lus dans l'AmmConfig ;
  - impact exact ;
  - H-1 ;
  - 0 échec, avec renvoi +4 slots en sensibilité ;
  - compte fermé séparément ;
  - fermeture WSOL séparée.
  - La barre de travail est d'environ 1,12 % à 100 SOL de réserve. Ce n'est qu'un dimensionnement : le calcul est
    toujours exact, position par position.
- **Effet minimal net d'intérêt : δ = +0,5 % de la mise, APRÈS ces coûts.**
- **σ déclaré = 2,5 %.** C'est une HYPOTHÈSE pour une fourchette de ±2 % avec glissement, PAS une estimation : aucune
  donnée n'a été vue.

## 5. Puissance et n requis (code `n_required`)

| Étape | α unilatéral | Puissance | n requis |
|---|---|---|---|
| Pilote (§ 2.5 de la note : G-0, puis G-1) | 0,05 | 0,80 | **155** entrées (cible de puissance) ; plancher G-1 de 30 entrées et 20 pools inchangé |
| Confirmation (fenêtre NOUVELLE, critères c1 à c5 du Dossier B) | 0,05/3 | 0,80 | **221** entrées |

**Décision du pilote, inchangée (note § 2.5)** :
- G-0 : C-1 à C-3 sur les swaps du pilote ; sinon STOP.
- Puis G-1 :
  - n < 30, ou moins de 20 pools : INCONCLUSIF ;
  - borne haute unilatérale à 95 % du net moyen < 0 : NO-GO ;
  - sinon GO_PILOTE.
- GO_PILOTE autorise seulement à PROPOSER la confirmation. Il ne veut jamais dire « rentable ».

## 6. Témoin et scission

- **Témoin apparié** (code `placebo`) :
  - mêmes pools ;
  - autant d'entrées par pool que R-CP1 ;
  - tirées uniformément parmi les swaps qui ont une référence à 600 s, avec la même contrainte (iii) ;
  - graine = sha256(sha de la fiche de gel + pool)[:8] ;
  - mêmes sorties et mêmes coûts.
  - Il est publié au pilote. En confirmation, c2 l'exige.
- **Scission** (code `halves`) : les deux moitiés en temps de la fenêtre, selon le temps de décision. Elles sont
  publiées au pilote ; en confirmation, c3 exige les deux moitiés positives.

## 7. Coût en essais (code `trials`)

R-CP1 et son témoin forment UN essai, compté à l'évaluation seulement : 168 → **169**, plafond 170. **Il ne reste
qu'un essai** ; toute variante (seuil, fenêtre, TP ou SL) ou tout second univers le consomme, après un nouveau
préenregistrement.

## 8. Règles d'arrêt fixées maintenant (codes `eligibility_stop`, `power_stop`)

1. **Après la liste U-2, à T0** :
   - moins de 20 pools éligibles : **STOP, INCONCLUSIF déclaré d'avance, aucun essai consommé** ;
   - de 20 à 23 pools : tous sont pris, sans remplacement ;
   - 24 ou plus : tirage de 24.
2. **Étape 0** (vecteurs publics, ≤ 100 crédits) : si l'audit du décodeur (C-1 à C-3) échoue, STOP (G-0).
3. **Avant l'étape 1**, d'après le nombre attendu d'entrées. La méthode d'estimation est fixée par R02 avant
   l'étape 1, sans donnée de la fenêtre :
   - moins de 30 : sous-puissance déclarée d'avance, et **c'est le propriétaire qui décide** ;
   - de 30 à 154 : le pilote est publié comme « sous la cible de puissance » ;
   - 155 ou plus : pilote à pleine puissance.
4. **Pendant l'étape 1** : arrêt dur à 98 % du plafond de crédits (note § 2.4).

## 9. Ce qui reste au propriétaire (BLOQUÉ PAR LE PROPRIÉTAIRE)

- La source de la liste U-2 : hôte Raydium, ou crédits Helius.
- Le GO de l'étape 0 (≤ 100 crédits), puis celui de l'étape 1 (≤ 50 000 crédits).
