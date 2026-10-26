# Audit final P1 et décisions d'accès à P2

26 octobre 2026 — PAPER ONLY.
Référence : `b89c4075d1c29adcd427d2f9947e59d81c81debb`.
Branche : `fix/p16i-coverage-final-audit`.
Dossier : `C:\Users\maxen\Downloads\rugger_bot_v1_p16h_workspace`.

## Quatre verdicts séparés

| Décision | Verdict | Motif déterminant |
|---|---|---|
| Correctif P1.6i | **VALIDEE** | Intersection de mints cohérente, orphelins séparés, 44 tests dédiés et non-régression financière. |
| Audit final P1 | **BLOQUEE** | Une défaillance interne du scanner peut laisser la garde autoriser une nouvelle entrée pendant le nettoyage du parent ; une erreur secondaire peut être perdue. Deux reproductions synthétiques sur sources inchangées. |
| Passage global aux expérimentations P2 synthétiques hors réseau | **NO-GO** | Le contrat de refus des entrées lorsque le scanner a échoué n'est pas satisfait dans tous les scénarios. Les backtests actuels présentent en outre des défauts de séparation temporelle. Les tests d'audit exécutés restent des contrôles P1, pas un démarrage P2. |
| Backtests sur données réelles | **NO-GO** | Groupes transaction/timestamp scindables entre train/test, labels d'entraînement postérieurs au début du test, provenance temporelle historique et disponibilité réelle des prix non validées, sélection répétée sur le test. |

Aucun verdict n'autorise du trading réel. La réussite d'un test synthétique, la
qualité d'un corpus historique, la couverture réelle du scanner et une rentabilité
démontrée sont quatre sujets distincts. Aucune rentabilité n'est démontrée.

## Référence, contrôles et méthode

Les contrôles Git préalables ont tous réussi depuis le cwd obligatoire : racine
exacte, branche attendue, HEAD et origin/main au SHA demandé, origin correct,
fichiers suivis inventoriés, statut entièrement propre. Pour chaque commande,
stderr était vide et le code était 0. Le détail figure dans
[P1_6I_QUOTE_COVERAGE.md](P1_6I_QUOTE_COVERAGE.md).
AGENTS.md et le plan technique ont été relus. Les anciens résultats du ZIP restent
un contexte historique ; les résultats suivants ont été reproduits ici.

La revue porte sur les sources actives de la chaîne scanner intégré → récupération
→ cotations → décisions/ledger → rapports et sur les voies recherche/export et
backtests citées ci-dessous. Les copies bot/bot, tests/tests, .bak et
.avant_correctif ne sont pas des sources de cette revue. Les nombreuses variantes
CLI de recherche creator_backtest_v*.py ne sont pas toutes certifiées par une revue
manuelle exhaustive ; leurs tests existants applicables ont été rejoués. Aucun GO
ne leur est accordé implicitement.

Les références de lignes ci-dessous désignent le SHA de base b89c4075 ; les fichiers
restent identiques sauf paper_report. Les sources ne sont pas remplacées par les
notes historiques. Les classifications sont :

- **Démontré par le code** : contrôle ou défaut visible dans une source active.
- **Reproduit par test** : scénario exécuté dans une copie isolée avec données
  synthétiques et réseau remplacé/interdit.
- **Documenté historiquement** : note antérieure, sans reproduction actuelle.
- **Inconnu/non vérifié** : aucune mesure ou donnée autorisée disponible.

Copies :
`C:\Users\maxen\AppData\Local\Temp\rugger_p16i_2ba59cb4fc5f4f9aa0d22225e8b26fa4\baseline`
et `patched`. Aucune base utilisateur, lecture de .env, clé, URL secrète, dépendance
installée, RPC/WS/API externe, véritable scanner, véritable boucle de collecte,
ordre, signature ou portefeuille financé. Les fonctions d'orchestration utilisées
par les nouveaux tests ont uniquement des tâches et services synthétiques.

