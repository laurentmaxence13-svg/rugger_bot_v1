# Fiche C-E — « entrée précoce à palier bas, compte de jetons fermé » — v0.2, à geler (RUGGER 01, 21/11/2026 ; R02 85d2e959)

**Statut.** Brouillon soumis à R02. Il est figé AVANT toute nouvelle lecture.
- **Choisi après regard.** C-E vient du placebo à palier bas de la porte C-D. Sur W1, ce placebo fait +0,17 % loyer
  récupéré (n = 35 ; cdgate 0.2, 2b173f10).
- **Jugé sur W2 SEULEMENT.** C-E ne peut être jugé ni sur W1, déjà lu, ni sur P0 visible, qui n'a aucun palier bas.
- **Emplacement.** Il vise un emplacement W2 resté VIDE ; K = 3 est inchangé.
- **Compteur N.** R02 déclare C-E recevable dans un emplacement vide (85d2e959). N passe à **168** dès l'écriture.
- **Interdit.** Aucune évaluation de C-E, ni d'une variante, sur W1.

## Règle causale complète

| Élément | Règle |
|---|---|
| Population | Pools LaunchLab SOL de W2, rejouables (`hrr.usable_timeline`) |
| Décision | L'événement du placebo statelab gelé (`statelab.points`, label `placebo:0`) : premier événement entier d'âge ≥ `placebo_target_age(pool)`. Cet âge est pseudo-aléatoire, compris entre 0 et 120 s : sha256 de `v1:<pool>`, 4 premiers octets, modulo 121. Il ne dépend que de l'adresse du pool, ce qui en fait la reprise exacte du comparateur observé |
| Sélection | Palier du `causal_fee_rate` gelé (événements jusqu'à la décision), arrondi à 500 ppm comme feeage `tier_of` : ≤ 2 500 ppm |
| Achat | 0,1 SOL, atterrissage après 4 slots, frais de courbe causaux, 5 000 + 100 000 lamports par transaction ; une position par pool |
| Vente | TP +7 % ou SL −5 % du coût, sinon horloge à 30 s (`statelab.exits.run_rule`, règle de cdgate) |
| Compte de jetons | FERMÉ après la vente totale **seulement si P-5 (`closedacct`) est livré et audité par R02 AVANT le gel ; sinon, loyer PERDU**. La fermeture se fait par une transaction séparée (conception live : branche `claude/r01-live-close-base-ata`, 9674826, jamais armée). Le modèle hors ligne est `closedacct` 0.1 : loyer récupéré, frais de nettoyage de 105 000 lamports (prudent) ; après 3 échecs, le compte reste ouvert et le loyer est perdu |
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
- **Déclaré d'avance (R02 85d2e959).**
  - Effet observé sur W1 (biaisé) : +0,17 %.
  - Effet minimal δ gelé du Dossier B : **+2 %**.
  - **Résultat attendu en W2 : NO-GO ou INCONCLUSIF.**
  - Durée W2 ≈ **48 à 64 jours**. C'est l'estimation de R02, sur ≈ 35 points en 4,01 jours.
- **Puissance (Dossier B § 6.1, R02).**
  - σ = max(13,7 %, σ du bras) ; δ gelé = +2 % ; donc **n_min = 414** et D ≈ 48 j (c = 1) à 64 j (c = 0,75).
  - Aucune estimation de σ tirée des 35 positions observées n'est utilisée : elles sont choisies après regard et à
    queue lourde.
- **Recommandation (R01 et R02).** C-E est recevable, mais NON recommandé. Son espérance est ≈ 0, et il allongerait
  W2 à 48–64 jours.

## Validation

W2 uniquement, avec les critères GO du Dossier B, sans assouplissement :
- le mode « compte fermé » n'est admis que si P-5 (`closedacct`) a passé l'audit de R02 ;
- une sensibilité « compte ouvert » (loyer perdu) est publiée à côté ;
- aucune variante de palier, d'âge ou de sortie n'est permise.
