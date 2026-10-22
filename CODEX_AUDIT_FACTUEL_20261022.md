# Audit factuel et transmissible — archive réelle du 22 octobre 2026

## Périmètre et preuve

- Archive fournie : `RUGGER_BOT_CODEX_COMPLET_20261022_190551.zip`
- SHA256 : `56f0e779b06bd831d3cbc2a13ebf039af8daaff4ac583426873b57718629dd08`
- Intégrité ZIP : OK (`ZipFile.testzip() = None`).
- Entrées : **184**; sources `.py` : **142**. Structure racine interne : `rugger_bot_v1/`.
- Le ZIP a été extrait **uniquement dans une copie du conteneur d'audit**, sans modifier le dossier VS Code de l'utilisateur.
- La commande de test exécutée sur la copie était `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider`.
- Résultat reproductible dans notre environnement Linux/Python : **46 passés, 1 échec, 1 ignoré**. Cela ne prouve pas la même exécution sur Windows; tests sans session marché ni trading.
- Fichiers Python examinés avec `compile()` : **141/142 valides**; échec de syntaxe dans `bot/bot/analyser/relay_analysis.py:783`, *copie imbriquée probablement inactive*. Aucun lancement d'ordre réel.

## Arborescence et modules du dépôt

```text
rugger_bot_v1/
├── bot/
│   ├── main.py                          scanner LaunchLab
│   ├── config.py                        configuration (ne pas afficher les secrets)
│   ├── solana/rpc.py, websocket.py      Helius, RPC/WS fallback
│   ├── scanner/transaction_parser.py    parser LaunchLab (def vers ligne 90)
│   ├── analyser/
│   │   ├── paper_trader.py              portefeuilles, quotes, entrée/sortie PAPER
│   │   ├── paper_engine.py              boucle intégrée, rapports, risques
│   │   ├── final_decision_engine.py     matrice de décision (ne pas modifier en P0)
│   │   ├── launchlab_onchain.py         cotations bonding curve
│   │   ├── multi_creator_research_engine.py  gate RPC, historique créateur
│   │   ├── behavior_pipeline.py         risques comportementaux
│   │   ├── research_pipeline.py         datasets/backtests exploratoires
│   │   └── creator_backtest_v6..v26.py  nombreuses variantes de recherche
│   ├── database/db.py
│   └── bot/                              **copies de modules imbriquées**
├── tests/
│   ├── test_research_pipeline.py        contient le test en échec
│   ├── test_paper_engine.py
│   ├── test_parser.py
│   ├── test_paper_session.py
│   └── tests/                            **tests dupliqués plus anciens**
├── data/                                 rapports/datasets de l'archive (pas la DB)
├── README.md, requirements.txt, .gitignore
└── *.bat, *.ps1                          scripts de lancement Windows
```

L'archive ne contient pas `.env`, `.venv` ou base SQLite active. C'est attendu pour un échange prudent. Elle ne contient pas non plus `.env.example`, bien que le README le mentionne : vérifier si ce fichier existe seulement sur le PC, car la commande d'export excluait les fichiers commençant par `.env`.

## Reproduction précise du test en échec

`tests/test_research_pipeline.py:80–94` :

- La fixture enregistre une entrée PAPER pour `mint='one'`, puis ferme la ligne avec `status='closed', net_return=-0.11, exit_reason='SL'`.
- **Pas de `pnl_sol` ni de `exit_time` renseignés** dans l'`UPDATE`.
- Le contrôle `entry_allowed()` utilise les clôtures avec `exit_time` compris entre minuit UTC et l'instant vérifié, puis agrège `pnl_sol`.
- Cette clôture artificielle n'est donc pas comptée dans les pertes du jour. Comme les autres limites sont relâchées dans le dernier appel, `entry_allowed(...)` renvoie **True**; le test ancien exige **False**, d'où l'échec constaté.
- Il n'est **pas** légitime de retourner à `SUM(net_return)` pour satisfaire le test. Une perte de 11 % sur une position de 1 SOL n'est pas une perte de 11 % sur un portefeuille de 10 SOL.
- Il faut revoir la cohérence de l'état « closed + exit_time NULL », les frais, l'allocation et la politique de rejet en présence de données historiques incomplètes. Établir une politique fail-closed claire et un test valide. Ne pas seulement « faire passer » l'assertion.

### Indices dans le code actif

