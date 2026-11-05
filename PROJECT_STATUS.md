# Rugger Master — état de référence unique

> **Ce fichier est la seule source de vérité sur l'état du projet.** Tout autre
> document d'état (`P1_*`, `P3_*`, `CODEX_*`, `LIVE_*_CHECKPOINT`,
> `docs/MASTER_CONTINUITY.md`, `CLAUDE.md` de la pile #89) est un **journal
> historique** : utile comme preuve, jamais comme état courant.
> L'ancien contenu de ce fichier (préparation P3, 26-27 oct.) reste lisible via
> `git show d9b950e:PROJECT_STATUS.md`. Celui de la pile #89 (498 lignes) via
> `git show cf9a084:PROJECT_STATUS.md`.

Dernière vérification : **2026-11-03**, sur `main` = `d9b950e` et sur la branche
d'intégration `integration/consolidation-20261103` (§4 bis). Niveau de preuve
indiqué partout : *mesuré* (commande rejouée ce jour), *code* (lu dans le dépôt),
*historique* (affirmé par une note, non rejoué), *inconnu*.

---

## 1. Objectif final

Un **seul** bot Rugger Master pour Solana / Raydium LaunchLab (puis CPMM après
migration), capable de :

1. observer les créations LaunchLab en temps réel ;
2. décider (Master) ENTER / WAIT / EXIT avec coûts réels en SOL ;
3. exécuter en PAPER, puis — **sur décision séparée du propriétaire** — en LIVE
   avec un portefeuille dédié et des limites strictes ;
4. être suivi depuis une interface (Rugger Wallet) et sur Axiom.

Trois jalons **distincts**, aucun n'est atteint aujourd'hui :

| Jalon | Signification | État |
|---|---|---|
| `LIVE_READY_TO_ARM` | moteur LIVE complet, désarmé, testé hors réseau | non atteint (*historique*) |
| `LIVE_EXECUTION_VERIFIED` | vrais ordres autorisés, réconciliés | non commencé |
| `ECONOMIC_EDGE_VALIDATED` | avantage net de frais, hors échantillon | **non démontré** — aucune rentabilité |

## 2. Architecture de référence (cible)

```
bot/scanner  bot/solana       → capture LaunchLab (WebSocket/RPC)        [main]
bot/market                    → décodage exact TradeEvent + courbe       [#90]
bot/p3  bot/p4                → preuves, coûts, replay causal            [#89]
bot/master_*.py               → décision Master (shadow/PAPER)           [#89]
bot/analyser  bot/database    → moteur PAPER, SQLite, rapports           [main]
bot/live (cœur, 23 modules)   → route, signer isolé, submission, journal [#89]
bot/dashboard + Rugger Wallet → interface unique                         [main + #89]
```

Règle : un composant n'existe qu'à **un** endroit. Les sondes réseau ponctuelles
(40 modules `helius_*`, `public_*`, `pinned_*`… dans `bot/live`) sortent du
moteur d'exécution vers un espace recherche (étape ultérieure, voir §6).

## 3. Composants : état et classement