## Matrice des contrôles P0/P1

« Testé » signifie testé dans le périmètre synthétique décrit ; ce n'est pas une
preuve de qualité ou d'exhaustivité du marché.

| Priorité / contrôle | Sources actives et constat | Preuves exécutées / état |
|---|---|---|
| P0 — Capital, réservations, entrée atomique | paper_trader.py:470,495,511,584 : BEGIN IMMEDIATE ou savepoint ; capital rapproché avec les PnL ; taille positive, solde engagé, limites revérifiées sous le même verrou | atomic_entry_limits, paper_capital_reservation, atomic_paper_close ; non-régression sur six sessions. Testé ; aucune DB réelle auditée. |
| P0 — Pertes journalières | paper_trader.py:311 : clôtures à exit_time, PnL SOL, dates finies et ordonnées ; minuit UTC et référence capital actuel moins PnL du jour | paper_loss_date_guard, atomic_entry_limits, realized_performance. Testé. Hypothèse : pas de flux externes au ledger ; 10 SOL/10 % conservés. |
| P0 — Clôtures TP/SL/trailing/timeout | paper_trader.py:619-687 : frais appliqués au retour du trade, PnL multiplié par position_sol ; transition open→closed et portefeuille dans la transaction | atomic_paper_close, paper_pipeline/end_to_end, capital_reservation ; mêmes sorties/capitaux avant/après. Testé, indicatif PAPER. |
| P0 — Métriques | paper_engine.py:493 : equity réalisée SOL, clôtures à exit_time, rapprochement ; historique incomplet → métriques inconnues, sans réparation | realized_performance et paper_session. Testé. Ne couvre pas le drawdown latent/exécutable. |
| P1 — Récupération idempotente | tx_recovery.py : réservation durable de tentative, lease, signature unique ; complete vérifie état/attempt, cache+candidats+receipt dans BEGIN IMMEDIATE | scanner_tx_recovery, multiple_launches : rejouements, crash/reprise, rollback après écriture, triggers/receipts. Testé. |
| P1 — WebSocket/ACK | websocket.py:25 : ACK avec identifiant/résultat attendu avant subscribed ; abonnement contrôlé sur notifications ; annulation propagée | websocket_backfill : refus, ACK incorrect/absent, reconnexion, mauvais abonnement, 429 simulés. Fournisseurs réels inconnus. |
| P1 — Backfill/receipts | backfill.py : pagination bornée, ancrage, checkpoints ; curseur et enqueue transactionnels, receipt signature/slot, bootstrap explicitement limité | websocket_backfill : trous, doublons, ancrage absent, pages bloquées, saturation, rollback, réception live pendant RPC lent. Testé relativement à l'ancre. |
| P1 — Multi-créations et parser | transaction_parser.py:112,128 ; launch_detector.py:12 : identités indépendantes, instruction externe/interne, métadonnées conflictuelles rejetées, SPL seul/swaps exclus | launchlab_parser, multiple_launches, complete_launch_export et deux cas P1.6i. Strict selon les critères codés ; pas certification externe d'un IDL ou de tous les payloads réels. |
| P1 — Dates/provenance des signaux | launch_detector.py:20-35 et paper_engine.py:207 : type exact, dates invalides/futures non fabriquées, cache brut préservé, signaux vérifiés avant stratégie | undated_launch_observation et paper_loss_date_guard. Testé ; divergence legacy d'export détaillée en B05. |
| P1 — FIFO/quotas | paper_engine.py:303-354 : ordre durable par mint ; files positions/candidats, capacité réservée, alternance à quota 1 ; tentative avancée avant I/O | candidate_scheduling et suites undated_launch_observation/scanner_entry_integrity. Testé sur budgets et scénarios synthétiques. |
| P1 — Prix/funding et doublons | launchlab_onchain.py, paper_trader.py:113,559 : owner/mint/monnaie/spot contrôlés, funding distinct de DEX, première observation retenue, conflits comptés avant décision | launchlab_onchain, market_data_provenance, paper_quote_consistency. Testé ; slippage, profondeur, fraîcheur et revente réelle non prouvés. |
| P1 — Historique créateur causal | paper_engine.py:357,381 : dates strictement antérieures, union de mints ; research_pipeline.py:116 (export_dataset) groupe les timestamps pour les comptes antérieurs | multiple_launches, complete_launch_export, behavior_pipeline. Bon pour les comptes de créations ; B06 concerne un autre champ de rendement historique. |
| P1 — Protection des entrées | paper_engine.py:65-130 et collect_once : parent vivant, état frais, subscribed/caught_up, receipt et autorisation commune décision/ledger | scanner_entry_integrity teste de nombreuses pannes ; **B01 révèle un cas manquant : enfant interne déjà échoué, parent encore vivant pendant son nettoyage**. Bloqué. |
| P1 — Fermetures intégrées | paper_engine.py:661,691,707,1300,1566 : exceptions conservées, cleanup protégé, tentatives indépendantes HTTP/fetcher/SQLite, diagnostics de tâches tardives | 71 tests P1.6h + supervision, ResourceWarning en erreur. Bon dans le moteur intégré ; **B02 concerne la supervision interne de bot.main**, B08 la voie CLI standalone. |
| P1 — Rapports | paper_report et _session_summary : calculs conservés, JSON moteur atomique ; P1.6i sépare couverture locale/orphelins/marché inconnu | 44 tests couverture + nettoyage et six comparaisons de sessions. Testé pour les rapports moteur. JSON recherche/CSV n'ont pas la même garantie atomique, voir B09. |
| P1 — Exports | research_pipeline.py:86,116,132 : identités de chaque création, earliest par mint, ordre déterministe, comptes antérieurs par groupe ; CSV prix enregistrement | complete_launch_export et CSV avant/après identiques. B05 : date fallback sans même exigence de provenance que l'entrée. |
| P1/P2 — Découpage chrono | research_pipeline.py:211,338 ; behavior_pipeline.py:319 : split par nombre de créations, sans regroupement transaction/timestamp | B03 reproduit la scission d'une transaction à timestamp égal. Non validé pour une preuve OOS. |
| P1/P2 — Disponibilité des labels | backtest calcule les outcomes de tous les événements avant le split effectif, sans purge des sorties dépassant la frontière | B04 reproduit des entrées test antérieures aux sorties d'entraînement. Non causal pour une évaluation prospective. |
| P1/P2 — Corpus, prix et rentabilité | marché non interrogé, âge fournisseur inconnu, prix observés/indicatifs, données complètes sélectionnées, coût hypothétique | Non vérifié sur données réelles. Aucun rendement observé dans les fixtures n'est une performance économique. |

