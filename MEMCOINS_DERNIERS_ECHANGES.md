# RUGGER BOT V1 — SUPPLÉMENT AUX DERNIERS ÉCHANGES

**Établi le 22 octobre 2026** — Journal de reprise destiné à Codex et à `RUGGER_BOT_DOSSIER_RECUPERATION_2026-10-22.md`.

## 1. Dernier échange connu après l'audit du 21 octobre

L'utilisateur a transmis la transcription suivante, qui constitue l'élément le plus récent disponible de la conversation « Memcoins » :

1. La suite de tests aurait passé **47 tests**, **0 échec**, **1 ignoré**, **1,72 seconde**. Une réponse précédente déclarait que deux anciennes erreurs avaient été corrigées. **Ce rapport n'est pas un test reproduit dans notre environnement.**
2. La discussion a décidé de conserver cette base comme référence **avant un nouveau contrôle du P0 financier**. Commande de simple inspection proposée : vérifier que le source de `paper_trader.entry_allowed` ne contient plus `SUM(net_return)`, et que celui de `paper_engine._session_summary` ne contient plus `equity = peak = 1.0`. Ces deux recherches sont des **heuristiques de reconnaissance**, pas des tests complets de bonne logique.
3. La discussion a ensuite fourni un script PowerShell/Python **qui réécrit `paper_trader.entry_allowed`** après sauvegarde locale `.bak_p0`. Il recherche le code ancien avec `SUM(net_return)`; lui substitue `SUM(pnl_sol)` pour les clôtures `exit_time`, rejette les P&L manquants; appelle `ensure_paper_portfolio(con, 10.0, now)`; prend le capital actuel `paper_capital(con)`; calcule `capital_day_start = capital_now - pnl_today`; compare la perte à `max_daily_loss_pct`. Deux vérifications unitaires incorporées utilisent un capital de 10 SOL et une unique ligne de trade avec perte de −0,05 SOL puis −1,0 SOL. Le script annonçait « CORRECTIF P0 : 2 tests financiers reussis » lorsque les assertions passent, mais la sortie réelle des deux assertions n'a pas été fournie dans la transcription.
4. **Après la modification**, l'utilisateur/assistant a rapporté **46 tests réussis, 1 échec, 1 ignoré**, avec échec de **`test_paper_entry_limits`**.
5. La discussion a reconnu qu'un `net_return=-20 %` sur une petite position n'est pas une perte de −20 % du portefeuille. Elle a demandé de lire le scénario complet du test, notamment les montants et dates des transactions, avec `Get-Content ...` puis `Select-String ... -Context 0,45`.
6. **Dernière phrase fournie :** la capture montrait seulement la fin du test, sans les lignes de création des pertes; l'assistant allait chercher le fichier de test dans l'archive. **Nous n'avons reçu ni son résultat, ni le test complet, ni sa correction définitive.**

### État factuel conservé

- Le précédent jeu à 47 réussites **ne prouve pas** la correction complète du P0 financier.
- La dernière exécution rapportée est **46 réussis / 1 échec / 1 ignoré**, après modification du calcul journalier.
- Le test `test_paper_entry_limits` **reste à diagnostiquer**. Il ne doit pas être « réparé » en supprimant un contrôle de risque ou en changeant aveuglément une assertion.
- Le calcul `_session_summary()`/drawdown n'a pas été confirmé corrigé dans cette séquence.
- La matrice de décision devait rester inchangée pendant cette investigation.
- Une session PAPER sur flux Solana était expressément reportée après résolution et revalidation du P0.

## 2. Archive jointe dans la conversation actuelle

Nom : `RUGGER_BOT_TESTS_CORRIGES_LEGER.zip`.

- Taille : **1 977 octets**.
- Intégrité ZIP : **aucune erreur détectée** (`ZipFile.testzip()` retourne `None`).
- SHA-256 : `f92b8614dd08948a034dd97f13cbde4266f951a6f1e58e008a0d9388c0bc0232`.
- Entrées (et seulement celles-ci) :
  - `tests/test_paper_engine.py` — 3 170 octets; SHA-256 `f409d84b4896aec1963ff51f0bdd3438aeb26f6d0af515df349dd2a5635f8630`.
  - `tests/test_parser.py` — 1 564 octets; SHA-256 `0636931abd69ef157d3b8e6946fb38c65598e6cd4abdcb707a4022e98d369eec`.
