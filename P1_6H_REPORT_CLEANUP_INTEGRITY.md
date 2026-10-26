# P1.6h — Intégrité des rapports et fermeture des ressources PAPER

Date : 26 octobre 2026. Référence : `e665d5ddaf8713e0eadacebfaaf8a02299994b59`.
Dépôt : `laurentmaxence13-svg/rugger_bot_v1`. Branche locale :
`fix/p16h-report-cleanup-integrity`. Aucun commit, push ou fusion.

## Périmètre et contrôles préalables

Les instructions AGENTS.md, le protocole et les documents d'audit/plan du
22 octobre ont été lus. Leur ancien résultat 46/1/1 décrit une archive historique,
et ne constitue pas la baseline du SHA demandé.

Le nouveau worktree obligatoire est
`C:\Users\maxen\Downloads\rugger_bot_v1_p16h_workspace`.
Depuis ce répertoire explicite, avant modification :

- `git rev-parse --show-toplevel` : exactement ce worktree ; aucun lien indiqué
  sur son répertoire racine.
- HEAD détaché initial, HEAD et origin/main au SHA demandé.
- origin : dépôt GitHub demandé ; fichiers suivis inventoriés.
- `git status --porcelain=v1 --untracked-files=all` : stdout vide, stderr vide,
  code 0. `git status --untracked-files=all` : working tree clean, stderr vide,
  code 0.
- `.pytest_cache` et `tests/.pytest_cache` absents du nouveau worktree : aucun
  accès aux caches de l'ancien dossier. Le partage des seules métadonnées `.git`
  avec l'ancien dépôt est le fonctionnement attendu de ce worktree.

La première création de branche a rencontré un refus d'écriture du verrou Git
par le sandbox. La même création, déjà autorisée par la mission, a réussi avec
l'exécution étendue. Aucun changement d'ACL ou de configuration Git, aucune
suppression et aucun masquage par .gitignore.
Une commande ultérieure `git -C` depuis la copie temporaire a rencontré le contrôle
de propriété Git ; les commandes relancées depuis le worktree explicite ont
réussi sans changer `safe.directory`. Tous les contrôles finaux utilisent ce cwd.

## Causes démontrées par le code de référence

| Source au SHA de référence | Cause et conséquence reproduites |
|---|---|
| `bot/analyser/paper_engine.py:1249-1260` | Connexion principale et schémas initialisés avant le try : une exception après acquisition SQLite saute la fermeture. |
| `paper_engine.py:1267-1271` | Affectation après `await LiveBehaviorFetcher(...).start()` : une session acquise dans start() peut devenir inaccessible au nettoyage si start() échoue. |
| `paper_engine.py:1288` | Le contexte HTTP nettoie une entrée réussie ; une entrée partielle en échec n'appelle pas automatiquement sa sortie. |
| `paper_engine.py:1309-1331` | Le rapport périodique partage le catch réseau de collect_once : un TimeoutError de rapport peut être traité comme une lenteur de cotation et laisser continuer les entrées. |
| `paper_engine.py:1333-1348` | Résumé, capital, console et écriture finale précèdent les fermetures : chacun peut empêcher fetcher.close et con.close. Une erreur du fetcher saute SQLite. Le finally peut remplacer l'exception moteur ou l'annulation. |
| `paper_engine.py:769-771,1343-1344` | Écriture directe du fichier cible : une écriture interrompue écrase le rapport précédent par du JSON partiel. |
| `paper_engine.py:1377-1395,1434-1446` | Acquisition des tâches avant protection complète ; exceptions des tâches récupérées puis ignorées ; diagnostic tardif absent après dépassement du délai. |
| `bot/analyser/multi_creator_research_engine.py:25-26,30-63` | Connexion autonome du schéma : PRAGMA, DDL ou commit en échec peuvent sauter close, avant même l'ouverture de la connexion principale du moteur. |
| `bot/analyser/behavior_pipeline.py:212-218` | Connexion autonome du cache : échec du PRAGMA, SELECT ou fetchall avant close. Protéger seulement la connexion principale ne suffit pas. |

Les sources actives sont `bot/`. Les copies historiques `bot/bot`, `tests/tests`,
.bak et .avant_correctif restent intactes.

## Reproduction avant correctif et résultats exacts

Interpréteur existant, sans installation :
`C:\Users\maxen\Downloads\rugger_bot_v1_paper (1)\rugger_bot_v1\.venv\Scripts\python.exe`.
Python **3.13.15**, pytest **9.1.1**, aiohttp **3.14.3**, Windows PowerShell 5.1.
Ce chemin réutilise uniquement l'interpréteur/les dépendances ; les imports du bot
proviennent des copies isolées.

