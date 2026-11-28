# R05 — Diagnostic de faisabilité des quatre stratégies économiques

Version 1 — 2026-11-26 ≈ 14:30Z. Rédigée **avant** la batterie de réfutation
(`R05_PREREGISTRATION_v2_REFUTATION.md`). Ses recommandations sont donc conditionnelles ; la section 7
est ajoutée après les tests, sans réécrire les sections 1 à 6.

Règle appliquée : **le but n'est pas de construire cinq robots, mais de décider lesquels méritent
d'exister.** Une stratégie n'est dite rentable qu'avec un résultat net reproductible, hors échantillon,
sous des hypothèses d'exécution réalistes. Aucune ne l'est à ce jour.

Légende : **[R]** reproduit par nos tests (dossier n° 1, empreintes identiques) ; **[H]** hypothèse ;
**[NM]** non mesuré.

---

## 1. Arbitrage (spatial, DEX–CEX, carry spot/perp, écart de funding)

**D'où pourrait venir le profit, et qui paie ?**
- *Spatial / DEX–CEX* : la fragmentation des carnets. On est payé pour transporter la liquidité plus vite que
  les autres. C'est une rente de vitesse et d'inventaire pré-positionné, pas une prime de risque.
- *Carry* : les acheteurs à levier paient le funding aux vendeurs de perp. C'est une prime de liquidité et de
  risque (basis, liquidation, contrepartie), qui rémunère le capital immobilisé.
- *Écart inter-plateformes* : la segmentation des clientèles (particuliers acheteurs sur Hyperliquid) et le
  coût de déplacement des marges.

**Obstacles réels mesurés**
- Écart brut CEX–CEX : 6,4 pb au maximum en 20 min. Il n'est **jamais** net positif, même aux meilleurs paliers
  publics. **[R]**
- La prime de carry s'est effondrée : funding BTC à 17,3 %/an en 2020-22, 4,2 %/an en 2025-26. Le carry permanent
  rapporte ≈ le prêt USDC (excès OOS −0,1 %/an). **[R]**
- Les marges et les inventaires doivent être répartis sur plusieurs plateformes : capital × N, transferts lents
  et payants. **[NM]**
- Restrictions d'accès : Binance API et Bybit refusent le conteneur (451/403). Aucun contournement.

| | Disponible | Manquant |
|---|---|---|
| **Données** | archive Binance (funding, klines) vérifiée ; funding Hyperliquid ; taux Aave ; photographie de carnets | historique de carnets (payant), historique de funding OKX au-delà de 3 mois, délais et frais réels de retrait, paliers de frais effectifs |

**Coûts complets** : 4 jambes, soit ≈ 38 pb par aller-retour pour le carry **[H]**. S'y ajoutent le glissement,
le funding négatif payé, les retraits **[NM]**, le capital immobilisé (1,33 par unité de notionnel au levier 3)
et une surveillance 24 h/24.

**Risques** : basis SOL jusqu'à −16,9 %, pire funding 30 j −36 %, 11 jours de liquidation potentielle au levier 5
sur SOL **[R]**, défaillance de plateforme (type FTX) **[NM]**, dépeg du stablecoin **[NM]**.

**Conditions d'abandon** : excès OOS ≤ 0 sur le taux sans risque crypto, avec borne d'IC ≤ 0 (atteint), ou
aucun instantané net positif aux meilleurs paliers (atteint).
**Conditions de réouverture** : funding moyen 90 j > taux de référence + 10 %/an **et** test prospectif
pré-enregistré positif.
**Statut avant réfutation** : spatial **abandonné** ; carry **rejeté**, à contre-vérifier (R1.1, R1.2).

## 2. Trading algorithmique BTC / ETH / SOL

**D'où pourrait venir le profit, et qui paie ?**
- *Tendance* : sous-réaction puis mimétisme des investisseurs, et prime de convexité (la stratégie vend tard,
  rachète tard). La contrepartie, ce sont les investisseurs lents.
- *Retour à la moyenne* : rémunération de la liquidité offerte aux traders pressés.
- *Flux* : l'information contenue dans les déséquilibres d'ordres. Elle est captée en premier par les plus
  rapides.

**Obstacles réels mesurés**
- 24 configurations testées ; aucune ne passe les critères. **[R]**
- La meilleure (F1, momentum 30 j long/plat) donne un Sharpe OOS de 1,24, mais un alpha non significatif
  (t = 1,39). Elle est fragile : 90 j et 180 j sont négatifs en TEST. **[R]**
- Les signaux horaires sont détruits par les coûts : point mort de 6 pb/côté pour F4. **[R]**
- Notre période TEST n'est pas aveugle pour le chercheur.

