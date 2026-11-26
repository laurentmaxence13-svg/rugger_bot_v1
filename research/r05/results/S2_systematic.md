# S2-A — Trading systématique BTC/ETH/SOL : résultats

Protocole : `docs/R05_PREREGISTRATION_v1.md` §2. Données : archive publique Binance spot 1 h, CHECKSUM vérifiés (`DATA_MANIFEST_binance.json`). Portefeuille équipondéré, rendements journaliers.

## Qualité des données

| Actif | Début | Fin | Barres | Heures manquantes | Doublons | Var. horaire max |
|---|---|---|---|---|---|---|
| BTCUSDT | 2018-01-01 | 2026-10-31 23:00 | 77304 | 163 | 0 | 18.2 % |
| ETHUSDT | 2018-01-01 | 2026-10-31 23:00 | 77304 | 163 | 0 | 20.9 % |
| SOLUSDT | 2020-08-11 | 2026-10-31 23:00 | 54527 | 19 | 0 | 30.6 % |

## Détention passive (référence)

| Période | Rend. annualisé | Vol | Sharpe | DD max |
|---|---|---|---|---|
| DESIGN | 21.1 % | 88.3 % | 0.67 | 87.9 % |
| VALID | 173.5 % | 58.5 % | 2.01 | 32.9 % |
| TEST | -18.0 % | 58.9 % | -0.04 | 64.3 % |
| OOS | 53.8 % | 58.8 % | 1.03 | 64.3 % |

## Configurations retenues sur CONCEPTION puis évaluées hors échantillon

| Famille / variante | Param. | Sharpe VALID | Sharpe TEST | Sharpe OOS net [IC 95 %] | Sharpe OOS brut | PSR | DSR (nul analytique / inter-essais) | ×2 coûts | Point mort (pb/côté) | Alpha ann. (borne 5 %) | Trades | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1_spot | 30 | 1.82 | 0.43 | 1.24 [0.09 ; 2.30] | 1.33 | 0.99 | 0.68 / 0.00 | 1.15 | 182.8 | 18.8 % (-4.1 %) | 168 | **NON_CONCLUANTE** |
| F1_perp | 30 | 0.82 | 0.62 | 0.72 [-0.24 ; 1.65] | 0.80 | 0.92 | 0.28 / 0.00 | 0.65 | 72.4 | 36.3 % (-8.6 %) | 339 | **SECONDAIRE (NON_CONCLUANTE)** |
| F2_spot | 20 | 1.35 | -0.32 | 0.72 [-0.42 ; 1.81] | 0.76 | 0.92 | 0.28 / 0.00 | 0.68 | 218.7 | 0.3 % (-21.4 %) | 69 | **REJETEE** |
| F2_perp | 100 | 0.50 | -0.46 | 0.00 [-1.01 ; 1.09] | 0.01 | 0.50 | 0.02 / 0.00 | -0.01 | 8.8 | -9.1 % (-47.0 %) | 30 | **SECONDAIRE (REJETEE)** |
| F3_spot | 24 | 0.20 | 0.51 | 0.37 [-0.41 ; 1.33] | 0.70 | 0.77 | 0.11 / 0.00 | 0.05 | 27.8 | 0.1 % (-13.5 %) | 287 | **REJETEE** |
| F3_perp | 4 | -1.22 | -1.61 | -1.41 [-2.40 ; -0.42] | -0.09 | 0.00 | 0.00 / 0.00 | -2.73 | -0.3 | -27.7 % (-46.9 %) | 2313 | **SECONDAIRE (REJETEE)** |
| F4_spot | 24 | -0.66 | -1.14 | -0.88 [-2.13 ; 0.21] | 0.97 | 0.05 | 0.00 / 0.00 | -2.67 | 6.3 | -13.4 % (-21.6 %) | 968 | **REJETEE** |
| F4_perp | 24 | -1.49 | -0.50 | -1.01 [-2.00 ; -0.08] | 0.73 | 0.03 | 0.00 / 0.00 | -2.73 | 3.0 | -15.7 % (-30.0 %) | 2698 | **SECONDAIRE (REJETEE)** |

