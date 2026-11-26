# R05 — Pré-enregistrement v1 (figé avant toute lecture de données de rendement)

Rédigé le 2026-11-26 ≈ 13:35Z, sur la base `66c6c2e` du dépôt. Aucune série de prix, de
funding, de volume ou de carnet n'a été lue avant le commit de ce texte. Seule
l'**existence** de fichiers a été vérifiée (codes HTTP, sans contenu).

## 0. Déclaration de connaissance préalable (biais du chercheur)

R05 n'est pas un observateur aveugle :
- la littérature publiée (momentum des séries temporelles, effet « carry » du funding,
  LVR des AMM, économie du market making) est connue et a orienté le choix des familles ;
- les connaissances générales de R05 sur l'évolution des marchés crypto couvrent grosso modo
  jusqu'au milieu de 2026. La période de test 2025-01 → 2026-10 n'est donc **pas
  parfaitement vierge** pour le chercheur (direction générale des prix), même si aucun
  résultat de stratégie n'y a été calculé.
- **Conséquence fixée d'avance** : un résultat historique positif ne vaut jamais admission
  définitive ; il ouvre au mieux une expérience PAPER **prospective** dont les règles sont
  figées avant observation (seul test réellement hors échantillon).

## 1. Règles communes

- Décision au temps t avec données ≤ t uniquement ; exécution au prix de clôture de la barre t
  et rendement gagné sur la barre t+1 (décalage d'une barre, testé).
- Coûts appliqués sur chaque variation de position (|Δposition| × coût par côté).
- Barèmes de frais = **HYPOTHÈSES** issues des grilles publiques de base (niveau VIP0 / retail),
  à revérifier en ligne avant toute expérience PAPER : Binance spot 10 pb ; Binance USDⓈ-M
  perp 2 pb maker / 5 pb taker ; OKX spot 8/10 pb, perp 2/5 pb ; Hyperliquid perp 1,5/4,5 pb ;
  Kraken Pro 25/40 pb ; Coinbase Advanced 60/120 pb (palier d'entrée) ; Deribit futures 0/5 pb ;
  Raydium CPMM 0,25 % (84 % aux LP), AMM v4 0,25 % (0,22 % aux LP), CLMM selon palier.
- Glissement de base : 2 pb par côté sur BTC/ETH/SOL spot/perp (hypothèse ; stress ×2, ×3).
- Statistiques : Sharpe annualisé (taux sans risque 0 pour S2, rendement USDC de prêt pour S1),
  IC 95 % par bootstrap stationnaire par blocs (blocs moyens de 20 jours, 2 000 tirages,
  graine 20261126), Probabilistic Sharpe Ratio (PSR) et Deflated Sharpe Ratio (DSR,
  Bailey & López de Prado) avec N = nombre total de configurations essayées dans la famille
  d'expériences, drawdown maximal, CVaR 95 % journalière, rotation, coût de point mort.
- Tout essai compte : chaque configuration évaluée est inscrite dans `results/` et dans N.

## 2. S2 — Trading systématique BTC / ETH / SOL (expérience S2-A)

**Données** : archive publique `data.binance.vision`, klines spot 1 h BTCUSDT, ETHUSDT
(depuis 2018-01), SOLUSDT (depuis 2020-09), jusqu'à 2026-10 inclus ; agrégation causale en
4 h et 1 j (UTC). Colonne « taker buy base volume » utilisée pour le flux.
**Découpage** : CONCEPTION 2018-01-01 → 2022-12-31 ; VALIDATION 2023-01-01 → 2024-12-31 ;
TEST 2025-01-01 → 2026-10-31. Sélection uniquement sur CONCEPTION.

**Familles et grilles (≤ 3 valeurs, une valeur commune aux 3 actifs)** :

| Code | Famille | Horizon | Règle | Grille |
|---|---|---|---|---|
| F1 | Momentum série temporelle | 1 j | position = signe du rendement des L derniers jours | L ∈ {30, 90, 180} |
| F2 | Rupture de volatilité (Donchian) | 1 j | entrée si clôture > plus haut des N jours précédents ; sortie si clôture < plus bas des N/2 jours | N ∈ {20, 55, 100} |
| F3 | Retour à la moyenne court terme | 1 h | z = rendement cumulé K h / (σ_1h × √K), σ sur 720 h passées ; position opposée au signe si \|z\| > 2, tenue K h | K ∈ {4, 12, 24} |
| F4 | Déséquilibre acheteurs/vendeurs | 1 h | I = (2·taker_buy − volume)/volume sur K h ; position = signe(I) si \|I\| > quantile 80 % de \|I\| sur les 720 h passées ; tenue 1 h | K ∈ {1, 4, 24} |

Variantes : **long/plat spot** (primaire, coûts spot 10 + 2 pb) et **long/court perp**
(secondaire, 5 + 2 pb, funding Binance payé/reçu quand l'historique existe). Taille : 1× le
capital alloué à l'actif quand en position. Portefeuille : 1/3 par actif (BTC, ETH, SOL),
rendements journaliers. Référence : détention passive équipondérée.
Régimes (descriptif, étiquettes ex post) : volatilité réalisée 30 j au-dessus/au-dessous de sa
médiane ; tendance 180 j haussière/baissière.

**Critères (sur le portefeuille, variante primaire, coûts de base)** :
1. Sharpe net VALIDATION > 0,5 **et** Sharpe net TEST > 0.
2. Sur VALIDATION+TEST : PSR(SR > 0) ≥ 0,95 **et** DSR ≥ 0,90 (N = 4 familles × 3 × 2 = 24).
3. Sharpe net hors échantillon > 0 avec coûts ×2.
4. Alpha journalier annualisé contre la détention passive > 0, borne basse IC 90 % > 0.

Verdict : REJETÉE si (1) ou (3) échoue ; NON CONCLUANTE si (1) et (3) passent mais (2) ou (4)
échoue ; CANDIDATE PAPER si tout passe.

## 3. S1 — Arbitrage, carry et funding

### S1-A Carry « cash-and-carry » (long spot, short perp), Binance
**Données** : funding USDⓈ-M (archive mensuelle), klines 1 h spot et perp, BTC/ETH/SOL, depuis
le début de l'archive de funding. Taux de référence : rendement de prêt USDC (DefiLlama, Aave v3
Ethereum) quand disponible, sinon hypothèse déclarée.
**Règles** : C0 position permanente ; C1 position si funding moyen des 7 jours passés,
annualisé, > H, sinon à plat, H ∈ {5 %, 10 %, 20 %} choisi sur CONCEPTION.
**Coûts** : 4 jambes par aller-retour (spot 10 + 2 pb, perp 5 + 2 pb) + variation du basis
perp−spot entre entrée et sortie. Capital = notionnel spot + marge perp (levier 3, donc 1,333 par
unité de notionnel). Liquidation : nombre d'épisodes où le mouvement défavorable maximal (hauts
1 h) dépasse le seuil de liquidation à levier 2, 3, 5 sans rééquilibrage intrajournalier.
**Découpage** : CONCEPTION → 2022-12-31 ; VALIDATION 2023-2024 ; TEST 2025-01 → 2026-10.
**Critères** : rendement net annualisé sur capital **au-dessus du taux de référence** > 0 sur
VALIDATION+TEST, borne basse IC 95 % (bootstrap mensuel) > 0 ; positif avec coûts ×2 ;
drawdown max < 10 % du capital ; zéro liquidation au levier retenu avec rééquilibrage quotidien.

### S1-B Écart de funding inter-plateformes (Hyperliquid vs Binance)
Long perp sur la plateforme au funding le plus bas, short sur la plus haute, si l'écart moyen des
3 jours passés annualisé > H ∈ {10 %, 20 %, 40 %} ; coûts 4 jambes perp (HL 4,5 + 2 pb,
Binance 5 + 2 pb) ; données HL `fundingHistory` (depuis l'ouverture) ; découpage CONCEPTION
→ 2024-06-30, VALIDATION 2024-07 → 2025-06, TEST 2025-07 → 2026-10 ; mêmes critères que S1-A,
plus un risque de transfert de marge entre plateformes déclaré NON MESURÉ.

### S1-C Arbitrage spatial instantané (CEX–CEX, DEX–CEX) — photographie prospective
Échantillonnage séquentiel ≈ toutes les 5 s pendant 20 min des meilleurs prix et de la
profondeur : OKX, Coinbase, Kraken (BTC, ETH, SOL ; conversion USDT/USD et USDC/USD par les
paires observées) ; devis Jupiter SOL↔USDC pour 1, 10, 100 SOL. Mesure : écart exécutable
(bid_A − ask_B)/mid, net des frais taker des deux plateformes. Critère : fraction des
instantanés à écart net > 0 et taille exécutable correspondante. Limite déclarée : instantanés
non simultanés (latence de requête), échantillon très court → **descriptif uniquement**.

## 4. S3 — Fourniture de liquidité

### S3-A Coupe transversale Raydium (instantané)
Univers : pools Raydium (API publique v3), types Standard/CPMM et Concentrated, triés par TVL,
au plus 60 pools, TVL ≥ 50 000 USD. Volatilité : clôtures journalières GeckoTerminal du pool
(30 derniers jours complets). Pour chaque pool :
frais LP / jour = (volume 7 j / 7) × taux de frais × part LP / TVL ;
LVR / jour (plage complète) = σ_j² / 8 ; avantage couvert = frais − LVR.
**Hypothèse H3a** : pour les pools Standard/CPMM, la médiane de l'avantage couvert est > 0.
Pour les pools concentrés, l'avantage n'est pas calculable exactement sans la distribution de
liquidité : rapport frais/LVR publié comme **indicateur**, pas comme preuve.
Biais déclarés : survivants (pools existants aujourd'hui), σ bruité par le rebond de prix DEX.

### S3-B Historique SOL–USDC
Séries journalières DefiLlama (TVL, APY de base = frais) des pools SOL–USDC Raydium/Orca,
σ réalisé SOLUSDT (Binance 1 h agrégé en 1 j, fenêtre 30 j causale).
**Hypothèse H3b** : moyenne sur 2023-01 → 2026-10 de (APY de base/365 − σ_j²/8) > 0 avec borne
basse IC 95 % > 0. Rapport également LP non couvert vs détention (perte d'impermanence réalisée).

## 5. S4 — Market making

### S4-A Markouts sur transactions réelles (borne optimiste)
Données : aggTrades spot Binance (archive publique), BTCUSDT, SOLUSDT, WIFUSDT, 3 dates tirées
uniformément dans [2025-01-01 ; 2026-10-31] avec la graine 20261126 (mêmes dates pour les 3).
Modèle : on cote au meilleur bid/ask, approximés par le dernier prix vendeur-initiateur
(bid) et acheteur-initiateur (ask) ; **remplissage optimiste** à chaque transaction agressive de
notre côté (tête de file) ; variante pessimiste : remplissage seulement si la transaction
traverse notre prix (fin de file). Markout = mid(t+h) − prix d'achat (symétrique à la vente),
h ∈ {1 s, 10 s, 60 s, 300 s}, en pb. Net = markout − frais maker.
**Critère** : MM jugé réaliste pour nos moyens seulement si le markout net moyen à 10 s est > 0
dans la variante pessimiste au palier de frais accessible (VIP0). Sinon : ABANDON du MM CEX
majeurs, avec le palier de frais de point mort publié.

### S4-B Spreads affichés vs frais (photographie)
Carnets OKX, Coinbase, Kraken, Hyperliquid (BTC, ETH, SOL + quelques actifs moins liquides),
spread relatif et profondeur à ±10 pb, comparés au frais maker de base de chaque plateforme.

## 6. S5 — Laboratoire
Évalué comme infrastructure : nombre d'expériences reproduites à l'identique, défauts détectés
par les contrôles automatiques, coût. **Aucun profit de trading ne lui est attribué.**

## 7. Ce que ce protocole ne permet pas
- Aucun résultat historique ne démontre une exécution réelle ; aucune expérience n'est un robot.
- Les photographies prospectives de 20 min ne mesurent ni la stabilité ni la capacité.
- Les frais sont des hypothèses de grille publique : à vérifier avant tout PAPER.