Le backfill caught_up et un receipt prouvent un traitement selon le contrat local
d'ancrage/enqueue ; ils ne prouvent pas une capture exhaustive de Solana ni que
toute transaction du marché est déjà reconstruite. Les métriques de couverture
P1.6i portent uniquement sur les mints connus, jamais sur ce marché inconnu.

## Anomalies restantes classées

### B01 — P1 critique : entrées encore permises après l'échec d'un enfant scanner

**Démontré par le code et reproduit**, avant et après P1.6i.
Sources : bot/main.py:59-70 ; paper_engine.py:99-125.

1. Une tâche interne du scanner lève une exception non rattrapée alors que le
   dernier état SQLite est encore frais, subscribed et caught_up.
2. bot.main entre dans son finally, annule ses enfants puis attend gather.
3. La publication disconnected/degraded vient seulement APRES cette attente.
4. Pendant un nettoyage retardé, le parent scanner n'est ni done ni cancelling.
   La garde ne voit donc pas l'échec déjà survenu de l'enfant.
5. Dans le test, la garde renvoie True ; le vrai collect_once, avec décision et
   cotation synthétiques, enregistre entry_allowed=1 et **un trade PAPER** dans
   une base jetable. Après libération de l'enfant et terminaison du parent, la
   garde refuse enfin.

