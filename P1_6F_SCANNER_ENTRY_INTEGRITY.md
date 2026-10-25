# P1.6f — Intégrité scanner et autorisations PAPER

## Référence et périmètre

Contrôles initiaux reproduits : branche `main`, HEAD et `main` exactement
`97e012d9ab1b98f1551c71247edd4b992d66057c`, statut Git complet vide.
Branche créée : `fix/p16f-scanner-entry-integrity`.
Lecture d'AGENTS.md, du plan technique et de l'audit factuel historique.
Aucun commit, push ou fusion. Aucun scanner réel lancé.

Seuls fichiers ajoutés/modifiés :

- `bot/analyser/paper_engine.py` : garde et permission commune.
- `tests/test_scanner_entry_integrity.py` : 52 cas synthétiques, paramétrages inclus.
- Ce rapport.

`paper_trader.py`, `backfill.py`, `main.py`, les consommateurs directs et les tests
de supervision/flux final ont été examinés, sans modification. Aucun changement
de schéma SQLite, de configuration financière, de rotation, de parsing ou d'export.

## Causes et reproduction sur le code original

Les numéros suivants désignent la référence Git, avant correctif :

| Anomalie | Source | Cause | Preuve synthétique avant correction |
|---|---|---|---|
| Scanner vivant mais dégradé autorisant une entrée | `paper_engine.py:1096` | `lambda: not scanner_task.done()` ignore les états persistants du scanner | Faux scanner toujours vivant, état `degraded/subscribed`, décision stratégique favorable : **1 position créée**, attendu 0 |
| Permission enregistrée contraire au garde | `paper_engine.py:767`, `:784`, `:818` | La permission financière est inscrite avant l'évaluation du garde scanner | Garde retournant False : décision **(enter=1, entry_allowed=1)**, attendu (1,0) ; aucune position créée |

Commande de reproduction sur les modules originaux, avant tout patch de production :
`python -B audit_runner.py -q tests/test_scanner_entry_integrity.py -p no:cacheprovider`.
Résultat : **2 failed**, sur les deux assertions ci-dessus. Ces deux tests passent
ensuite sans changer leurs attentes.

## Politique scanner retenue

Le garde (`paper_engine.py:62`) est créé avant de donner la main aux tâches
scanner/moteur. Il mémorise l'heure de début et le `checked_at` initial du programme
configuré, lu en mode SQLite `mode=ro`. Cette inspection ne crée jamais de base.
Le programme est sélectionné avec la même variable non secrète et le même défaut
que `bot.config` ; une ligne saine d'un autre programme ne suffit pas.

Une permission scanner positive exige simultanément :

1. Tâche scanner ni terminée ni en cours d'annulation.
2. Ligne du programme présent, lisible, `history_status='caught_up'`,
   `reason IS NULL`, `ws_state='subscribed'`.
3. `checked_at` numérique fini, au moins égal au début de cette supervision,
   strictement supérieur à la valeur persistante initiale, non futur et âgé
   d'au plus **120 secondes**. Si aucune ligne initiale n'existait, la comparaison
   à sa valeur initiale est sans objet.
4. Curseur non vide, slot entier positif ou nul et receipt de récupération
   présent avec exactement le même slot.

Les 120 secondes sont un délai technique conservateur égal à deux intervalles
par défaut du backfill (60 s), et ne changent aucun seuil de stratégie.
Si l'inspection initiale échoue, le premier état lisible établit seulement une
référence : il faut ensuite un nouveau `checked_at` supérieur pour autoriser.
Une ancienne ligne future ne devient donc pas autorisante simplement parce que
le verrou initial a disparu ou que l'horloge finit par la rejoindre.

Tous les états manquants/inconnus/illisibles, erreurs SQLite, refus d'abonnement,
déconnexions, rattrapages et états dégradés refusent les nouvelles entrées.

`backfill.py:120-145` démontre que `baseline` ne représente qu'une fenêtre récente
de démarrage ; il est **refusé**. `caught_up` signifie que l'ancre sauvegardée a été
retrouvée et que les signatures ont été mises en récupération atomiquement. Il
reste insuffisant sans les autres contrôles ci-dessus. Cela ne prouve ni que tous
les traitements de récupération sont terminés, ni une couverture du marché.