## Toutes les configurations (24 essais, tous comptés dans N)

| Config | Sharpe DESIGN | Sharpe VALID | Sharpe TEST | Rend. ann. OOS | DD max OOS |
|---|---|---|---|---|---|
| F1_30_spot | 1.27 | 1.82 | 0.43 | 52.0 % | 40.2 % |
| F1_90_spot | 1.03 | 1.38 | -0.07 | 28.1 % | 39.8 % |
| F1_180_spot | 1.03 | 1.43 | -0.29 | 24.0 % | 47.8 % |
| F1_30_perp | 1.55 | 0.82 | 0.62 | 27.5 % | 46.2 % |
| F1_90_perp | 0.94 | 0.16 | -0.05 | -11.0 % | 63.1 % |
| F1_180_perp | 1.44 | 0.24 | -0.38 | -14.3 % | 76.3 % |
| F2_20_spot | 1.53 | 1.35 | -0.32 | 20.8 % | 39.6 % |
| F2_55_spot | 1.30 | 1.19 | -0.18 | 18.6 % | 33.1 % |
| F2_100_spot | 1.51 | 1.28 | -0.30 | 18.6 % | 33.4 % |
| F2_20_perp | 1.12 | 0.17 | -0.18 | -9.9 % | 58.1 % |
| F2_55_perp | 0.90 | 0.25 | -0.18 | -8.7 % | 54.8 % |
| F2_100_perp | 1.30 | 0.50 | -0.46 | -10.3 % | 56.6 % |
| F3_4_spot | -0.24 | -0.04 | -2.00 | -15.5 % | 58.2 % |
| F3_12_spot | -0.49 | 0.77 | -0.28 | 1.6 % | 23.2 % |
| F3_24_spot | 0.61 | 0.20 | 0.51 | 5.3 % | 24.7 % |
| F3_4_perp | 0.64 | -1.22 | -1.61 | -27.6 % | 72.9 % |
| F3_12_perp | -0.84 | -1.59 | -0.50 | -22.5 % | 65.2 % |
| F3_24_perp | -0.15 | -1.68 | 0.04 | -19.7 % | 59.8 % |
| F4_1_spot | -8.35 | -12.43 | -14.95 | -79.3 % | 99.8 % |
| F4_4_spot | -3.51 | -5.29 | -7.93 | -51.8 % | 94.3 % |
| F4_24_spot | -0.56 | -0.66 | -1.14 | -9.7 % | 41.6 % |
| F4_1_perp | -5.92 | -11.88 | -13.15 | -88.9 % | 100.0 % |
| F4_4_perp | -2.95 | -6.62 | -6.09 | -67.7 % | 98.7 % |
| F4_24_perp | -0.61 | -1.49 | -0.50 | -18.8 % | 60.7 % |

## Régimes (descriptif, étiquettes ex post, échantillon complet)

| Config retenue | Sharpe vol haute | Sharpe vol basse | Sharpe tendance + | Sharpe tendance − | Passif vol haute / basse |
|---|---|---|---|---|---|
| F1_spot | 1.52 | 0.91 | 2.22 | -0.23 | 0.83 / 0.74 |
| F1_perp | 1.44 | 0.85 | 1.71 | 0.34 | 1.41 / 0.80 |
| F2_spot | 1.58 | 0.77 | 2.00 | 0.05 | 0.83 / 0.74 |
| F2_perp | 1.02 | 0.26 | 0.97 | 0.19 | 1.41 / 0.80 |
| F3_spot | 0.74 | 0.16 | 1.32 | 0.02 | 0.83 / 0.74 |
| F3_perp | 0.52 | -1.21 | 0.17 | -0.53 | 1.41 / 0.80 |
| F4_spot | -0.37 | -1.17 | -0.12 | -1.23 | 0.83 / 0.74 |
| F4_perp | -0.65 | -0.97 | -0.83 | -0.66 | 1.41 / 0.80 |