Copies de sources et fixtures de test suivies, sans .git, .env, data utilisateur,
base utilisateur ou launchlab_tx.json racine :

- Référence : `C:\Users\maxen\AppData\Local\Temp\rugger_p16h_1f3dd657737746918d0709f3ee7ac1ce\baseline`.
- Correctif : même racine temporaire, sous-dossier `patched`.

Le lanceur neutralise dotenv avant les imports ; son audit hook bloque les
connexions, bind et résolutions réseau hors socketpair interne local d'asyncio.
L'exception socketpair est locale au thread. Les plugins pytest automatiques et
les écritures de pyc sont désactivés. Les bases des tests sont en mémoire ou dans
des répertoires temporaires synthétiques. Aucun vrai scanner, RPC, WebSocket ou
collecteur réseau n'a été lancé. Une session aiohttp réelle sans requête a été
utilisée pour vérifier son état fermé.

| Exécution | Résultat réellement observé |
|---|---|
| Suite active originale, avant correction | **414 passed, 1 skipped, 242 subtests passed**, 26,45 s, code 0 |
| Première reproduction avec fixtures corrigées | **25 failed, 5 passed**, 0,63 s, code 1 |
| Tests d'acceptation finaux sur sources originales | **57 failed, 14 passed**, 1,51 s, code 1 |
| Nouveaux tests + supervision existante, après correction, `-W error::ResourceWarning` | **81 passed**, 1,52 s, code 0 |
| Suite active finale | **485 passed, 1 skipped, 242 subtests passed**, 27,30 s, code 0 |

Les 71 nouveaux cas sont des tests pytest, pas des sous-tests comptés deux fois.
Les échecs avant patch incluent les attentes nouvelles d'écriture atomique et de
diagnostic structuré ; un test de compatibilité vise également un helper absent
de la référence. La première reproduction de 25 échecs est indépendante de ces
nouveaux helpers et démontre les défauts opérationnels initiaux.

Une première version de la fixture d'horloge consommait des ticks lors des appels
internes d'initialisation : les scénarios normaux ne collectaient rien. Elle a été
corrigée avant de retenir les reproductions ci-dessus. Deux assertions de fixtures
ont ensuite été corrigées : dossier partagé des deux rapports lors d'un mkdir en
échec, et création préalable de launch_candidates pour tester un rapport réel.
Aucune protection de production n'a été affaiblie pour satisfaire ces assertions.

Le skip demeure `tests/test_research_pipeline.py:17`, « base utilisateur absente ».
La suite active complète utilise `tests --ignore=tests/tests`, comme la baseline ;
les doublons historiques et une compilation récursive des copies inactives ne
font pas partie de cette validation.

## Correctif exact, acquisition et fermeture

Dans `paper_engine.py` :

- `_raise_paper_failures` (ligne 661) conserve les objets exceptions et leur
  provenance dans `paper_failures`. L'exception principale est relancée, avec notes
  sous Python >=3.11 et chaînage natif des erreurs secondaires sous Python 3.10.
  Les diagnostics déjà attachés sont conservés lors de la supervision externe.
- `_await_paper_cleanup` (ligne 691) possède une tâche de nettoyage, la protège par
  shield et l'attend même lors d'annulations répétées du parent.
- `_write_json_report` (ligne 707) centralise la publication atomique.
- `run` (ligne 1300) protège les acquisitions dès l'initialisation. Les échecs de
  rapport/console sortent de la boucle et ne sont plus confondus avec les erreurs
  réseau temporaires de collecte. Les paramètres de retry de collecte restent
  identiques.
- `run_with_scanner` (ligne 1471) protège l'acquisition progressive des tâches.
  `_stop_supervised_tasks` (ligne 1566) distingue les exceptions déjà observées,
  les erreurs simultanées, les erreurs de nettoyage sous annulation et les tâches
  encore en attente. Les erreurs tardives passent au gestionnaire d'exceptions
  de la boucle, y compris après une annulation portant des erreurs secondaires.

Ordre d'acquisition :

1. Connexion courte de Database : déjà protégée par contextlib.closing.
2. Connexion courte du schéma de recherche : PRAGMA, DDL inchangé, commit, fermeture.
3. Connexion principale : PRAGMA, setup, schémas d'audit/statut, portefeuille et
   référence de capital de session.