Test : test_audit_confirms_internal_scanner_failure_leaves_entry_permission_open.
Ce n'est ni un appel réseau, ni une transaction Solana, ni une régression de P1.6i.
Le cas existait dans la référence. Le simple fait de tester l'échec immédiat d'un
parent scanner simulé, comme dans les anciennes suites, ne couvrait pas cette
fenêtre dans l'orchestrateur interne réel.

**Condition bloquante de clôture P1 et du GO global P2.** Une future correction
ciblée doit rendre le refus effectif dès l'échec interne, avant la première attente
de nettoyage, y compris si la publication SQLite échoue. La fenêtre ne doit pas
être remplacée par un délai supposé suffisamment court. Aucun correctif scanner
n'est appliqué dans cette mission.

### B02 — P1 élevé : erreur secondaire de nettoyage scanner ignorée

**Démontré et reproduit.** Source bot/main.py:69 :
`await asyncio.gather(*tasks, return_exceptions=True)` est utilisé sans examiner
les exceptions retournées.

Le backfill synthétique échoue, puis le worker de récupération lève une autre
exception pendant son annulation. Cette seconde exception figure dans le résultat
de gather mais n'est ni propagée ni attachée au graphe d'erreurs exposé au parent.
L'erreur principale reste visible ; la seconde perd sa provenance publique.
Test : test_audit_confirms_scanner_secondary_cleanup_error_is_discarded.
La collecte explicite des erreurs dans le superviseur PAPER externe ne peut pas
récupérer une exception déjà abandonnée par le scanner interne.

Correction future : examiner toutes les sorties de nettoyage, préserver l'erreur
principale/l'annulation et rendre les secondaires diagnostiquables. Ajouter un
cas simultané et un cas d'échec de publication de l'état. Pas de modification ici.

### B03 — Bloquant pour backtests réels : transaction/timestamp scindés train/test

**Démontré et reproduit.** Sources research_pipeline.py:211,338 et
behavior_pipeline.py:319. `split=int(len(events)*train_fraction)` puis tranches
positionnelles ; verified_launches retourne une création par mint, donc plusieurs
événements peuvent partager une signature et un timestamp.

Fixture : 50 créations synthétiques de même transaction et timestamp. Avec les
seuils par défaut du backtest, **35 train / 15 test**, train_end=test_start=1000 et
la même signature des deux côtés. Des rendements synthétiques positifs sont
calculés ; ils ne démontrent pas d'indépendance OOS. Les structures de transaction
sont des fixtures de parser, pas des transactions signées ni une validation de
faisabilité on-chain d'un lot de 50 créations.

Test : test_audit_confirms_one_transaction_and_timestamp_cross_train_test.
Il faut grouper les identités transaction/timestamp selon un protocole figé et
n'autoriser aucun groupe de part et d'autre de la frontière. Le moteur de backtest
reste inchangé conformément à la mission.

### B04 — Bloquant pour une interprétation prospective : labels pas encore connus

**Démontré et reproduit.** research_pipeline.py:324-353 calcule des retours à un
horizon futur sans retirer les événements train dont la sortie dépasse l'entrée
des premiers événements test. Un tri des seuls signaux n'assure pas la causalité.

Fixture de 60 événements espacés : train_end=1410, test_start=1420, mais sortie du
dernier train à 5070 et première entrée test à 1480, avec les délais par défaut.
Le backtest produit **42 train / 18 test** sans bloquer ce chevauchement.
Test : test_audit_confirms_training_labels_extend_past_test_entries.

Un protocole de purge/embargo fondé sur les horodatages d'entrée/sortie et la
véritable disponibilité des données est nécessaire avant une évaluation OOS.
L'absence de purge concerne également les sélections de seuils momentum et règles
comportementales lorsque leurs labels chevauchent le test.

