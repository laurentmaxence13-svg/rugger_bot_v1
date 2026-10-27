# Instructions durables pour OpenAI Codex — Rugger Bot V1

Ces instructions s’appliquent au **dépôt réel `rugger_bot_v1`**, local ou Cloud. Elles s'appliquent à tous les travaux Codex sur ce dépôt. En cas de doute, privilégier la sécurité des données, la précision factuelle et la réversibilité.

## Mission et ordre de priorité

Rugger Bot est un outil Python d'observation de nouveaux tokens Solana et de simulation de trading **PAPER ONLY**, centré sur Raydium LaunchLab. Objectif : stabiliser le bot, mesurer ce qu'il fait vraiment, et étudier un éventuel avantage quantitatif net de frais, slippage, latence et risque. Aucune rentabilité n'est démontrée.

1. P0 : cohérence des finances simulées, contrôles de risques, états des positions, données SQLite et fiabilité du reporting.
2. P1 : intégrité des événements LaunchLab, RPC/WebSocket, capture/prix/funding, qualité des données, tests de non-régression.
3. P2 : expériences de stratégie, scénarios réalistes et mesures hors échantillon, **après** fiabilisation.
4. P3 : améliorations ergonomiques, architecture sophistiquée, optimisation prématurée.

## Garde-fous non négociables

- **Aucun trading réel**, aucun ordre, signature, transaction, seed/private key, portefeuille financé, activation « live orders » ou test de transactions réelles. Ne créer aucun composant de passage au réel.
- **Mandat courant du 27 octobre 2026 : exécution autonome autorisée.** Lire, reproduire, corriger, tester sur copie isolée, contre-vérifier, créer des branches/commits et ouvrir des PR sans redemander l’accord pour ces actions. Conserver une référence Git, des correctifs proportionnés, des preuves chiffrées et un retour arrière. Ne remplacer aucun dossier entier avec un ancien ZIP.
- Les scanners, boucles PAPER et collectes réseau ne sont pas autorisés par une simple exécution de tests. Une collecte courte exige un protocole préenregistré, des accès/droits/quotas gratuits vérifiés et des budgets stricts ; aucune campagne prolongée, dépense ni augmentation payante sans accord spécifique. Aucune migration ou modification de base utilisateur dans le cadre des tests.
- Ne jamais lire, afficher ni transmettre les valeurs de `.env`, clés API ou URL RPC avec secrets. Lister seulement les *noms de variables* et la présence des fichiers, sans les ouvrir. Ne copier aucune base `.db` vers un service distant. Les jeux de tests doivent être synthétiques ou anonymisés.
- **Ne pas modifier la matrice de décision**, les critères anti-rug, la pondération des scores, les seuils d'entrée, les TP/SL ou les règles de stratégie durant l'audit financier P0.
- Le dépôt réel est prioritaire sur les notes historiques. Un résultat annoncé dans la discussion n'est pas nécessairement reproduit. Signaler : « démontré par le code », « reproduit par test », « documenté historiquement », « inconnu ».
- Aucune dépendance, API ou ressource payante sans accord. Ne pas réécrire en Rust ni déployer des équipes d'agents par défaut. Sous-agents spécialisés uniquement si leur revue est utile, limitée et autorisée.
- Les anciens fichiers `bot/bot/`, `tests/tests/`, `*.bak*`, `*.avant_correctif` constituent potentiellement des copies historiques : **ne pas les supprimer ni les prendre comme source active sans démonstration**.

## Réalité auditée le 22 octobre 2026 (sur une copie ZIP)

**Historique uniquement** : les défauts et nombres ci-dessous ne décrivent pas nécessairement la version courante. Lire `PROJECT_STATUS.md` et `CODEX_CONTINUATION.md` avant de décider du travail suivant.