4. Objet fetcher, conservé **avant** start ; start peut acquérir sa session RPC.
5. Session HTTP du moteur, conservée **avant** son entrée de contexte.
6. Connexions courtes du cache lors des lectures, chacune fermée avant le parsing.

Ordre de sortie du moteur, avec chaque tentative protégée indépendamment :

1. Fermeture de la session HTTP créée par le moteur, si acquise.
2. Fermeture du fetcher créé par le moteur, même après start partiellement échoué.
3. Lecture du résumé et du capital final si l'initialisation financière est achevée.
4. Fermeture de la connexion principale, même si les étapes précédentes échouent.
5. Impression et publication du rapport de session à partir des données en mémoire.
6. Propagation de l'exception principale et des diagnostics secondaires.

Le résumé est lu pendant que SQLite est encore disponible. Son impression se fait
après les tentatives de fermeture. Aucune lecture financière n'est inventée si
l'initialisation ou la lecture du résumé échoue : l'ancien rapport reste présent.

La désactivation historique de l'enrichissement optionnel lorsque son constructeur
échoue avant acquisition est conservée. Un échec de start après acquisition est
propagé et nettoyé ; il ne poursuit plus une session avec une ressource partielle.
Le constructeur inspecté du fetcher ne crée pas de session : celle-ci est acquise
dans SolanaRPC.__aenter__. Le cas d'échec après cette acquisition est testé.

Les deux autres fichiers de production sont strictement nécessaires :
`multi_creator_research_engine.py` protège les connexions de db_connect et
ensure_schema ; `behavior_pipeline.py` protège celle de load_cached_transactions.
En cas de double échec, ils relancent l'erreur de lecture/initialisation avec
l'erreur de fermeture comme cause. Les SQL, réglages PRAGMA et traitements de
données restent sémantiquement identiques. Aucun autre appel de recherche n'est
refactoré. Database, qui possède déjà son closing, n'est pas modifié.

Le moteur ferme uniquement les objets qu'il a créés. Le gate fourni par un appelant
n'est pas fermé. paper_report emprunte une connexion et la laisse utilisable.
Le moteur tente chaque fermeture une seule fois ; il n'annonce jamais sa réussite
si elle a levé une exception.

## Erreurs, annulations et supervision

- Erreur moteur seule : même objet exception relancé.
- Erreur moteur puis rapport/fermeture : principale conservée, secondaires attachées
  avec leur étape ; aucune réussite renvoyée.
- Annulation pendant collecte, start ou nettoyage : reste CancelledError ; les
  diagnostics des fermetures sont conservés. Une annulation reçue pendant le
  nettoyage conserve la priorité d'annulation, avec les autres erreurs accessibles.
- Session financière échouée/annulée dont les métriques sont lisibles : conclusion
  explicitement `ECHEC`/`ANNULEE`, sans modifier les métriques ni ajouter de faux succès.
- Fin normale : schéma, calculs, valeurs et conclusion existants conservés.
- Scanner terminé ou en échec : contrat RuntimeError avec cause conservé ; nettoyage
  du moteur et du scanner. Les gardes d'entrée restent identiques.
- Délai de supervision dépassé : erreur explicite avec noms des tâches encore en
  attente ; second cancel et observation des erreurs tardives. La tâche n'est pas
  déclarée terminée. Les tests libèrent ensuite volontairement leur tâche réfractaire.

La compatibilité syntaxique Python 3.10 a été vérifiée par ast.parse sans pyc ;
le chemin sans add_note est simulé par test. Seul Python 3.13.15 a été exécuté.

## Intégrité JSON

Le payload est sérialisé avant publication. Un NamedTemporaryFile unique est créé
dans le même répertoire que la cible ; son handle est fermé avant write_text et
os.replace pour Windows. Le remplacement n'a lieu qu'après écriture complète.
Le temporaire est retiré sur erreur ; un échec de retrait reste diagnostiqué.
Le rapport périodique conserve son comportement allow_nan existant ; le rapport
final conserve allow_nan=False. L'ordre des clés et l'indentation restent inchangés.

Une erreur de mkdir, sérialisation, écriture partielle ou remplacement laisse
l'ancien rapport valide intact. Sans ancien rapport, aucun nouveau JSON partiel
n'est publié. Aucun temporaire ne reste dans les scénarios d'échec testés.
L'impression de la destination du rapport final précède son remplacement : une
exception de console à cet endroit ne remplace pas le rapport précédent.
Une conclusion financière normale affichée avant une erreur ultérieure d'écriture
ne signifie pas que l'exécution a réussi : l'exception de rapport reste propagée.

