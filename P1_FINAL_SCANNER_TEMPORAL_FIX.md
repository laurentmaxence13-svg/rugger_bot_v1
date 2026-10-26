# Correctifs finaux scanner et intégrité temporelle avant P2

26 octobre 2026 — PAPER ONLY.
Référence exacte : `1c6175aa33190dc82d442e105e72a77e85a3c78c`.
Worktree : `C:\Users\maxen\Downloads\rugger_bot_v1_p16h_workspace`.
Branche : `fix/p1-final-scanner-temporal-gates`.
Aucun commit, push, fusion ou démarrage P2.

## Résultats et portée

- B01/B02 : **VALIDEE** sur le scanner intégré et sa récupération interne.
- B03/B04 : **VALIDEE** sur research_pipeline.backtest, momentum_backtest,
  behavior_pipeline.behavior_backtest et leurs grilles appelantes.
- Les voies héritées creator_backtest_v25/v26 conservent des découpages non sûrs.
  Elles sont inventoriées dans P1_FINAL_GATE_RECHECK.md, sans prétendre bénéficier
  du correctif. Les verdicts globaux y restent NO-GO.

La mission modifie les droits d'entrée en cas de panne et les cohortes temporelles
d'évaluation. Aucun seuil de sélection, score, règle TP/SL/trailing, coût, capital
initial 10 SOL ou allocation 10 % n'est changé.

## Contrôles préalables et isolation

AGENTS.md et l'audit P1 ont été lus ; les tests de caractérisation et les sources
actives ont été examinés. Depuis le cwd obligatoire, avant toute écriture :

| Contrôle Git | stdout | stderr | Code |
|---|---|---|---:|
| rev-parse --show-toplevel | racine obligatoire exacte | vide | 0 |
| branch --show-current | fix/p1-final-scanner-temporal-gates | vide | 0 |
| rev-parse HEAD origin/main | SHA demandé deux fois | vide | 0 |
| remote get-url origin | https://github.com/laurentmaxence13-svg/rugger_bot_v1.git | vide | 0 |
| status --porcelain=v1 --untracked-files=all | vide | vide | 0 |
| status --untracked-files=all | working tree clean | vide | 0 |
| ls-files | inventaire des fichiers suivis | vide | 0 |

La branche existait déjà. Aucune création de branche, modification d'ACL,
.gitignore, suppression de cache ou git clean. Les historiques bot/bot,
tests/tests, .bak et .avant_correctif restent intacts et ne servent pas de source
active. L'ancien résultat de ZIP n'est pas une baseline de cette mission.

Référence/version de retour arrière : SHA ci-dessus et copie originale dans :
`C:\Users\maxen\AppData\Local\Temp\rugger_p1final_04fb2cdeb78c4965812c836ec166f0a8\baseline`.
Le sous-dossier `patched` contient la copie corrigée testée. Seules des sources et
fixtures suivies ont été copiées, sans .env, base utilisateur, data utilisateur ou
launchlab_tx.json racine.

Interpréteur existant :
`C:\Users\maxen\Downloads\rugger_bot_v1_paper (1)\rugger_bot_v1\.venv\Scripts\python.exe`.
Python **3.13.15**, pytest **9.1.1**, sans installation.
Le lanceur tests/p16h_isolated_runner.py existant, inchangé, refuse une racine avec
.git, neutralise dotenv avant import et bloque connexions/résolutions externes.
Les seuls socketpair locaux internes d'asyncio sont admis, par exception locale
au thread. Plugins pytest automatiques, pyc et cache pytest sont désactivés.
Aucun scanner réel, fournisseur, RPC, WebSocket réel, ordre, signature, argent réel,
portefeuille financé, secret ou base SQLite utilisateur n'a été utilisé.

## Causes et reproductions avant correction

Les lignes de cette section désignent le SHA de référence.

| Défaut | Source et scénario |
|---|---|
| B01 | bot/main.py:59-70 attend les enfants avant de publier disconnected ; paper_engine.py:99-125 vérifie le parent et SQLite, mais pas l'échec déjà survenu d'un enfant. Une clôture d'enfant retardée laisse une fenêtre d'entrée. |
| B02 | bot/main.py:69 et la sortie de recover_transactions utilisent gather(return_exceptions=True) sans exposer les exceptions secondaires. |
| B03 | research_pipeline.py:211,338 et behavior_pipeline.py:319 coupent une liste de créations par nombre d'événements. Même signature et/ou même timestamp peuvent être partagés entre train et test. |
| B04 | Les outcomes sont calculés à horizon futur sans retirer les labels train connus seulement pendant/après le début du test. Le tri des signaux ne garantit pas la disponibilité des résultats. |

