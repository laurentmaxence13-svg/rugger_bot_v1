# cdgate 0.1 — porte de non-réfutation de C-D sur W1 (règle de R02, inscrite au registre avant toute exécution)

**Règle figée.** C'est celle du Dossier A v1.6 § 10, branche conjonction, sans changement :
- entrée au 1ᵉʳ événement entier d'âge ≥ 450 slots ;
- éligible si `causal_fee_rate` (gelé, sur les événements jusqu'à la décision) ≤ 2 500 ppm ;
- 0,1 SOL ; latence de 4 slots ;
- TP +7 % ou SL −5 % du coût, sinon horloge à 30 s (`statelab.exits.run_rule`, inchangé) ;
- loyer perdu ; une position migrée compte −1.

**Population.** La plage d'évaluation W1 entière (constantes de latelab 0.4).

**Pare-feu HW1.** Une entrée éligible à un âge ≥ 600 s est comptée, mais jamais rejouée (testé : aucun rejeu).

**Porte.** n ≥ 30 ET borne HAUTE de l'IC 95 % du net moyen ≥ 0 : C-D reste alors candidat. Sinon, l'emplacement
reste VIDE. Compteur : N + 1.

**Descriptif, hors porte.** Ces chiffres sont donnés au format du propriétaire :
- n, grappes, net moyen et médian, IC, extrêmes, gagnantes, part des 5 meilleurs ;
- décomposition, en part de la mise :
  - brut ;
  - frais de courbe : exacts à l'achat, et `fee_for` de la vente brute ;
  - transactions ;
  - loyer ;
- glissement à l'achat : 1 − jetons reçus / jetons du même achat sur l'état de décision ;
- net à 10 slots de latence ;
- cycles : pools tardifs, éligibles, clôturés, achats refusés, ≥ 600 s ;
- placebo gelé restreint au palier ≤ 2 500 ppm, même sortie ;
- référence MASTER W1 citée : ea152a32, −4,26 %.

**Exécution.** Seulement par R03, après le PASS de R02, dans un dossier NEUF ; sha à R02 avant toute lecture.
```
PYTHONPATH=<aff97638>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg 0.4>:<cdgate_pkg> RUGGER_NO_DOTENV=1 \
  python -B -m cdgate.gate --pools <export W1> --manifest-sha256 <ancré> --out <DOSSIER NEUF>
```

**Preuves.**
- 10 tests réussis.
- Défauts volontaires : 12 sur 12 détectés (`MUTATIONS_cdgate_v0_1.json`).
- Sans défaut, la suite passe dans l'environnement exact du runner.
