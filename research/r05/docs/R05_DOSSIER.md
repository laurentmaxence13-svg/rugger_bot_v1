# R05 — Dossier de recherche n° 1 (2026-11-26)

Statut des preuves : **reproduit par test** = recalculé deux fois à l'identique depuis les données
vérifiées (empreintes sha256 identiques) ; **hypothèse** = valeur supposée, non mesurée ;
**non mesuré / non évaluable** = explicitement absent. Aucun ordre, aucun crédit Helius, aucune dépense.
Protocole figé avant toute donnée : `docs/R05_PREREGISTRATION_v1.md` (commit `fb317a5`, poussé avant
le premier téléchargement). Défauts et déviations : `docs/REGISTRE_DEVIATIONS_DEFAUTS.md`.

---

## 1. Mission et indépendance

R05 dirige un programme parallèle à RUGGER MASTER : chercher, **démontrer ou réfuter**, un avantage
économique net sur cinq directions. R05 ne touche ni `bot/`, ni les bases, ni `.env`, ni les
protocoles gelés G2-3 / N1 / livepaper ; il lit leurs enseignements. R01–R04 ne sont pas mobilisés ;
toute aide de leur part sera formulée comme une demande. Aucun processus R05 ne tourne en dehors des
sessions : la seule collecte « en direct » a duré 20 minutes, dans cette session.

## 2. Ce qui a été réellement fait aujourd'hui

| Étape | Preuve |
|---|---|
| Accès aux données publiques gratuites ouvert (environnement personnel approuvé) ; refus géographiques 451/403 de `api.binance.com`, `fapi.binance.com`, `api.bybit.com` **non contournés** | R05-D1, R05-D2 |
| Pré-enregistrement des 5 directions, commité et poussé **avant** tout téléchargement | `fb317a5` |
| 784 fichiers de l'archive publique Binance demandés : **772 vérifiés contre le CHECKSUM officiel**, 12 absents (2019) consignés | `results/DATA_MANIFEST_binance.json` |
| Funding Hyperliquid (≈ 30 000 points/actif depuis 2023-05), DefiLlama (Aave v3 USDC, pools SOL-USDC), Raydium (60 pools), GeckoTerminal (60 séries), photographie live 20 min (240 tours, 7 920 requêtes, 0 échec) | manifestes + `evidence/r05_snapshots_20261126.tar.gz` (sha256 dans `evidence/SHA256SUMS.txt`) |
| Noyau `r05lab` (données, backtest à décalage testé, statistiques, LP/LVR, markouts) : **20 tests réussis**, sans réseau | `tests/test_core.py` |
| 4 familles d'expériences exécutées, **deux fois, empreintes identiques** | `results/*.json` |
| 4 défauts trouvés par nos propres contrôles et corrigés, dont un qui **abaissait** notre seul résultat positif | R05-D3 à D6 |

## 3. Résultats par direction

### S2 — Trading systématique BTC/ETH/SOL (Binance spot 1 h, 2018-01 → 2026-10)

Découpage : CONCEPTION 2018–2022, VALIDATION 2023–2024, TEST 2025-01 → 2026-10. 24 configurations,
toutes comptées. Coûts de base 12 pb/côté (spot), 7 pb + funding (perp). Détail : `results/S2_systematic.md`.

| Famille (paramètre choisi sur CONCEPTION) | Sharpe VALID | Sharpe TEST | Sharpe OOS net [IC 95 %] | Point mort (pb/côté) | Verdict |
|---|---|---|---|---|---|
| F1 momentum 30 j, long/plat | 1,82 | 0,43 | 1,24 [0,09 ; 2,30] | 183 | **NON CONCLUANTE** |
| F2 rupture Donchian 20 j, long/plat | 1,35 | −0,32 | 0,72 [−0,42 ; 1,81] | 219 | REJETÉE |
| F3 retour à la moyenne 24 h | 0,20 | 0,51 | 0,37 [−0,41 ; 1,33] | 28 | REJETÉE |
| F4 déséquilibre de flux 24 h | −0,66 | −1,14 | −0,88 [−2,13 ; 0,21] | 6 | REJETÉE |
| Détention passive (référence) | 2,01 | −0,04 | 1,03 | — | — |

