# Feuille de route technique — Codex / Rugger Bot V1

## Phase 0 — Inspection strictement sans écriture

1. Vérifier que l'espace de travail courant a `bot/`, `tests/`, `data/`, `README.md`, et identifier le vrai répertoire racine; ne pas supposer que le répertoire VS Code « rugger_bot_v1_paper (1) » est l'import Python.
2. Identifier les points d'entrée actifs (`bot/main.py`, `bot/analyser/paper_engine.py`, `.bat`, `.ps1`). Vérifier les imports pour prouver quelle branche `bot/` fonctionne et distinguer le sous-dossier `bot/bot/`.
3. Lire sans secrets ni valeurs sensibles `tests/test_research_pipeline.py` (test de limite), `paper_trader.entry_allowed`, `paper_capital`, `ensure_paper_portfolio`, `record_quote`, `paper_engine._performance_metrics`, `_session_summary`, `paper_report`.
4. Inspecter seulement les **schémas** SQLite, au besoin sur une copie ou en mode strictement lecture seule, sans migration. Le fichier SQLite fourni séparément pourrait différer de la DB active du PC.
5. Fournir un tableau « anomalie / source:ligne / cause / test à créer / risque de régression / correction minimale ».
6. **S'arrêter et demander l'accord de l'utilisateur avant toute modification ou exécution créant des fichiers.**

## Phase 1 — P0 financier après autorisation

Priorités :

- Expliciter les invariants : `initial_capital_sol`, `realized_capital_sol`, `position_sol`, `pnl_sol`, coûts, entrées, clôtures, solde engagé vs disponible, historique manquant.
- Définir si les pertes journalières reposent sur capital du début UTC, sur capital initial ou référence différente; expliquer le choix et le verrouiller en tests. En cas de données incohérentes, **ne pas autoriser de nouvelles entrées PAPER** par défaut, avec diagnostic explicite.
- Prévoir tests de régression déterministes et cohérents, sur **SQLite `:memory:` ou base temporaire** :
  1. Portefeuille de 10 SOL, une position de 1 SOL perdant 10 % : **−0,1 SOL = −1 % du portefeuille**. Ne déclenche pas un plafond de perte du portefeuille à 10 %.
  2. Portefeuille 10 SOL, pertes réalisées cumulées de **−1 SOL** le même jour : limite de 10 % atteinte, entrée refusée (test frontière).
  3. Fermeture d'une position créée la veille mais clôturée aujourd'hui : perte du jour comptée aujourd'hui.
  4. Ligne `closed` sans date de clôture / sans P&L réel : cas invalide, refus PAPER / alerte selon politique définie.
  5. Gagnants et perdants de tailles différentes : rendement portefeuille calculé en SOL et non par produit des pourcentages de trades.
  6. P&L latents : distinction explicite `realized-only` vs `mark-to-market`; ne pas afficher un DD latent si prix manquant.
  7. Frais déduits exactement une fois, gestion des frais absents, revente impossible.
  8. Plusieurs positions ouvertes, préservation du solde; aucune entrée dupliquée.
  9. Compteurs session : entrées par `entry_time`, clôtures par `exit_time` et motifs de rejet par `risk_flags_json`.
  10. Variations de capital, jours UTC et absence de référence : ne pas inventer le capital initial.
- Corriger les *causes*, pas des assertions isolées. Privilégier patch minimal, réversible et étayé. Mettre à jour les consommateurs des métriques si la sémantique change.
- Après validation des changements, exécuter le même groupe de tests qu'en baseline et les nouveaux tests. Conserver logs de test anonymisés; contrôle de syntaxe des modules **actifs**, sans être trompé par les copies `bot/bot`.

## Phase 2 — P1 fiabilité du collecteur / prix

- Scanner LaunchLab strict: vérifier discriminator Anchor/transaction interne, `initializeMint2` et distinction create vs swap. `deployer_candidate` = fee payer hypothétique, pas créateur prouvé.
- Solidifier Helius 429 via `AdaptiveRPCGate` et `Retry-After`, WebSockets et repli RPC public. Mesurer erreurs, reconnects, pertes d'événements et latences médiane/p95/p99; ne pas confondre finalité de la blockchain et détection effective.
- Prix: distinguer funding LaunchLab, réserves virtuelles, prix curve Q64, liquidité réellement exécutable après migration et cotation DexScreener. Marquer donnée manquante ou estimation avec provenance et âge. Ne pas considérer `None` comme zéro.
- Dédupliquer mints/signatures/slots et calibrer les délais d'observation; s'assurer d'une **unicité des candidats** par launch et de la disponibilité causale des données.
- SQLite: inspecter transactionnalité, WAL, busy_timeout, concurrence du scanner/analyses, reprise après panne, migrations non destructives, taille réelle des fichiers et index.
- Mesurer couverture : mints détectés, mints identifiés, mints cotés, fraîcheur des quotes, profils créateurs valides, ratio décisions distinctes / mints distincts.

## Phase 3 — P2 recherche et stratégie après confirmation

La finalité n'est pas d'imiter un trader ni de « booster le score ». Comparer sous protocole scientifique les stratégies : entrée précoce, entrée différée, créateurs récurrents, wallets coordonnés, bonding curve, migration, momentum, filtres de rugs, sorties adaptatives. Séparer : (1) fraude/risque de rug, (2) probabilité de hausse, (3) exécutabilité (profondeur et sortie), (4) risque de portefeuille.

Comparer des baselines simples puis modèles plus complexes seulement avec données suffisantes. Séparer dans le temps, éviter fuite future et survivorship bias, tenir compte des créateurs répétés, tester des coûts pessimistes, les queues extrêmes et ruptures de liquidité; démontrer des résultats reproductibles et hors échantillon. Aucune décision réelle sans autorisation explicite, hors champ de ce projet.

## Livrables Codex à chaque étape

- État du code réellement ouvert, version/commandes vérifiées, fichiers concernés.
- Tableau P0/P1/P2/P3 et classement par impact/effort/risque.
- Rapport compréhensible et chiffré avec exemples et limites.
- Diff minimal uniquement après accord; rollback précis; nouvelle liste de tests et résultat complet.
- Documentation sans secrets : `PROJECT_CONTEXT.md`, `KNOWN_ISSUES.md`, `TEST_RESULTS.md`, `DECISIONS.md`, `CHANGELOG.md` après autorisation.
