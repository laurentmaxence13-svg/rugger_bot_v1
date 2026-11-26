# R05 — Protocoles PAPER prospectifs v1 (figés le 2026-11-26, avant toute donnée de la fenêtre)

PAPER ONLY : aucun ordre, aucune clé, aucun portefeuille, aucun dépôt. Les deux protocoles se jugent
**uniquement sur des données publiques postérieures au 2026-11-27 00:00Z**, avec le code figé
`experiments/prospective_eval.py` (empreinte au commit de ce texte). **Aucun robot ne tourne en continu** :
l'évaluation est lancée aux dates de lecture par une session R05 ou par le propriétaire. Une vérification de
câblage sur une fenêtre passée a été faite ; elle n'est pas une preuve et n'est pas publiée comme résultat.

## PAPER-1 — LP couverte, plage complète, Raydium AMM v4 SOL-USDC 0,25 % (priorité 1)

**Question** : la LP couverte produit-elle, en prospectif, un excès sur le prêt USDC après tous les coûts ?

| Élément | Règle figée |
|---|---|
| Fenêtre | 2026-11-27 → 2027-05-31 ; lectures 2027-01-31 (descriptive), 2027-02-28 (contrôle d'arrêt), décision 2027-05-31 |
| Position simulée | LP V = capital / 1,1667 dans le pool `58oQCh…YQo2` ; short perp SOLUSDT = V/(2P) ; rééquilibrage du short **et** du capital chaque jour à 00:00Z ; levier 3 |
| Coûts | échange 3 pb sur la moitié des montants déplacés, transfert 2 pb, perp 5 + 2 pb ; entrée et sortie comprises ; funding réel |
| Frais LP | DefiLlama (pool `12edc6f3`) × 0,88 ; recoupés mensuellement avec les volumes quotidiens GeckoTerminal (récupérer avant 180 jours) |
| Référence | Aave v3 USDC (DefiLlama) |
| Succès (2027-05-31) | (1) excès > 0 avec borne basse IC 90 % > 0 (bootstrap par blocs quotidien) ; (2) écart GeckoTerminal/DefiLlama < 20 % ; (3) aucune liquidation ; (4) excès > 0 à coûts × 2 ; (5) si la mesure directe est autorisée, frais mesurés par √(x·y)/offre LP à ± 20 % des frais DefiLlama |
| Arrêt (dès le 2027-02-28) | excès cumulé < 0 **et** frais/LVR < 1,5 sur la fenêtre ; ou 60 jours consécutifs où les frais < LVR + 2 %/an ; ou écart de sources > 30 % ; ou incident de sécurité Raydium |
| Ce que le PAPER ne montrera pas | exécution réelle des dépôts (MEV), risque de contrat, délais de transfert réels, accès du propriétaire à une plateforme de couverture |

**Questions au propriétaire, sans blocage** : (a) quelle plateforme de couverture vous est réellement accessible
(Binance Futures depuis la France, Hyperliquid, autre) ? (b) acceptez-vous un collecteur horaire gratuit
(GitHub Actions ou votre PC) pour mesurer directement √(x·y)/offre LP ? Sans cela, PAPER-1 reste jugeable
à partir des sources publiques.

## PAPER-2 — Momentum 30 j long/plat BTC/ETH/SOL (priorité 2, preuve plus faible)

**Question** : la règle réduit-elle le drawdown sans sacrifier le rendement, hors de toute période connue du
chercheur ?

| Élément | Règle figée |
|---|---|
| Fenêtre | 2026-11-27 → 2027-11-30 ; lecture à 6 mois (2027-05-31), décision à 12 mois |
| Règle | signal quotidien UTC : rendement 30 j > 0 → investi, sinon USDT ; exécution à la clôture de la barre 00:00Z (délai 1 h) ; 1/3 par actif ; 12 pb par côté |
| Référence | détention passive équipondérée |
| Succès (12 mois) | Sharpe net > 0 **et** (rendement ≥ passif − 5 points **ou** drawdown max ≤ 0,6 × celui du passif) |
| Arrêt (6 mois) | drawdown de F1 > drawdown du passif, ou rendement inférieur de plus de 20 points dans un marché haussier |
| Limite déclarée | 12 mois ne peuvent pas prouver un alpha ; ils peuvent réfuter la promesse « drawdown réduit à rendement comparable » |

## Observations prospectives sans place PAPER

- **P-HL1** : carry short perp Hyperliquid / long spot Binance, BTC/ETH/SOL, levier 3 (idée post hoc).
- **C0** : carry Binance permanent (réouverture si le funding moyen 90 j > taux de référence + 10 %/an).
- **S1-B′** : écart de funding permanent Hyperliquid − Binance.
Toutes se jugent avec les mêmes sources, sur la même fenêtre, sans infrastructure.
