# Relais RUGGER : diagnostic des déclenchements, correctifs P1 et circuit unique (mission #211)

Rédigé par RUGGER 04 le 2026-11-06, sur mandat du propriétaire. **Rien n'est activé** : pas de
workflow de production, pas de secret, pas de permission, pas de fusion, pas de dépense.
Statuts employés : *démontré par le code*, *reproduit par test*, *observé* (journal de plateforme),
*inconnu*.

## 1. Diagnostic : pourquoi #211 n'a laissé aucune preuve de démarrage

Chaîne réelle d'une mission : **étiquette GitHub → tâche planifiée (routine) → session Claude Cloud →
exécution effective → compte rendu**. Pour #211, chaque maillon a été vérifié :

| Maillon | Constat | Statut |
|---|---|---|
| Étiquette | `rugger-04-run` posée à la création de #211 (2026-11-06 00:46 UTC) | observé (GitHub) |
| Routine | « RUGGER 04 — Supervision & Stratégie » (`trig_016xLuuyEibebGT8vRzAyuWR`) déclenchée à 00:46:38 sur `issues.labeled` #211, `ROUTINE_RUN_STATUS_SUCCEEDED` | observé (liste des tâches planifiées) |
| Session | `cse_016VkauGgdYpza3TDGDnL8Q1`, modèle Sonnet, démarrée en 5 s | observé (transcription) |
| Exécution | **échec** : le serveur MCP GitHub de la session n'a pas pu se connecter (`400 CLIENT_HTTP_NOT_IMPLEMENTED`). L'agent a abandonné après 9 s, sans essayer `git` ni l'API REST, qui passent pourtant par le proxy de session. Il a seulement envoyé une notification push. | observé (transcription) |
| Compte rendu | aucun commentaire : sans outil GitHub, la routine ne pouvait pas écrire | observé |
| Relance | le commentaire de coordination du 2026-11-06 20:00 n'a pas relancé la routine : seul `issues.labeled` est observé comme déclencheur, et l'étiquette n'a pas été reposée. Les filtres d'événements de la routine ne sont pas exposés par l'API. | observé / inconnu |

Autres défauts observés dans les mêmes routines :
- le connecteur nommé `Claude-Docs` n'est pas chargé (« reserved MCP server name ») ;
- le texte de la routine RUGGER 01 code en dur une « première mission PR #147 », désormais périmée ;
- **doublon #213 / #214** : la routine RUGGER 03 (exécution à 17:52 sur #212) et la session interactive
  RUGGER 03 ont traité la même mission sans aucun verrou commun. Deux PR sont nées pour le même
  besoin. Aucun mécanisme du dépôt ni de la plateforme n'empêchait ce cas.

**Cause racine** : trois circuits indépendants donnent des missions aux mêmes agents, sans identifiant
de mission commun ni verrou :
1. les sessions Claude interactives, coordonnées par RUGGER 04 et le registre T-REG ;
2. les routines GitHub déclenchées par étiquette ;
3. le suivi horaire ChatGPT, qui n'est pas un orchestrateur continu.

Les échecs d'exécution (outil indisponible) ne laissent pas de trace dans l'issue, et rien ne relance
une mission bloquée.