- Archive `RUGGER_BOT_CODEX_COMPLET_20261022_190551.zip` : 184 entrées, 142 fichiers `.py`, intégrité ZIP OK. La source d'origine du PC peut avoir évolué depuis sa création : recontrôler le dossier courant.
- Commande exécutée sur copie isolée : `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider` : **46 réussis, 1 échec, 1 ignoré**. Le seul échec : `tests/test_research_pipeline.py::PipelineTests::test_paper_entry_limits`.
- `bot/analyser/paper_trader.py:301` : `entry_allowed()` utilise déjà les `pnl_sol` des clôtures à `exit_time`, mais appelle `ensure_paper_portfolio(con, 10.0, now)` et reconstitue `capital_day_start = capital_now - pnl_today` ; vérifier la justesse de ces hypothèses.
- `bot/analyser/paper_engine.py:263` `_performance_metrics` et `:716` `_session_summary` **contiennent encore l'ancien drawdown par composition des retours de trades**. Le rapport de session prend les motifs de rejet dans `reasons_json` au lieu de `risk_flags_json`, et sélectionne les clôtures sur l'heure d'entrée.
- `tests/test_research_pipeline.py:80` le test en échec met `status='closed', net_return=-0.11`, **sans `pnl_sol` ni `exit_time`** ; le contrôle journalier filtrant sur `exit_time` ne voit donc pas de P&L réalisé du jour et renvoie `True`. Il faut un test financièrement cohérent, et vérifier qu'aucune protection n'est affaiblie.
- Une seconde arborescence `bot/bot` est présente : des modules sont différents de `bot/`. Son `analyser/relay_analysis.py` possède une erreur de syntaxe à la ligne 783. Cela n'a pas bloqué le test ciblé, mais risque de bloquer une compilation récursive globale.
- Une base historique distincte `rugger_bot.db`, fournie auparavant, montrait un trade PAPER fermé avec `net_return=+0.577...`, **`pnl_sol=NULL`**, portefeuille réalisé toujours **10 SOL**. La performance financière ne peut pas être tenue pour vérifiée.

Lire impérativement `CODEX_AUDIT_FACTUEL_20261022.md` et `CODEX_PLAN_TECHNIQUE_20261022.md`. Les résultats documentent **une copie de l'archive** et ne remplacent pas les vérifications sur ton dossier courant.

## Devise et capital

La version inspectée utilise **10 SOL de capital PAPER**, allocation historique de 10 %; une proposition plus récente évoque **1 000 €**. Ne pas substituer l'euro au SOL ou remettre à zéro `paper_portfolio` sans conception de conversion historique et accord explicite. Dans un premier temps, conserver les unités SOL réelles du code.

## Critères de sortie d'une correction P0

1. Diagnostic prouvant la cause et le scénario.
2. Cas tests corrects mathématiquement : proportion du portefeuille réellement engagée, frais, date de clôture, capital de début de journée, données incomplètes, clôtures intersessions, et P&L en SOL.
3. Tests de référence et nouveaux tests exécutés sur copie / environnement de test autorisé, résultat complet publié.
4. Comparaison de rapport et de P&L avant/après, compatibilité historique et vérification de la non-régression.
5. Aucune modification des critères de sélection; rollback disponible.

## Reprise et livraison courantes

Lire `CODEX_CONTINUATION.md`, `PROJECT_STATUS.md` et les sources/tests pertinents.
Les anciens protocoles d’arrêt après audit (`PROMPT_DEMARRAGE_CODEX.txt`, plan du
22 octobre) sont historiques ; le mandat courant remplace ces seules limitations
de procédure. Les protections financières, secrets, bases et réseau restent actives.

Priorité : sorties qualifiées, identités/supplies, conservation/replay, coûts en SOL,
puis protocole prospectif. Ne jamais inventer une route, un fill, une réconciliation
ou une rentabilité. UNKNOWN et INSUFFICIENT DATA restent des résultats explicites.
Une projection contrefactuelle n’est pas un état futur observé.

Utiliser `python -B tools/offline_check.py` pour les tests sur copie jetable sans
réseau, `.env` ou base utilisateur ; l’interpréteur doit disposer des dépendances
du projet et de pytest. Tester les régressions causales puis la suite pertinente.
Avant chaque PR significative, examiner tout le diff et faire une contre-vérification
proportionnée. Mettre à jour `CODEX_CONTINUATION.md` et `PROJECT_STATUS.md` avec
commits, commandes exécutées, résultats et limites. Préserver les travaux existants.
Les sous-agents doivent rester spécialisés et non redondants. Aucun travail de fond
n’est promis après la fin de session.