- `bot/analyser/paper_trader.py:301–342` : `entry_allowed` (déjà modifié). Filtres de pertes sur `pnl_sol` et `exit_time`. `ensure_paper_portfolio(con, 10.0, now)` peut créer une référence par défaut ; vérifier avant d'adopter comme règle permanente. Dénominateur reconstruisant le capital du début de journée à partir du capital actuel. Cela suppose l'absence d'autres flux et une comptabilisation parfaite des clôtures.
- `bot/analyser/paper_engine.py:263` : `_performance_metrics` compose les `net_return` fractionnaires comme s'ils concernaient la totalité du capital. Le traitement de `pnl_sol=None` par `or 0.0` peut masquer un manque de donnée.
- `bot/analyser/paper_engine.py:716` : `_session_summary` présente les mêmes erreurs, suit `entry_time` pour les trades fermés au lieu de la date de clôture et utilise `reasons_json` comme motifs de rejet (peut inclure des facteurs positifs).
- `bot/analyser/final_decision_engine.py:229` : `decide(features, min_score=45.0, min_liquidity=1000.0)`; score de départ 50. **Ne pas modifier pendant P0**.
- `bot/analyser/multi_creator_research_engine.py:84,122` : gate RPC adaptative et retry 429. Fonctionnement réseau actuel NON testé ici.
- `tests/tests/` et `bot/bot/` : duplications concrètes, d'où l'importance de ne pas assimiler deux copies à un même état de code.

## Audit d'une ancienne base historique jointe séparément (lecture seule)

**Attention :** le fichier SQLite `rugger_bot.db` avait été fourni dans un autre envoi. Il n'est pas nécessairement synchronisé avec le ZIP du 22 octobre. Il a été examiné via une connexion SQLite `mode=ro&immutable=1`; il **n'est pas inclus** dans le pack Codex.

| Indicateur lu dans cette base | Valeur |
|---|---:|
| Lignes de `launch_candidates` | 1 745 |
| Mints uniques dans `launch_candidates` | 1 319 |
| Lignes `paper_prices` | 573 |
| Mints avec au moins une cotation | 18 |
| Décisions PAPER | 276 |
| Décisions d'acceptation | 0 |
| Transactions PAPER enregistrées | 1 |
| Transactions clôturées sans `pnl_sol` | 1 |
| Capital virtuel initial | 10 SOL |
| Capital réalisé enregistré | 10 SOL |
| Historique Helius dans `research_tx_cache` | 12 476 lignes |

Le trade unique porte `net_return ≈ +0,5770` (environ **+57,7 % sur le trade**), mais aucun `pnl_sol`. Ce chiffre ne représente donc **pas** un rendement démontré du portefeuille. Un rapport ancien du ZIP affiche en effet `net_return_after_costs ≈ 0,577` tout en affichant **`pnl_sol = 0.0` et un portefeuille inchangé à 10 SOL**. Cela est financièrement incohérent : Codex doit traiter les valeurs manquantes comme **inconnues**, pas comme zéro réalisé.

Le rapport du ZIP du 22 octobre, stocké dans `data/paper_engine_report.json`, est lui-même un artefact historique : `launches_observed=1467`, `quotes_recorded=1674`, `launches_with_quotes=41`, `rejected_decisions=1376`, `accepted_decisions=1`, `strategy_mode='shadow_final'`, `validation_status='diagnostic_not_validated'`. Les chiffres ne doivent **pas** être confondus avec une mesure actuelle en live, ni avec la base SQLite historique citée ci-dessus.

## Distinction des résultats de tests

- Le rapport du 21 octobre `AUDIT_PAPER_CORRECTIF.md` annonçait **53 passés / 1 ignoré** sur une copie source modifiée. Ce correctif complet **n'est pas** intégré dans le ZIP réel du 22 octobre : les fonctions de drawdown/session restent anciennes.
- Une étape antérieure sur le PC annonçait **47 passés / 1 ignoré**.
- Après patch manuel de `entry_allowed`, le PC annonçait **46 passés / 1 échec / 1 ignoré**. Notre reproduction indépendante sur le ZIP confirme **exactement ce dernier état**.
- **Aucun résultat de pytest positif ne suffit à établir la justesse des prix exécutables ni la rentabilité.**

## Risques à prioriser

**P0 immédiats :** test `test_paper_entry_limits` et données clôturées incomplètes; drawdown et returns portefeuille faux; P&L manquant masqué; bilan de session incorrect (intersessions et drapeaux de risque); cohérence du capital du début de journée et des frais.

**P1 ensuite :** données on-chain vs DEX, couverture des mints cotés, 429 et WebSocket, doublons, horodatages, reprise après panne, concurrence SQLite, compatibilité Python/Windows, copies `bot/bot`, intégrité des instructions LaunchLab et compatibilité `MarketQuote`.

**P2 après stabilisation :** calibration scientifique score/anti-rug, tests d'entrée précoce vs confirmation, backtests chronologiques et hors échantillon, stress tests sur frais/slippage, coût de data/RPC, démonstration éventuelle d'espérance nette positive.

## Limitations de cet audit

- Aucun marché Solana interrogé; aucun ordre ni transaction envoyé.
- Pas de vérification de l'environnement `.venv` Windows ni de son `.env`.
- Les observations de la DB sont historiques et potentiellement décalées de celles de l'archive de code.
- Aucun fichier du PC de l'utilisateur modifié. Le pack qui accompagne ce rapport est **documentaire**, pas un correctif automatique.