| | Disponible | Manquant |
|---|---|---|
| **Données** | klines 1 h 2018-2026 vérifiées (77 304 barres BTC) | historique de carnets ; univers plus large d'actifs (gratuit dans l'archive, non téléchargé) |

**Coûts complets** : 10 pb + 2 pb par côté au comptant **[H]** ; funding pour les positions courtes **[R]** ;
infrastructure minimale (décision quotidienne) ; aucune dépense.

**Risques** : drawdown de 40 % même pour F1 **[R]** ; pertes répétées en marché sans tendance (Sharpe −0,23 en
tendance baissière, descriptif) **[R]** ; disparition progressive de l'effet **[NM]**.

**Conditions d'abandon** : placebo p > 0,05 ; perte de l'effet avec 1 h de délai ; dépendance à un seul actif ;
puis, en prospectif, Sharpe ≤ 0 sur 6 mois.
**Statut avant réfutation** : F1 **non concluante** ; F2–F4 **rejetées**.

## 3. Fourniture de liquidité (AMM)

**D'où pourrait venir le profit, et qui paie ?**
- Les flux non informés (particuliers, routage d'agrégateurs) paient des frais.
- Les arbitrageurs, eux, retirent la LVR : le LP est vendeur de convexité.
- Profit = frais des flux non informés − LVR − coûts. Il peut persister si le routage continue d'envoyer du
  volume à un pool à 0,25 % alors que des pools moins chers existent.

**Obstacles réels mesurés**
- LVR de SOL-USDC ≈ 6,9 %/an. **[R]**
- Sur 60 pools, l'avantage médian est nul (H3a non concluante). Les pools memecoins sont trop volatils pour leur
  rotation. **[R]**
- Les pools concentrés ne sont pas évaluables sans la liquidité active.
- La source de frais a déjà été corrigée une fois (R05-D5). **[R]**
- La couverture exige une seconde plateforme (perp). **[NM]**

| | Disponible | Manquant |
|---|---|---|
| **Données** | DefiLlama (TVL, frais), GeckoTerminal (prix, volumes), API Raydium (réserves, offre LP), Binance (prix, perp, funding) | historique on-chain des réserves (crédits Helius : autorisation requise), distribution de liquidité CLMM, exécution réelle des couvertures |

**Coûts complets** : échange d'entrée et de sortie (0 à 3 pb mesurés sur Jupiter) **[R]** ; frais Solana
(négligeables) **[H]** ; couverture perp 5 + 2 pb sur le notionnel rééquilibré **[H]** ; funding du short **[R]** ;
capital sur deux plateformes (1,17 par unité de LP) **[H]** ; surveillance.

**Risques** : faille de contrat Raydium **[NM]**, dépeg USDC **[NM]**, liquidation du short **[R]**, écart spot/perp
**[R]**, effondrement du volume si le routage change **[NM]**, MEV sur dépôts et retraits **[NM]**.

**Conditions d'abandon** : échec d'un test éliminatoire R3.1 ou R3.2 ; puis, en prospectif, excès couvert ≤ 0 sur
3 mois, ou frais < LVR + coûts pendant 60 jours consécutifs.
**Statut avant réfutation** : **seul candidat** (H3b soutenue), à faire tomber si possible.

## 4. Market making

**D'où pourrait venir le profit, et qui paie ?** Les preneurs pressés paient le spread ; les plateformes paient
des remises aux gros teneurs de marché ; le risque d'inventaire est rémunéré.

**Obstacles réels mesurés**
- Sur Binance, la sélection adverse dépasse le spread avant tout frais, même en tête de file : markout 10 s de
  −0,66 à −0,92 pb (BTC, SOL). Le frais maker de point mort est négatif. **[R]**
- Le demi-spread est inférieur au frais maker de base sur 22 carnets sur 23. **[R]**
- La priorité dans la file et la latence profitent aux HFT. **[NM]** pour nous, mais nous ne disposons
  d'aucun avantage de colocation.

| | Disponible | Manquant |
|---|---|---|
| **Données** | aggTrades (3 jours), carnets (20 min) | données de file d'attente, historique L2 (payant), mesure de notre latence |

**Coûts complets** : frais maker 1,5 à 60 pb selon la plateforme **[H]**, capital d'inventaire, colocation
(payante) **[NM]**, développement lourd.

**Risques** : inventaire pendant les sauts, flux toxiques, pannes.

**Conditions d'abandon** : markout net pessimiste ≤ 0 aux paliers accessibles (atteint sur CEX).
**Statut avant réfutation** : **abandonné** sur CEX majeures ; contre-test sur les petites capitalisations
Hyperliquid (R4.1).

## 5. Laboratoire (infrastructure transversale)

Il ne génère aucun rendement. Sa valeur se mesure aux erreurs qu'il évite : quatre défauts détectés avant toute
conclusion, dont une surestimation de 13,6 % des frais du seul candidat. Il sert les quatre stratégies ;
aucun profit ne lui est attribué.

## 6. Recommandation conditionnelle (avant réfutation)

| Rang | Piste | Condition pour entrer en PAPER approfondi |
|---|---|---|
| 1 | LP couverte, plage complète, paires majeures (S3) | survivre à R3.1 et R3.2 ; R3.3 décide si la piste est générale ou limitée à SOL-USDC |
| 2 | Momentum quotidien long/plat (S2-F1) | survivre à R2.1, R2.2 et R2.3 |
| — | Carry, arbitrage spatial, market making | aucune place, sauf réouverture par R1.1 ou R4.1 |

Si une piste échoue, **sa place n'est pas attribuée d'office** à une autre.

---

## 7. Résultats de la batterie de réfutation

Ajouté après exécution du protocole v2 (`7cdf3a9`). Les sections 1 à 6 ci-dessus n'ont pas été modifiées.
Détail : `results/R3_lp_refutation.json`, `results/R2_R1_refutation.json`, `results/R4_hl_markouts.json`.

### 7.1 LP couverte SOL-USDC (S3) — survit aux 5 tests éliminatoires, mais **n'est pas générale**

| Test | Résultat | Statut |
|---|---|---|
| R3.1 source indépendante | frais GeckoTerminal / DefiLlama corrigé = 0,95 sur 158 jours, corrélation 0,997 | passe (indépendance partielle : les deux sources lisent les mêmes swaps on-chain) |
| R3.2 (a) simulation complète, rééquilibrage 24 h | 19,3 %/an sur capital ; taux de référence 3,6 % ; **excès +14,0 %/an**, IC mensuel [+0,37 % ; +2,01 %] | passe |
| R3.2 (b) coûts × 2 | excès +13,5 %/an | passe |
| R3.2 (c) frais GeckoTerminal (depuis 2026-05-27) | excès +30,2 %/an | passe |
| R3.2 (d) moitié récente (2025-12 → 2026-10) | excès +16,0 %/an | passe |
| R3.2 (e) drawdown max | 0,7 % ; aucune liquidation | passe |
| R3.2 (D) frais × 0,5 | excès +1,9 %/an, IC mensuel [−0,29 % ; +0,65 %] | **l'excès s'annule vers −58 % de frais (interpolation linéaire) et n'est plus significatif dès −50 %** |
| R3.3 généralité (51 pools évalués sur 67) | médiane −2,3 %/an [IC −4,4 % ; +0,04 %], 39 % positifs ; SOL-USDC +41 %/an, RAY-USDC −1,7 %, memecoins autour de zéro ou négatifs | **thèse générale éliminée** |
| R3.1b mesure directe (25 min, API Raydium) | √(x·y)/offre LP : +6,25·10⁻⁶ (≈ 13 %/an), soit 1,22 × les frais impliqués par le volume GeckoTerminal à 0,22 % (1,07 × à 0,25 %) | aucun signe de surestimation des sources (indicatif) |
| R3.4 concentration | 41,6 % de l'avantage vient des 5 % de jours aux frais les plus élevés ; sans eux +13,1 %/an ; minimum glissant 90 j +4,7 %/an ; tous les trimestres positifs | robuste dans le temps |

- **Décomposition sur 21 mois, en % du capital** : frais +49,4 % ; LVR réalisée −11,8 % (prix LP −33,3 %,
  couverture +21,5 %) ; funding ≈ 0 ; coûts −1,0 %.
- Rééquilibrer plus souvent n'aide pas : 4 h donne +13,4 %, 1 h donne +12,5 %. Les coûts montent et la LVR
  attendue ne dépend pas de la fréquence.
- Un Sharpe de 7,8 n'est **pas** une qualité : il signifie que les risques restants sont absents du modèle
  (contrat, dépeg, accès à la couverture, événements extrêmes).
- **Origine du profit identifiée** : le pool hérité à 0,25 % de la paire la plus échangée de Solana reçoit un
  volume routé élevé (rotation ≈ 20 %/j) pour une volatilité modérée. Ses frais valent 4 à 8 fois sa LVR.
- **Fragilité** : un seul pool, et une dépendance au routage des agrégateurs.
- **R3.5 taille du capital (post hoc, défaut R05-D8)** : avec un transfert de capital par jour et 2 $ de frais
  fixes par transfert (hypothèse), l'excès devient **−52 %/an à 1 100 $**. Il reste +6,7 % à 10 000 $ et +13,3 % à
  100 000 $. Avec la règle à bande [50 % ; 200 %], il suffit de 12 transferts en 21 mois, sans liquidation, et
  l'excès vaut +13,0 % à 1 100 $. **À petite taille, la stratégie n'est viable qu'avec des transferts rares.**
  PAPER-1 a été amendé en ce sens **avant** le début de sa fenêtre.

### 7.2 Momentum 30 j long/plat (S2-F1) — survit aux 3 tests éliminatoires, preuve statistique faible

| Test | Résultat | Statut |
|---|---|---|
| R2.1 placebo (2 000 permutations à exposition et nombre de transactions identiques) | Sharpe 1,24 contre médiane placebo 0,76 (95ᵉ centile 1,22) ; **p = 0,042** ; ajusté de la sélection parmi 8 : ≈ 0,34 | passe à la lettre, **non significatif après ajustement** |
| R2.2 exécution 1 h plus tard | Sharpe 1,22 (contre 1,24) | passe |
| R2.3 retrait d'un actif | 1,18 / 1,24 / 1,11 | passe |
| R2.4 par année (Sharpe F1 / passif ; drawdown F1 / passif) | 2023 : 2,70 / 2,72 ; 2024 : 0,92 / 1,36 ; 2025 : 0,75 / 0,07, DD 19 % / 49 % ; 2026 (10 mois) : 0,03 / −0,20, DD 31 % / 50 % | descriptif |
| R2.5 voisinage 20–60 j (post hoc) | Sharpe OOS de 0,97 à 1,26 | pas un hasard de paramètre |

F1 apporte une **réduction des pertes en marché baissier**, au prix d'un retard en forte hausse (2024).
Ce n'est pas un alpha neutre au marché.

### 7.3 Rejets contre-vérifiés

- **R1.1 carry avec marge de portefeuille** (capital 1,10) : excès +0,86 %/an, IC mensuel [−0,09 % ; +0,27 %].
  **Rejet confirmé.**
- **R1.2 carry Hyperliquid** (post hoc, descriptif) : excès +10,5 % (2023-05 → 2024-06), +4,0 % (2024-07 → 2025-06),
  +0,9 % (2025-07 → 2026-10). Funding BTC : 21,0 % → 14,2 % → 7,6 %. La prime se comprime aussi vers le taux sans
  risque. **Aucune place PAPER** ; observation P-HL1.
- **R4.1 market making Hyperliquid** (photographie de 25 min, 300 carnets à 5 s, frais maker 1,5 pb) : markout net
  pessimiste à 10 s de WIF −9,0 pb (n 94), JUP −6,8 (n 93), POPCAT −2,5 (n 14), kPEPE −3,9 (n 96). Aucun actif
  n'est positif. Le seuil de 200 remplissages n'est jamais atteint : l'échantillon est trop court pour affirmer
  un résultat positif, mais il suffit à montrer l'absence d'avantage visible. **Rejet confirmé.**

## 8. Décision : deux pistes PAPER, aucune démontrée rentable

| Stratégie | Origine du profit | Preuve après réfutation | Décision |
|---|---|---|---|
| Fourniture de liquidité couverte, SOL-USDC AMM v4 | volume routé non informé ≫ LVR sur ce pool précis | 5/5 tests éliminatoires passés ; excès simulé +14 %/an ; **un seul pool**, la généralité est éliminée ; excès nul vers −58 % de frais, non significatif dès −50 % | **PAPER-1, priorité 1** |
| Momentum 30 j long/plat | persistance des tendances, réduction d'exposition en baisse | 3/3 tests passés ; p = 0,042 brut, ≈ 0,34 ajusté ; alpha non significatif | **PAPER-2, priorité 2, preuve faible** : il réduit les drawdowns, sans alpha prouvé |
| Carry spot/perp (Binance, Hyperliquid) | prime de levier payée par les acheteurs | rejet confirmé avec marge de portefeuille ; la prime converge vers le taux sans risque | aucune place ; observation prospective |
| Arbitrage spatial CEX–CEX / DEX–CEX | vitesse et inventaire pré-positionné | jamais net positif, même aux meilleurs paliers | abandon |
| Market making (Binance, Hyperliquid petites capitalisations) | spread payé par les preneurs | la sélection adverse dépasse le spread avant frais sur Binance (BTC, SOL, WIF) et sur Hyperliquid (4 petites capitalisations) | abandon |

**Jugement de R05.** La seule piste qui possède à la fois un mécanisme économique identifié, un résultat net
simulé intégralement et une survie aux tests adverses est la LP couverte sur **un** pool. C'est une base
mince : un seul pool, 21 mois, des sources qui lisent les mêmes swaps, et des risques non modélisés (contrat,
dépeg, accès à la couverture). Elle mérite un PAPER approfondi parce qu'il est gratuit et peut la réfuter
vite (contrôle d'arrêt au 2027-02-28). Elle ne mérite **pas encore** de développement d'exécution.
Le momentum mérite seulement un suivi léger : 12 mois ne prouveront pas un alpha, mais peuvent réfuter
la promesse « drawdown réduit ».

Si l'on exige un avantage **démontré** avant tout développement, **aucune piste ne le satisfait aujourd'hui.**

**Consultation des autres Ruggers (proposée, non envoyée, pour ne pas perturber les protocoles en cours
jusqu'au 06/12)** :
- à R01 : relecture de nos hypothèses de coût de dépôt et de retrait LP au regard de `lpcost` et `cpmmcost` ;
- à R02 : audit indépendant de `simulate_hedged_lp` et du placebo R2.1.
L'envoi se fera avec l'accord du propriétaire, après les verdicts du 06/12.

---

## 9. Mise à jour du 2026-11-28 — réplications (protocole v3, `5e96192`, addendum v3.1)

| Test | Résultat | Conséquence |
|---|---|---|
| **H2b** momentum 30 j sur 18 autres cryptomonnaies (2023-01 → 2026-10) | rendement identique au passif (11,2 %/an) ; Sharpe 0,47 contre 0,49 ; drawdown 65 % contre 77 % (seuil 0,7 non atteint) ; placebo p = 0,30 ; 9 actifs sur 18 battent le passif | **NON RÉPLIQUÉ** : la baisse de volatilité vient de l'exposition partielle, pas du timing. PAPER-2 devient une observation |
| **H3d** frais − LVR sur 9 pools plage complète natif/stable, 5 chaînes | 6/9 IC > 0 : Uniswap v2 ETH-USDC +3,2 % et ETH-USDT +3,6 % (Ethereum), Base +12,0 %, BSC +5,8 %, Raydium SOL-USDT +13,0 %, SOL-USDC +21,4 % | mécanisme **GÉNÉRAL** : les pools dominants des paires principales reçoivent plus de frais que leur LVR |
| **H3d-net** simulation couverte complète, frais fixes par chaîne | positifs avec IC > 0 : Raydium SOL-USDC +14,1 %, SOL-USDT +6,8 %, Base Uniswap v2 +5,0 % (à 10 000 $) ; Ethereum ≈ 0 (gaz, taux sans risque) ; BSC −1,0 % ; Polygon −1,8 % (3 heures de liquidation) | le profit net n'existe que là où **l'avantage est grand et les coûts fixes faibles** |
| Recoupement des sources | SOL-USDT : GeckoTerminal / DefiLlama 0,98 ; Base : **3,2** (corrélation 0,997) | Base **non évaluable** (biais de méthode d'une source) ; SOL-USDT confirmé |

**Lecture critique.**
- Le mécanisme LP est général, ce qui renforce PAPER-1.
- Mais le **profit net** reste concentré sur Solana, c'est-à-dire sur le même actif, la même chaîne et la même
  période : la diversification réelle est faible.
- Sur Ethereum, l'avantage existe (+3 %/an), mais il est rendu nul par le coût du capital et le gaz.
- Le seul candidat hors Solana (Base) est bloqué par une contradiction de sources que je ne peux pas trancher sans
  lire ses réserves on-chain.

**Portefeuille PAPER au 2026-11-28 :**

| Piste | Statut |
|---|---|
| PAPER-1 (SOL-USDC) | priorité 1, maintenue |
| PAPER-1b (SOL-USDT ; Base en observation ; Ethereum en témoin négatif) | extension |
| PAPER-2 (momentum) | observation |

Il n'y a donc **qu'une seule piste distincte** (la LP couverte sur pools dominants à coûts fixes faibles) ; je
n'en invente pas une seconde.

**Automatisation en place**, dans des sessions planifiées réelles et non en arrière-plan de celle-ci :
- collecte quotidienne D-1 à 00:37Z : instantané de 53 pools Raydium, mesure directe des frais par
  √(x·y)/offre LP ;
- lecture mensuelle le 3 à 02:17Z : évaluateur figé, chiffres commités, aucune interprétation automatique.
