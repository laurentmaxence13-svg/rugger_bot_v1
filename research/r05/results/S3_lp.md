# S3 — Fourniture de liquidité : frais vs LVR

Protocole : `docs/R05_PREREGISTRATION_v1.md` §4. Avantage couvert = frais LP − LVR (plage complète, σ²/8).
Une stratégie LP n'est jamais jugée rentable sur ses seuls frais.

## S3-A — coupe transversale (top 60 pools Raydium par TVL, instantané du 2026-11-26)

| Type | Pools | avec σ | Frais LP médians (ann.) | LVR plage complète médiane (ann.) | Avantage médian (ann.) | Part avantage > 0 | CF* médian |
|---|---|---|---|---|---|---|---|
| AMMv4 | 16 | 16 | 4.3 % | 3.0 % | 0.0 % | 50 % | 1.0 |
| CLMM | 43 | 16 | 0.0 % | 5.6 % | non évaluable | — | 6.3 |
| CPMM | 1 | 1 | 20.0 % | 28.5 % | -8.5 % | 0 % | 0.7 |

**H3a (pools non concentrés)** : n = 17, avantage médian -0.0 % /an [IC 95 % -0.1 % ; 2.3 %], hors paires stables -0.0 % ; part > 0 : 47 % → **H3a NON CONCLUANTE**.

Pools CLMM : l'avantage n'est pas calculable sans la liquidité active. On publie **CF\*** = frais/TVL ÷ LVR plage complète : les LP d'un pool concentré ne couvrent la LVR que si leur liquidité est en moyenne moins de CF\* fois plus concentrée qu'une plage complète. Indicateur, pas preuve.