Les six caractérisations originales donnent **6 passed en 0,62 s** : elles
confirment les défauts de référence, pas des propriétés de sécurité satisfaites.
Les assertions devenues positives, copiées dans un fichier de preuve séparé sur
la référence originale, donnent **5 failed, 2 deselected en 0,53 s, code 1** :
refus pendant cleanup avec/sans erreur SQLite, erreur secondaire conservée,
transaction/timestamp non séparables et labels futurs rejetés.

Le fichier temporaire `baseline/tests/test_expected_scanner_temporal_safety.py`
sert uniquement à cette preuve avant patch ; il n'est pas livré. Les fichiers
suivis originaux de la baseline ne sont pas remplacés.

## A — Refus scanner indépendant de SQLite

### Canal de santé et ordre des opérations

Nouveau module `bot/scanner/supervision.py:5`, ScannerHealth, avec une instance
par supervision. Le canal démarre fermé tant qu'aucune tâche n'est enregistrée.
Chaque tâche interne surveillée est enregistrée. Un échec positionne un verrou
mémoire de refus, conserve l'objet exception et réveille un événement de panne.
Cette opération est synchrone : aucune écriture SQLite ni attente de nettoyage
ne précède le refus. La propriété failed ne possède pas de setter de remise à zéro.

Le canal est partagé par main.run, les tâches backfill/récupération, les tâches
réception/worker de recover_transactions et la garde du moteur PAPER. La garde
contrôle le canal ET tous ses anciens contrôles parent/SQLite : âge d'état,
subscribed/caught_up, raison vide, renouvellement depuis le démarrage, receipt
signature/slot. Un canal absent, non démarré ou défaillant refuse l'entrée.

Un état SQL frais ne remet jamais ce verrou à zéro. Le retour à l'autorisation
nécessite un NOUVEAU contexte de supervision, des tâches vivantes, puis un état SQL
réellement renouvelé et vérifié. Les refus transitoires SQLite précédents restent
actifs. Le mode explicite sans scanner conserve son contrat précédent.

bot/main.py:23 possède ses tâches et sa session RPC, y compris un démarrage RPC
partiellement réussi. Un watcher de l'événement de panne réagit même si l'enfant
responsable n'a pas fini son propre cleanup. Le refus ne dépend donc plus de
parent.done() ou du seul résultat d'un accès SQL.

Le callback de publication live mémorise une exception SQLite AVANT qu'elle ne
quitte le flux. websocket._observed_connection signale également les erreurs
survenant dans un transport acquis AVANT sa fermeture asynchrone. Le callback
optionnel on_failure garde le comportement de l'API standalone lorsqu'il n'est
pas fourni. Sous supervision, une telle panne ne peut pas rouvrir les entrées
par simple reconnexion/rafraîchissement dans le même contexte.

Ordre de sortie : refus mémoire déjà effectif → arrêt/attente bornée des enfants
→ publication du dernier état disconnected → tentative de sortie RPC → propagation
des erreurs. Publier l'état final après les enfants évite qu'un enfant interrompu
remplace la cause terminale par « interrupted ». Si cette publication échoue, le
refus tient toujours et la tentative de fermeture RPC a tout de même lieu.

### Préservation des erreurs, tâches et annulations

Les helpers de nettoyage P1.6h ont été extraits de paper_engine vers supervision :
_raise_paper_failures, _await_paper_cleanup et _stop_supervised_tasks. Leurs AST
sont IDENTIQUES à la référence ; paper_engine conserve les imports/alias attendus.
Cette extraction évite de dupliquer les garanties ou de créer un import circulaire
entre scanner et moteur PAPER.

main.run et recover_transactions attendent ce nettoyage protégé par shield.
L'exception principale reste identifiable ; les exceptions des autres tâches,
publication et sortie RPC sont attachées avec provenance dans paper_failures et
notes/chaînage existants. Une annulation reste CancelledError, y compris après
plusieurs cancel pendant le cleanup. Une annulation normale des pairs n'est pas
promue artificiellement comme nouvelle erreur principale.

