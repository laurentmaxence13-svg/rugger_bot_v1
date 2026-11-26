# R05 — Pré-enregistrement v2 : batterie de réfutation (figée avant exécution)

Rédigé le 2026-11-26 ≈ 14:25Z, après le dossier n° 1 (`4ae7be4`). Objectif : **chercher à faire tomber**
les deux meilleurs résultats (S3-B LP SOL-USDC, S2-F1 momentum 30 j) et vérifier que les rejets
(S1 carry, S4 MM) ne sont pas dus à nos propres hypothèses défavorables. Une piste n'est proposée en
PAPER approfondi que si elle survit à **tous** ses tests éliminatoires (E). Les tests descriptifs (D)
informent sans décider. Toute idée née de données déjà vues est marquée **post hoc** et ne peut être
validée que sur des données postérieures au 2026-11-27 00:00Z.

## R3 — Fourniture de liquidité couverte, Raydium AMM v4 SOL-USDC 0,25 % (pool `58oQCh…YQo2`)

- **R3.1 (E) Indépendance de la source de frais.** Reconstituer les frais LP quotidiens depuis le volume
  quotidien GeckoTerminal du pool (historique maximal disponible) × 0,22 % / TVL DefiLlama ; comparer à
  DefiLlama × 0,88. Élimination si les frais reconstitués < 50 % des frais DefiLlama corrigés sur la période commune.
- **R3.1b (D) Mesure directe prospective.** Échantillonner toutes les 60 s, pendant la session, réserves et
  offre LP via l'API Raydium : la croissance de √(x·y)/offre LP n'est due qu'aux frais. La comparer aux
  frais impliqués par le volume minute GeckoTerminal sur la même fenêtre (rapport attendu ≈ 0,22/0,25 ou 1).
- **R3.2 (E) LP couverte simulée intégralement**, 2025-01-24 → 2026-10-31 : valeur LP exacte
  V = V₀·√(P/P₀)·G(t) (prix horaire Binance SOLUSDT, G = croissance des frais réinvestis) ; short perp
  SOLUSDT Binance égal à l'exposition SOL de la LP (V/2P), rééquilibré toutes les 24 h (primaire), 4 h et 1 h
  (secondaires) ; funding réel (archive) ; coût de rééquilibrage 5 + 2 pb sur le notionnel échangé ; entrée et
  sortie : échange de la moitié du capital à 3 pb, ouverture/fermeture perp à 7 pb ; capital = V₀·(1 + 1/(2·3)).
  Référence : Aave v3 USDC. **Élimination** si l'une des conditions échoue :
  (a) excès annualisé > 0 avec borne basse IC 95 % (bootstrap mensuel, blocs 3) > 0 ;
  (b) excès > 0 avec coûts × 2 ; (c) excès > 0 avec la source de frais R3.1 ;
  (d) excès > 0 sur la moitié la plus récente (2025-12-01 → 2026-10-31) ; (e) drawdown max < 15 %.
  (D) frais × 0,5 ; nombre de jours où un short à levier 3 non rééquilibré intrajournalier aurait été liquidé.
- **R3.3 (E) Généralité.** Univers figé : pools DefiLlama `raydium-amm` « Standard - 0.25% » de TVL ≥ 250 000 $
  au 2026-11-26 (liste en cache, sha256 au manifeste). Pour chacun : adresse via l'API Raydium (paire de mints,
  AMM v4 0,25 %, plus forte liquidité), clôtures quotidiennes GeckoTerminal (σ), frais DefiLlama × 0,88.
  Avantage moyen quotidien = frais − r_j²/8 sur 2025-01-23 → 2026-10-31 (ou depuis la première date disponible,
  ≥ 60 jours exigés). **Élimination de la thèse « LP couverte en général »** si la médiane inter-pools n'est pas > 0
  avec IC 95 % bootstrap > 0 : la piste se réduirait alors au seul SOL-USDC (fragilité déclarée).
  Biais du survivant déclaré (pools vivants aujourd'hui).
- **R3.4 (D) Concentration.** Part de l'avantage due aux 5 % de jours aux frais les plus élevés ; avantage sans ces jours.

## R2 — Momentum 30 j long/plat BTC/ETH/SOL (S2-F1), période OOS 2023-01 → 2026-10

- **R2.1 (E) Placebo.** 2 000 stratégies long/plat aléatoires par actif, conservant **exactement** la suite des
  durées des segments investis et non investis de F1 (permutation aléatoire de l'ordre des segments, même
  exposition, même nombre de transactions, mêmes coûts). p = part des placebos dont le Sharpe OOS du
  portefeuille ≥ celui de F1. Élimination si p > 0,05.
- **R2.2 (E) Délai d'exécution.** Décision à la clôture quotidienne, exécution à la clôture de l'heure suivante
  (01:00Z). Élimination si le Sharpe OOS net < 0,5.
- **R2.3 (E) Retrait d'un actif.** Élimination si le Sharpe OOS d'un portefeuille à deux actifs est ≤ 0.
- **R2.4 (D)** Résultats par année civile. **R2.5 (D, post hoc)** voisinage L ∈ {20, 25, 30, 35, 40, 50, 60}.

## R1 — Contre-vérification du rejet du carry

- **R1.1 (E pour une réouverture)** C0 Binance avec marge de portefeuille : capital 1,10 par unité de notionnel.
  Réouverture seulement si excès OOS > 0 avec borne basse IC 95 % > 0.
- **R1.2 (D, post hoc)** Carry short perp Hyperliquid / long spot Binance, par période. Une règle prospective
  P-HL1 (position permanente, BTC/ETH/SOL équipondérés, levier 3) est figée ici et ne sera jugée que sur les
  données postérieures au 2026-11-27.

## R4 — Contre-vérification du rejet du market making sur carnets de perp DEX

- **R4.1 (E pour une réouverture)** Photographie prospective de 25 min sur Hyperliquid : carnets (5 s) et
  transactions récentes de WIF, JUP, POPCAT, kPEPE. Markouts 10 s et 60 s contre le mid observé ; remplissage
  optimiste (transaction au meilleur prix de notre côté) et pessimiste (transaction qui traverse ce prix) ;
  frais maker 1,5 pb. Réouverture seulement si le markout net pessimiste à 10 s est > 0 sur un actif avec
  ≥ 200 remplissages et une erreur-type permettant de l'affirmer (moyenne − 2 erreurs-types > 0).

## Décision

Deux pistes au plus pour le PAPER approfondi : celles qui survivent à tous leurs tests (E). Si aucune ne
survit, R05 le déclare. Une idée post hoc ne peut occuper une place qu'en **observation prospective**.