Permissions ou réglages manquants, **à décider par le propriétaire** (rien n'a été modifié) :
- rétablir le connecteur GitHub des routines, ou leur imposer le repli `git` + API REST ;
- ajouter aux textes des routines la règle de verrou (§3) et l'obligation de poster une preuve de
  démarrage ou d'échec ;
- **ne pas reposer `rugger-04-run` sur #211** tant que la session interactive RUGGER 04 détient cette
  mission : sinon, nouveau doublon.

## 2. Correctifs des quatre P1 du contre-audit #210 (reproduit par test)

| P1 | Correctif (démontré par le code) | Tests (`tests/test_relay_p1.py`) |
|---|---|---|
| 1. Rapport non authentifié sur `issues.closed` | `last_comment` (texte libre) n'est plus jamais cru. Il faut un **objet commentaire** (`authenticate_report`) : auteur dans la liste autorisée, association OWNER ou MEMBER, `id` entier, rattaché à **cette** issue du **bon** dépôt, `created_at` postérieur au lancement (`since`). Le même commentaire ne peut pas compléter deux fois (`comment:<id>`). | `P1_1_*` : texte libre, tiers, bot, autre issue, commentaire antérieur au lancement, objets malformés, acceptation unique |
| 2. Source du `delivery_id` | Une seule source acceptée : `gha-run:<GITHUB_RUN_ID>`, construite par `delivery_id_from_actions_env`, qui vérifie le dépôt et le nom d'événement. Tout autre identifiant est refusé (fail-closed). Une réexécution du même run garde le même identifiant, donc reste idempotente. Il n'existe aucun récepteur HTTP : pas de `X-GitHub-Delivery`, pas de signature à vérifier. En ajouter un exigerait d'abord la vérification de signature. | `P1_2_*` |
| 3. TOCTOU entre RUNNING et COMPLETED | `relay_store.transact` : la lecture d'état, la vérification RUNNING sur l'issue, l'authentification du rapport, la revendication des clés de déduplication et les effets se font dans **une seule** transaction `BEGIN IMMEDIATE`. Le chemin `issues.labeled` est décidé sous le même verrou. | `P1_3_*` : écrivain concurrent inséré au milieu, 8 livraisons parallèles → 1 seul successeur |
| 4. `since` invalide | `relay_planner.parse_since` : un horodatage absent, malformé ou naïf donne `None`. `decide` réutilise `watchdog` → agent BLOCKED et escalade, jamais d'exception. L'exécuteur bloque l'agent si son heure de lancement est corrompue. | `P1_4_*` |

Audit RUGGER 02 de #215 @ `2c37c6d` : BLOCKED sur deux points, corrigés ensuite (tests `R02AuditBlockers215`,
rouge 2/2 puis vert) :
- **B1** : le kill switch était lu hors verrou. Il est désormais relu sous `BEGIN IMMEDIATE`, dans
  `transact` et dans `apply_decision`.
- **B2** : `issue_url` est désormais **obligatoire**. Sans lui, le commentaire est refusé, aussi bien
  sur `issue_comment` que sur `issues.closed`.

Ré-audit RUGGER 02 @ `b7159ee` : B1 et B2 levés. Trois observations traitées ensuite (tests
`KillSwitchOwnerAlerts`, rouge 4/4 puis vert) :
- **O-1** : un refus dû au kill switch n'est plus journalisé comme « doublon ».
- **O-2** : `run_outbox` relit le kill switch avant **chaque** envoi ; un passage à ON arrête le drain.
- **O-3** (décision du propriétaire du 2026-11-10) : le propriétaire est alerté à l'activation, à la
  levée et en cas d'échec de reprise (`set_kill_switch`, `owner_alert`, `relay_executor.resume`). Les
  autres escalades restent suspendues tant que le kill switch est ON.

Identité du bot : `ALLOWED_BOTS` reste **vide**. L'identité réelle de l'acteur Claude Cloud / GitHub
App est **inconnue** et n'est pas devinée. Conséquence : un rapport posté par un acteur bot est refusé.
**Limite importante** : tous les agents écrivent aujourd'hui sous le compte du propriétaire. La liste
autorisée prouve donc « écrit avec les droits du compte propriétaire », pas « écrit par le
propriétaire humain ». C'est le point P1-5, qui reste ouvert.