### B05 — P1 qualité historique : dates fallback différentes des dates d'entrée

**Démontré et reproduit sur fixture legacy, pas constaté dans une base réelle.**
research_pipeline.py:98 : `timestamp=tx.get('blockTime') or saved_time` peut produire
un événement exporté daté à partir de research_launches alors que le cache brut a
blockTime=NULL. paper_engine._verified_launch_time refuse cette même provenance
pour de nouvelles entrées et la classe non datée.

Test : test_audit_confirms_saved_date_fallback_diverges_from_entry_provenance.
Ce comportement d'export est une compatibilité historique déjà testée, pas une
nouvelle régression corrigée silencieusement. Il faut rendre la provenance et sa
politique d'acceptation explicites pour le corpus d'étude, sans fabriquer de date
ni transformer une date de réception en date de chaîne.

### B06 — P2 élevé, latent : rendement « antérieur » créateur non causal

**Démontré et reproduit.** behavior_pipeline.py:325-336 ajoute immédiatement le
rendement futur de chaque observation dans prior_returns. L'observation suivante
peut recevoir ce résultat même si elle partage le timestamp de création et que la
sortie précédente n'est pas encore survenue.

Dans le test, m001 possède prior_launches=0 (compte de créations correct) et un
creator_prior_mean_return positif provenant du futur de son sibling. Test :
test_audit_confirms_unused_creator_prior_return_is_not_causal.

Les RULES actuelles ne consomment PAS ce champ : ce test ne démontre pas une
altération actuelle de leur sélection par ce seul champ. Son utilisation future
comme feature ferait entrer une fuite temporelle. Il faut conditionner l'historique
aux résultats réellement connus avant l'instant observé, ou exclure ce champ.

### B07 — P2 méthodologie : sélection sur le test, biais et unité de performance

**Démontré par le code pour la sélection, limites quantitatives non mesurées.**
research_pipeline.backtest_grid (399-433) teste plusieurs horizons et désigne des
horizons éligibles selon les résultats test. momentum_grid/behavior_grid présentent
aussi plusieurs horizons ; les règles/seuils sont choisis sur train mais la
consultation répétée du même test ne constitue pas un dernier holdout indépendant.
Un protocole de sélection et un jeu final indépendant restent nécessaires.

Les observations incomplètes sont exclues et comptées ; cette transparence ne
prouve pas que l'absence de prix soit aléatoire. Les tokens morts/non cotés peuvent
être sous-représentés. Les coûts restent hypothétiques ; fraîcheur fournisseur,
latence, profondeur exécutable, sorties impossibles et biais de collecte ne sont
pas validés dans un corpus réel.

research_pipeline.py:380-389 compose des retours de trades sur une equity unitaire
hypothétique. Ce diagnostic de recherche n'est pas le portefeuille PAPER de
10 SOL, alloué à 10 %, avec positions simultanées et réservations. Ne pas attribuer
son selected_max_drawdown ou equity_multiple au ledger SOL. Aucun changement de
stratégie ni de ce calcul n'est effectué dans P1.6i.

### B08 — P1 résiduel : voie CLI PAPER standalone non protégée comme le moteur intégré

**Démontré par le code ; pas reproduit pendant cet audit.**
paper_trader.py:744-795 ouvre SQLite avant sa boucle et son contexte HTTP sans
finally de fermeture SQLite. Cette voie CLI reste documentée historiquement et
ne bénéficie pas automatiquement du cleanup de paper_engine.run. Une annulation
ou une initialisation en échec n'a pas le même contrat de fermeture explicite.
Ce point devra être reproduit puis corrigé ou cette voie retirée du périmètre de
validation déclaré ; aucune suppression ou modification n'a lieu ici.

### B09 — P1 résiduel : atomicité limitée aux rapports du moteur intégré

