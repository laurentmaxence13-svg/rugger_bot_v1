# RUGGER BOT V1 — DOSSIER DE CONTEXTE RÉCUPÉRÉ

**Établi le 22 octobre 2026** · Destination : ChatGPT / OpenAI Codex · **PAPER ONLY**

> Ce dossier rassemble le maximum d'éléments techniques retrouvés dans la bibliothèque de la conversation « Memcoins » et des échanges accessibles. **Il ne remplace pas l'audit du dernier ZIP effectivement installé sur le PC.** Les rapports, scripts historiques et patchs peuvent correspondre à des versions différentes. Les éléments « annoncés » ne sont pas des tests reproduits lors de cette récupération.

## 1. Mission et principe directeur

- Projet : `rugger_bot_v1`, robot de recherche/trading algorithmique de nouveaux memecoins sur Solana, avec détection Raydium LaunchLab.
- Objectif : identifier et **démontrer** un éventuel avantage statistique exploitable après frais, impact, slippage, latence, erreurs d'exécution et risque de rug ; aucune rentabilité présumée ni garantie.
- Ne pas transformer le projet en « usine à IA ». **Codex comme développeur principal**, avec audit/test indépendant ponctuel ; conserver un seul moteur de trading automatisé rapide, inspectable et déterministe.
- Règle absolue : **aucun ordre réel, aucune signature, aucune clé privée ni seed phrase**, aucun déploiement en argent réel durant ce programme. Préserver les barrières PAPER, ne pas connecter de portefeuille financé.
- Préserver le travail existant, faire une sauvegarde, auditer en lecture seule avant toute modification ; tests et comparaisons avant/après ; abandonner toute hypothèse infirmée.

## 2. Environnement et architecture connus (code historique retrouvé, intégration non vérifiée)

- Windows, PowerShell, Visual Studio Code, Python, environnement `.venv`, `asyncio`, `aiohttp`, SQLite ; source `bot/` et `tests/`.
- Solana RPC / WebSockets ; Helius en source RPC principale, RPC public de secours. WebSocket pour les événements de création et `getTransaction` pour enrichissement.
- Raydium LaunchLab : identification des véritables lancements via instructions vérifiées ; distinguer *création de mint*, *swap*, *création LaunchLab*, *graduation/migration*.
- Collecte de prix via DexScreener (`token-pairs/v1/solana/` et repli `latest/dex/tokens/`) et expérimentation de cotation on-chain LaunchLab.
- Analyse comportementale : ancienneté/récurrence du créateur, ventes, transferts relais, signatures de financement, bundles ou activité même slot, graphe/liaisons de wallets, concentration des holders.
- Variables de marché : prix, nombre de cotations, momentum 60 s / 300 s, liquidité en USD, volume 5 min/24 h, activité acheteurs-vendeurs 5 min, market cap, FDV, profondeur, estimation de slippage, funding LaunchLab.
- Traitement : `scanner → tx parser → candidates/creator → behavior/market/holder features → final_decision_engine → PAPER → SQLite → rapports`.
- Modules effectivement visibles dans la bibliothèque (fichiers historiques, pas nécessairement leurs dernières versions) : `bot/analyser/paper_engine.py`, `paper_trader.py`, `final_decision_engine.py`, `behavior_pipeline.py`, `multi_creator_research_engine.py`, `launchlab_onchain.py` (cité par imports), `bot/scanner/transaction_parser.py` (cité), `bot/solana/rpc.py` (cité), `bot/database/db.py` (cité), `bot/config.py` (cité).
- Orchestrateur `paper_engine` : scanner + collecte + comportement, mode d'observation sans modèle, stratégies diagnostiques `shadow_baseline` et `shadow_final`, mode `validated` protégé par admissibilité hors échantillon ; rapports de session.
- `paper_trader` stocke notamment `paper_prices`, `paper_trades`, `paper_portfolio`, `paper_decisions`, et prévoit des migrations de schéma SQLite sans effacer l'historique.
- Un `AdaptiveRPCGate` utilise un sémaphore/lock de cadence, backoff sur HTTP 429 et tentatives sur erreurs réseau. Sa fiabilité en conditions prolongées n'est pas validée ici.

