> **EXEMPLE FICTIF — AUCUNE DONNÉE DE W1.** Rendu du gabarit sur la lecture inventée des tests (w1x/tests/test_reading.py) : tous les chiffres ci-dessous sont faux par construction. Il ne sert qu'à relire le texte fixe et la mise en page.

# EXPLORATOIRE — NON OFFICIEL — pas le verdict W1 — pas une preuve de rentabilité future

**Synthèse de la lecture préliminaire de W1 (bras MASTER gelé, simulation hors ligne).** Document source : `LECTURE_PRELIMINAIRE.json`, sha256 `822404017c5758604f5b811f4a52650512d7018d9a93ceb14887ba474adb2c70`, ancré par RUGGER 02. Chaque chiffre est suivi de sa clé dans ce fichier ; aucun autre calcul que le changement d'unité.

Rappels. Vous avez choisi l'option A : le verdict officiel W1 sera calculé plus tard, quel que soit ce résultat. W1 n'est plus une donnée « non vue » pour toute idée nouvelle. Les cinq hypothèses gelées ne sont pas lues ici. Aucun ordre réel n'a été passé : tout est simulé.

## 1. Réponse courte

Sur la plage d'évaluation de W1, le MASTER a ouvert 15 (`master.Q1_positions.opened`) positions et en a clôturé 10 (`master.Q1_positions.closed`). Résultat net après tous les frais : +0,005000 SOL (`master.Q7_unit.net_sum_sol`) au total, soit +0,000500 SOL (`master.Q7_unit.net_mean_sol`) et +0,50 % (`master.Q2_result_lamports.net_return_mean`) du capital engagé par opération en moyenne. Intervalle de confiance à 95 % de ce rendement moyen : de -3,86 % (`master.Q6_interval_95_of_the_mean_net_return.low`) à +3,20 % (`master.Q6_interval_95_of_the_mean_net_return.high`). L'intervalle contient zéro : le signe du résultat n'est pas établi.

## 2. Positions

| | |
|---|---|
| Pools du MANIFEST (rejoués et exclus) | 22 (`master.Q1_positions.eligible_manifest_pools`) |
| dont exclus pour défaut de données | 2 (`master.Q1_positions.excluded_pools`) |
| Pools de la plage d'évaluation | 17 (`master.Q1_positions.evaluation_pools`) |
| Pools hors plage (échauffement), seulement comptés | 3 (`master.Q1_positions.pools_outside_the_evaluation_range`) |
| Sans entrée | 2 (`master.Q1_positions.no_entry`) |
| Positions ouvertes | 15 (`master.Q1_positions.opened`) |
| Cycles avec achat exécuté | 14 (`master.Q1_positions.cycles_with_entry`) |
| Positions clôturées | 10 (`master.Q1_positions.closed`) |
| Non clôturées : `counterfactual_divergence` | 1 (`master.Q1_positions.not_closed.counterfactual_divergence`) |
| Non clôturées : `migrated_unpriced` | 2 (`master.Q1_positions.not_closed.migrated_unpriced`) |
| Non clôturées : `open_at_end` | 1 (`master.Q1_positions.not_closed.open_at_end`) |
| Non clôturées : `open_at_window_end` | 1 (`master.Q1_positions.not_closed.open_at_window_end`) |

## 3. Résultat après frais et distribution (cycles clôturés)

