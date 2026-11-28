# R05 — Pré-enregistrement v4 : phase intensive (figé le 2026-11-28, avant toute collecte de cette phase)

(E) = éliminatoire, (D) = descriptif. L'horodatage du commit fait foi.

## T1 (E) — Toxicité réelle des flux de PAPER-1, mesure sans modèle

- **Données** : transactions réelles des pools Raydium AMM v4 SOL-USDC (`58oQCh…YQo2`) et SOL-USDT
  (`7Xawhb…EbEmX`). Elles sont relevées dans l'API GeckoTerminal toutes les 5 minutes pendant au moins 2 heures
  de cette session, et dédoublonnées par (tx, montants). Prix de référence : clôtures **à la seconde** d'OKX
  SOL-USDT ; pour SOL-USDC, elles sont converties par USDC-USDT à la seconde.
- **Mesure** : P&L des LP sur chaque transaction à l'horizon h ∈ {0 s, 60 s, 300 s}, en dollars et pondéré par le
  volume : montant de stablecoin reçu ou payé par le pool − quantité de SOL × prix de référence (t + h), moins la
  part protocole (3 pb du volume). On obtient une **capture LP en pb du volume**.
- **Prédiction issue de S3** : capture positive, de l'ordre de 0,75 × 22 pb.
- **Élimination** : si la capture à 60 s a une borne haute d'IC 95 % (bootstrap par blocs de 50 transactions)
  < 0 sur SOL-USDC, la conclusion « frais > LVR » de PAPER-1 est contredite et PAPER-1 est **suspendu** jusqu'à
  explication. Si l'IC contient 0 : non concluant (échantillon court), à prolonger.

## T2 (E) — LVR estimée à la minute

- Variance réalisée à partir des klines **1 min** Binance SOLUSDT (archive vérifiée), 2025-01-24 → 2026-10-31,
  comparée à la variance horaire.
- **PAPER-1 maintenu** seulement si l'avantage moyen « frais DefiLlama × 0,88 − RV_1min/8 » a une borne basse
  d'IC 95 % > 0. C'est une hypothèse prudente : avec 0,25 % de frais, l'arbitrage n'exploite pas les écarts
  inférieurs à 25 pb.

## T3 (E) — Résolution de Base par lecture on-chain

- Événements `Swap` de la paire Uniswap v2 WETH-USDC de Base (`0x88a4…b9c`), lus sur un nœud RPC public, sur la
  plus longue fenêtre récente lisible (≥ 30 jours). Frais LP exacts = 0,3 % des montants entrants valorisés au
  prix du pool, divisés par la TVL ; vérification de `feeTo` (frais protocole) de la factory.
- La source (GeckoTerminal ou DefiLlama) à ± 20 % de la mesure on-chain devient la référence, et H3d-net Base est
  recalculé avec elle. **Base devient candidat** de PAPER-1b si l'excès net est > 0 avec un IC > 0 ; sinon il est
  exclu.
- Si l'accès RPC est impossible, T3 reste ouvert ; rien n'est supposé.

## T4 (E) — Basis des futures datés Deribit (instantané)

- Pour chaque échéance BTC et ETH à au moins 30 jours : basis annualisé = (mark future / index − 1) × 365 / jours.
- Net = basis − taux Aave − coûts annualisés. Les coûts couvrent l'aller-retour : future 5 pb × 2, spot 12 pb × 2,
  amortis sur la durée.
- **Opportunité** seulement si net > 2 %/an. Sinon le carry daté est écarté **à cette date**.

## T5 (E) — Coffre de market making Hyperliquid (HLP), allocation passive

- Historique public du coffre (`vaultDetails`, portefeuille « allTime »). Rendements journaliers tirés du P&L
  cumulé rapporté à la valeur du compte.
- Métriques : rendement, volatilité, drawdown, pires jours, excès sur Aave avec IC (bootstrap mensuel).
- **Candidat « PAPER-3 »** si l'excès > 0 avec une borne basse d'IC > 0 **et** un drawdown max < 15 %. Le risque
  de contrepartie Hyperliquid est déclaré non mesurable.

## T6 (D) — Concentration des flux de SOL-USDC

Part du volume collecté en T1 apportée par les 10 premières adresses émettrices. Seules des parts agrégées sont
publiées, jamais de liste d'adresses.