## 3. Paramètres HISTORIQUES, à ne pas considérer comme configuration définitive

- Ancien capital PAPER : **10 SOL** ; allocation **10 %** du capital disponible par position. Modes de portefeuille et métriques libellés en SOL.
- À la reprise de projet dans la nouvelle conversation, souhait formulé : **1 000 € fictifs**. **Ne pas convertir/modifier silencieusement les unités** : discuter un choix unique ou un modèle multidevise testable. Les versions actuelles en ZIP doivent être examinées.
- Score historique initial voisin de **50/100** ; seuil d'entrée évoqué d'environ **45/100** dans le prompt maître. Dans un `final_decision_engine_optimized.py` antérieur (2 octobre), la fonction `decide` déclare `min_score=62.0`, `min_liquidity=1000.0` ; **la valeur effective dépend de la version et des arguments à l'appel**.
- Exemple de paramètres historiques de `paper_engine.py` (15 octobre) : `max_open=3`, `max_entries_day=20`, `max_daily_loss_pct=10.0`, `initial_capital_sol=10.0`, `position_pct=10.0`, `poll=15` s, cotation et cache RPC sous quotas.
- Le score utilise notamment bonus/pénalités créateurs, liquidité, ventes, transferts, mêmes slots, holders, momentum, qualité des prix, volume, pression acheteuse/vendeuse, slippage.
- Les seuils ont été élaborés avec ChatGPT/observations limitées ; **aucun étalonnage professionnel hors échantillon démontré**.
- Séparer **risque de rug**, **probabilité/amplitude de hausse** et **réalité d'exécution** : ce sont trois problèmes différents.

## 4. Chronologie et archives retrouvées dans la bibliothèque `/Memcoins`

### 26 septembre – 2 octobre : recherche initiale et raffinement

- Multiples itérations `creator_backtest_v6.py` jusqu'à `creator_backtest_v26.py`, diagnostics swaps créateurs `creator_swap_diagnostic_v12.py` à `v16.py`, `creator_swap_validation_v17.py`, analyse de 14 lancements, transfert relais et prix/impact.
- `multi_creator_research_engine.py` : collection et mise en cache d'historiques des créateurs ; données dans `research_creators`, `research_launches`, `research_tx_cache` ; adaptation RPC Helius 429.
- 2 octobre : fichiers historiques `paper_engine.py`, `paper_trader.py`, `behavior_pipeline.py`, `final_decision_engine.py` et variantes `_optimized.py`.

### 14–15 octobre : intégration et premières sessions

