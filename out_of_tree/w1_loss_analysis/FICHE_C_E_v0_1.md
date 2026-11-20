# Fiche C-E — « entrée précoce à palier bas, compte de jetons fermé » — v0.1, à geler (RUGGER 01, 21/11/2026)

**Statut.** Brouillon soumis à R02. Il est figé AVANT toute nouvelle lecture.
- **Choisi après regard.** C-E vient du placebo à palier bas de la porte C-D. Sur W1, ce placebo fait +0,17 % loyer
  récupéré (n = 35 ; cdgate 0.2, 2b173f10).
- **Jugé sur W2 SEULEMENT.** C-E ne peut être jugé ni sur W1, déjà lu, ni sur P0 visible, qui n'a aucun palier bas.
- **Emplacement.** Il vise un emplacement W2 resté VIDE ; K = 3 est inchangé.
- **Compteur N.** R02 dit si le choix de C-E compte dans N.

## Règle causale complète

| Élément | Règle |
|---|---|
| Population | Pools LaunchLab SOL de W2, rejouables (`hrr.usable_timeline`) |
| Décision | L'événement du placebo statelab gelé (`statelab.points`, label `placebo:0`) : premier événement entier d'âge ≥ `placebo_target_age(pool)`. Cet âge est pseudo-aléatoire, compris entre 0 et 120 s : sha256 de `v1:<pool>`, 4 premiers octets, modulo 121. Il ne dépend que de l'adresse du pool, ce qui en fait la reprise exacte du comparateur observé |
| Sélection | Palier du `causal_fee_rate` gelé (événements jusqu'à la décision), arrondi à 500 ppm comme feeage `tier_of` : ≤ 2 500 ppm |
| Achat | 0,1 SOL, atterrissage après 4 slots, frais de courbe causaux, 5 000 + 100 000 lamports par transaction ; une position par pool |
| Vente | TP +7 % ou SL −5 % du coût, sinon horloge à 30 s (`statelab.exits.run_rule`, règle de cdgate) |
| Compte de jetons | FERMÉ après la vente totale, par une transaction séparée (conception live : branche `claude/r01-live-close-base-ata`, 9674826, jamais armée). Le modèle hors ligne est `closedacct` 0.1 : loyer récupéré, frais de nettoyage de 105 000 lamports (prudent) ; après 3 échecs, le compte reste ouvert et le loyer est perdu |
| Migrée | −1 (pas de vente, donc pas de fermeture) |

**Pare-feu HW1.** L'âge de décision est ≤ 120 s, donc sans recouvrement avec HW1-4 (600 s). Aucun signal de réserve,
de progression ou de signataire n'est lu. La sélection ne lit que le palier de frais.

## Rentabilité attendue, au format du propriétaire

- **Observation W1, biaisée vers le haut (choisie après regard).** Placebo à palier bas : net loyer perdu −1,82 %
  [−3,29 ; −0,33] ; loyer récupéré, sans frais de nettoyage, **+0,17 %** ; brut +0,89 % ; frais de courbe 0,50 % ;
  tx 0,21 % ; gagnantes 20 % ; n = 35.
- **Avec les frais de nettoyage** (105 000 lamports, soit 0,105 %), on obtient **≈ +0,07 %**, c'est-à-dire à peu près
  l'équilibre.
- **Espérance honnête : ≈ 0.** Un résultat positif en W2 serait une surprise, pas une attente.

## Risque, exécution, puissance

- **Risques.**
  - Le palier bas peut disparaître : il est absent de P0, et une règle d'arrêt « palier disparu » est à reprendre du
    Dossier B.
  - Une entrée précoce reste exposée à la course de latence : −0,91 % à 10 slots sur P0, pour les entrées précoces.
  - Un tiers peut faire échouer la fermeture par un dépôt de poussière, au prix d'un frais par tentative.
  - Les gains sont concentrés : la part des 5 meilleurs atteint 98 % dans l'observation.
- **Exécution réelle.**
  - Le palier est lisible à la décision.
  - La fermeture est écrite et testée hors ligne (branche live), mais elle n'est NI armée NI prouvée sur la chaîne.
  - L'entrée à âge pseudo-aléatoire est exécutable : c'est un calcul local.
- **Taux d'entrée.** ≈ 35 positions sur la plage W1 (≈ 4 j), soit **≈ 9 par jour**, à faire confirmer par R03 sur des
  comptes de population.
- **Puissance.**
  - L'écart-type par cycle est d'environ 4,4 %, d'après l'IC du placebo (n = 35).
  - Pour détecter un net de +0,5 % (puissance de 80 %), il faut ≈ 600 cycles, soit ≈ 70 jours.
  - Pour +1 %, il faut ≈ 150 cycles, soit ≈ 17 jours.
  - **C-E est sous-puissant à moins de +1 % de vrai net** : c'est à déclarer d'avance (Dossier B).

## Validation

W2 uniquement, avec les critères GO du Dossier B, sans assouplissement :
- le mode « compte fermé » n'est admis que si P-5 (`closedacct`) a passé l'audit de R02 ;
- une sensibilité « compte ouvert » (loyer perdu) est publiée à côté ;
- aucune variante de palier, d'âge ou de sortie n'est permise.
