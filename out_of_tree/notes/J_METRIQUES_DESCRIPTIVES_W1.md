# W1 — définitions des métriques descriptives (fixées AVANT les données)

**Statut.** Ces métriques sont DESCRIPTIVES. Elles ne modifient jamais la décision économique, qui est celle d'`evaluate_w1` gelé :
- `WAIT_*` signifie NON CONCLUANT ;
- `NO_GO` signifie NÉGATIF ;
- `CHALLENGER_FOR_W2` signifie POSITIF À CONFIRMER. Ce n'est jamais une autorisation LIVE.

Aucune métrique ne s'ajoute après lecture des données. Une métrique que les données ne permettent pas de calculer est publiée « non calculable », avec sa raison.

## 1. Sources et population

- **Sources** : les bundles ancrés (`run/bundles`), `w1_report.json`, `ledger/ledger.json` (cycles recalculés) et la série SOL/USD ancrée. Rien d'autre.
- **Bras** : M1 (MASTER L1), P1b (placebo L1), P1 (placebo V2), P2 (abstention), S1 (snipe immédiat), S2 (délai fixe de 5 s, la référence), S3 (CH1).
- **Population principale** : les pools du segment d'évaluation, `w1_eval.w1_split(start, end, embargo=4 513)['all']`, avec les bornes de `w1_run.plan(S0)`. C'est la population de la décision. La même population sert à tous les bras, et les pools de la période de chauffe sont exclus. Les résultats par moitié A et B sont publiés aussi.
- **Cycle entré** : `entry_index` non nul. **Cycle clos** : `outcome = 'closed'`. Les autres issues (`open_at_window_end`, `open_at_end`, `migrated_unpriced`, `counterfactual_divergence`) sont **non valorisées** : elles sont comptées par motif et n'entrent jamais dans une moyenne de rendement, sauf dans la mesure pessimiste (§2).
- **Unité** : SOL, à 1 SOL = 10⁹ lamports. Le dollar n'est donné qu'à titre indicatif : point Pyth « as-of » de la sortie, avec le nombre de refus publié.

## 2. Définitions, pour chaque bras et pour les cycles clos sauf mention contraire

| Métrique | Formule |
|---|---|
| Rendement net r_i | `pnl_lamports / (spent + tx_costs + failed_attempt_costs)`, la formule gelée de `trial_metrics` |
| P&L net (SOL) | Σ `pnl_lamports` / 10⁹ |
| P&L brut (SOL) | Σ (`pnl_lamports` + frais LaunchLab + `tx_costs` + `failed_attempt_costs`) / 10⁹, soit mouvement de marché − slippage (décomposition du ledger) |
| Espérance nette par cycle | moyenne des r_i (`mean_return` gelé) ; **mesure pessimiste** = (Σ r_i − nombre de non valorisés) / nombre de cycles entrés, c'est-à-dire que chaque non-valorisé compte −100 % (gelé) |
| Effectifs | entrés, clos, non valorisés par motif, créateurs indépendants (signés vérifiés) |
| Taux de réussite | part des r_i > 0 |
| Gain moyen / perte moyenne | moyenne des r_i \| r_i > 0, et moyenne des r_i \| r_i ≤ 0 |
| Distribution | quantiles 1, 5, 25, 50, 75, 95 et 99 % des r_i ; minimum ; maximum |
| Pertes extrêmes | nombre de r_i ≤ −50 % et de r_i ≤ −90 % ; CVaR 5 % = moyenne des ⌈5 % × n⌉ pires r_i |
| Drawdown (SOL) | P&L net cumulé des cycles clos, triés par (`exit_slot`, pool) ; plus grande baisse depuis le sommet précédent. Taille fixe de 0,1 SOL, sans exposition simultanée modélisée : ce n'est **pas** un drawdown de portefeuille |
| Concentration | part du P&L net positif total due aux 1, 5 et 10 meilleurs pools ; P&L net sans les 5 meilleurs pools |
| Décomposition des coûts | Σ du mouvement de marché, du slippage, des frais LaunchLab et des coûts de transaction et d'échec (ledger `comparison`) |
| Incertitude | IC 95 % bootstrap de la moyenne des r_i, rééchantillonné par créateur, avec B = 10 000 et seed = 20261108 (la méthode gelée), pour chaque bras ayant au moins 2 cycles clos |

## 3. Comparaisons, toutes descriptives

- **M1 contre S2 (référence), S1, P1b, P1 et P2**, sur la même population : différence des espérances nettes et des P&L nets. Les tests de décision restent H1 et H2 d'`evaluate_w1`, avec la correction de Holm.
- **Pools entrés à la fois par M1 et par S2** : nombre de pools communs, puis moyenne des différences r(M1) − r(S2) sur ces pools.
- **Sensibilités**, toutes hors N :
  - latence de 10 slots (`M1_latency10`) ;
  - frais d'échec de 105 000 lamports ;
  - horizon de sortie par événement ;
  - pour chacune : espérance nette et P&L net, exactement comme au §2.

## 4. Réserves de modèle (verdict opérationnel), écrites d'avance

- Ni `min_out` ni slippage maximal : les remplissages sont optimistes **pour tous les bras**, et l'effet relatif entre M1 et la référence est indéterminé.
- `block_time` est arrondi à la seconde.
- Un TP ou un SL entre la deadline et l'atterrissage remplace la vente à l'horloge.
- Une sortie après migration n'est pas valorisée.
- Le taux de frais est inféré causalement.
- La taille d'entrée est fixe.
- Le SOL/USD vient de Pyth, avec l'âge et la confiance fixés par l'étude ancrée.
- Le décompte des créateurs indépendants a une limite sybil.
- L'indépendance du ledger est partielle.
- La couverture est auditée chez le même fournisseur que la collecte.
- La latence est fixée à 4 slots.
- Il n'y a qu'une fenêtre d'environ 5 jours.

## 5. Calcul

Le calcul est fait par un module unique (`w1aux/metrics.py`). Il lit **seulement** les fichiers ancrés, ne réécrit rien, et produit `metrics.json` avec son sha. Il sera testé sur le pack gelé et ancré par RUGGER 02 **avant la collecte LaunchLab**. Il s'exécute après l'étape `ledger` de dayj.