## Permission, décision et écriture financière

Dans `collect_once`, le contrôle intervient après les attentes de cotation et
d'enrichissement comportemental, après la construction de la décision, avant son
enregistrement (`paper_engine.py:839-905`).

- `enter` conserve son sens de décision stratégique, indépendamment du scanner.
- La permission financière conserve son calcul antérieur : garde des limites
  pour un nouveau mint ; chemin de continuation pour un mint déjà en portefeuille.
- La permission scanner est calculée séparément.
- `entry_allowed` reçoit leur conjonction, également transmise comme `allow_entry`
  à `record_quote`. Le refus scanner est explicite dans l'audit du mint.
- Une permission n'est pas une promesse d'exécution. `record_quote` conserve sa
  vérification financière finale sous verrou (`paper_trader.py:727`), ses contrôles
  de modèle, de capital libre et d'unicité. La présence réelle du trade et les
  statuts `TRADE_PAPER_OUVERT` / `TRADE_PAPER_FERME` désignent l'exécution simulée.
  `DECISION_ENTRY` reste une décision autorisée, pas une preuve d'ouverture.

Le garde supervisé lit avec **la même connexion SQLite**, dans la transaction de
la décision et du ledger. Aucun `await` ne sépare permission, décision et écriture.
La transaction de production obtient `BEGIN IMMEDIATE` ; une autre connexion peut
lire mais ne peut modifier l'état scanner entre ces étapes. Un test tente cette
modification depuis une seconde connexion au moment d'enregistrer la décision :
SQLite refuse l'écriture concurrente (`database is locked`), puis l'entrée cohérente
est enregistrée. Un autre test injecte une panne d'insertion du trade : prix,
décision et entrée de cette transaction sont tous annulés. Le statut provisoire
`PRIX_OK`, écrit avant cette transaction, n'est pas une preuve d'ouverture.

Pour un appelant possédant déjà une transaction, le mécanisme de savepoint existant
reste utilisé. Les écritures déjà effectuées sur cette connexion détiennent le
verrou ; le correctif ne change pas la durée des transactions de l'appelant.

## Continuité des positions et mode autonome

Un scanner dégradé ne supprime aucun candidat, n'interrompt pas le moteur et
n'empêche pas la collecte des prix. Dans `paper_trader.py:619-689`, la gestion
d'une position ouverte et sa clôture précèdent le filtre interdisant une nouvelle
entrée. Ce chemin reste inchangé. Les tests TP et SL avec garde refusant
`entry_allowed` donnent respectivement +0,18 SOL et −0,22 SOL sur une position de
1 SOL ; les relectures ne recréent ni position ni PnL.

L'arrêt effectif du scanner conserve la politique historique du superviseur :
échec explicite et arrêt du moteur, avec nettoyage des tâches. Le correctif ne
fournit pas de gestion autonome indéfinie après cet arrêt. Il distingue cet arrêt
de l'état dégradé d'une tâche encore vivante, qui laisse le moteur fonctionner.

`--no-scanner` conserve le contrat historique : aucun scanner démarré et aucun
garde scanner transmis au moteur. Un message indique maintenant explicitement le
mode autonome et l'absence de garantie de couverture. Les autres limites PAPER
restent actives. Aucun état scanner sain n'est fabriqué.

## Tests réellement exécutés

Copie isolée : `C:\Users\maxen\AppData\Local\Temp\rugger_p16f_1pyeruiz`.
Copie limitée aux sources et fixtures de tests suivies, sans `.env`, base
utilisateur, secrets, répertoires historiques imbriqués ou données de marché.
Interpréteur du venv existant : Python 3.13.15, pytest 9.1.1 ; aucune installation.
Le lanceur d'audit bloque les connexions et la résolution réseau, neutralise
`dotenv.load_dotenv`, désactive les plugins pytest automatiques et compte les
sous-tests unittest. Les paires de sockets internes à asyncio sont seules permises
pour son mécanisme local de réveil. Aucun appel à un service externe.

