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