En cas de plusieurs enfants déjà en échec à l'observation, l'ordre d'acquisition
est utilisé pour leur récupération ; si un signal de panne précède la terminaison
d'un enfant, sa cause enregistrée est immédiatement disponible. Aucun résultat de
gather n'est abandonné. Les dépassements du délai d'arrêt restent explicites et
les erreurs tardives sont diagnostiquées par le helper P1.6h inchangé.
Les coroutines annulées avant leur première exécution sont fermées pour éviter
les RuntimeWarning de coroutine jamais attendue.

### Preuves exécutées

- Refus de la vraie garde et entry_allowed=0, zéro nouveau trade dans la fenêtre
  de cleanup retardé, même avec publication SQLite échouée et état rafraîchi sain.
- Échec du receiver interne avant la fin du nettoyage du worker : parent encore
  vivant, verrou déjà fermé, cause conservée, aucune tâche finale oubliée.
- Notification d'une erreur de transport avant son __aexit__ retardé.
- Erreur de publication live avant teardown du flux ; watcher réveillé et refus
  effectif sans dépendre d'une lecture SQLite.
- Démarrage RPC partiel : une tentative de sortie, même si elle échoue ensuite.
- Plusieurs enfants en échec, plusieurs erreurs de nettoyage et annulations
  répétées : originale/cancellation et secondaires retrouvées par identité.
- Nouvelle supervision : ancien contexte toujours refusé ; nouveau contexte encore
  refusé avant renouvellement SQL, puis autorisé après preuve fraîche.
- Supervision saine réelle, services mockés : une entrée de 1 SOL sur 10 SOL reste
  possible après vérification ; avant le démarrage vérifié, refus.
- Après refus mémorisé, une position existante conserve ses sorties : TP +0,18 SOL
  et capital 10,18 ; SL −0,22 SOL et capital 9,78. Aucun nouveau seuil ajouté.

Ces tests n'utilisent pas de réseau : « transport » et « RPC » sont des doubles.
Les ensembles asyncio.all_tasks avant/après sont comparés dans les scénarios
concernés ; les enfants retenus par une barrière de test sont libérés explicitement.
Une ressource dont close échoue ou refuse de terminer n'est pas déclarée libérée.

## B — Groupes temporels et labels effectivement disponibles

Nouveau helper `bot/analyser/temporal_split.py:5`, appelé par les trois voies
principales. Les grilles appellent ces mêmes fonctions et héritent du contrôle.

1. Validation des dates/identités et rejet des mints dupliqués à ce niveau. Les
   exports vérifiés fournissent déjà une identité par mint ; aucun export n'est
   modifié ou réparé ici.
2. Tri déterministe par date, signature, créateur, mint, pool.
3. Cible inchangée int(N * train_fraction), défaut 0,7. La frontière retenue est
   la dernière frontière légale au plus à cette cible : timestamp strictement
   différent et aucune signature répartie de part et d'autre. Une signature qui
   réapparaît à une date différente lie conservativement l'intervalle traversé.
4. Frontière fixée sur TOUS les événements connus avant exclusion des prix
   manquants. La période test commence au premier événement brut retenu en test,
   même si celui-ci n'a pas de cotation complète.
5. Purge des observations train dont l'heure REELLE de cotation de sortie est
   >= au début de cette période test. Égalité exclue : l'ordre intra-timestamp
   ne prouve pas une connaissance antérieure. Les observations purgées ne sont
   jamais déplacées vers le test.
6. Minima contrôlés APRÈS groupes, données manquantes et purge : 30 train, 15 test,
   et tous les seuils de sélection existants, dont les cinq signaux, inchangés.
   Aucun déplacement opportuniste de frontière pour sauver ces minima.

L'embargo est donc produit par l'intervalle effectif d'observation du label :
horizon de sortie configuré + retard réel du prix présent dans la fenêtre. Aucun
nouveau nombre arbitraire de secondes n'est ajouté à une stratégie. Si les groupes
ou labels ne permettent plus les minima, la fonction refuse/retourne insufficient_data
selon son contrat précédent ; elle n'affiche pas une validation réussie.

research._outcome_observation conserve les prix et le calcul numérique d'outcome,
et expose entry_time/exit_time ; outcome reste un wrapper au résultat float/None.
Les fenêtres incohérentes, sortie antérieure à l'entrée ou référence postérieure,
ne produisent pas d'observation. Les fenêtres, frais et délais valides restent
inchangés. momentum et behavior possédaient déjà l'heure de sortie observée.

Métadonnée additive temporal_split : cible brute, frontière utilisée, début brut
de période test, nombre purgé, max_train_label_time, politique et disponibilité
d'une frontière. La propriété vérifiée est max_train_label_time < début brut du
test pour tout train utilisable. Les anciens champs train_end/test_start restent
les dates des observations complètes ; test_start peut donc différer du début brut
qui commande la purge lorsqu'un premier événement test est incomplet.

