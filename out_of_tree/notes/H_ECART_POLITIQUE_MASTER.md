# H — Politique MASTER visée : ce qui est implémenté et ce qui reste à faire (sans toucher au gel W1)

**Référence** : plan directeur MASTER V2 (livrable C, §2.2 modules M0 à M10, §5 challengers). Chaque ligne a été vérifiée dans le code gelé (arbre aff97638, empreinte 682447fd), par lecture ou recherche, le 2026-11-09.

**Règle** : rien de ce qui « reste à faire » n'entre dans W1. W1 évalue la politique gelée telle quelle. Les ajouts sont prévus pour un essai ultérieur, avec un nouveau pré-enregistrement.

## 1. Ce que W1 exécute (gelé)

| Bras W1 | Politique | Code |
|---|---|---|
| **M1** | MASTER L1 : orchestrateur de décision du MASTER, scorer avec plan TP/SL à l'entrée, sortie à l'horloge, latence de 4 slots, frais causaux, historique créateur causal, SOL/USD collecté | `historical_research_replay.py`, `w1_run.L1_EXIT`, `CreatorHistory` |
| **P1b** | Placebo d'entrée aléatoire, même sortie que M1 | `PLACEBO_ARM` |
| P1, P2 | Placebo aléatoire ; abstention | `policies.RandomEntry`, `NoTrade` |
| S1, S2 | Snipe immédiat ; délai fixe de 5 s (référence) | `ImmediateSnipe`, `FixedDelay` |
| S3 | CH1 VETO-INITIÉS-5S | `challengers.InsiderVeto5s` |
| Sensibilités | Latence 10 slots (hors N) ; frais d'échec 105 000 lamports ; horizon par événement | `w1_eval.DESCRIPTIVE` |

**Évaluation (M8)** : pré-enregistrement haché et registre chaîné, segments chronologiques avec embargo (4 513 slots), bootstrap par créateur, tests H1 à H4 avec correction de Holm, PSR et DSR sur tous les essais, règle WAIT si SOL/USD manque. Fichier : `w1_eval.py`.

**Résultat net vérifiable (hors gel, w1aux ancré)** : le ledger recalcule chaque cycle (frais, atterrissage, sortie) et décompose le P&L ainsi : P&L = mouvement de marché − slippage − frais LaunchLab − coûts de transaction − échecs. `dayj` enchaîne toute la chaîne avec ancrage par RUGGER 02.

## 2. Écart par module

| Module | Implémenté (gelé) | Reste à développer (hors W1) |
|---|---|---|
| M0 Contrat de données | Créateur signé vérifié, transaction entière, fenêtre de collecte, exclusions par motif | Continuité des réserves (B-D1), part des pools où le payeur n'est pas le créateur (E0b) |
| M1 Features causales | `native_features`, entrées « as-of » causales, historique créateur | Features RS2 (vente d'initiés), RS5 (financement et bundles) : **absentes** |
| M2 Vetos | CH1 (S3) ; CH2 `CreatorBag30s` codé mais pas dans les bras W1 | CH7 CASCADE, CH8 PRÉ-MIGRATION : **absents** |
| M3 Timing | `Policy`, `PolicyArm`, âge d'entrée borné | — |
| M4 Seuil de coût g\* | — | CH5, CH6 : **absents** |
| M5 Exécution | Latence en slots, impact propre, frais causaux, coûts de transaction, sortie à l'horloge, stress des échecs (descriptif) | **Slippage maximal (`min_out`) absent du rejeu** : un ordre réel rejeté serait compté comme rempli |
| M6 Sorties | TP, SL, trailing, max_hold, sortie à l'horloge (`ExitRule`) | Sortie sur vente d'initié (RS2) : **absente** |
| M7 Taille et capital | 0,1 SOL fixe, une entrée et une sortie par pool | Kelly contraint, exposition simultanée, limites de drawdown (couche portefeuille) : **absents** |
| M8 Évaluation | Holm, PSR, DSR, bootstrap par créateur, embargo, segments | MatchedAgeRandom, CSCV/PBO, SPA/StepM : **absents** |
| M9 Régime et arrêt total | — | Tout, à calibrer sur W1 |
| M10 Champion et challengers | Placebos et tournoi par bras | Mode ombre (soumis à votre autorisation) |

## 3. Ce que cela implique

- W1 peut démontrer, ou réfuter, l'avantage net du MASTER L1 gelé contre l'abstention, le placebo et le snipe, après tous les frais modélisés.
- W1 ne peut **pas** démontrer la politique ultime complète : M4, M7, M9, la sortie sur initiés et le slippage maximal manquent.
- Résultat important : en l'absence de `min_out`, le rejeu remplit des ordres qu'un vrai routeur aurait refusés. Le biais est **favorable** au MASTER sur les mouvements violents. Il doit être mentionné dans la lecture des résultats W1.
- Priorité suggérée après W1, selon les résultats et chaque fois avec nouveau pré-enregistrement et audit : (1) `min_out` / slippage maximal dans le rejeu ; (2) couche portefeuille M7 ; (3) M9 calibré sur W1 ; (4) RS2 avec sortie sur initiés.