| Paire | Type | Frais | TVL (k$) | Rotation /j | Frais LP /an | σ /j | LVR plage complète /an | Avantage /an (CLMM : CF\*) | Rotation de point mort /j |
|---|---|---|---|---|---|---|---|---|---|
| CC-USDC | CLMM | 0.01 % | 75,945 | 0.2 % | 0.0 % | n/d | n/d | n/d | n/d |
| NIGHT-USDC | CLMM | 0.01 % | 48,809 | 0.1 % | 0.0 % | n/d | n/d | n/d | n/d |
| TTWO-USDC | CLMM | 0.01 % | 32,128 | 0.6 % | 0.0 % | n/d | n/d | n/d | n/d |
| USDC-SI | CLMM | 0.01 % | 32,128 | 0.5 % | 0.0 % | n/d | n/d | n/d | n/d |
| USEF-USDC | CLMM | 0.01 % | 32,128 | 0.4 % | 0.0 % | n/d | n/d | n/d | n/d |
| VTC-USDC | CLMM | 0.01 % | 32,128 | 0.3 % | 0.0 % | n/d | n/d | n/d | n/d |
| USDC-UODF | CLMM | 0.01 % | 32,128 | 0.2 % | 0.0 % | n/d | n/d | n/d | n/d |
| UDTF-USDC | CLMM | 0.01 % | 32,128 | 0.1 % | 0.0 % | n/d | n/d | n/d | n/d |
| XDC-USDC | CLMM | 0.01 % | 29,886 | 0.6 % | 0.0 % | n/d | n/d | n/d | n/d |
| USDC-NOTF | CLMM | 0.01 % | 28,412 | 0.1 % | 0.0 % | n/d | n/d | n/d | n/d |
| USDC-NOTF | CLMM | 0.01 % | 26,367 | 0.2 % | 0.0 % | n/d | n/d | n/d | n/d |
| WSOL-GTA | CLMM | 0.01 % | 20,131 | 0.8 % | 0.0 % | n/d | n/d | n/d | n/d |
| GFT-USD1 | CLMM | 4.00 % | 19,944 | 0.0 % | 0.0 % | n/d | n/d | n/d | n/d |
| UITP-USDT | CLMM | 0.01 % | 19,461 | 0.0 % | 0.0 % | n/d | n/d | n/d | n/d |
| WSOL-XDC | CLMM | 0.01 % | 17,273 | 0.3 % | 0.0 % | n/d | n/d | n/d | n/d |
| WSOL-WENRL | CLMM | 0.01 % | 17,273 | 0.1 % | 0.0 % | n/d | n/d | n/d | n/d |
| WSOL-DCTY | CLMM | 0.01 % | 17,184 | 3.6 % | 0.1 % | n/d | n/d | n/d | n/d |
| WSOL-Midnight | CLMM | 0.01 % | 14,451 | 0.3 % | 0.0 % | n/d | n/d | n/d | n/d |
| WSOL-HBAR | CLMM | 0.01 % | 14,451 | 0.6 % | 0.0 % | n/d | n/d | n/d | n/d |
| WSOL-USDC | AMMv4 | 0.25 % | 14,376 | 21.3 % | 17.1 % | 3.5 % | 5.6 % | 11.5 % | 7.0 % |
| ATX-USDC | CLMM | 0.01 % | 12,647 | 1.0 % | 0.0 % | n/d | n/d | n/d | n/d |
| Old Slerf-WSOL | AMMv4 | 0.25 % | 12,065 | 0.0 % | 0.0 % | 0.4 % | 0.1 % | -0.1 % | 0.1 % |
| USDC-TRX | CLMM | 0.05 % | 11,946 | 0.3 % | 0.1 % | 1.9 % | 1.6 % | CF* 0.0 | 10.3 % |
| smole-WSOL | AMMv4 | 0.25 % | 11,748 | 0.0 % | 0.0 % | 0.4 % | 0.1 % | -0.1 % | 0.1 % |
| USD1-USDC | CLMM | 0.01 % | 9,912 | 45.0 % | 1.4 % | 0.1 % | 0.0 % | CF* 1057.0 | 0.0 % |
| BOME-WSOL | AMMv4 | 0.25 % | 9,587 | 4.1 % | 3.3 % | 2.7 % | 3.4 % | -0.0 % | 4.2 % |
| MEW-WSOL | AMMv4 | 0.25 % | 6,207 | 2.6 % | 2.1 % | 1.8 % | 1.4 % | 0.7 % | 1.8 % |
| RAY-USDC | AMMv4 | 0.25 % | 5,578 | 13.4 % | 10.8 % | 5.7 % | 14.7 % | -4.0 % | 18.3 % |
| WSOL-USDC | CLMM | 0.04 % | 5,444 | 407.0 % | 49.9 % | 3.4 % | 5.4 % | CF* 9.3 | 43.8 % |
| JCT-USDC | CLMM | 0.01 % | 5,317 | 5.8 % | 0.2 % | n/d | n/d | n/d | n/d |
| USX-USDC | CLMM | 0.01 % | 5,303 | 0.0 % | 0.0 % | 0.0 % | 0.0 % | CF* 9.4 | 0.0 % |
| USDC-MONERO | CLMM | 0.01 % | 4,931 | 2.9 % | 0.1 % | n/d | n/d | n/d | n/d |
| USDC-MONERO | CLMM | 0.01 % | 4,913 | 11.8 % | 0.4 % | n/d | n/d | n/d | n/d |
| FLR-USDC | CLMM | 0.01 % | 4,787 | 4.2 % | 0.1 % | n/d | n/d | n/d | n/d |
| USDC-MONERO | CLMM | 0.01 % | 4,701 | 3.1 % | 0.1 % | n/d | n/d | n/d | n/d |
| WSOL-Fartcoin  | AMMv4 | 0.25 % | 4,672 | 7.2 % | 5.8 % | 2.6 % | 3.1 % | 2.7 % | 3.8 % |
| USD1-WLFI | CLMM | 0.25 % | 4,524 | 0.0 % | 0.0 % | 12.7 % | 73.8 % | CF* 0.0 | 96.2 % |
| LIKE-WSOL | AMMv4 | 0.25 % | 4,305 | 0.3 % | 0.2 % | 0.6 % | 0.2 % | 0.1 % | 0.2 % |
| $NAP-WSOL | AMMv4 | 0.25 % | 4,300 | 0.0 % | 0.0 % | 0.4 % | 0.1 % | -0.1 % | 0.1 % |
| $WIF-WSOL | AMMv4 | 0.25 % | 3,875 | 5.6 % | 4.5 % | 2.5 % | 2.9 % | 1.6 % | 3.6 % |
| WSOL-USD1 | CLMM | 0.25 % | 3,816 | 33.8 % | 25.9 % | 3.5 % | 5.6 % | CF* 4.6 | 7.3 % |
| PEPE-USDC | CLMM | 0.01 % | 3,751 | 8.4 % | 0.3 % | n/d | n/d | n/d | n/d |
| USDv-USDC | CLMM | 0.01 % | 3,532 | 1.6 % | 0.0 % | 0.0 % | 0.0 % | CF* 347.2 | 0.0 % |
| WSOL-jellyjelly | AMMv4 | 0.25 % | 3,503 | 8.8 % | 7.1 % | 4.7 % | 10.2 % | -3.1 % | 12.7 % |
| RAY-WSOL | AMMv4 | 0.25 % | 3,498 | 5.0 % | 4.0 % | 3.4 % | 5.3 % | -1.3 % | 6.6 % |
| WSOL-pippin | AMMv4 | 0.25 % | 3,385 | 59.6 % | 47.8 % | 10.0 % | 45.5 % | 2.3 % | 56.7 % |
| CARDS-USDC | CLMM | 0.40 % | 3,318 | 46.9 % | 57.5 % | 7.9 % | 28.3 % | CF* 2.0 | 23.1 % |
| WSOL-BC | CLMM | 0.25 % | 2,963 | 5.1 % | 3.9 % | 3.5 % | 5.6 % | CF* 0.7 | 7.3 % |
| AKE-USDC | CLMM | 0.01 % | 2,947 | 12.8 % | 0.4 % | 0.2 % | 0.0 % | CF* 21.4 | 0.6 % |
| PUNDU-WSOL | AMMv4 | 0.25 % | 2,898 | 0.0 % | 0.0 % | 0.3 % | 0.0 % | -0.0 % | 0.0 % |
| ANT-USDC | CLMM | 0.25 % | 2,682 | 255.7 % | 196.0 % | n/d | n/d | n/d | n/d |
| CRCLx-USDC | CLMM | 0.10 % | 2,515 | 113.5 % | 34.8 % | 3.8 % | 6.4 % | CF* 5.4 | 21.0 % |
| WSOL-arc | AMMv4 | 0.25 % | 2,446 | 10.7 % | 8.6 % | 2.4 % | 2.6 % | 6.0 % | 3.3 % |
| SPCX-USDC | CLMM | 0.25 % | 2,426 | 146.9 % | 112.6 % | 3.9 % | 7.1 % | CF* 15.9 | 9.3 % |
| WSOL-USELESS | CPMM | 0.25 % | 2,365 | 26.1 % | 20.0 % | 7.9 % | 28.5 % | -8.5 % | 37.2 % |
| NVDAx-USDC | CLMM | 0.10 % | 2,360 | 343.0 % | 105.2 % | 5.7 % | 14.7 % | CF* 7.1 | 48.1 % |
| TSLAx-USDC | CLMM | 0.10 % | 2,305 | 101.6 % | 31.2 % | 3.7 % | 6.3 % | CF* 4.9 | 20.6 % |
| POPCAT-WSOL | AMMv4 | 0.25 % | 2,287 | 8.0 % | 6.5 % | 2.9 % | 3.8 % | 2.7 % | 4.7 % |
| QQQx-USDC | CLMM | 0.10 % | 2,251 | 53.5 % | 16.4 % | 2.2 % | 2.2 % | CF* 7.4 | 7.2 % |
| GTR-USDC | CLMM | 0.25 % | 2,163 | 6.0 % | 4.6 % | 6.7 % | 20.4 % | CF* 0.2 | 26.7 % |