Le champ creator_prior_mean_return, non consommé par les RULES actuelles, a été
rendu causal en soutien du correctif : seuls les résultats dont exit_time est
strictement antérieur à l'entrée observée sont utilisés. Un résultat d'un sibling
futur/purgé ne peut pas rester dans une feature de train. Les prédicats _rule et
la liste des stratégies restent inchangés.

### Changements intentionnels de cohortes

| Scénario synthétique | Référence | Après correction |
|---|---|---|
| 50 événements bien espacés, signatures/timestamps distincts | 35 / 15 | 35 / 15 ; chiffres identiques hors temporal_split |
| 50 créations par paires partageant transaction/date | 35 / 15, une paire scindée | 34 / 16, aucune signature/date commune |
| Même fixture à rendements alternés +0,18 / +0,38 | moyenne train ≈0,277143, test ≈0,286667 | train et test ≈0,28 ; différence due uniquement aux cohortes |
| 50 créations de même transaction et timestamp | 35 / 15 apparemment valide | absence de frontière → refus sans réduire les minima |
| 60 événements denses à horizon 1 h | 42 / 18 avec labels futurs | 42 labels train purgés → refus/insufficient_data |
| 47 événements, purge donnant seulement 29 train | modèle ancien non purgé | refus malgré 15 observations test disponibles |
| Prix de sortie retardé de 100 s, cible avant le test | label pouvait être gardé | label effectivement postérieur purgé ; idem si premier test incomplet |

Aucun de ces rendements de fixture n'est une preuve de profit économique.

## Résultats exacts et non-régression

| Exécution | Résultat retenu |
|---|---|
| Baseline au SHA demandé | **535 passed, 1 skipped, 242 subtests passed**, 29,94 s, code 0 |
| Caractérisations originales | **6 passed**, 0,62 s : défauts de référence confirmés |
| Assertions de sécurité positives sur référence, fichier séparé | **5 failed, 2 deselected**, 0,53 s, code 1 |
| Nouveaux tests + audit converti | **75 passed**, 1,61 s, warnings en erreur |
| Groupe scanner/temporal/P1.6h/P1.6f/WS/récupération | **253 passed, 5 subtests passed**, 12,81 s, warnings en erreur |
| Suite active finale | **604 passed, 1 skipped, 242 subtests passed**, 32,08 s, code 0, stderr vide |

Le skip est inchangé : tests/test_research_pipeline.py:17, base utilisateur absente.
Les 69 cas supplémentaires sont 51 tests temporels, 17 tests scanner et une variante
supplémentaire du cas B01 (publication échouée). Les anciennes propriétés financières
et de risque ne sont ni supprimées ni remplacées par des assertions plus faibles.
Les tests complets utilisent tests --ignore=tests/tests, comme la baseline.
Un passage intermédiaire sur une étape du correctif a donné 597/1/242 ; le résultat
604/1/242 ci-dessus concerne le périmètre final.

Les attentes d'export à 35/15 et leurs oracles Decimal ont été corrigés à 34/16
pour ne plus imposer une paire scindée. Les doubles de scanner sain déclarent leur
canal surveillé et les streams mockés acceptent le callback optionnel on_failure.
Les contrôles SQL, financiers et de taille minimale correspondants restent testés.
Une première fixture de minimum utilisait 45 événements donnant déjà trop peu de
test ; elle a été remplacée par 47 événements pour prouver la baisse à 29 train
APRES purge, sans changer un minimum de production.

Comparaisons exécutées sur six sessions PAPER normales, avec vrais calculs/ledger/
rapports/audit/exports et seuls services/prix/horloge/décision de fixture remplacés :
vide, TP, SL, rejet, garde fermée, non daté. Identité STRICTE des deux artefacts
normal_scenarios.json, incluant octets JSON/CSV, tables et définitions SQLite,
transactions et capitaux, décisions/audits/statuts, conclusions et console hors
la seule ligne du chemin temporaire. SHA256 commun :
`677fe804066dafa634e585419e5dc2d80e3d706debbb711d2cb0e5f23d469f10`.