| | |
|---|---|
| Net total | +0,005000 SOL (`master.Q2_result_lamports.net_sum`) |
| Net moyen par opération | +0,000500 SOL (`master.Q2_result_lamports.net_mean`) |
| Net médian | -0,002000 SOL (`master.Q2_result_lamports.net_median`) |
| Rendement net moyen (du capital engagé) | +0,50 % (`master.Q2_result_lamports.net_return_mean`) |
| Rendement net médian | -2,00 % (`master.Q2_result_lamports.net_return_median`) |
| Part des opérations gagnantes | 40,0 % (`master.Q2_result_lamports.win_rate`) |
| Somme des gains / somme des pertes | 1,21 (`master.Q2_result_lamports.profit_factor`) |
| Brut total (avant glissement et frais) | +0,042100 SOL (`master.Q2_result_lamports.gross_sum`) |
| Brut moyen | +0,004210 SOL (`master.Q2_result_lamports.gross_mean`) |
| 10 % des opérations font moins que | -0,008000 SOL (`master.Q3_distribution_lamports.p10`) |
| Médiane | -0,002000 SOL (`master.Q3_distribution_lamports.p50`) |
| 90 % des opérations font moins que | +0,005000 SOL (`master.Q3_distribution_lamports.p90`) |
| Meilleure opération | +0,020000 SOL (`master.Q3_distribution_lamports.maximum`) |
| Pire opération | -0,008000 SOL (`master.Q3_distribution_lamports.minimum`) |
| Part des 5 meilleures dans les gains | 100,0 % (`master.Q3_distribution_lamports.share_of_the_5_best`) |

## 4. Où part l'argent

| Poste (total des cycles clôturés) | |
|---|---|
| Brut : évolution du prix pendant la détention | +0,042100 SOL (`master.Q4_failure_factors.decomposition_lamports.market_move`) |
| − glissement de nos propres ordres | +0,000000 SOL (`master.Q4_failure_factors.decomposition_lamports.slippage`) |
| − frais de la courbe (achat et vente) | +0,035000 SOL (`master.Q4_failure_factors.decomposition_lamports.launchlab_fees`) |
| − frais de transaction | +0,002100 SOL (`master.Q4_failure_factors.decomposition_lamports.tx_costs`) |
| − tentatives échouées | +0,000000 SOL (`master.Q4_failure_factors.decomposition_lamports.failed_attempt_costs`) |
| = Net | +0,005000 SOL (`master.Q4_failure_factors.decomposition_lamports.net`) |
| Résidu de cette identité (rapporté tel quel, en lamports) | 0.0 (`master.Q4_failure_factors.decomposition_lamports.identity_residual`) |

Motifs de sortie des cycles clôturés :

- `autre` : 2 (`master.Q4_failure_factors.exit_reasons.autre`)
- `exit_horizon` : 1 (`master.Q4_failure_factors.exit_reasons.exit_horizon`)
- `exit_horizon_clock` : 1 (`master.Q4_failure_factors.exit_reasons.exit_horizon_clock`)
- `max_hold` : 1 (`master.Q4_failure_factors.exit_reasons.max_hold`)
- `stop_loss` : 3 (`master.Q4_failure_factors.exit_reasons.stop_loss`)
- `take_profit` : 1 (`master.Q4_failure_factors.exit_reasons.take_profit`)
- `trailing_stop` : 1 (`master.Q4_failure_factors.exit_reasons.trailing_stop`)

## 5. MASTER contre référence et contre hasard (totaux seulement)

Cette comparaison préfigure, sans les remplacer, les tests officiels.