Commandes exécutées depuis la copie (interpréteur : `.venv\Scripts\python.exe`
du dépôt, appelé par son chemin absolu) :

```text
python -B audit_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
python -B audit_runner.py -q tests/test_scanner_entry_integrity.py -p no:cacheprovider
```

| Exécution | Résultat exact |
|---|---|
| Baseline suivie, avant nouveaux tests | **297 passed, 1 skipped, 242 subtests passed** (15,56 s) |
| Deux reproductions sur code original | **2 failed** (0,36 s), défauts attendus |
| Nouveaux tests seuls, correctif final | **52 passed** (5,71 s) |
| Toute la suite après correctif final | **349 passed, 1 skipped, 242 subtests passed** (21,98 s) |

Le seul skip reste `tests/test_research_pipeline.py:17`, base utilisateur absente :
elle n'a pas été ouverte pour supprimer ce skip. Les anciens tests temporaires
des audits ne sont pas ajoutés artificiellement au décompte. Les 52 nouveaux cas
de cette mission sont réellement présents dans le fichier ajouté au dépôt.

### Couverture des scénarios demandés

| Demande | Preuve exécutée | Résultat |
|---|---|---|
| 1, 18 : scanner sain, entrée réelle et statuts | `test_healthy_actual_entry`, `test_healthy_supervised_wiring_uses_current_state` | Position 1 SOL, enter=1, permission=1, statut ouvert |
| 2-9 : dégradé, arrêté, WS, refus, rattrapage, démarrage, baseline, caught_up insuffisant | Tests paramétrés `unhealthy`, `stopped_or_cancelling`, `caught_up_needs_coherent_fresh_state` | Refus ; observations conservées |
| 10-11 : tables absentes, lecture SQLite impossible | `missing_table`, `sqlite_read_error`, `custom_guard_sqlite_exception`, `empty_scanner_state`, `absent_database` | Aucune permission positive ; aucune base créée |
| 12-13 : changements pendant cotation/enrichissement et avant écriture | `status_changes_during_quote_await`, `status_changes_during_behavior_await`, `status_changes_before_decision_and_record_quote`, `task_stops_during_quote_await` | Permission 0 et pas de nouvelle entrée |
| 14 : TP/SL sous scanner dégradé | `degraded_keeps_tp_sl_and_replay_does_not_duplicate_pnl`, deux paramètres | Clôtures et PnL normaux |
| 15-17 : limites, garde, enter=1/permission=0 | `financial_denial_is_not_bypassed`, deux reproductions initiales désormais vertes | Aucune ouverture ; permission cohérente |
| 18 : permission ne garantissant pas l'exécution | `atomic_financial_recheck_stays_active` | Refus final financier sous transaction ; pas de trade malgré permission préalable |
| 19 : mode autonome explicite | `explicit_no_scanner_keeps_standalone_contract` et test existant `test_no_scanner` | Contrat historique conservé |
| 20 : reconnexion, sans entrée forcée | `reconnection_rechecks_without_forcing_strategy` | Scanner sain + stratégie refusant : aucune entrée ; observation favorable ultérieure : entrée |
| 21 : reprise, fraîcheur, lecture initiale impossible | `restart_rejects_persisted_healthy_row_until_new_check`, `state_freshness_expires`, `unreadable_initial_state_requires_subsequent_renewal` | Ancien état insuffisant ; renouvellement requis |
| 22 : lecteurs/collectes concurrents, verrous | `sqlite_lock_prevents_status_change_between_permission_and_insertion`, `concurrent_collections_do_not_duplicate_entry`, `exclusive_lock_does_not_authorize_from_old_state`, `locked_database_stops_collection_without_financial_write` | Lecture cohérente, écritures concurrentes bloquées ; aucune entrée inventée |
| 23 : P1.6d | `daily_loss_date_guard_stays_fail_closed` + suite existante | Historique incomplet bloque le nouveau mint, PnL inchangé |
| 24 : P1.6a/b/e et autres tests existants | Suite complète, sources de ces correctifs inchangées | Aucune régression constatée |
| 25 : pas de double entrée/PnL, erreur ledger | Tests concurrence, rejeu TP/SL et `ledger_error_rolls_back_decision_price_and_entry` | Une seule position/clôture ; rollback financier atomique |