Trois backtests normaux sans chevauchement, et leurs outcomes, sont aussi identiques
après retrait de la seule métadonnée temporal_split. SHA256 commun de
safe_backtests_normalized.json :
`eff212635d7bb3bf97def910dac7bf1581b21e3b79519715322ac8960e06c7f6`.
Les changements de métriques sur cohortes modifiées sont explicités ci-dessus.
Les fichiers physiques SQLite ne sont pas comparés octet par octet ; leur contenu
et leur schéma le sont.

Vérification source/AST : paper_trader, final_decision_engine, launchlab_onchain,
parser/détecteur, backfill et database/db sont identiques octet par octet. Dans
paper_engine, collect_once, les limites financières utilisées, métriques, rapports,
ordonnanceur, historiques et run sont identiques par AST. Les trois helpers partagés
ont le même AST qu'avant extraction. Les exports et _rule/grilles sont identiques
par AST. Les fichiers modifiés sont analysables en syntaxe Python 3.10 ; seul
Python 3.13.15 a été exécuté.

Les logs finaux final-suite.stdout.log, final-suite.stderr.log (vide) et
final-suite.exit.txt (0), les comparaisons et les scripts de preuve sont conservés
à la racine temporaire d'audit indiquée plus haut. Aucune base réelle n'y figure.

## Fichiers exactement modifiés/ajoutés

Production (8) :

- bot/main.py — canal de refus, watcher, préservation erreurs, acquisitions/cleanup.
- bot/scanner/supervision.py — nouveau canal mémoire ; helpers P1.6h partagés.
- bot/scanner/tx_recovery.py — surveillance receiver/worker avant cleanup interne.
- bot/solana/websocket.py — notification synchrone avant fermeture du transport.
- bot/analyser/paper_engine.py — garde/canal partagés ; imports des mêmes helpers.
- bot/analyser/temporal_split.py — nouveau découpage groupé et purge des labels.
- bot/analyser/research_pipeline.py — voies basic/momentum et heures de sortie.
- bot/analyser/behavior_pipeline.py — découpage commun et historique de résultats causal.

Tests (6) :

- tests/test_scanner_failure_latch.py — nouveau, 17 cas.
- tests/test_temporal_split.py — nouveau, 51 cas.
- tests/test_p1_final_audit.py — assertions positives B01/B02/B03/B04/B06 ; variante
  publication échouée ; cas legacy B05 toujours caractérisé comme résiduel.
- tests/test_scanner_entry_integrity.py — doubles de santé explicites, assertions
  de refus/SQL/finance conservées.
- tests/test_websocket_backfill.py — callback optionnel accepté par les doubles.
- tests/test_complete_launch_export.py — oracle cohérent avec les groupes 34/16.

Rapports (2) : P1_FINAL_SCANNER_TEMPORAL_FIX.md et P1_FINAL_GATE_RECHECK.md.
Aucun autre fichier suivi modifié ; anciens rapports conservés intacts.

## Rejouer et rollback

Depuis une copie jetable de sources sans .git, .env ou base utilisateur :

```text
python -B tests/p16h_isolated_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
python -B tests/p16h_isolated_runner.py -q tests/test_scanner_failure_latch.py tests/test_temporal_split.py tests/test_p1_final_audit.py tests/test_scanner_entry_integrity.py tests/test_scanner_tx_recovery.py tests/test_websocket_backfill.py tests/test_paper_report_cleanup.py tests/test_scanner_supervision.py -p no:cacheprovider -W error
python -B tests/p16h_isolated_runner.py --compare
```

Pour rejouer la baseline déjà enrichie d'un fichier temporaire de preuve, ajouter
`--ignore=tests/test_expected_scanner_temporal_safety.py`. Les fichiers suivis
originaux doivent rester ceux du SHA de référence pour obtenir 535/1/242.

Rollback NON exécuté : sauvegarder le diff des dix fichiers suivis et les six
ajouts hors du worktree, puis restaurer précisément :

```text
git restore --source=1c6175aa33190dc82d442e105e72a77e85a3c78c -- bot/main.py bot/analyser/paper_engine.py bot/scanner/tx_recovery.py bot/solana/websocket.py bot/analyser/research_pipeline.py bot/analyser/behavior_pipeline.py tests/test_complete_launch_export.py tests/test_p1_final_audit.py tests/test_scanner_entry_integrity.py tests/test_websocket_backfill.py
```

Déplacer ensuite les six ajouts sauvegardés : les deux nouveaux modules, les deux
nouveaux fichiers de tests et les deux nouveaux rapports. Aucun git clean,
suppression récursive, modification d'ACL ou de base, remplacement de dossier,
commit ou push. Les sources de référence restent disponibles dans baseline.
