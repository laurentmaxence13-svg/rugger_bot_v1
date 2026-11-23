# Fiche de gel G2-3 « élargissement de la demande » — génération 2 (v0.1, SANS T0)

RUGGER 01, 23/11/2026. Tâche T-R01-1.
- **Statut : prête à ancrer, NON ancrée.** Elle se gèle le jour où le propriétaire signe le texte D (+3 essais, choix
  de l'α de confirmation, crédits de la fenêtre), sans aucun développement de plus. On n'y remplit alors que les
  champs `<…>`.
- **Famille : INDÉPENDANTE du déclencheur de prix.**

**Mécanisme.** Une hausse nette du nombre d'ACHETEURS DISTINCTS signale une demande large et nouvelle, distincte
de l'offre concentrée des détenteurs (M4). La barrière CPMM est de ≈ 0,8 à 1,1 % (M1). M7 (W1) n'est qu'une
motivation descriptive.

**Entrée (`cpmmgen2.decisions_g23`).** Au swap i, au temps t :
- le nombre d'acheteurs distincts (payeur de frais des transactions d'achat, `fee_payer`) sur ]t − 600 ; t] est
  ≥ **2 × b₃(pool)** ;
- aucune position G2-3 sur le pool depuis 3 600 s ;
- b₃(pool) = médiane, sur les 1 008 fenêtres de 600 s de [T0 − 7 j ; T0), des acheteurs distincts du pool
  (`baseline_b3`), écrite par pool dans la fiche avant la fenêtre : `<table b₃ par pool>`.
- **Un pool où b₃ = 0 est EXCLU** (compté), jamais traité.
- Le multiplicateur 2 est déclaré, sans principe externe (note 1 au critère « degrés de liberté »).

**NON ÉVALUABLE** si b₃ = 0 pour plus de la moitié des pools.

**Témoin.** `cpmmprereg.placebo`, graine de la fiche.

**Données.** Le payeur est lu dans la transaction brute collectée (`accountKeys[0]`), sans crédit de plus. Le code
d'extraction est `cpmmgen2.fee_payer`, à auditer par R02.

## Champs communs (identiques pour les 3 fiches de la génération 2)

| Rubrique (b4edc143 § 3) | Valeur gelée |
|---|---|
| Statut | PILOTE (mot maximal GO_PILOTE), puis CONFIRMATION sur une fenêtre NOUVELLE |
| Fenêtre | DISJOINTE de la génération 1 (R-CP1, B1) : **[T0 ; T0 + D j)**, avec T0 = `<T0, ancré par R02>` et D = `<D, chiffré par R03>` |
| Univers | Pools Raydium CPMM établis U-1 à U-4 (note pilote v0.2, b4c6562c) ; liste U-2 hachée à T0 : `<sha256 de la liste>` ; tirage de 24 pools ; exclusions `cpmmcost.pool_gate` comptées |
| Ordre | Achat de 0,1 SOL, atterrissage +4 slots, H-1 au pire cas (cpmmcost 0.3) |
| Garde (R-0.3) | 20 000 ppm à l'achat ; refus facturé, sans entrée ni relance ; sensibilité 50 000 ; vente sans garde |
| Sortie | TP +2 % / SL −2 % de la mise sur la valeur de vente exacte, vérifiés à chaque swap après l'atterrissage, avec la vente 4 slots après le déclencheur ; sinon horloge à 30 min + latence gelée (`cpmmprereg.exit_point`) |
| Coûts (R-0.3) | `cpmmcost.position` : frais lus dans l'AmmConfig, impact exact, tx 105 000 lamports, compte fermé, WSOL fermé séparément ; échecs 0 en primaire, 1 par tx en sensibilité |
| Latence | 4 slots ; sensibilité 10 slots |
| Témoin | Apparié par pool ; graine = int(sha256(sha de CETTE fiche de gel + pool)[:8], 16) |
| Comptage avant T0 | Déclencheurs sur [T0 − 7 j ; T0) seulement (`cpmmgen2.trigger_count`) ; données ≥ T0 REFUSÉES ; aucun résultat calculé ; puis `power_stop` |
| n | Pilote : 155 (α 0,05, puissance 0,80, σ 2,5 %, δ +0,5 %). Confirmation : n_c = 262 (Holm, α₂ 0,025, 1er pas 0,025/3) ou 221 (0,05/3), selon `<choix du propriétaire dans le texte D>` ; σ_c = max(σ du pilote, 2,5 %) |
| GO / STOP du pilote | G-0 : décodeur C-1 à C-3, sinon STOP. G-1 (`cpmmcost.pilot_verdict`) : moins de 30 entrées ou moins de 20 pools → INCONCLUSIF ; borne haute unilatérale à 95 % < 0 → NO-GO ; sinon GO_PILOTE |
| Confirmation | Fenêtre NOUVELLE ; c1 à c5 sur grappes par pool ; famille de la génération corrigée par Holm (`cpmmgen2.holm`) ; p unilatéral par bootstrap groupé (`cpmmgen2.bootstrap_p`), 10 000 tirages, graine de la fiche de gel |
| Compteur d'essais | 170 → 173 sous le texte D du propriétaire (+3) ; 1 essai par fiche, compté à l'évaluation (`cpmmgen2.trials`) |
| Règle d'élimination | Si R-CP1 ET B1 sont NO-GO, G2-1 et G2-2 sont RETIRÉES et G2-3 reste seule (K = 1, α₂ entier) (`cpmmgen2.withdrawn_if_family_negative`) |
| Publication | Part des entrées COMMUNES entre G2-1, G2-2 et G2-3, et avec les déclencheurs de type R-CP1 de la fenêtre (descriptif) ; refus de garde ; attentes vides (G2-2) ; pools exclus (G2-3) |
| Code gelé | `cpmmgen2/rule.py` `<sha au gel>` ; cpmmprereg 0.2 `rule.py` 9f46f052 (importé, inchangé) ; cpmmcost 0.3 |
| Vocabulaire | R-0.1 : NÉGATIF / INCONCLUSIF / GO_PILOTE / CONFIRMÉ, jamais d'autre mot |
