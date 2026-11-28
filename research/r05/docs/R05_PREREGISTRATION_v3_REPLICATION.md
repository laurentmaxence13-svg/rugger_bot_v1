# R05 — Pré-enregistrement v3 : réplications et mesure directe (figé le 2026-11-28 ≈ 11:15Z)

Objectif : attaquer la faiblesse principale de chaque piste PAPER — **un seul pool** pour PAPER-1, **trois
actifs corrélés** pour PAPER-2 — par des réplications sur des univers jamais examinés, définis ici par des
critères neutres (TVL, capitalisation), avant tout téléchargement de rendements.

## H2b — Réplication du momentum 30 j long/plat sur 18 autres cryptomonnaies

- **Univers figé** : XRP, LTC, BCH, ADA, DOT, LINK, BNB, XLM, DOGE, UNI, AAVE, EOS, TRX, XTZ, ATOM, VET, THETA, FIL
  (plus grosses capitalisations non stables au 2021-01-01, de mémoire du chercheur, hors BTC/ETH/SOL déjà
  utilisés, hors jetons enveloppés et actifs absents de Binance). Paire USDT, klines **1 j** de l'archive
  Binance (CHECKSUM). Un actif retiré de la cote reste dans l'univers jusqu'à sa dernière donnée (pas de biais
  du survivant par construction de la liste).
- **Règle** : celle de PAPER-2, inchangée (L = 30, long/plat, 12 pb par côté, 1/N par actif disponible).
- **Fenêtre** : 2023-01-01 → 2026-10-31 (descriptif complémentaire : tout l'historique disponible).
- **Tests** : (a) drawdown max du portefeuille ≤ 0,7 × celui de la détention passive ; (b) placebo par
  permutation de segments (méthode R2.1, 2 000 tirages) : p ≤ 0,05 ; (c) ≥ 60 % des actifs avec un Sharpe F1 >
  Sharpe passif ; (D) écart de rendement annualisé avec le passif.
- **Verdict** : RÉPLIQUÉ si (a), (b) et (c) ; PARTIEL si (a) seul ; NON RÉPLIQUÉ sinon. **Non répliqué ⇒
  PAPER-2 perd sa place et devient une simple observation.**

## H3d — Réplication multi-chaînes du mécanisme LP (« pool plage complète dominant de la paire principale »)

- **Univers figé** (cache DefiLlama du 2026-11-26) : pools à produit constant, paire jeton natif enveloppé /
  USDC ou USDT, TVL ≥ 250 000 $, frais versés aux LP. Aerodrome v1 est exclu, car ses frais vont aux votants.

| Chaîne | Projet | Paire | Pool DefiLlama | Part LP des frais |
|---|---|---|---|---|
| Ethereum | uniswap-v2 | USDC-WETH | 702fff16-4bfa-4c1f-8c02-e0ea0f5ecde6 | 1,00 (0,30 %) |
| Ethereum | uniswap-v2 | WETH-USDT | 196aa543-1881-4515-9928-577693d4fa72 | 1,00 |
| Ethereum | sushiswap | WETH-USDT | b1ff3e89-14a0-42a1-b760-716304387201 | 0,833 (0,25/0,30) |
| Ethereum | pancakeswap-amm | WETH-USDT | d77a4965-de74-48d4-afc5-1a73e3ce9d65 | 0,68 (0,17/0,25) |
| Base | uniswap-v2 | WETH-USDC | dfe517bb-4beb-45ae-b847-5d4067fc7ef9 | 1,00 |
| BSC | pancakeswap-amm | USDT-WBNB | a3878e88-0c9f-49ef-adbc-da5fe048192d | 0,68 |
| Polygon | quickswap-dex | WMATIC-USDC | 81a51af8-4a0e-409b-9688-264323afc1fe | 0,833 |
| Solana | raydium-amm | WSOL-USDC (Standard) | 12edc6f3-4926-4b4f-b97c-38ef6a458574 | 0,88 (pool de référence) |
| Solana | raydium-amm | WSOL-USDT (Standard) | cdd04383-21ea-45d1-94d6-295e58100559 | 0,88 |

- Les parts LP sont des **hypothèses** de barème. Une borne haute (part = 1,00) est publiée à côté.
- **Volatilité** : variance réalisée horaire Binance (ETHUSDT, BNBUSDT, MATICUSDT puis POLUSDT, SOLUSDT).
  Avantage quotidien = frais LP − RV/8.
- **Fenêtre** : couverture DefiLlama dans 2023-01-01 → 2026-10-31, au moins 180 jours.
- **Verdict** : mécanisme GÉNÉRAL si ≥ 5 pools sur 9 ont un IC 95 % de l'avantage moyen > 0 (part LP) ;
  SPÉCIFIQUE si ≤ 2 ; MIXTE sinon. SPÉCIFIQUE ⇒ PAPER-1 est maintenu, mais son risque idiosyncratique devient
  le premier risque déclaré.

## D-1 — Mesure directe prospective des frais (collecteur quotidien)

- Chaque jour, un instantané par l'API publique Raydium des réserves et de l'offre LP des pools AMM v4 de
  l'univers R3.3, plus WSOL-USDT. Sur un pool AMM, la croissance quotidienne de √(x·y)/offre LP mesure les
  frais réinvestis **sans passer par aucun agrégateur**.
- Évaluation au 2027-02-28 : frais directs par pool contre DefiLlama × 0,88 ; avantage direct = frais directs − LVR
  (clôtures GeckoTerminal). Critère pour PAPER-1 : frais directs SOL-USDC à ± 20 % des frais DefiLlama corrigés.
- Automatisation : tâche planifiée quotidienne, commit des instantanés sur la branche R05. Une journée sans
  instantané reste un trou déclaré, jamais une interpolation silencieuse.
