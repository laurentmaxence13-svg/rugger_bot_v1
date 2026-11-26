# S4 / S1-C — Microstructure : market making et arbitrage spatial

Frais = **HYPOTHÈSES** de grilles publiques de base, à revérifier. Markouts = bornes optimistes (pas de latence, pas de course à l'annulation, pas de limite d'inventaire).

## S4-A — markouts sur transactions réelles Binance spot (3 jours tirés au sort : 2025-02-18, 2025-05-24, 2026-08-23)

| Actif | Demi-spread médian (pb) | Markout 1 s opt./pess. | 10 s opt./pess. | 60 s opt./pess. | 300 s opt./pess. | Net 10 s pess. VIP0 (10 pb) | Frais maker de point mort (pb) | Verdict |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 0.08 | -0.56 / -0.81 | -0.92 / -1.29 | -0.95 / -1.29 | -0.83 / -1.09 | -11.29 | -1.29 | **ABANDON (palier VIP0)** |
| SOLUSDT | 0.31 | -0.28 / -1.15 | -0.66 / -1.56 | -0.73 / -1.62 | -0.80 / -1.36 | -11.56 | -1.56 | **ABANDON (palier VIP0)** |
| WIFUSDT | 4.39 | 2.75 / -3.87 | 0.81 / -5.52 | -0.26 / -6.26 | 0.37 / -5.54 | -15.52 | -5.52 | **ABANDON (palier VIP0)** |

## S4-B — spreads affichés vs frais maker (photographie snap_20261126T133835Z.jsonl.gz, 240 tours, 0 requêtes en échec sur 7920, désynchronisation médiane d'un tour 0.40 s, p95 0.60 s)

| Plateforme | Instrument | Spread médian (pb) | p90 (pb) | Profondeur médiane ±10 pb par côté (devise de cotation) | Frais maker (pb) | Demi-spread − maker (pb) |
|---|---|---|---|---|---|---|
| coinbase | BONK-USD | 45.77 | 45.77 | n/d (niveau 1) | 60.0 | -37.12 |
| coinbase | BTC-USD | 0.00 | 0.00 | n/d (niveau 1) | 60.0 | -60.00 |
| coinbase | ETH-USD | 0.59 | 1.00 | n/d (niveau 1) | 60.0 | -59.71 |
| coinbase | JTO-USD | 8.49 | 12.70 | n/d (niveau 1) | 60.0 | -55.76 |
| coinbase | SOL-USD | 1.41 | 2.82 | n/d (niveau 1) | 60.0 | -59.30 |
| coinbase | WIF-USD | 10.52 | 12.03 | n/d (niveau 1) | 60.0 | -54.74 |
| hyperliquid | BTC | 0.16 | 0.16 | 5,506,400 | 1.5 | -1.42 |
| hyperliquid | ETH | 0.59 | 0.59 | 9,547,013 | 1.5 | -1.21 |
| hyperliquid | HYPE | 0.16 | 0.33 | 145,104 | 1.5 | -1.42 |
| hyperliquid | JUP | 1.28 | 2.98 | 12,445 | 1.5 | -0.86 |
| hyperliquid | SOL | 0.14 | 0.14 | 413,840 | 1.5 | -1.43 |
| hyperliquid | WIF | 4.50 | 6.12 | 13,298 | 1.5 | 0.75 |
| kraken | SOLUSD | 1.41 | 1.41 | 598,496 | 25.0 | -24.30 |
| kraken | XBTUSD | 0.02 | 0.02 | 546,675 | 25.0 | -24.99 |
| okx | BONK-USDT | 9.14 | 9.15 | 2,742 | 8.0 | -3.43 |
| okx | BTC-USDT | 0.02 | 0.02 | 114,296 | 8.0 | -7.99 |
| okx | BTC-USDT-SWAP | 0.02 | 0.02 | 524,145 | 2.0 | -1.99 |
| okx | ETH-USDT | 0.06 | 0.06 | 135,514 | 8.0 | -7.97 |
| okx | JTO-USDT | 8.45 | 8.46 | 434 | 8.0 | -3.77 |
| okx | SOL-USDC | 1.41 | 2.82 | 37,699 | 8.0 | -7.29 |
| okx | SOL-USDT | 1.41 | 1.41 | 309,802 | 8.0 | -7.30 |
| okx | SOL-USDT-SWAP | 1.41 | 1.41 | 1,235,062 | 2.0 | -1.30 |
| okx | WIF-USDT | 7.52 | 15.02 | 746 | 8.0 | -4.24 |

## S1-C — meilleur écart exécutable entre plateformes (achat ask / vente bid, en USD)

| Actif | Instantanés | Écart brut médian (pb) | max (pb) | Part brut > 0 | Part net > 0 (frais de base) | Part net > 0 (meilleurs paliers) | Net max meilleurs paliers (pb) |
|---|---|---|---|---|---|---|---|
| BTC | 240 | 0.75 | 6.38 | 100 % | 0 % | 0 % | -0.30 |
| ETH | 240 | 0.12 | 4.86 | 58 % | 0 % | 0 % | -1.64 |
| SOL | 240 | -0.15 | 4.31 | 40 % | 0 % | 0 % | -0.80 |

### DEX (Jupiter) vs médiane des mids CEX, SOL

| Sens | Taille | Devis | Coût médian vs mid CEX (pb) | Meilleur (pb) | Part meilleure que le mid CEX | Route la plus fréquente |
|---|---|---|---|---|---|---|
| SOL->USDC | 1 | 60 | -0.20 | -1.93 | 60 % | BisonFi |
| SOL->USDC | 10 | 60 | -0.00 | -1.72 | 50 % | BisonFi |
| SOL->USDC | 100 | 60 | 0.28 | -1.51 | 45 % | Manifest+BisonFi |
| SOL->USDC | 1000 | 60 | 0.80 | -1.01 | 27 % | BisonFi+BisonFi+Deriverse |
| USDC->SOL | 100 | 60 | 1.16 | -1.45 | 8 % | BisonFi |
| USDC->SOL | 1000 | 60 | 1.55 | -1.23 | 8 % | BisonFi |
| USDC->SOL | 10000 | 60 | 1.79 | -1.06 | 7 % | BisonFi+Manifest |
| USDC->SOL | 100000 | 60 | 2.94 | 0.10 | 0 % | Deriverse+BisonFi+Raydium CLMM+Scorch+BisonFi |