- Leurs arbres syntaxiques Python se parsèrent sans erreur (`ast.parse`). **Aucun pytest complet n'a pu être exécuté à partir de ce ZIP**, puisqu'il ne contient ni le package `bot/` ni les dépendances nécessaires.

### Comportements vérifiés dans les sources des tests

`tests/test_paper_engine.py` :
- `paper_report()` doit présenter `paper_only=True`, `real_orders_enabled=False`, `private_keys_used=False`.
- Le collecteur doit enregistrer une cotation enrichie `MarketQuote` et afficher un statut `PRIX_OK`, sans ouvrir de position lorsqu'aucun modèle n'est présent.
- Le mode `shadow_baseline` doit rester diagnostique, et les snapshots comportementaux ne doivent pas utiliser des transactions futures.

`tests/test_parser.py` :
- Détection du mint créé (`initializeMint2`) et du fee payer.
- `find_raydium_launch()` accepte une instruction explicitement identifiée comme `initialize_v2` dans le scénario factice.
- Un `sell_exact_in` ou la seule présence du Program ID **ne doit pas être reconnu comme un lancement neuf**.

**Prudence :** ces fichiers de tests concernent une révision antérieure à la dernière modification manuelle de la limite de perte. Ne les écrase pas automatiquement sur le dossier principal sans diff et approbation.

## 3. Analyses financières à effectuer en priorité

- Calcul de perte journalière **en SOL réalisé** et non addition de pourcentages. Travailler avec `pnl_sol` valide et la **date de clôture**.
- Cohérence du dénominateur de perte quotidienne (capital initial, capital au début de journée, capital fin de journée), y compris autres variations non-trading, P&L incomplet et absence de portefeuille.
- Vérifier que la modification ne crée pas silencieusement un portefeuille de `10.0 SOL` alors que la référence de capital attendue est différente.
- Identifier si les positions ouvertes comptent dans la perte ou si la limite est volontairement « réalisée uniquement »; traiter les cas de liquidation impossible.
- Calcul de `drawdown` via courbe de capital, en distinguant réalisé uniquement et valorisé mark-to-market.
- Positions fractionnaires : une perte de 20 % sur **1 SOL engagé** dans un portefeuille de 10 SOL donne **−0,2 SOL / −2 % du portefeuille** hors frais.
- Contrôler les clôtures intersessions, frais non déduits deux fois, doubles entrées, dates UTC et transactions avec P&L manquant.
- Après approbation de l'utilisateur, tests unitaires et intégration sur base SQLite temporaire, puis PAPER sans fonds réels.

## 4. Incompatibilité de devises à résoudre explicitement

Le **prompt historique** décrit un portefeuille **10 SOL**; un **prompt plus récent pour Codex** décrit **1 000 € fictifs**. Le dernier ZIP fourni ne contient aucun code de portefeuille permettant de trancher. La bonne procédure est de conserver la devise et le capital du code actuel jusqu'à ce qu'un cahier de migration et ses tests aient été explicitement acceptés. Les deux chiffres ne sont pas interchangeables.

## 5. Fichiers de référence joints à utiliser

- `RUGGER_BOT_DOSSIER_RECUPERATION_2026-10-22.md` : contexte de septembre-octobre, correctifs, décisions, données historiques, zones d'incertitude.
- `PROMPT_MAITRE_CODEX_RUGGER_BOT_V1.md` : instructions opératoires, procédure d'audit et priorité P0.
- `RUGGER_BOT_TESTS_CORRIGES_LEGER.zip` : deux tests seulement, jamais base de projet complète.

**Dernier état garanti :** aucun code complet exécuté ou modifié au cours de cette récupération; seules les données lisibles et les deux tests du ZIP ont été inspectés.