## S3-B — historique SOL-USDC (DefiLlama × variance réalisée Binance)

| Pool | Période | Jours | Frais LP ann. (moy. / méd.) | LVR plage complète ann. | Avantage ann. moyen [IC 95 %] | Avantage médian / tronqué 5 % | Jours > 0 | CF* | LP non couvert − détention |
|---|---|---|---|---|---|---|---|---|---|
| Raydium AMM v4 SOL-USDC 0,25 % (plage complète) | 2025-01-23 → 2026-10-31 | 647 | 28.2 % / 15.9 % | 6.9 % | 21.4 % [12.1 % ; 32.8 %] | 8.9 % / 17.3 % | 95 % | 4.1 | 32.2 % |
| Orca Whirlpool SOL-USDC (concentré) — indicatif | 2023-07-07 → 2026-10-31 | 1126 | 102.7 % / 60.8 % | 8.7 % | non évaluable | — | — | 11.7 | n/d |
| Raydium CLMM SOL-USDC 0,04 % (concentré) — indicatif | 2025-01-23 → 2026-10-31 | 647 | 57.1 % / 44.7 % | 6.9 % | non évaluable | — | — | 8.3 | n/d |

**H3b** (Raydium AMM v4 SOL-USDC 0,25 % (plage complète)) : **H3b SOUTENUE**. Couverture : 2025-01-23 -> 2026-10-31 (pré-enregistré : 2023-01 -> 2026-10 ; historique DefiLlama disponible seulement depuis cette date).

Correction R05-D5 appliquée : l'APY de base DefiLlama compte la totalité des frais de transaction ; recoupé avec les volumes GeckoTerminal du même pool (39 jours, corrélation 1,00, rapport 0,88 = 0,22/0,25), il est ramené à la part LP (AMM v4 × 0,88 ; CLMM × 0,84 ; Orca non corrigé, part inconnue).
