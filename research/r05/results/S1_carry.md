# S1 — Carry et funding : résultats

Protocole : `docs/R05_PREREGISTRATION_v1.md` §3. Données : archive Binance (CHECKSUM vérifiés), API publique Hyperliquid, DefiLlama (Aave v3 USDC, taux de référence). Rendements sur **capital** (S1-A : 1 + 1/3 = 1.333 par unité de notionnel ; S1-B : 1.00).

## S1-A — funding moyen annualisé par période (Binance USDⓈ-M)

| Actif | DESIGN | VALID | TEST | Jours funding < 0 | Pire funding 30 j | Basis moyen (pb) [min ; max] | Jours de liquidation OOS (L=2/3/5) |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 17.3 % | 9.9 % | 4.2 % | 12.2 % | -1.3 % | -1.7 [-74 ; 31] | 0/0/1 |
| ETHUSDT | 21.9 % | 10.6 % | 3.6 % | 12.0 % | -1.8 % | -1.1 [-103 ; 36] | 0/0/3 |
| SOLUSDT | -5.8 % | 7.5 % | -0.1 % | 28.5 % | -36.0 % | -3.2 [-1690 ; 71] | 0/1/11 |

## S1-A — portefeuille équipondéré, net de frais, sur capital

| Config | Période | Rend. ann. | Vol | Sharpe | DD max | Taux réf. moyen | Excès ann. sur réf. | IC 95 % excès mensuel | Temps investi |
|---|---|---|---|---|---|---|---|---|---|
| C0 | DESIGN | 8.4 % | 6.5 % | 1.27 | 14.2 % | n/d | n/d | [n/d ; n/d] | 99.9 % |
| C0 | VALID | 7.2 % | 0.7 % | 10.19 | 0.9 % | 5.4 % | 1.5 % | [-0.0 % ; 0.3 %] | 100.0 % |
| C0 | TEST | 1.9 % | 0.3 % | 5.53 | 0.6 % | 3.8 % | -1.9 % | [-0.2 % ; -0.1 %] | 100.0 % |
| C0 | OOS | 4.6 % | 0.6 % | 8.07 | 0.9 % | 4.6 % | -0.1 % | [-0.1 % ; 0.1 %] | 100.0 % |
| C1_H0.05 | DESIGN | 12.7 % | 1.6 % | 7.37 | 1.9 % | n/d | n/d | [n/d ; n/d] | 84.2 % |
| C1_H0.05 | VALID | 4.7 % | 0.7 % | 6.74 | 1.5 % | 5.4 % | -0.8 % | [-0.3 % ; 0.2 %] | 83.9 % |
| C1_H0.05 | TEST | -1.8 % | 0.4 % | -4.26 | 3.6 % | 3.8 % | -5.6 % | [-0.5 % ; -0.4 %] | 56.5 % |
| C1_H0.05 | OOS | 1.6 % | 0.6 % | 2.63 | 3.6 % | 4.6 % | -3.1 % | [-0.4 % ; -0.1 %] | 70.8 % |
| C1_H0.1 | DESIGN | 12.4 % | 1.6 % | 7.36 | 1.3 % | n/d | n/d | [n/d ; n/d] | 63.7 % |
| C1_H0.1 | VALID | 3.9 % | 0.6 % | 6.07 | 1.3 % | 5.4 % | -1.6 % | [-0.3 % ; 0.1 %] | 47.5 % |
| C1_H0.1 | TEST | -0.3 % | 0.2 % | -1.65 | 0.5 % | 3.8 % | -4.0 % | [-0.4 % ; -0.3 %] | 5.4 % |
| C1_H0.1 | OOS | 1.9 % | 0.5 % | 3.92 | 1.3 % | 4.6 % | -2.7 % | [-0.3 % ; -0.1 %] | 27.4 % |
| C1_H0.2 | DESIGN | 10.0 % | 1.5 % | 6.22 | 1.2 % | n/d | n/d | [n/d ; n/d] | 34.1 % |
| C1_H0.2 | VALID | 1.6 % | 0.5 % | 3.25 | 0.3 % | 5.4 % | -3.8 % | [-0.4 % ; -0.2 %] | 14.9 % |
| C1_H0.2 | TEST | 0.0 % | 0.0 % | nan | 0.0 % | 3.8 % | -3.8 % | [-0.4 % ; -0.3 %] | 0.0 % |
| C1_H0.2 | OOS | 0.9 % | 0.4 % | 2.33 | 0.3 % | 4.6 % | -3.8 % | [-0.4 % ; -0.2 %] | 7.8 % |