| Composant | Où | État | Classement |
|---|---|---|---|
| Scanner, client Solana, SQLite, config | `main` | testé (*mesuré*) | **CONSERVER** |
| Moteur PAPER `bot/analyser` | `main` | testé ; audit P0 du 22/10 corrigé par #1–#4 (*historique*) | **CONSERVER** |
| Décodeur TradeEvent + courbe exacte `bot/market` | #90 seulement | testé, unique dans le dépôt (*code*) | **FUSIONNER** dans la référence |
| Master `bot/master_*.py`, `bot/p4` | #89 seulement | testé ; S1 bank réel ajouté par #89 | **CONSERVER**, intégrer |
| Preuves/campagnes `bot/p3` (73 modules) | #89 | testé ; beaucoup de campagnes ponctuelles 009–012 | **AMÉLIORER** : garder le noyau, archiver les campagnes après intégration |
| Moteur LIVE cœur (23 modules `bot/live`) | #89 | testé hors réseau, désarmé ; anti-double envoi présent (`rpc.py:98`) | **CONSERVER** |
| Sondes réseau dans `bot/live` (40 modules) | #89 | scripts de recherche mélangés au moteur | **AMÉLIORER** : déplacer hors `bot/live` |
| Interfaces : Streamlit Rugger Wallet (#61), service Render (#63/#64/#87, #65–#74), aperçu Vercel (#86) | 3 endroits | trois UIs concurrentes | **FUSIONNER** : une seule (décision D4) |
| Workflows CI (52 sur l'intégration, dont 2 `schedule:` Helius et 45 réseau sur `pull_request`) | intégration | 47 passés en `workflow_dispatch` seul (§4 bis) | **AMÉLIORER** : réactiver un par un avec budget |
| Copies `bot/bot/` (66 fichiers), `tests/tests/` (6), `*.bak*`, `*.avant_correctif` (6) | `main` | importées nulle part (*code*, `git grep`) ; inventaire en cours (#94) | **SUPPRIMER** après #94 |
| ~40 notes `.md` à la racine (`P1_*`, `P3_*`, `CODEX_*`) | `main` | historiques | **ARCHIVER** dans `docs/history/` (étape ultérieure) |
| Suivi Axiom | — | **aucun code** ; Axiom n'est cité que comme concurrent | **À DÉFINIR** (D5) |

## 4. PR et dépendances

Le dépôt contient **deux piles indépendantes** qui ne se connaissent pas :

- **Pile A** — `#22 → … → #88 → #89`, base `main@7ddddb9` (avant le terminal
  PAPER). **839 commits, ~115 000 lignes, 784 fichiers** hors de `main`. Contient
  Master, LIVE, P3/P4, Render.
- **Pile B** — `#90 → #91…#99`, base `main@d9b950e`. Agent Claude planifié.
  Contient `bot/market`, outils hors ligne, protocole d'autonomie.

Aucun fichier commun entre A et B (*mesuré*). L'intégration est faisable :
`#89 + main + #90` fusionnent avec **6 conflits**, tous dans les fichiers du
terminal PAPER (`bot/dashboard/app.py`, `README.md`, `TERMINAL_PAPER.md`,
`LANCER_TERMINAL_PAPER.bat`, `requirements-dashboard.txt`,
`.github/workflows/paper-terminal-ci.yml`) ; en prenant la version `main`
(correctifs Windows #59/#60 postérieurs) : **3974 réussis, 1 ignoré, 0 échec**.

| Catégorie | PR | Motif |
|---|---|---|
| **Porteuse à intégrer après revue** | **#89** (inclut 41 PR ouvertes) | pointe de la pile A, verte |
| **Porteuse à intégrer après revue** | **#90** | base de la pile B, verte, `bot/market` unique |
| Déjà contenues dans #89 → fermer après intégration de #89 | #22, #29–#31, #33, #34, #36–#39, #41, #42, #45–#48, #50, #52–#55, #65–#74, #76–#79, #81, #83–#85, #88 | 0 commit hors de #89 (*mesuré*) |
| Remplacées par une meilleure implémentation | #44 (anti-double envoi déjà dans #89, `bot/live/rpc.py:98`), #40 (ses commits propres se déclarent couverts par #41, inclus dans #89), #43 (fermée) | garde équivalent présent |
| Remplacée | #35 (61 commits) | branche parallèle de #36–#39, intégrée autrement via #39 « codex-free PR35–PR38 » ; à confirmer en revue |
| Corrections / décision nécessaires | #56 (1 commit Render ledger expérimental), #86 (Vercel), #80, #82 (preuves réseau ponctuelles) | dépendent de D3/D4 |
| Preuves historiques à conserver ouvertes temporairement | #24, #27, #28, #49 (recherche P3, 2–8 commits) | jamais intégrées, utiles comme trace |
| Pile B, en revue | #92, #93 (slot timing), #94 (inventaire copies), #95–#99 (rapports hors ligne) | sur #90, petites, testées par CI |
| Protocole d'autonomie | #91 | à garder **hors** de la référence (règles des agents) |

Ordre d'intégration recommandé (le propriétaire fusionne, jamais un agent) :
1. Décisions D1–D3 ci-dessous.
2. Branche d'intégration `#89 + main + #90`, désactivation des `schedule:`, revue.
3. Fermeture des 41 PR contenues ; rebase de #92–#99 sur la nouvelle référence.
4. Nettoyage (§6 étapes 2–4).

## 4 bis. Branche d'intégration `integration/consolidation-20261103`

Décisions D1, D2, D3, D6 approuvées. Base `main` `d9b950e`. Fusions, dans
l'ordre (`--no-ff`, aucun cherry-pick) :

| # | Branche | SHA fusionné | Base de fusion | Conflits |
|---|---|---|---|---|
| PR #100 | `claude/practical-lovelace-jylnbi` | `84e4f0c` | `d9b950e` | 0 |
| PR #90 | `claude/launchlab-trade-events` | `4f2875d` | `d9b950e` | 0 |
| PR #88 | `feat/prepurchase-bitquery-official-sample-proof-20261102` | `ce0f76d` | `7ddddb9` | 7 (journal dans la PR) |
| PR #89 | `feat/master-real-s1-bank-bridge-20261102` | `cf9a084` | `ce0f76d` (= #88) | 0 |
| PR #91 | `claude/autonomy-framework-20261103` | `327cc8c` | `7bd4fad` | 0 |
| PR #98 | `claude/dev-20261103-master-feature-reconstructibility-v1` | `33dbe78` | `4f2875d` | 0 |

#91 et #98 sont fusionnées en plus de l'ordre demandé parce que
`BACKLOG.json`, `MASTER_CONTINUITY.md` et `tools/master_feature_inventory.py`
n'existent que sur ces branches. Aucun fichier copié à la main.

Points chauds attendus : `final_decision_engine.py` n'est modifié par aucune
branche ; `p4_experiment.py`, `master_decision.py` et `CLAUDE.md` n'existent
que dans #89 ; `AGENTS.md` n'a changé que dans #89 (version #89 retenue = D1).
Les correctifs Windows de `main` (socketpair, blocage réseau thread-local,
neutralisation dotenv) sont dans `tests/p16h_isolated_runner.py`, **identique**
des deux côtés ; ceux du terminal (lanceur `.bat`/`.ps1`, pins pandas/numpy,
garde graphique vide, job CI Windows) sont conservés côté `main`.

Changements de code en plus des fusions (un commit chacun, réversibles) :
`tools/offline_check.py` (liste blanche pile B), `bot/market/replay.py` (taux
de frais par pool, finding 3), `tools/master_feature_inventory.py` (finding 1-2),
`bot/dashboard/local_db.py` et `bot/live/journal.py` (fermeture SQLite, §7),
tests (fermeture SQLite + `tests/conftest.py`), CI (dépendances, mode strict
3.13). Aucun seuil, critère anti-rug, score, TP/SL ni taille de position
modifié. Aucun run du Master.

Conflits du terminal PAPER revus (2026-11-03, ronde 2) : les lignes de #89
écartées sont une référence à la branche obsolète `feat/paper-terminal-20261101`
(CI, doc), un ancien commentaire de `requirements-dashboard.txt`, et l'ancien
`.bat` autonome qui installait Streamlit dans `.venv`, l'environnement du bot.
Le `.ps1` de `main` couvre tout (environnement séparé `.venv-dashboard`,
contrôle HTTP, smoke test, réparation pip). `bot/dashboard/app.py` : aucune
ligne de #89 perdue. **Rien à restaurer.**

Workflows (D3) : 47 workflows réseau passent en **`workflow_dispatch` seul**
(2 `schedule:` Helius, 45 `pull_request`, 2 `push`). Rien n'est supprimé, aucun
secret touché. Restent automatiques : `offline-tests.yml`,
`rugger-isolated-ci.yml`, `paper-terminal-ci.yml` (hors ligne).

Inventaire des 49 workflows manuels (47 modifiés + `helius-index-first-cohort`
et `public-migration-readonly`, déjà manuels), analyse YAML des conditions
`if:` de job :
- **Lançables à la main : 35** (33 parmi les 47). 12 sans aucune condition
  PR ; 23 dont la condition de job autorise explicitement `workflow_dispatch`.
  18 de ces 35 utilisent `HELIUS_API_KEY` : chaque lancement consomme du quota
  et demande un budget.
- **Devenus inopérants : 13** (tous leurs jobs exigent un événement
  `pull_request` ou un label) : `bitquery-four-official-samples-once`,
  `free-public-solana-cohort`, `free-public-solana-forward-paper`,
  `genuine-signed-master-paper-replay`, `helius-recent-signed-sol-trades`,
  `helius-rolling-signed-paper`, `helius-signed-master-paper`,
  `helius-sol-forward-paper-cycle`, `public-signed-receipt-one-shot`,
  `render-master-readiness-smoke`, `render-public-paper-smoke`,
  `signed-sol-causal-s1s2-quote-research`, `signed-sol-readonly-raydium-quote`.
- **Partiel : 1** : `helius-historical-ed25519-replay` (le job
  `official-four-table-vendor-sample` exige un label).
Les rendre lançables exige d'éditer leur `if:` : décision du propriétaire,
avec budget, workflow par workflow. Non fait ici.

## 5. Dernier état réellement testé

Commande de référence (harnais isolé, sans réseau, sans `.env`, avertissements
en erreur) :
`python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error`
(`check.py` n'existe pas ; `tools/offline_check.py` vient de #89. Pour `main`,
qui ne l'a pas, la même copie a été posée en fichier non suivi.)
Dépendances : `requirements*.txt` de la branche, pins `pandas==2.3.3`,
`numpy==2.3.4`. 2026-11-03.

| Révision | Python | Résultat | Code | stderr |
|---|---|---|---|---|
| `main` `d9b950e` | 3.12.3 | 1358 réussis, 1 ignoré, 242 sous-tests | 0 | vide |
| `main` `d9b950e` | 3.13.18 | 5 échecs, 1 erreur, 1352 réussis, 1 ignoré, 242 sous-tests ; 6/6 = `ResourceWarning` SQLite | 1 | vide |
| intégration `e301bfe` (ronde 1) | 3.12.3 | 4011 réussis, 1 ignoré, 242 sous-tests | 0 | vide |
| intégration `e301bfe` (ronde 1) | 3.13.18 | 17 échecs, 3 erreurs, 3992 réussis ; 20/20 = `ResourceWarning` SQLite | 1 | vide |
| intégration `16331cd` (ronde 2) | 3.11.18 | **4014 réussis, 1 ignoré, 242 sous-tests** | 0 | vide |
| intégration `16331cd` (ronde 2) | 3.12.3 | **4014 réussis, 1 ignoré, 242 sous-tests** | 0 | vide |
| intégration `16331cd` (ronde 2) | 3.13.18 | **4014 réussis, 1 ignoré, 242 sous-tests** (3 exécutions identiques) | 0 | vide |

CI GitHub Actions sur `16331cd` : `rugger-isolated-ci` (3.11, harnais,
`-W error`) run 41706205234 **succès**, 4014 réussis ; `offline-tests` (3.13,
harnais, `-W error`) run 41706205137 **succès**, 4014 réussis ; `paper-terminal-ci`
run 41706205152 **succès** (Linux + Windows 3.12 et 3.13). Avant correction
(`2a17093`) : `rugger-isolated-ci` échouait (`streamlit` absent, 3.11) et
`offline-tests` aussi (`cryptography` absent, 23 modules LIVE).

Le seul ignoré est `tests/test_research_pipeline.py:17` (« base utilisateur
absente », attendu sans base locale). Les échecs 3.13 de la ronde 1 (et les 6
de `main`) avaient tous la même cause, des connexions SQLite non fermées ;
corrigée en ronde 2 (§7). Aucun échec fonctionnel.
Mesures antérieures, `pytest` simple sans `-W error` : `main` 1358,
#90 1404, #89 3926.

Aucun de ces tests ne prouve une exécution réelle ni une rentabilité.

## 6. Prochaine mission prioritaire

1. ~~`#89 + main + #90`, conflits résolus côté `main`, `schedule:` désactivés,
   suite complète publiée.~~ Fait sur `integration/consolidation-20261103`
   (§4 bis), en attente de revue. **Le propriétaire fusionne, jamais un agent.**
2. ~~Corriger les connexions SQLite non fermées (Python 3.13 `-W error`).~~
   Fait en ronde 2 ; le CI 3.13 tourne désormais en mode strict.
3. Fermer les 41 PR contenues dans #89 ; rebaser #92–#97 et #99 sur la
   nouvelle référence.
4. Déplacer les 40 sondes hors de `bot/live` (aucun changement de logique).
5. Supprimer `bot/bot/`, `tests/tests/`, `*.bak*`, `*.avant_correctif`
   après revue de #94 ; archiver les notes racine dans `docs/history/`.

Chaque étape = une PR courte, testée, réversible.

## 7. Blocages

**Techniques**
- ~~Python 3.13 + `-W error` échouait (déjà sur `main`).~~ **Résolu en ronde 2.**
  Cause : Python 3.13 signale toute `sqlite3.Connection` non fermée ; le
  ramasse-miettes levait l'avertissement dans un test sans rapport. Localisé
  (`PYTHONTRACEMALLOC=1`) : 75 fuites, 23 lignes. Produit : 2 sites corrigés,
  `bot/dashboard/local_db.py:38` (`with sqlite3.connect()` ne ferme pas) et
  `bot/live/journal.py` (connexion laissée ouverte si l'initialisation échoue,
  prouvé par un test sur fichier corrompu ; ajout de `with`). Les 69 autres
  `sqlite3.connect` du produit ferment (`closing()`, `close()` ou fermeture
  par l'appelant ; certains seulement sur le chemin normal, pas en `finally`). Tests : 19 `with ... as con`
  fermés par `closing()`, 8 `addCleanup(con.close)`, et `tests/conftest.py`
  ferme à la fin de chaque test les `ExecutionJournal` qu'il a ouverts
  (seuls les tests en créent ; `sqlite3.connect` n'est pas intercepté, donc une
  fuite du produit resterait visible).
- 13 workflows manuels sont inopérants et 1 est partiel (liste en §4 bis) :
  leurs jobs exigent un événement PR ou un label. 18 workflows lançables
  utilisent `HELIUS_API_KEY`. Chaque réactivation demande une revue et un budget.
- `bitquery-four-official-samples-once.yml` (#88) était du YAML invalide
  (nom d'étape avec « : » non cité), donc rejeté par GitHub : corrigé.
- `tools/offline_check.py` ne copiait pas les outils et fixtures `.json.gz`
  de la pile B : 2 erreurs de collecte. Liste blanche étendue à 4 chemins
  explicites et aux `.json.gz` sous `tests/fixtures/` seulement.
- `main` non protégé ; l'identité connectée est administratrice. Les règles des
  agents ne sont pas une barrière technique.
- Tâches planifiées (relu le 2026-11-03 vers 19:50 UTC, inchangé depuis
  18:04) : agent dev **désactivé** depuis 18:01:43 UTC (dernier déclenchement
  17:11:51, aucun travail ; dernier push d'un agent dev à 11:16 UTC) ;
  validation **active**, quotidienne à 06:07 UTC malgré son nom « no
  recurrence » ; relecteur **actif**, ponctuel 2027-01-01. Aucune exécution
  GitHub Actions déclenchée par `schedule` dans l'historique du dépôt. Sessions
  Claude visibles : une revue indépendante de #101 en attente d'une réponse du
  propriétaire ; une session « Census » a poussé `claude/admiring-curie-r2gl1p`
  (sans PR, hors périmètre de cette consolidation). Détail dans
  `docs/MASTER_CONTINUITY.md`.
- `BACKLOG.json` a `start_new_work: false` sur cette branche, mais **`true`**
  sur `claude/autonomy-framework-20261103`, que lisent les routines. La pause
  effective est l'état de la tâche planifiée.
- `data/` est ignoré par git : seules 3 archives de pools SOL sont versionnées
  (fixtures #90).

**Économiques**
- P3 : **NO-GO / INSUFFICIENT DATA** (*historique*, non contredit). Pas de
  couverture indépendante, frais complets, sorties qualifiées ni réconciliation.
- Seuils Master protégés : 50 cycles économiques qualifiés et 20 créateurs
  indépendants avant toute entrée opérationnelle — non atteints.
- Latence d'exécution (2 slots) : hypothèse non vérifiée.
- Coût des tentatives échouées et loyer : voir ci-dessous.

## Independent audit findings, 2026-11-03

Niveau de preuve : *mesuré* sur les fixtures versionnées
`tests/fixtures/launchlab_sol_pools/` (3 pools SOL), sauf mention contraire.

1. **`depth_usd` reclassé `NEEDS_EXTRA_READS`** dans
   `tools/master_feature_inventory.py` et son test : la capacité de courbe est
   exacte en SOL, mais le champ est en USD et exige un taux absent des
   événements. Comptes : **13 / 5 / 16 / 3** (événements / transactions /
   lectures supplémentaires / inconnu), au lieu de 14/5/15/3. Rapport #98
   (`docs/research/MASTER_FEATURE_RECONSTRUCTIBILITY.md`) mis à jour.
2. **Fixtures trop courtes pour les fenêtres.** Les pools couvrent **16, 31 et
   29 s**. `momentum_60s`, `momentum_300s`, `price_change_5m_pct`,
   `price_change_1h_pct` valent `None` ; `tx_buys_5m`, `tx_sells_5m` sont des
   fenêtres **partielles**. Exactement **7** `SignalFeatures` sont calculables
   entièrement (`signal_time`, `observed_at`, `fee_bps`, `slippage_bps_est`,
   `bundle_transactions`, `bundle_wallets`, `same_slot_wallets`) plus 2
   comptes partiels (`computable_on_span`, testé). Tout run du Master sur ces
   fixtures est un **Master tronqué** et doit être étiqueté ainsi. Aucun run du
   Master n'est présenté ici.
3. **Le taux de frais de courbe est une entrée par pool** : **10 000 / 12 500 /
   18 000 ppm** observés, un taux par pool. Recherche des valeurs codées en dur
   (`12500`, `12_500`, `0.0125`, `1.25 %`, constantes `*FEE_RATE*`) dans
   `bot/` et `tools/` hors `bot/bot` :
   - `bot/market/replay.py:30` `DEFAULT_FEE_RATE_PPM = 12_500`, défaut de
     `ExecutionModel` et donc de `replay()` : **corrigé** (correctif sûr, seul
     appelant hors tests = `tools/launchlab_baseline_report.py`, qui passait
     déjà le taux observé). Par défaut, le taux est lu sur le dernier événement
     réel à l'indice de décision ; un taux explicite reste prioritaire ; taux et
     source sont enregistrés dans `TradeResult`. Tests :
     `tests/test_replay_fee_rate_per_pool.py` (4).
   - `tests/test_launchlab_market_events.py:28`, `tests/test_launchlab_replay.py:12` :
     constantes de fixtures synthétiques, légitimes.
   - `tests/test_p3_quotes.py:25,105` : `priceImpactPct`, pas un taux de frais.
   - Hypothèse codée en dur à revoir (non corrigée, moteur LIVE) :
     `share_fee_rate_ppm=0` dans `bot/live/route.py:186` et
     `bot/live/evidence.py:414`.
4. **Transactions échouées : 59 / 173 signatures (34,1 %)** dans les fixtures.
   Le modèle de coût doit porter un terme « tentative échouée » (frais de base +
   priorité payés sans fill). `bot/market/replay.py` n'en a pas. Pour **notre**
   bot, ce taux est **UNKNOWN** tant qu'il n'est pas mesuré ; le taux observé
   chez les autres traders n'est pas transposable.
5. **Loyer ATA / WSOL.** Règle retenue : capital **immobilisé**
   (`rent_locked`), **récupérable** à `CloseAccount` (`rent_recovered`),
   **passé en perte** (`rent_written_off`) seulement sur impossibilité prouvée
   (poussière après vente partielle, compte orphelin, jeton gelé, clôture jamais
   exécutée). Part non récupérable = frais des transactions create/close quand
   elles ne sont pas groupées avec l'achat/la vente. Pas d'ajout au plancher de
   coût comme perte par défaut. État du code (*code*) :
   - LIVE : `bot/live/journal.py` a `locked_rent_lamports` par position,
     réconcilié par `bot/live/engine.py:228` ; `bot/live/positions.py:161`
     le traite comme actif immobilisé. **Lacune** : pas de `rent_recovered` ni
     de `rent_written_off`.
   - `bot/p3/own_fee_bounds.py` : `ata_rent_locked_lamports` +
     `ata_recovered_at_horizon` ; compte le loyer en borne haute de coût s'il
     n'est pas récupéré à l'horizon. Cohérent comme borne, pas comme perte.
   - `bot/market/replay.py` : suppose le loyer remboursé, **sans** frais de la
     transaction de clôture. **Lacune.**
   - Registre PAPER (`bot/analyser`) : aucun champ de loyer. **Lacune.**
   Ces lacunes ne sont pas corrigées dans cette PR (consigne).

## 8. Décisions et validations nécessaires (propriétaire)

| # | Décision | Recommandation |
|---|---|---|
| D1 ✅ approuvée | **Consigne active** : `AGENTS.md` de `main` dit « PAPER ONLY, aucun composant réel, première mission en lecture seule » ; celui de #89 et `LIVE_READINESS_MANDATE.md` (29/10) autorisent le développement LIVE désarmé. | Adopter la version #89 lors de l'intégration : développement LIVE autorisé, **aucune** signature réelle, aucun fonds, activation = décision séparée. |
| D2 ✅ approuvée | Pile A comme base de la référence (plutôt que reconstruire depuis `main`). | Oui : verte, contient Master + LIVE ; reconstruire serait une réécriture géante. |
| D3 ✅ approuvée | Workflows réseau automatiques de #89. Mesure corrigée : **2** `schedule:` réels (Helius, toutes les 6 h), pas 4 ; et 45 workflows réseau déclenchés par `pull_request`, qui auraient tourné à l'ouverture de la PR d'intégration. | Fait : tous en `workflow_dispatch` seul ; réactiver un par un avec budget. |
| D4 | Interface unique : Streamlit Rugger Wallet, Render ou Vercel. | Une seule ; les deux autres archivées. |
| D5 | « Suivi Axiom » : sens exact ? (voir le portefeuille LIVE dans Axiom, ou exporter les positions vers Axiom ?) | Préciser ; rien n'existe aujourd'hui. |
| D6 ✅ approuvée | Agent planifié : continuer sur la pile B pendant l'intégration ? | Le mettre en pause pendant l'intégration, puis le rebaser sur la nouvelle référence. |
| D7 | Protection de `main` (GitHub Pro payant) ou risque accepté. | Décision de coût. |

## Règle de mise à jour

Toute PR qui change l'état du projet met à jour **ce fichier** (sections
concernées seulement) avec révision, commande et résultat. Les journaux détaillés
vont dans la description de la PR, pas dans un nouveau fichier d'état.