## Comparaisons normales avant/après

Six sessions bornées à 40 secondes simulées utilisent les vrais collect_once,
record_quote, calculs de risque, rapports, audits et exports, avec seulement les
cotations, la décision de fixture, l'horloge et la session de transport remplacées.
Les payloads LaunchLab du cache sont synthétiques. Aucun critère de production
n'est changé par ces fixtures.

| Session | Trades clos | P&L net | Capital final |
|---|---:|---:|---:|
| Vide | 0 | 0 SOL | 10 SOL |
| TP : .001 → .0012, coût 200 bps, position 1 SOL | 1, TP | +0,18 SOL | 10,18 SOL |
| SL : .001 → .0008, mêmes coût et position | 1, SL | −0,22 SOL | 9,78 SOL |
| Décision rejetée | 0 | 0 SOL | 10 SOL |
| Garde scanner fermée | 0 | 0 SOL | 10 SOL |
| Lancement non daté | 0 | 0 SOL | 10 SOL |

Comparaison exacte : JSON périodique et de session, y compris leurs octets ;
toutes les tables et définitions SQLite ; transactions, décisions, audit et statuts ;
CSV prix/dataset avec octets, dont des lignes de dataset non vides ; conclusions
et console, après retrait de la seule ligne contenant le chemin temporaire du
rapport. Les fichiers SQLite physiques ne sont pas comparés octet par octet.

Les deux artefacts `baseline/normal_scenarios.json` et
`patched/normal_scenarios.json` sont identiques, SHA256 commun :
`9b16bb8aed90d6c818a871ef1613bfea31b49813f9bd8a6f8e1f399e7f9fca9a`.

Les fonctions collect_once, _realized_metrics, _performance_metrics, _session_summary,
_print_session_summary, gardes scanner, ordonnanceur et observation non datée sont
identiques par AST. paper_trader.py (FIFO, TP/SL/trailing, frais et capital),
final_decision_engine.py, scanner/parser/recovery/backfill et research_pipeline.py
(exports) sont identiques octet par octet à la référence. Le calcul de quote_coverage
n'est pas corrigé : P1.6i reste hors périmètre.

## Couverture des exigences de défaillance

| Exigences de la mission | Preuves |
|---|---|
| 1-2,23,32 : rapports normaux, fin bornée | test_normal_session_has_no_orphans_and_finances_unchanged ; six test_synthetic_normal_sessions ; comparaison avant/après complète |
| 3-8 : mkdir, JSON, écriture, replace, rapport précédent, pas de JSON partiel/temporaire | test_session_report_failure_closes_every_resource ; test_periodic_report_failure_preserves_file_and_closes ; test_failed_new_periodic_report_never_publishes_partial_json |
| 9-10 : résumé, capital final, impression | injections summary/print ; test_final_capital_read_error_never_skips_closes ; test_final_console_error_preserves_previous_session_report |
| 11-15 : fermeture fetcher/SQLite/HTTP, double erreur, erreur moteur + rapport/close | test_close_failures_are_visible_and_do_not_skip_other_closes ; test_collection_error_remains_primary ; diagnostics imbriqués sous supervision |
| 16-19 : annulation, start partiel, initialisations et HTTP | test_partial_initialization_is_cleaned ; test_research_initialization_closes_its_own_connection ; test_cache_read_failure_closes_its_separate_sqlite ; tests real_fetcher/actual_aiohttp/repeated_external_cancellation/cancellation_during_fetcher_start |
| 20-22,24-25 : sans fetcher/scanner, supervision, erreurs simultanées, pas d'orphelins | tests live False/True ; suite existante test_scanner_supervision ; tests simultaneous_scanner, supervisor_partial_acquisition et tâches tardives/réfractaires ; égalité asyncio.all_tasks dans les scénarios concernés |
| 26-28 : pas de faux succès, pas d'entrée après erreur, P&L | conclusions ECHEC/ANNULEE ; test_report_failure_stops_before_next_paper_entry ; mêmes tables/capitaux/rapports sur six sessions |
| 29-31 : P1.6d/f/g, FIFO, TP/SL/trailing | suites existantes loss_date_guard, scanner_entry_integrity, undated_launch_observation, scheduling, atomic_entry/close et paper_pipeline toutes rejouées ; fonctions et fichiers financiers inchangés |
| 33 : fichiers/connexions | compteurs de chaque tentative ; session aiohttp.closed ; BEGIN EXCLUSIVE sur base synthétique après erreur ; zéro temporaire ; groupe ciblé sous ResourceWarning en erreur |
| 34 : non-régression | suite active complète, résultat exact ci-dessus |