| | MASTER | Référence | Hasard (placebo) |
|---|---|---|---|
| Cycles clôturés | 10 (`master.Q1_positions.closed`) | 2 (`others.reference.closed_cycles`) | 1 (`others.placebo_random.closed_cycles`) |
| Net moyen par opération | +0,000500 SOL (`master.Q2_result_lamports.net_mean`) | -0,003000 SOL (`others.reference.mean_net_pnl_lamports`) | +0,006000 SOL (`others.placebo_random.mean_net_pnl_lamports`) |
| Rendement net moyen | +0,50 % (`master.Q2_result_lamports.net_return_mean`) | -3,00 % (`others.reference.mean_net_return`) | +12,00 % (`others.placebo_random.mean_net_return`) |
| Brut (total) | +0,042100 SOL (`master.Q4_failure_factors.decomposition_lamports.market_move`) | +0,001420 SOL (`others.reference.decomposition_lamports.market_move`) | +0,009710 SOL (`others.placebo_random.decomposition_lamports.market_move`) |
| Glissement (total) | +0,000000 SOL (`master.Q4_failure_factors.decomposition_lamports.slippage`) | +0,000000 SOL (`others.reference.decomposition_lamports.slippage`) | +0,000000 SOL (`others.placebo_random.decomposition_lamports.slippage`) |
| Frais de la courbe (total) | +0,035000 SOL (`master.Q4_failure_factors.decomposition_lamports.launchlab_fees`) | +0,007000 SOL (`others.reference.decomposition_lamports.launchlab_fees`) | +0,003500 SOL (`others.placebo_random.decomposition_lamports.launchlab_fees`) |
| Frais de transaction (total) | +0,002100 SOL (`master.Q4_failure_factors.decomposition_lamports.tx_costs`) | +0,000420 SOL (`others.reference.decomposition_lamports.tx_costs`) | +0,000210 SOL (`others.placebo_random.decomposition_lamports.tx_costs`) |
| Net (total) | +0,005000 SOL (`master.Q4_failure_factors.decomposition_lamports.net`) | -0,006000 SOL (`others.reference.decomposition_lamports.net`) | +0,006000 SOL (`others.placebo_random.decomposition_lamports.net`) |

## 6. Fiabilité

- Intervalle de confiance à 95 % du rendement net moyen : de -3,86 % (`master.Q6_interval_95_of_the_mean_net_return.low`) à +3,20 % (`master.Q6_interval_95_of_the_mean_net_return.high`) ; rééchantillonnage par créateur, 2000 (`master.Q6_interval_95_of_the_mean_net_return.draws`) tirages, 6 (`master.Q6_interval_95_of_the_mean_net_return.clusters`) créateurs ou pools distincts. L'intervalle contient zéro : le signe du résultat n'est pas établi.
- Concentration : 6 (`master.Q5_creators.distinct_clusters`) créateurs ou pools distincts parmi les cycles clôturés ; les cinq plus présents en détiennent 90,0 % (`master.Q5_creators.share_of_the_5_largest`).
- Une seule période : plage d'évaluation de 1 000 slots (`population.evaluation_max` − `population.evaluation_min`), de l'ordre de 4 jours (durée exacte non mesurée dans cette lecture).
- Coûts, latence et mise sont ceux du protocole gelé ; nos ordres simulés n'ont pas existé : leur effet sur les autres acteurs est inconnu.
- Les outils en flux utilisés pour cette lecture produisent les mêmes fichiers que la chaîne gelée sur les jeux de référence seulement (pilote, jeux de prix ouverts, jeux synthétiques), pas sur une fenêtre réelle de la taille de W1.
- Ce n'est pas la décision W1 : ni le test officiel contre la référence et le hasard, ni la correction pour le nombre d'essais (159 essais comptés à ce jour, chiffre donné par RUGGER 02) ne sont calculés ici.
- Lecture non aveugle : elle a été faite avant le verdict officiel.

## 7. Pistes d'amélioration

Ce sont des HYPOTHÈSES, à tester sur des données futures (W2), jamais sur W1. Elles viennent de ce que les données de développement avaient déjà établi ; aucune ventilation de W1 n'a été faite pour en chercher d'autres.

1. Réduire le coût d'un aller-retour : récupérer le loyer du compte de token en fermant le compte après la vente.
2. Élargir l'univers exécutable aux tokens Token-2022 d'une liste stricte.
3. Se limiter aux pools à frais de courbe faibles.
4. Mesurer la migration et le marché d'après-migration, sur lesquels il n'existe aucune donnée : collecte soumise à votre accord.
5. Réévaluer la décision d'entrée elle-même : sur les données de développement, la perte venait de l'achat, pas de la règle de vente.

## 8. Suite

- Verdict officiel W1 : il reste à calculer (option A). La seule voie prête est Google Cloud, dans la limite de budget que vous aviez fixée, avec un paquet audité ; elle attend votre décision de dépense.
- Les cinq hypothèses gelées seront lues une seule fois, après ce verdict officiel.
- Aucun ordre réel, aucune activation, aucune dépense sans votre accord.