- **Démontré (reproduit)** : aucune famille ne satisfait les quatre critères. F1 est la meilleure :
  OOS +52 %/an, drawdown 40 % contre 64 % en détention passive, robuste aux coûts ×2 (Sharpe 1,15),
  mais **alpha non significatif** (+18,8 %/an, t = 1,39, borne 5 % à −4,1 %) et DSR 0,68 < 0,90
  (le Sharpe annualisé qu'atteint par hasard le meilleur de 24 essais nuls est ≈ 1,01).
- F1 est **fragile** : en TEST, les horizons 90 j et 180 j sont négatifs (−0,07 et −0,29) ; seul 30 j
  tient. Par régime (descriptif) : Sharpe 2,22 en tendance haussière, −0,23 en tendance baissière.
  L'apport est surtout une **réduction du drawdown**, pas un alpha démontré.
- F4 contient un signal brut (Sharpe OOS brut 0,97), mais son point mort est de 6 pb/côté : il ne paie pas
  des frais retail. Les variantes long/court perp sont toutes rejetées.
- **Ne permet pas de conclure** : la période TEST n'est pas vierge pour le chercheur (voir §7) ; échantillon de
  3 actifs fortement corrélés.

### S1 — Arbitrage, carry et funding

Détail : `results/S1_carry.md`, `results/S4_S1C_micro.md`.

**S1-A carry long spot / short perp (Binance), sur capital (levier 3), contre le prêt USDC Aave v3 :**

| Funding moyen annualisé | 2020–2022 | 2023–2024 | 2025-01 → 2026-10 |
|---|---|---|---|
| BTC | 17,3 % | 9,9 % | 4,2 % |
| ETH | 21,9 % | 10,6 % | 3,6 % |
| SOL | −5,8 % | 7,5 % | −0,1 % |

- Carry permanent (C0) : 7,2 %/an en 2023-24 (taux de référence 5,4 %), 1,9 %/an en 2025-26 (référence 3,8 %).
  **Excès hors échantillon −0,1 %/an** [IC mensuel −0,13 % ; +0,14 %]. → **REJETÉE** : le carry des majeures
  rapporte désormais l'équivalent d'un prêt de stablecoin, avec en plus un risque de contrepartie et d'exécution.
- Carry conditionnel (seuil 5 % choisi sur CONCEPTION) : excès OOS −3,1 %/an → REJETÉE.
- Risques mesurés : basis SOL jusqu'à −16,9 % (pire funding 30 j : −36 %, épisode 2022) ; jours où la hausse
  intrajournalière aurait liquidé un short non rééquilibré au levier 5 : BTC 1, ETH 3, SOL 11 (2023-2026).
- **S1-B écart Hyperliquid − Binance** : funding HL ≈ 13,9 %/an contre 7,2 % (BTC, 2023-05 → 2026-10),
  écart moyen ≈ 6,7–7,1 %/an ; la règle conditionnelle pré-enregistrée perd (excès OOS −5,9 %/an, 67 entrées) → **REJETÉE**.
  *Observation post hoc, non testée* : une position permanente sur l'écart pourrait capter ≈ 6,7 %/an avant
  basis et coûts ; elle doit être **pré-enregistrée et testée sur des données postérieures au 2026-11-26** avant
  toute conclusion (risque de contrepartie Hyperliquid et transferts de marge non mesurés).
- **S1-C arbitrage spatial** (photographie 20 min, OKX/Coinbase/Kraken) : écart brut max 6,4 pb ; **jamais
  positif net des frais**, même aux meilleurs paliers publics (meilleur net −0,30 pb). DEX–CEX : Jupiter cote
  SOL→USDC jusqu'à 10 SOL au mid CEX (médiane −0,2 à 0,0 pb), achat de 100 à 100 000 USDC à +1,2 à +2,9 pb :
  pas d'arbitrage, mais une exécution DEX très bon marché sur SOL-USDC. → **ABANDON** de l'arbitrage spatial.

### S3 — Fourniture de liquidité (frais vs LVR)

Détail : `results/S3_lp.md`. Mesure : avantage couvert = frais LP − LVR, LVR = σ²/8 (plage complète,
Milionis et al. 2022) — une borne prudente (les frais réduisent l'arbitrage réel).

- **S3-B (pré-enregistré) — Raydium AMM v4 SOL-USDC 0,25 %, plage complète, 2025-01-23 → 2026-10-31 (647 j)** :
  frais LP 28,2 %/an en moyenne (médiane 15,9 %), LVR 6,9 %/an ; **avantage moyen +21,4 %/an [IC 95 % 12,1 ; 32,8]**,
  médian +8,9 %/an, positif 95 % des jours. → **H3b SOUTENUE**, après correction R05-D5 (DefiLlama comptait la
  totalité des frais ; recoupement GeckoTerminal : rapport 0,88, corrélation 1,00).
- Ordre de grandeur après couverture (**hypothèses**, non mesuré) : capital 1,17 par unité de LP (marge du short
  à levier 3), rééquilibrage quotidien ≈ 2 %/an de frais perp, taux de référence ≈ 4,6 % → excès ≈ +11 %/an sur la
  moyenne, ≈ +1 %/an sur la médiane. **L'avantage dépend des journées de fort volume.**
- Instantané actuel du même pool : rotation 21 %/j contre un point mort de 7 %/j.
- **S3-A coupe transversale (60 pools)** : AMM v4 — avantage médian 0,0 %/an, 50 % positifs ; H3a **NON CONCLUANTE**.
  Pools memecoins : σ de 2,5 à 10 %/j, point mort de rotation de 4 à 57 %/j (ex. WSOL-pippin : 59,6 % contre
  56,7 %, avantage +2,3 %/an ; WSOL-USELESS CPMM −8,5 %/an). Pools concentrés : **non évaluables** sans
  liquidité active (CF* = 8 à 12 sur SOL-USDC).
- **Enseignement pour N1 (sans modifier son protocole)** : le seuil de R01 (`dossier_15`, σ²/8) est confirmé
  par nos données. Les pools où la LP couvre la LVR ont **une faible volatilité par rapport à leur rotation**
  (SOL-USDC). Les pools CPMM memecoins, très volatils, en sont structurellement loin, avant même les coûts fixes.

### S4 — Market making

Détail : `results/S4_S1C_micro.md`.

- **S4-A markouts sur transactions réelles Binance** (3 jours tirés au sort, graine pré-enregistrée), en pb :

| Actif | Demi-spread médian | Markout 10 s, remplissage optimiste | Markout 10 s, pessimiste | Net VIP0 (maker 10 pb) |
|---|---|---|---|---|
| BTCUSDT | 0,08 | −0,92 | −1,29 | −11,3 |
| SOLUSDT | 0,31 | −0,66 | −1,56 | −11,6 |
| WIFUSDT | 4,39 | +0,81 | −5,52 | −15,5 |

- La sélection adverse dépasse le spread **avant tout frais**, même en tête de file : le frais maker de point
  mort est négatif (il faudrait des remises). → **ABANDON** du MM sur CEX majeures avec nos moyens.
- Spreads affichés (S4-B) : sur 23 carnets, le demi-spread est inférieur au frais maker de base partout, sauf
  WIF sur Hyperliquid (+0,75 pb, avant une sélection adverse mesurée à −5,5 pb sur Binance).

### S5 — Laboratoire

Infrastructure, sans rendement attribué. Valeur démontrée aujourd'hui : un protocole figé avant les
données, une provenance vérifiée, une exécution déterministe, et **quatre défauts détectés avant
conclusion**. L'un d'eux (R05-D5) aurait surévalué de 13,6 % les frais du seul résultat positif.
Coût : 0 €.

## 4. Tableau comparatif (indicateurs obligatoires)

| Dimension | S1 carry/funding | S2 systématique | S3 LP | S4 MM | S5 labo |
|---|---|---|---|---|---|
| Performance nette | C0 : excès −0,1 %/an OOS | F1 : +52 %/an OOS, alpha +18,8 % non significatif | SOL-USDC : avantage +21,4 %/an (moy.), +8,9 % (méd.), avant couverture | négative avant frais | sans objet |
| Risque | DD 0,9 % ; liquidations au levier 5 ; basis −16,9 % (SOL) | DD 40 % (passif 64 %) ; CVaR 95 % −4,5 %/j | perte d'impermanence couverte par hypothèse ; risque de contrat NON MESURÉ | inventaire NON MESURÉ | — |
| Exécution | 4 jambes, 38 pb aller-retour (hyp.) | point mort 183 pb/côté | DEX SOL-USDC 0 à 3 pb ; coût de couverture ≈ 2 %/an (hyp.) | markout −1,3 à −5,5 pb | — |
| Statistiques | 46 mois OOS | 1 400 j OOS, 24 essais, DSR 0,68 | 647 j, un seul pool | 3 j × 3 actifs ; 20 min de carnets | — |
| Robustesse | rejet stable aux seuils et aux coûts ×2 | fragile aux horizons en TEST | dépend des pics de volume ; une seule source principale | rejet même en remplissage optimiste | 2 exécutions identiques |
| Exploitation | comptes CEX + perp, marge | spot simple, quotidien | LP Solana + couverture perp | colocation, paliers VIP | 0 € |
| Faisabilité | élevée | élevée | moyenne (deux plateformes, rééquilibrage) | faible | élevée |
| Durabilité | avantage **disparu** (funding 17 → 4 %) | dépend des régimes de tendance | dépend du routage des flux (Jupiter) : NON MESURÉ | concurrence HFT | — |
| **Recommandation** | **surveiller** (C0) ; S1-B′ à pré-enregistrer ; **abandonner** l'arbitrage spatial | **surveiller** (prospectif gelé) | **approfondir** | **abandonner** (CEX majeures) | **poursuivre** |
| Confiance dans l'évaluation | élevée (rejet) | moyenne | **faible à moyenne** | élevée (rejet) | — |

## 5. Avis de R05 et décision proposée

1. **Aucune direction ne démontre aujourd'hui un avantage net exploitable.** Je ne désigne pas de gagnant.
2. **Le seul candidat est la LP couverte, en plage complète, sur une paire majeure à forte rotation (SOL-USDC
   AMM v4).** C'est la seule hypothèse pré-enregistrée soutenue. Elle repose sur un pool, 21 mois, une source
   principale déjà corrigée une fois, et une couverture non modélisée. Elle mérite l'effort de développement
   prioritaire, sous forme de **vérification**, pas de déploiement.
3. **Le trend following quotidien (F1)** réduit les drawdowns sans alpha prouvé. Il est peu coûteux à suivre en
   prospectif : il suffit de geler la règle et de la juger plus tard sur l'archive publique, sans robot.
4. **Le carry, l'arbitrage spatial et le market making CEX** n'offrent pas d'avantage avec nos moyens. Pour le
   carry, la cause est mesurée : la prime a convergé vers le taux sans risque crypto.
5. **Pour RUGGER MASTER** : le coût d'exécution DEX sur SOL-USDC (0 à 3 pb) est sans commune mesure avec
   l'aller-retour de ≈ 0,98 % des petits pools CPMM. Cela rejoint la décomposition W1 de R01/R02 : la barrière
   est d'abord structurelle (coûts, volatilité), avant d'être une question de signal. Information transmise
   pour avis, sans demande d'action.

**Décision proposée** : si la voie actuelle n'aboutit pas, investir d'abord dans **S3 (LP couverte sur
paires majeures)**, adossée au **laboratoire S5**, avec **S2-F1** en suivi prospectif à coût nul.

## 6. Plan de recherche et calendrier

| Quand | Expérience | Critère de validation (fixé avant données) | Ressources |
|---|---|---|---|
| 27/11 → 04/12 | **S3-V1** : reconstitution indépendante des frais LP 2025-2026 du pool AMM v4 à partir des volumes GeckoTerminal paginés | écart < 5 % avec DefiLlama corrigé, sinon la source la plus prudente fait foi | gratuit |
| 27/11 → 04/12 | **S3-H** : backtest de la LP **couverte** (short perp SOL, funding réel de l'archive, rééquilibrage 1 j et 4 h, capital complet) | excès sur Aave > 0 avec borne basse IC 95 % > 0 ; positif à coûts ×2 ; pré-enregistré avant exécution | gratuit |
| 27/11 → 04/12 | **S3-X** : extension pré-enregistrée à d'autres paires majeures et corrélées (ETH-USDC, JitoSOL-SOL, mSOL-SOL…), univers fixé avant lecture | même critère, correction de Holm | gratuit |
| dès le 27/11 | **Registre prospectif v1 gelé** : F1 (30 j long/plat), C0, LP couverte SOL-USDC ; jugé sur les seules données postérieures au gel | 1ʳᵉ lecture le 28/02/2027, décision le 31/05/2027 | gratuit, sans robot |
| décembre | **S1-B′** (écart de funding permanent HL−Binance), pré-enregistré, testé uniquement sur les données postérieures au 26/11 | excès > 0, IC > 0, transferts de marge chiffrés | gratuit |
| sur autorisation | vérification on-chain des frais réellement versés aux LP (états du pool) | coût en crédits chiffré avant demande ; alternative gratuite d'abord | Helius : **demande au propriétaire**, aucun crédit consommé sans accord |
| sur autorisation | PAPER prospectif intrajournalier (si nécessaire seulement) | règles gelées avant observation | hôte durable : demande au propriétaire |

## 7. Risques qui peuvent fausser nos conclusions

1. **Contamination du chercheur** : mes connaissances couvrent à peu près le marché jusqu'à mi-2026. Le TEST
   2025-2026 n'est donc pas aveugle. **Seul remède : le prospectif gelé.**
2. **Tests multiples** : 24 essais en S2 et 6 règles en S1. Corrigés par DSR et par seuils fixés d'avance.
   Toute nouvelle variante augmente N.
3. **Méthode des sources** : DefiLlama a déjà dû être corrigé (D5). L'avantage S3 repose encore sur une source
   agrégée.
4. **Biais du survivant** en S3-A : seuls les pools qui existent aujourd'hui sont observés.
5. **Échantillons courts** : 20 min de carnets, 3 jours de transactions, un pool pour S3-B.
6. **Frais supposés** : grilles publiques de base non revérifiées en ligne ; les paliers réels peuvent différer.
7. **Exécution non modélisée** : latence, transactions Solana échouées, MEV sur la couverture et les
   rééquilibrages.
8. **Risques non mesurables par nos données** : contrepartie (type FTX), contrat intelligent, dépeg du stablecoin.
9. **Changement de régime** : le funding s'est déjà comprimé ; le volume du pool AMM v4 peut se déplacer si le
   routage change.
10. **Devise et taille** : les résultats sont en USD ; le capital évoqué est en euros (1 000 €) ou en SOL. À
    petite taille, les coûts fixes (retraits, transactions) pèsent davantage. Non mesuré ici.

## 8. Reproduire

```bash
cd research/r05 && export PYTHONDONTWRITEBYTECODE=1
python -m pytest -q -p no:cacheprovider tests                     # 20 tests, sans réseau
python -m experiments.fetch_binance && python -m experiments.fetch_public_json
python -m experiments.s1_carry && python -m experiments.s2_systematic
python -m experiments.s3_lp && python -m experiments.s4_micro
```

Les instantanés non re-téléchargeables (carnets live, Raydium, GeckoTerminal, DefiLlama) sont archivés
dans `evidence/r05_snapshots_20261126.tar.gz`. Pour rejouer S3/S4 à l'identique, il faut les extraire dans `data/`.