Sélection C1 sur DESIGN : **C1_H0.05**.

- **C0** : REJETEE — critères {'excess_gt_0': False, 'ci_low_gt_0': False, 'cost_x2_excess_gt_0': False, 'dd_lt_10pct': True} ; excès OOS ×2 coûts -0.1 %.
- **C1_H0.05** : REJETEE — critères {'excess_gt_0': False, 'ci_low_gt_0': False, 'cost_x2_excess_gt_0': False, 'dd_lt_10pct': True} ; excès OOS ×2 coûts -6.0 %.

## S1-B — écart de funding Hyperliquid − Binance

| Actif | Depuis | Funding HL ann. | Funding Binance ann. | Écart moyen ann. | Part du temps \|écart 3 j\| > 10 % | σ basis inter-plateformes (pb/j) |
|---|---|---|---|---|---|---|
| BTCUSDT | 2023-05-13 | 13.9 % | 7.2 % | 6.7 % | 29.1 % | 4.6 |
| ETHUSDT | 2023-05-13 | 13.9 % | 7.2 % | 6.7 % | 25.2 % | 5.4 |
| SOLUSDT | 2023-05-13 | 12.0 % | 4.9 % | 7.1 % | 35.9 % | 6.5 |

| Seuil H | Période | Rend. ann. | Sharpe | DD max | Excès ann. | IC 95 % excès mensuel | Temps investi | Entrées |
|---|---|---|---|---|---|---|---|---|
| H0.1 | DESIGN | 7.7 % | 5.81 | 0.7 % | 1.3 % | [-0.2 % ; 0.5 %] | 79.3 % | 26 |
| H0.1 | VALID | -1.1 % | -1.41 | 1.9 % | -6.5 % | [-0.7 % ; -0.3 %] | 49.3 % | 34 |
| H0.1 | TEST | -1.9 % | -4.39 | 3.0 % | -5.5 % | [-0.6 % ; -0.4 %] | 20.1 % | 33 |
| H0.1 | OOS | -1.6 % | -2.58 | 4.4 % | -5.9 % | [-0.6 % ; -0.4 %] | 32.6 % | 67 |
| H0.1 | OOS_cost_x2 | -5.7 % | -6.15 | 12.9 % | -10.2 % | [-1.0 % ; -0.7 %] | 32.6 % | 67 |
| H0.2 | DESIGN | 5.0 % | 4.58 | 0.6 % | -1.2 % | [-0.4 % ; 0.2 %] | 50.4 % | 22 |
| H0.2 | VALID | -0.3 % | -0.56 | 0.6 % | -5.6 % | [-0.6 % ; -0.4 %] | 14.8 % | 15 |
| H0.2 | TEST | -0.3 % | -1.31 | 0.5 % | -3.9 % | [-0.4 % ; -0.3 %] | 3.5 % | 5 |
| H0.2 | OOS | -0.3 % | -0.76 | 1.0 % | -4.6 % | [-0.5 % ; -0.3 %] | 8.3 % | 20 |
| H0.2 | OOS_cost_x2 | -1.7 % | -2.91 | 3.8 % | -6.0 % | [-0.7 % ; -0.4 %] | 8.3 % | 20 |
| H0.4 | DESIGN | 2.4 % | 3.48 | 0.2 % | -3.7 % | [-0.4 % ; -0.1 %] | 21.7 % | 18 |
| H0.4 | VALID | -0.1 % | -0.72 | 0.2 % | -5.5 % | [-0.6 % ; -0.3 %] | 2.2 % | 3 |
| H0.4 | TEST | -0.1 % | -1.21 | 0.1 % | -3.7 % | [-0.3 % ; -0.3 %] | 0.2 % | 1 |
| H0.4 | OOS | -0.1 % | -0.80 | 0.3 % | -4.5 % | [-0.5 % ; -0.3 %] | 1.1 % | 4 |
| H0.4 | OOS_cost_x2 | -0.3 % | -1.43 | 0.8 % | -4.7 % | [-0.5 % ; -0.3 %] | 1.1 % | 4 |

Sélection sur DESIGN : **H0.1** → **REJETEE** — {'excess_gt_0': False, 'ci_low_gt_0': False, 'cost_x2_excess_gt_0': False, 'dd_lt_10pct': True}.
Non mesuré : transferts de marge inter-plateformes, risque de contrepartie Hyperliquid.