### Comparaison financière avant/après, scanner sain

Exécution séparée avec chargement du module original sauvegardé dans la copie et
du module corrigé ; SQLite synthétique distinct pour chaque version. Le garde
original vivant est comparé au nouveau garde avec état récent et cohérent.
Comparaison exacte des six tables : `paper_trades`, `paper_portfolio`,
`paper_prices`, `paper_decisions`, `paper_signal_status`, `paper_mint_audit`.

| Scénario | Avant | Après | Comparaison des six tables |
|---|---|---|---|
| Entrée favorable | 1 position de 1 SOL ; capital 10 SOL | Identique | Identiques |
| TP, prix 1 → 1,2 | PnL +0,18 SOL ; capital 10,18 SOL | Identique | Identiques |
| SL, prix 1 → 0,8 | PnL −0,22 SOL ; capital 9,78 SOL | Identique | Identiques |
| TP puis rejeu | Une clôture ; capital 10,18 SOL | Identique | Identiques |
| Limite financière max_open=0 | Zéro trade, aucun portefeuille créé par cet appel | Identique | Identiques |
| Refus stratégique, liquidité nulle | Zéro trade ; capital 10 SOL | Identique | Identiques |

Résultat de comparaison conservé dans `healthy_comparison.json` dans la copie.
Capital initial 10 SOL, allocation 10 %, frais et règles financières inchangés.
Les constantes de TP/SL de la stratégie ne sont pas modifiées : les chiffres du
tableau sont les résultats des mêmes fixtures avant/après.

## Limites et risques résiduels

- SQLite décrit le dernier état enregistré, pas la réalité instantanée du réseau.
  Une panne silencieuse peut rester indétectée jusqu'à son signalement ou
  l'expiration des 120 s. `checked_at` est l'heure de contrôle du backfill, pas
  un heartbeat WebSocket. Les événements WS modifient son état séparément.
- Le receipt garantit l'identité du curseur en file, pas le succès de tous les
  fetchs/parseurs. Aucun taux de couverture réel n'est calculable ici.
- Une récupération longue ou un état persistant futur peut interdire des entrées
  plus longtemps, même si le scanner travaille encore. C'est un refus conservateur.
  Si la première lecture échoue, un contrôle supplémentaire peut être nécessaire.
- Les horloges sont murales, comme le backfill existant ; leur exactitude et la
  stabilité de la configuration de programme sont supposées. Pas de nonce de
  session persistant : des processus scanner distincts partageant la même base
  peuvent publier le même état. Le mode supervisé testé utilise son scanner unique.
- Le verrou élimine une modification SQLite concurrente durant l'écriture, pas
  un changement physique du réseau qui n'aurait pas encore été enregistré.
- Un verrou SQLite exclusif peut empêcher aussi les cotations et clôtures : le
  garde ne peut rendre une base indisponible utilisable. Le test vérifie l'absence
  d'ouverture financière, pas une disponibilité malgré le verrou.
- Les anciens consommateurs financiers et historiques ne sont pas réécrits.
  Les décisions passées contradictoires ne sont ni corrigées ni supprimées.
- Aucun réseau réel ni couverture terrain, aucune rentabilité et aucun GO global
  P2 ne sont démontrés par cette validation synthétique.

## Retour arrière précis

Procédure documentaire, **non exécutée**. Depuis la racine, après vérification
qu'aucun travail ultérieur n'est à conserver :

```powershell
git restore --source=97e012d9ab1b98f1551c71247edd4b992d66057c --worktree -- bot/analyser/paper_engine.py
Remove-Item -LiteralPath '.\tests\test_scanner_entry_integrity.py', '.\P1_6F_SCANNER_ENTRY_INTEGRITY.md'
git status --porcelain=v1 --untracked-files=all
git switch main
```

Ces suppressions ciblent uniquement les deux nouveaux fichiers de cette mission,
sans récursion. Aucun rollback de base n'est nécessaire : aucune base réelle n'a
été ouverte ou migrée, aucun historique financier modifié. La branche locale peut
rester présente ; aucune suppression de branche n'est nécessaire.
