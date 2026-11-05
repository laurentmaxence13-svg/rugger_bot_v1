# Relais automatique RUGGER 01–04 — procédure (NON ACTIVÉE) — issue #187

Statut : **conception + prototype pur** (`tools/relay_planner.py`, 14 tests hors réseau). Aucun workflow, secret, permission ou boucle n'est ajouté.

## Ce qui est réel / pas réel
- Une routine Claude Cloud est déclenchée par l'événement GitHub `issues.labeled` sur `rugger-0N-run` : **exécution ponctuelle**, pas un daemon. Le relais n'est donc pas « 24/7 » : il enchaîne des exécutions, chacune à la demande d'un événement. Si aucun événement n'arrive (agent bloqué, crédit épuisé, routine désactivée), la chaîne s'arrête : c'est le rôle du watchdog.
- Non vérifié ici : que `issues.labeled` posé par un `GITHUB_TOKEN` d'Actions déclenche la routine (GitHub ne relance pas les *workflows* sur événements du `GITHUB_TOKEN` ; pour une routine via webhook de l'app, **inconnu** → à tester une fois, avec accord du propriétaire).

## Contrat de rapport (lu par le relais)
Dernier commentaire de l'issue fermée :
```
STATUS: COMPLETED | BLOCKED
NEXT_TASK:            (optionnel ; sans lui => aucune mission créée)
  agent: rugger-02
  title: ...
  criteria: critère précis et vérifiable (>= 20 car.)
```

## Machine à états par agent
WAITING → READY (successeur autorisé) → RUNNING (label posé) → COMPLETED | BLOCKED. RUNNING > 6 h => BLOCKED + escalade. BLOCKED/COMPLETED sans NEXT_TASK valide => aucune création.

## Règles (implémentées et testées)
| Exigence | Test |
|---|---|
| Idempotence (clé événement:issue, hash du successeur) | `test_idempotent`, `test_duplicate_successor` |
| Max 1 run/agent (successeur mis en file WAITING) | `test_max_one_run_per_agent` |
| Plafonds : 2/h/agent, 6/j/agent, 16/j global | `test_hourly_quota`, `test_global_day_quota` |
| Exclusion live/trade/paiement/secret/merge/protection/déploiement | `test_forbidden_domains` |
| Pas de mission sans critère précis | `test_vague_criteria_rejected`, `test_no_next_task_no_creation` |
| BLOCKED / rapport sans STATUS → escalade propriétaire | `test_blocked_escalates`, `test_missing_status_escalates` |
| Watchdog | `test_watchdog` |
| Module pur (imports restreints, pas de `open`) | `test_module_is_pure` |

Limite assumée : la liste d'exclusion est un filtre lexical (faux positifs possibles, ex. le mot « main » ⇒ escalade). Choix fail-closed.

## Activation future (décision propriétaire, non faite)
1. Un workflow `on: issues: [closed]`, `permissions: issues: write` seul, sans checkout de code non audité, qui appelle le planner et exécute les actions CREATE_ISSUE/ADD_LABEL. Le workflow doit persister l'état (ex. une issue « RELAY STATE » éditée) — **à concevoir et auditer par RUGGER 02**.
2. Auditer d'abord la question d'événements ci-dessus sur une issue de test.
3. Kill-switch : variable de dépôt `RELAY_ENABLED` ≠ `true` ⇒ no-op. Retour arrière : supprimer le workflow.
Aucune de ces étapes n'est exécutée.

---
## Mise à jour mandat #196 (toujours NON ACTIVÉ)

### Pourquoi un label posé par `GITHUB_TOKEN` ne peut pas être supposé déclencher la routine
- Documenté par GitHub : les événements produits avec le `GITHUB_TOKEN` d'Actions ne déclenchent **pas** de nouveaux *workflows* (anti-boucle), à l'exception de `workflow_dispatch`/`repository_dispatch`. Le webhook `issues.labeled` est quand même émis, mais ce que la routine Claude reçoit n'est **pas démontré** : elle dépend de l'abonnement de la routine et de l'identité de l'acteur, que je ne peux pas vérifier ici. → **inconnu, à tester une fois sur une issue de test avec accord du propriétaire**. Ne jamais bâtir le relais sur cette hypothèse ; le watchdog et le propriétaire restent le filet.
- Preuve indirecte dans ce dépôt : le déclenchement actuel de #196 provient d'un label posé par le propriétaire, pas d'un bot.

### Ajouts (code, testé hors réseau : `python -m unittest tests.test_relay_planner tests.test_relay_store`)
| Besoin #196 | Implémentation | Tests |
|---|---|---|
| (1) stockage durable + idempotence transactionnelle | `tools/relay_store.py` : SQLite, `processed` PK, `launches` PK(dedupe), **outbox** écrite dans la même transaction `BEGIN IMMEDIATE`; l'appel GitHub se fait *après* commit (`run_outbox`), 3 essais max puis FAILED | `Durable.*` (redémarrage, doublon, rollback, retry, envoi unique) |
| (2) WAITING→READY | `relay_planner.promote()` ; `ENQUEUE` n'écrase plus l'état RUNNING (bug du prototype : `SET_STATE WAITING` perdait le run) | `Promotion.*` |
| (3) payload GitHub | `tools/relay_payload.py` + `label_names()` (objets `{"name":..}` et chaînes) ; payload mal formé ou sans delivery id ⇒ refus | `Payload.*` |
| (4) rapports réels | `normalize_report()` : seul `STATUS:` unique est fiable ; formats #185 (`VERDICT : BLOCKED`), #190 (`État final : BLOCKED partiel`), #181 (`statut : PRÉPARATION PARTIELLE`) ⇒ BLOCKED non fiable + escalade, **jamais COMPLETED**, même avec un bloc NEXT_TASK | `Reports.*` |
| (5) watchdog | `relay_planner.watchdog(state, now)` appelable par un planificateur, indépendant de tout événement ; départ inconnu ⇒ fail-closed ; ne se répète pas | `Watchdog.*` |
| (6) quotas fail-closed | ledger illisible/corrompu ⇒ quota « dépassé » ; droits minimaux : `permissions: contents: read` pour la CI ; futur exécuteur : `issues: write` seul | `Watchdog.test_corrupt_ledger_fails_closed` |

### Watchdog : scheduler proposé, NON activé
Un `on: schedule: cron: "17 * * * *"` appelant `watchdog()` sur la base d'état, derrière `RELAY_ENABLED == 'true'`. Les workflows planifiés sont retardés/désactivés après 60 jours d'inactivité : le watchdog doit lui-même être surveillé. Non ajouté.

### CI
`.github/workflows/relay-planner-ci.yml` (lecture seule, `pull_request` filtré sur `tools/**`, `tests/test_relay_*`) ; présent **uniquement sur la branche de PR** — à retirer avant tout merge vers `main` si le propriétaire ne veut pas ce workflow. Résultats à lire sur le SHA exact du commit, par PR.

### Limites restantes
Aucun exécuteur GitHub réel (CREATE_ISSUE/ADD_LABEL) n'est écrit ; `send` est injecté. Le filtre FORBIDDEN reste lexical. La concurrence multi-processus repose sur SQLite (un seul hôte).
