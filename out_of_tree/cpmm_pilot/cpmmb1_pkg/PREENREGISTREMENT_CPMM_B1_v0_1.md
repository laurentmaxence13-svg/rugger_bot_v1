# Préenregistrement — hypothèse CPMM B1 (miroir momentum de R-CP1) sur pools établis (v0.1), AVANT toute donnée du pilote

RUGGER 01, 23/11/2026.
- **Mandat.**
  - Catalogue R-1 v0.2, hypothèse B1 ; audit R02 1070aae6 (décisions 1 à 3).
  - Décision de coordination R04 du 23/11 : B1 est la 2e hypothèse de la génération du pilote CPMM.
- **Fiche SÉPARÉE.** R-CP1 (fiche v0.2 66ab4ab4, code cpmmprereg 0.2 059a3b5) reste STRICTEMENT inchangée : pas de
  partage d'α, pas d'amendement.
- **Règle figée en code** : `cpmmb1/rule.py`. Elle importe cpmmprereg 0.2 sans le modifier ; le sha de `rule.py`
  est vérifié par un test. Elle est testée sur des pools synthétiques seulement. Aucune donnée n'existe ni n'est lue.
- **Ancrage.** La fiche doit être ancrée par R02 AVANT T0. Sinon, B1 attend une fenêtre suivante.

## 1. Hypothèse

Sur les mêmes pools Raydium CPMM ÉTABLIS que R-CP1 (univers U-1 à U-4, liste U-2 hachée à T0), un achat de 0,1 SOL
après une HAUSSE de 3 % ou plus en 10 minutes, dans un pool actif, a un net moyen positif après TOUS les coûts de
cpmmcost 0.3.

**Mécanisme.** L'attention et la diffusion lente de l'information sur des jetons à flux de détail entretiennent le
mouvement.

**Pourquoi ce choix sans degré de liberté.** B1 est le miroir EXACT de R-CP1 : mêmes paramètres, signe opposé.
Aucun seuil n'est choisi. Si A1 et B1 sont toutes deux NÉGATIVES, la famille « mouvement de prix sur 10 minutes »
est close sur CPMM.

## 2. Règle de décision B1 (code `decisions`)

Au swap réel i, au temps de bloc t_i, on entre si les trois conditions tiennent :
- (i) spot_i / spot_ref − 1 ≥ **+3 %**, où ref est le DERNIER swap j tel que t_j ≤ t_i − 600 s ; s'il n'y en a
  aucun, il n'y a pas de décision ;
- (ii) au moins 20 swaps réels dans ]t_i − 600 ; t_i] ;
- (iii) aucune position B1 ouverte sur ce pool dans les 3 600 s précédentes.

La règle est causale (testé). La frontière de +3 % est incluse (testé à 103/100 contre 102,99/100).

**Ordre, sortie, coûts et témoin** : ceux de R-CP1, importés sans changement.
- Achat de 0,1 SOL, atterrissage +4 slots, H-1.
- Garde de l'achat à 20 000 ppm (sensibilité 50 000).
- TP +2 % / SL −2 % sur la valeur de vente exacte, sinon horloge à 30 min.
- Compte fermé.
- Témoin apparié par pool. **Sa graine est celle de la fiche B1** : sha256(sha de la fiche de gel B1 + pool)[:8].

## 3. Puissance, α et verdicts (α PROPRE à B1)

| Étape | α unilatéral | Puissance | n requis | Mot maximal |
|---|---|---|---|---|
| Pilote, G-0 puis G-1 | 0,05 | 0,80 | **155** (plancher de G-1 : 30 entrées et 20 pools) | GO_PILOTE |
| Confirmation (fenêtre NOUVELLE) | 0,05/3 | 0,80 | n_c, avec σ_c = max(σ du pilote, 2,5 %) ; 221 si σ_c = 2,5 % | CONFIRMÉ, NON CONFIRMÉ ou INCONCLUSIF (c1 à c5 et A1) |

La publication l'écrit en clair : **B1 a son propre α**, distinct de celui de R-CP1. La confirmation à 0,05/3 sur
une fenêtre nouvelle absorbe jusqu'à 3 hypothèses (R02 1070aae6, décision 1).

## 4. Comptage des déclencheurs et règle d'arrêt (PROPRES à B1)

- **Code `trigger_count`.** On compte les seuls déclencheurs B1 sur [T0 − 7 j ; T0). Toute donnée à T0 ou après est
  REFUSÉE ; aucun résultat n'est calculé. Testé : le comptage de R-CP1 ne voit pas une hausse, celui de B1 la voit.
- **Attendu.** ⌊ déclencheurs × D / 7 ⌋. C'est une estimation de planification seulement, avec la mention
  « optimiste : refus de garde inconnus ».
- **Arrêt de puissance** (`power_stop`) :
  - moins de 30 : sous-puissance déclarée, décision du propriétaire ;
  - de 30 à 154 : publié « sous la cible de puissance » ;
  - 155 ou plus : pleine puissance.
- **Indépendance.** Les crédits du comptage sont imputés au plafond de l'étape 1, qui est partagée avec R-CP1. La
  collecte est la même, sans aucune donnée de plus.

## 5. Coût en essais

B1 et son témoin forment UN essai : **le 170e et dernier** sous le plafond actuel (169 → 170).
- Il n'est consommé qu'au **lancement du pilote**, qui reste soumis au GO du propriétaire (U-2, étapes 0 et 1).
- Le propriétaire peut encore refuser B1 avant T0.
- Au-delà de 170, aucune hypothèse n'est possible sans une autorisation chiffrée et une règle de correction ancrée.

## 6. Ce qui reste au propriétaire

C'est la même chose que pour R-CP1 :
- la source U-2 ;
- le GO de l'étape 0 ;
- puis le GO de l'étape 1.

Il peut aussi refuser B1 avant T0.