**Démontré par le code ; scénarios de panne non rejoués ici.**
research_pipeline.py:116,132 et ses branches CLI écrivent directement CSV et JSON.
Ces sorties ne possèdent pas le même remplacement atomique que les rapports
paper_engine. Leur contenu normal est testé et comparé ; leur résistance à une
écriture interrompue reste à traiter si elles servent d'entrée validée pour P2.
Ce constat ne remet pas en cause les tests d'atomicité P1.6h du moteur intégré.

## Tests réellement exécutés et portée des résultats

Python **3.13.15**, pytest **9.1.1**, dépendances déjà présentes, aucun téléchargement.
Lanceur offline existant tests/p16h_isolated_runner.py, sans modification.

| Exécution | Résultat exact |
|---|---|
| Référence originale avant correction | **485 passed, 1 skipped, 242 subtests passed**, 26,76 s, code 0 |
| 44 tests de couverture sur référence originale | **44 failed**, 2,25 s, code 1 |
| Six caractérisations d'audit sur référence originale | **6 passed**, 0,57 s, code 0 |
| Couverture + caractérisations + nettoyage P1.6h + supervision, ResourceWarning en erreur | **131 passed**, 3,90 s, code 0 |
| Suite finale active complète | **535 passed, 1 skipped, 242 subtests passed**, 28,72 s, code 0 |

Le skip « base utilisateur absente » reste tests/test_research_pipeline.py:17.
Les copies historiques tests/tests sont exclues, comme en baseline. Une suite
intermédiaire avait donné 534 passed/1 skipped/242 subtests en 30,64 s ; le dernier
cas explicite distingue encore mieux l'intersection d'un plafonnement artificiel.

**Les six caractérisations passent parce qu'elles constatent les anomalies.**
Elles n'affirment pas que la garde est sûre ou que le backtest est causal. Le
535/1/242 final n'est donc pas un certificat de clôture P1. Une correction future
doit convertir les attentes correspondantes en propriétés de sécurité positives :
refus d'entrée, zéro trade dans la fenêtre d'échec, toutes erreurs exposées, groupes
et labels séparés, historique causal.

Les deux tests scanner utilisent les vraies fonctions d'orchestration/garde/
collect_once, avec RPC, WebSocket, backfill et récupération remplacés par tâches
synthétiques finies. La tâche retenue pour reproduire la fenêtre est explicitement
libérée en finally ; les ensembles asyncio.all_tasks avant/après sont égaux. La
fixture ferme ses connexions. Aucun service ou flux réel n'est démarré.

## Non-régression et fichiers livrés

Les six sessions normales comparées avant/après conservent :

- mêmes tables et définitions SQLite, capital SOL, positions, frais, décisions,
  audits, statuts et CSV prix/dataset, avec leurs octets ;
- mêmes JSON de session et conclusions, et mêmes JSON périodiques hors les deux
  champs de couverture corrigés et les quatre champs ajoutés ;
- TP : 10 → 10,18 SOL ; SL : 10 → 9,78 SOL ; vide/rejet/garde fermée/non daté :
  capital final 10 SOL, aucun trade clos ;
- mêmes sources de stratégie, de comptabilité, de scanner et de backtest octet
  par octet. Dans paper_engine, seule la définition paper_report diffère par AST.

SHA256 commun des artefacts normaux après normalisation explicite des seuls
champs de couverture :
`76fe78a7422a1fc1a9ce4c14ae98128e2b5970bcc34b390cf7a3901772da8aff`.
Les détails de la formule, exemples et contrats JSON figurent dans le rapport P1.6i.

Fichiers exactement modifiés/ajoutés par la mission :

1. bot/analyser/paper_engine.py — correction de paper_report uniquement.
2. tests/test_quote_coverage.py — 44 cas dédiés.
3. tests/test_p1_final_audit.py — six caractérisations des défauts restants.
4. P1_6I_QUOTE_COVERAGE.md.
5. P1_FINAL_AUDIT_AND_P2_GATE.md.