Rouge → vert : sur `tools/` de `582ea25` (head #209), les nouveaux tests donnent **18 échecs sur
73** (4 FAIL, 14 ERROR). Les 52 tests existants passent sur l'ancien comme sur le nouveau code.
Sur la branche corrigée : **73/73 OK** (puis **75/75** avec les tests B1/B2). Ils exigent maintenant des heures UTC explicites et des
`delivery_id` `gha-run:<n>`, conformément au contrat.

## 3. Circuit unique proposé (NON activé)

Règle : **une mission → un identifiant stable → un verrou → une seule session responsable.**

- **Identifiant** : l'identifiant T-REG (`T-0039`), ou `issue:<n>` pour une mission sans tâche T-REG.
- **Verrou atomique** (`relay_store.claim_mission`) : un seul détenteur à la fois. Il est nommé
  explicitement : `session:<id>` pour une session interactive, `routine:rugger-0N` pour une routine.
  Un second demandeur reçoit le nom du détenteur et **ne travaille pas**.
- **Preuve de démarrage** (`start_mission`) : identifiant d'un commentaire ou d'un commit,
  obligatoire.
- **Bail** de 90 min, renouvelé par `heartbeat_mission`. Un bail expiré peut être repris,
  **au plus 3 tentatives**, puis la mission passe BLOCKED avec escalade au propriétaire.
- **État terminal** (`finish_mission`) : COMPLETED, BLOCKED ou CANCELLED. Une mission terminée n'est
  jamais reprise : c'est ce qui empêche un nouveau #213 après #214.
- **Séparation des circuits** :
  - sessions manuelles et routines prennent le **même** verrou ;
  - le suivi ChatGPT ne fait qu'**observer** : il ne prend jamais de verrou et ne pose une étiquette
    que sur une mission libre.
- **Absence de réponse** : bail expiré → nouvelle tentative bornée → escalade.

Limite : le verrou est une primitive du dépôt. Il n'empêche les doublons que si **chaque** exécutant
l'appelle. Pour cela, il faut un état partagé et durable, accessible aux routines comme aux sessions.
SQLite sur un runner éphémère ne l'est pas (P1-6). Le choix d'un stockage partagé est une décision du
propriétaire : par exemple un commentaire-verrou sur l'issue écrit par une seule identité, une branche
d'état dédiée, ou un service externe.

## 4. Plan de test de bout en bout, en environnement isolé (à exécuter seulement avec accord)

Pré-requis : un **dépôt de test** séparé (jamais `rugger_bot_v1`), aucun secret de production,
aucun fournisseur réseau.
1. Créer l'issue de test « mission X » et poser `rugger-0N-run` : vérifier **un seul** démarrage
   (verrou pris, preuve de démarrage publiée).
2. Reposer l'étiquette, et lancer en parallèle une session manuelle sur la même mission : vérifier le
   refus, le nom du détenteur publié et l'absence de travail en double.
3. Commentaire de rapport `STATUS: COMPLETED` par le détenteur → CI hors ligne verte → audit RUGGER 02
   sur le SHA → `finish_mission` COMPLETED.
4. Rejouer l'événement (même run) puis un nouvel événement identique : aucun effet.
5. Simuler un agent muet (pas de heartbeat) : expiration du bail, 3 reprises au plus, puis BLOCKED et
   escalade.
6. Kill switch ON : aucune action.
7. Critère final : 1 démarrage, 1 rapport, 1 audit, 1 état terminal, 0 doublon. Chaque preuve
   (identifiant d'événement, commentaire, SHA, run CI) est consignée.

## 5. Restent BLOQUÉS (décision du propriétaire ; non simulés)

- **P1-5** : expéditeur réel et idempotence après plantage. `run_outbox` ne vérifie pas l'existence
  préalable de l'issue. Il faut une identité d'écriture distincte et l'accord du propriétaire.
- **P1-6** : stockage durable partagé. SQLite sur un runner éphémère ne convient pas.
- **P1-7** : déclenchement d'une routine Claude par une étiquette posée par `GITHUB_TOKEN`. Non
  prouvé : seul le test de bout en bout du §4 peut le trancher.
- **Routines** : réparer le connecteur GitHub (ou imposer le repli REST), ajouter la règle de verrou
  et de preuve de démarrage à leurs textes, et retirer la mission périmée codée en dur dans
  RUGGER 01.