Les doubles fermetures ne sont pas utilisées pour masquer une erreur. Dans les
fixtures qui font volontairement échouer close sans libérer le handle, le test
constate l'échec puis libère lui-même la ressource synthétique en teardown.
Cela démontre les tentatives indépendantes, pas une fermeture réussie fictive.

## Reproduire la validation

Dans une copie jetable des seules sources/fixtures, sans .git et sans .env,
avec l'interpréteur existant :

```text
python -B tests/p16h_isolated_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
python -B tests/p16h_isolated_runner.py -q tests/test_paper_report_cleanup.py tests/test_scanner_supervision.py -p no:cacheprovider -W error::ResourceWarning
python -B tests/p16h_isolated_runner.py --compare
```

Le lanceur refuse une racine contenant .git. Pour reproduire la référence,
extraire les sources suivies au SHA demandé dans une autre copie, y ajouter les
mêmes nouveaux tests et le lanceur ; exclure le nouveau fichier de tests pour
rejouer les 414 tests de baseline. L'exécuter seul reproduit les échecs avant patch.
`--compare` écrit l'artefact normal_scenarios.json dans chaque copie ; comparer
leurs SHA256 ou leur contenu exact. Aucun fichier de base réel ne doit être copié.

## Fichiers livrés et rollback

Trois fichiers de production seulement :

1. `bot/analyser/paper_engine.py` : lifecycle, erreurs, rapports atomiques, supervision.
2. `bot/analyser/multi_creator_research_engine.py` : durée de vie des connexions
   d'initialisation, sans changement de schéma ni de recherche.
3. `bot/analyser/behavior_pipeline.py` : durée de vie de la connexion de lecture
   du cache, sans changement de classification ni de stratégie.

Ajouts : `tests/test_paper_report_cleanup.py` (71 cas),
`tests/p16h_isolated_runner.py` (validation hors réseau et comparaison),
et le présent `P1_6H_REPORT_CLEANUP_INTEGRITY.md`.
Aucun autre fichier suivi modifié. Référence de rollback : SHA initial ; les
sources originales sont également conservées dans la copie baseline.

Rollback proposé, non exécuté : conserver un diff des trois fichiers et une copie
des trois nouveaux fichiers hors du worktree, puis, depuis le nouveau worktree :

```text
git restore --source=e665d5ddaf8713e0eadacebfaaf8a02299994b59 -- bot/analyser/paper_engine.py bot/analyser/multi_creator_research_engine.py bot/analyser/behavior_pipeline.py
```

Déplacer ensuite les trois ajouts sauvegardés hors du worktree si un état
entièrement propre est souhaité. Ne pas utiliser git clean, remplacer un dossier
complet, toucher à une base ou aux permissions. Aucun commit de rollback nécessaire.

## Limites et risques résiduels

- Démontré par le code et reproduit : erreurs injectées, fermeture tentée,
  absence de tâche résiduelle dans les scénarios coopératifs, non-régression
  synthétique des rapports et finances.
- Inconnu : comportement d'un vrai fournisseur Helius, RPC/WS, scanner en production
  ou environnement marché ; aucun de ces services n'a été interrogé.
- Une fermeture qui lève ou ne revient jamais ne peut pas être déclarée réussie.
  Les fermetures async volontairement infinies peuvent laisser des tâches en attente ;
  la supervision les diagnostique, sans pouvoir forcer la libération d'une ressource
  tierce réfractaire. Les tests réfractaires se terminent après libération explicite.
- Un constructeur tiers qui lève sans retourner le handle de ses allocations reste
  responsable de celles-ci ; les objets récupérables et entrées partielles après
  acquisition sont couverts ici.
- Le remplacement atomique protège contre les écritures partielles ordinaires, pas
  contre une coupure électrique avec garantie de durabilité fsync, ni contre un kill
  du processus avant son finally. Un unlink refusé reste une erreur diagnostiquée.
- Un ancien rapport conservé après échec demeure historique : son timestamp ne vaut
  pas preuve de réussite de la session en échec.
- Pas de test runtime sous Python 3.10 ; uniquement syntaxe et simulation du chaînage.
- Aucun changement de capital initial 10 SOL, allocation 10 %, seuil, frais, TP/SL,
  trailing, limite de perte, décision, historique financier ou export.
- Aucun GO global P2 et aucune rentabilité démontrée.