Capital initial 10 SOL, allocation 10 %, frais, seuils, scores, critères,
TP/SL/trailing, schémas financiers, moteur de backtest et scanner restent inchangés.
Aucun commit, push ou fusion. Aucune correction silencieuse des anomalies B01-B09.

## Conditions exactes pour réexaminer les GO

Pour la clôture P1 et un passage global en P2 synthétique :

1. Mission distincte corrigeant B01 : panne interne → refus immédiat avant toute
   attente de cleanup ; le test doit prouver guard=False, entry_allowed=0 et zéro
   nouveau trade même avec état SQLite encore frais et parent vivant. Tester le
   cas où la mise à jour de l'état échoue, ainsi que l'échec simultané des tâches.
2. Corriger B02 : aucune exception de tâche perdue, principale et annulations
   préservées, erreurs secondaires diagnostiquables et absence de tâche restante
   dans les scénarios coopératifs. Délai dépassé explicitement diagnostiqué.
3. Résoudre ou exclure explicitement les voies non couvertes B08-B09 du protocole
   validé ; reproduire leurs défauts avant toute correction. Ne pas transférer une
   garantie du moteur intégré à un autre point d'entrée par simple analogie.
4. Avant d'interpréter les performances P2, utiliser un évaluateur démontré causal :
   groupes transaction/timestamp insécables, labels train connus avant la frontière,
   features créateur basées sur résultats déjà connus, politique explicite pour les
   dates/provenances manquantes. Corriger les backtests existants dans une mission
   autorisée ou ne pas les utiliser comme évaluateur de performance indépendant.
5. Figement du protocole synthétique : seeds, jeux, hypothèses de coût/exécution,
   fenêtres, critères et jeu final indépendant ; métriques et unités cohérentes
   avec le capital SOL réellement engagé. Aucune nouvelle stratégie ou seuil n'a
   été choisi ici.
6. Rejouer baseline, nouveaux tests de sécurité positifs et suite active complète
   dans une copie sans réseau ; publier le diff, les comparaisons et un rollback.
   Puis réexaminer les quatre verdicts, sans GO automatique hérité de ce rapport.

Pour les backtests sur données réelles, ajouter : audit autorisé de snapshots
historiques sans secrets, provenance/horodatages et disponibilité des cotations,
réconciliation/dédoublonnage, traitement des absences et biais de sélection,
univers effectivement étudié documenté, coût/latence/exécutabilité justifiés et
validation indépendante hors période de sélection. La couverture globale du
marché demeure inconnue tant qu'aucune mesure adaptée n'est disponible ; un
sous-univers audité ne doit pas être présenté comme le marché entier.
Aucune de ces étapes n'autorise du trading réel.

## Limites non vérifiées et rollback

Aucun corpus utilisateur ni environnement fournisseur n'a été inspecté ou interrogé.
Aucun vrai taux de perte d'événements, latence p95, qualité d'un endpoint, prix
réellement revendable ou performance économique n'est mesuré. La conformité à un
IDL externe à jour n'a pas été vérifiée par réseau. Python 3.10 n'a pas été exécuté
(syntaxe compatible contrôlée pour le fichier modifié) ; Windows/Python 3.13.15
constituent l'environnement reproduit. Les fermetures qui échouent ou refusent de
terminer ne peuvent pas être déclarées libérées de force.

Rollback proposé, non exécuté : conserver un diff et les quatre ajouts hors du
worktree ; restaurer le seul fichier de production :

```text
git restore --source=b89c4075d1c29adcd427d2f9947e59d81c81debb -- bot/analyser/paper_engine.py
```

Déplacer les quatre ajouts sauvegardés hors du worktree si un état propre est
souhaité. Aucun git clean, suppression de caches, changement d'ACL, accès à une
base, remplacement de dossier ou commit n'est nécessaire. Les sources de la
baseline sont conservées dans la copie isolée indiquée plus haut.

Mission arrêtée après correction P1.6i, tests et rapports. Les blocages sont
signalés ; aucune expérimentation P2 ou correction hors périmètre n'est engagée.