- Archives repérées : `RUGGER_CODE.zip`, `RUGGER_ACTUEL.zip`, `RUGGER_RPC_FALLBACK.zip`, `RUGGER_PARSER_FIX.zip`, `RUGGER_SQLITE_FIX.zip`, `RUGGER_BOT_FINAL_SOURCE.zip`, `RUGGER_BOT_INTEGRE_PAPER.zip`, `RUGGER_BOT_PAPER_STABLE.zip`, `RUGGER_BOT_ONCHAIN_PAPER_CORRIGE.zip`, `RUGGER_BOT_DIAGNOSTIC_ONCHAIN.zip`, `RUGGER_BOT_AUDIT_PAPER_V1.zip`, `RUGGER_BOT_SESSION_2H.zip`, `RUGGER_BOT_CALIBRATION_V2.zip`, `RUGGER_BOT_PRIX_PAPER_FIX.zip`, `RUGGER_BOT_LAUNCHLAB_FIX.zip`.
- Artefacts retrouvés : `launchlab_tx.json`, bases `rugger_bot.db` et variantes (volumes de l'ordre de 224 à 246 Mo), fichiers `paper_engine_report.json`, `paper_session_report.json`, `paper_session_report(1).json`.
- Ces volumes et noms confirment l'existence de données et de code archivés, **pas leur validité ou intégrité analysée ici**.

### 21 octobre : audit et correctifs les plus récents répertoriés

1. **20:48 UTC** `RUGGER_BOT_AUDIT_SOURCE.zip` — 3 880 961 octets ; rapport d'audit dit 298 entrées ZIP, archive intègre lors de l'audit antérieur.
2. **21:11 UTC** `AUDIT_PAPER_CORRECTIF.md` — 5 556 octets et `RUGGER_BOT_CORRECTIF_DIFF.patch` — 14 940 octets (ceux-ci sont effectivement lisibles dans la bibliothèque).
3. **21:12 UTC** `RUGGER_BOT_CORRECTIF_PAPER_P0.zip` — 29 402 octets ; correctifs annoncés de `paper_trader.py`, `paper_engine.py` et tests financiers.
4. **21:34–21:35 UTC** `TESTS_A_CORRIGER.zip` et tests Python à réexaminer.
5. **21:46 UTC** `RUGGER_BOT_CORRECTION_2_TESTS.zip` — 2 014 octets.
6. **21:52 UTC** `RUGGER_BOT_TESTS_CORRIGES_LEGER.zip` — 1 977 octets ; archive ZIP la plus récente retrouvée, **patchs de tests seulement**, pas version complète du bot.

**Important :** la séquence « base complète + correctif PAPER P0 + correctifs de tests » est l'hypothèse de reconstitution à vérifier sur le PC. Les patchs ne doivent pas être appliqués aveuglément ni dans un ordre arbitraire sur des fichiers déjà modifiés.

**Limite d'accès :** les ZIP et SQLite sont listés dans la bibliothèque, mais l'outil disponible dans cette session n'a pas autorisé leur matérialisation en octets ; ils ne sont pas encore ouverts/inspectés ici. En revanche, les rapports, patchs, fichiers `.py` et `.json` cités ont pu être lus. L'utilisateur pourra joindre son ZIP local ; on le comparera à ces artefacts.

## 5. Audit financier P0 du 21 octobre — constats documentés

Source textuelle : `/Memcoins/AUDIT_PAPER_CORRECTIF.md` et `/Memcoins/RUGGER_BOT_CORRECTIF_DIFF.patch`.

- **Bug A — limite de perte quotidienne :** ancien `entry_allowed()` additionnait `net_return` par trade et utilisait la date **d'entrée** au lieu de comparer le **P&L réalisé en SOL** des trades clôturés dans la journée UTC. Un trade de faible taille et un trade de tout le capital ne doivent pas peser identiquement.
- **Bug B — rendement et drawdown :** ancien calcul composait les rendements relatifs de chaque trade comme si chaque trade engageait 100 % du capital. Devient faux avec allocations partielles.
- **Bug C — clôtures intersessions :** les clôtures pendant une session de positions ouvertes avant celle-ci étaient ignorées.
- **Bug D — motifs de rejet :** le rapport utilisait `reasons_json`, mélangeant parfois des signaux positifs dans les motifs négatifs ; le correctif utilise `risk_flags_json`, avec comptage des rejets sans flag.
- **Bug E — compatibilité cotations / parseur :** anciens tests supposaient des triples `(liquidité, prix, paire)` ou assimilaient incorrectement certaines instructions LaunchLab à des lancements.

**Correctif rapporté :** P&L net réalisé en `pnl_sol`, tri par heure de clôture, courbe de capital basée sur P&L réalisé, signalisation des données historiques incomplètes, normalisation des cotations legacy et traitement des risk flags.

**Limites du correctif :** drawdown **réalisé uniquement**, sans pertes latentes ; capital initial SOL / journée UTC ; prix réellement négociables, slippage, migrations, concurrence SQLite, gestion des données manquantes, reprise après panne et rentabilité ne sont PAS validés.

**Tests annoncés par le rapport dans l'environnement d'audit :** avant, 45 réussis / 2 échecs / 1 ignoré ; après correctif et six nouveaux tests, **53 réussis / 1 ignoré**. Autres correctifs de fichiers tests : **47 réussis / 1 ignoré** rapportés dans un autre contexte. Ces chiffres concernent des jeux de tests ou versions différentes, ne pas les comparer comme progression automatique.

Commande de revalidation sur Windows, dans la racine du projet et sans trading réel :

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/tests
```

Une trace historique mentionnait un échec `test_paper_entry_limits` après corrections intermédiaires : **vérifier explicitement qu'il passe sur le dernier projet local**.

## 6. Rapports de session réellement consultés — résultats insuffisants

**`paper_engine_report.json` (15 octobre, ancien état) :**
- Cache Helius : **12 471 transactions** ; lancements observés : **1 416** ; cotations stockées : **573** ; **18** lancements avec cotations (couverture **1,27 %** du dénominateur des lancements observés).
- Décisions : **276**, toutes rejetées ; score moyen **0,06884** tel que présent dans le rapport (unités/échelle à vérifier).
- Positions : 0 ouvertes, 1 `shadow_final` clôturée ; indicateur `average_net_return=0.577...` et `win_rate=1.0`, **mais** `pnl_sol=0`, capital réalisé **10 → 10 SOL**, frais hypothétiques **0 bps**, validation `diagnostic_not_validated`. **Ne pas présenter ce chiffre comme +57,7 % réalisé ou une rentabilité prouvée.** Les champs sont incohérents ou de portée différente.
- Couverture d'informations marché complémentaires seulement ~8,38 % des cotations ; `fee_bps` 0 %. Donc métriques lacunaires.

**`paper_session_report.json` (session de 7 250 s) :**
- **246 décisions**, **246 rejets**, **0 entrée**, **0 clôture**, P&L **0 SOL** ; rapport ancien classe dans `rejection_reasons` des motifs positifs tels que `comportement_observe`, ce qui confirme le bug de diagnostic.

**`paper_session_report(1).json` (session de 7 287 s) :**
- **230 décisions**, **7 candidats uniques**, **229 rejets**, **1 acceptation**, **0 entrée**, **0 clôture**, P&L **0 SOL**. Les résultats ne suffisent pas à conclure sur la stratégie.

D'autres traces de session évoquent **215 analyses / 5 mints uniques / 0 position**. Garder distincts sessions, décisions et mints uniques.

## 7. Problèmes prioritaires (sans présumer qu'ils subsistent dans le ZIP actuel)

**P0 — bugs faussant directement les chiffres / protections**
- Unités des positions et du capital ; P&L réalisé et non réalisé ; frais comptés une seule fois ; drawdown et perte quotidienne.
- Déclenchement/suivi/fermeture PAPER, réalisme des prix et slippage, cas sans liquidité et sorties impossibles ; double entrée/replay ; collisions SQLite ; cohérence des positions après redémarrage.
- Intégrité des métriques et identification des transactions manquantes.

**P1 — qualité de la collecte / validation**
- Erreurs Helius **429**, quotas, repli RPC ; déconnexions WebSocket, resubscribe et événements perdus ; taux de détection des LaunchLab uniques.
- Distinction *funding de bonding curve* vs *liquidité DEX* ; cotations indisponibles ou périmées ; horodatages disponibles avant décision ; synchronisation scanner/DB.
- Rejets trop nombreux/itérations répétées sur mêmes mints ; explication de l'acceptation sans entrée ; indicateurs manquants ; qualité des tests LaunchLab stricts.
- Passage de **comptages d'événements** à **effectifs de mints uniques / sessions / trades clôturés** ; métriques p50/p95/p99 de latence.

**P2 — science et stratégie**
- Validations chronologiques, walk-forward, purge/embargo si nécessaire, test indépendant ; bootstrap/intervalles, stress slippage/frais/latence.
- Comparer *sniping premier bloc* vs *attendre confirmation*, créateurs récurrents, bundles/wallet clusters, momentum, graduation/migration, risques de rug, baseline naïve.
- Tester modèles simples avant ML (régression logistique, Random Forest, XGBoost, LightGBM, modèles de survie/graphes si échantillons adéquats). Éviter le surapprentissage et le biais de survivance.

**P3 — facultatif** : GUI, automatisations secondaires, refonte massive, Rust, système multi-agent permanent sans preuve d'avantage.

## 8. Cahier des charges scientifique retrouvé

Deux documents de la bibliothèque :
- `/Memcoins/Texte collé.txt` — **39 847 octets**, première version du prompt large.
- `/Memcoins/Texte collé(1).txt` — **47 143 octets**, version étendue de **23 sections** et environ **1 648 lignes**.

Le second insiste sur :
- Recherche internationale (arXiv, SSRN, publications académiques, GitHub, vidéos, X/Reddit, documentations officielles) ; qualité des sources graduée A à E.
- Experts quantitatifs cités : Marcos López de Prado, David H. Bailey, Ernest Chan, Robert Carver, Larry Harris, Cartea/Jaimungal/Penalva, David Aronson, Edward Thorp, Nassim Taleb, Jean-Philippe Bouchaud et autres.
- Spécialistes/écosystème : FomoIsBack / Antoine Markarian / F Project, Solana/Anza/Agave, Helius/Mert Mumtaz, Jito, Raydium, Jupiter, Yellowstone, Geyser ; concurrents Axiom, BullX, Photon, GMGN, Trojan, BONKbot.
- Les références sont des **pistes à rechercher**, pas des preuves que leurs méthodes privées seraient connues ou pertinentes.
- Architecture candidate en cinq familles : (A) rug/manipulation, (B) potentiel de hausse, (C) exécution réalisable, (D) risque/position, (E) décision finale. Ne créer que ce qui améliore des résultats mesurés.
- Données par token à horodatages réels : secondes, 15/30 secondes, 1/3/5/10/15/30 minutes, 1 h et plus, y compris tokens morts / sans prix / sans sortie pour éviter biais de survivance.
- Exiger démonstration d'avantage *net de coûts*, validation hors échantillon, robustesse temporelle, stress tests, comparaison avec des baselines et possibilité de rejeter toute stratégie.

Le grand prompt demandait aussi une analyse des changements récents Solana/Alpenglow et de la recherche publique ; **ces sujets sont à revérifier via sources actuelles**, pas réputés déjà confirmés.

## 9. Procédure d'accueil du dernier ZIP dans Codex — à effectuer seulement après réception

1. Décompresser dans un dossier isolé ; **ne pas effacer la version locale ni la base de données**. Contrôler la présence de `.env`, clés privées, secrets ; les exclure de toute publication/prompt.
2. Inventorier les fichiers, dépendances, scripts d'entrée, tests, schémas SQLite et configurations ; produire un graphe d'import du moteur. Identifier **la version réelle** et ses dates/commits.
3. Comparer cette version à l'archive signalée `RUGGER_BOT_AUDIT_SOURCE.zip` et au contenu annoncé des correctifs PAPER P0 / tests. **Ne pas réappliquer** un patch déjà intégré.
4. Contrôler `entry_allowed`, `_performance_metrics`, `_session_summary`, `risk_flags_json`, gestion legacy quotes, détecteur LaunchLab strict, `PRIX_OK` et test `test_paper_entry_limits`.
5. Lancer syntaxe/imports puis tests unitaires sur **copie / DB temporaire**, sans aucune transaction réelle. Préserver l'état de la DB originale.
6. Produire audit P0/P1/P2/P3 avec fichier/ligne, scénario reproductible, couverture, et ordre minimal de corrections réversibles. Ne pas annoncer de rentabilité.
7. Revalider PAPER sur données enregistrées puis flux observés, avec coût/latence/scénarios de pannes, et compter **mints uniques**, **trades exécutables** et **P&L réel simulé net**.
8. Écrire fichiers pérennes `PROJECT_CONTEXT.md`, `DECISIONS.md`, `CHANGELOG.md`, `KNOWN_ISSUES.md`, `TEST_RESULTS.md`, sans stocker de secrets, pour ne plus dépendre de l'historique ChatGPT.

## 10. Limites et preuves

**Vu directement dans des fichiers texte accessibles :** prompt maître (47 Ko), ancien prompt (39 Ko), rapport d'audit PAPER, patch ligne par ligne, scripts Python historiques, tests, rapports JSON d'anciennes sessions, index et métadonnées des archives ZIP.

**Reconstitué par traces d'anciens échanges / rapports :** résultats des tests de l'audit et correctifs successifs, observations de sessions non fournies directement en JSON, décisions de passage à Codex, versions annoncées.

**Non vérifié ici :** contenu binaire des ZIP, correspondance avec la version qui tourne sur le PC, dernières modifications appliquées, tests Windows actuels, base SQLite complète, résultats en direct, toute rentabilité, exhaustivité de la conversation « Memcoins ».

**Prochaine entrée attendue :** dernier ZIP local du projet + prompt maître Codex que l'utilisateur prévoit d'envoyer. Le dossier actuel doit ensuite être réconcilié avec ces pièces et avec l'export complet de la conversation, lorsqu'il sera disponible.
