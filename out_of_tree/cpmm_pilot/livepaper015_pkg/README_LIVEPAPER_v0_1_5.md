# livepaper 0.1.5 (projet) — 0.1.4 + points (a), (b) et (c) de R02 ; empreinte du texte signé EN ATTENTE

RUGGER 01, 26/11/2026. Périmètre minimal : R02 (03:01Z), consignes de R04 (03:08Z). Rien d'autre ne change.
Base : livepaper 0.1.4, commit 2965fcc, PASS DE CODE R02 à 02:57:05Z, documentée dans `README_LIVEPAPER_v0_1_4.md` de
ce commit. Le plafond reste 25 000 / 24 500 : le texte du propriétaire est aligné sur le code (R04).
Texte candidat : v6 b02c8b8e4007dbeb4b049bbb63d550d9ba6fcc2d5fd781b33cb7b60e36125a58 (2 091 octets), figé par R04 à
03:08Z, **non signé**. Les v3, v4 et v5 sont caducs. **Ce projet n'est pas exécutable.**

## Changements
- **(a) Empreinte du texte signé.**
  - `AUTHORIZED_TEXT_SHA256 = frozenset()` : la constante est EN ATTENTE. Aucun transport ne peut s'ouvrir.
  - 1366025b est retiré : `WITHDRAWN_TEXT_SHA256`.
  - Le test `test_the_authorized_text_is_inscribed` **échoue volontairement** tant que l'empreinte n'est pas inscrite.
    Il exige exactement une empreinte de 64 caractères hexadécimaux, hors textes retirés. J'ai vérifié sur une copie
    qu'il passe avec une empreinte valide.
  - L'empreinte sera inscrite par une version auditée, seulement après la signature du propriétaire et sa vérification
    à la source par R02. À ce moment, la désélection nominative du runner de mutants (`PENDING_TEST`) sera retirée.
- **(b) Une seule règle de reprise** (R04, 04:32Z, pour s'en tenir aux « deux gardes d'arrêt » du texte v6 ; la
  version reste la 0.1.5, il n'y a pas de 0.1.6). Un journal n'est repris que si deux conditions sont réunies :
  1. il ne contient **nulle part** un ERROR, ni un STOP `incident:*`, `credit_hard_stop_*` ou `end_of_test_86400`,
     sinon `journal_stopped_for_good:<raison ou ERROR>` (R04, 04:39Z) ;
  2. **son dernier enregistrement lu sur le disque est `STOP planned_end_of_process`**, sinon
     `journal_ended_without_planned_stop:<raison ou type>`.
  - Elle refuse aussi un journal qui finit sur START, STEP ou ERROR : processus tué sans STOP (SIGKILL, conteneur
    perdu), sur la réserve de R02 à 04:25Z et la décision de R04 à 04:26Z. Conséquence acceptée : le test s'arrête
    alors définitivement.
  - Elle est contrôlée dans `cli.run`, sur le fichier, avant le transport, le grand livre et le rejeu, puis dans
    `Runner.run` sur `Journal.loaded`, c'est-à-dire les enregistrements lus sur le disque. Le START écrit par le
    processus dans un journal neuf n'est donc pas pris pour une fin de journal.
  - Un enregistrement définitif suivi d'un arrêt prévu, cas que livepaper ne peut pas écrire, est refusé au lieu
    d'être supposé impossible.
  - Le commit 83a4d8d (garde (b) « tout STOP définitif ») reste un état intermédiaire non exécutable.
- **(c) Durée limitée à 24 h.** Le test dure au plus `TEST_S = 86 400 s` depuis START.
  - `check_window` refuse toute commande à start + 86 400 s ou après (`test_window_over`), avant toute requête réseau
    et avant le grand livre :
    - `run` : après la création du transport, qui n'envoie rien, et avant le rejeu ;
    - `collect-gsfa` : avant le transport ;
    - `ordercheck` : avant la lecture des collectes (R02, 03:09Z) ;
    - `Runner.run`.
  - En marche, un STOP `end_of_test_86400` intervient avant tout nouveau sondage.
- `SCHEMA = 'livepaper-v0.1.5'`.
  - Identiques à la 0.1.4 : méthodes (`METHODS_livepaper_v0_1_4.txt`, inchangé), plafond, D13, D14, D15.
  - Identiques à la 0.1.2 : `fill.py` et `ordercheck.py`.

## Tests (cas limites écrits avant les mutants)
- (a) :
  - l'ancien texte 1366025b n'ouvre plus le transport, même quand une autre empreinte est inscrite ;
  - un texte inscrit l'ouvre ; un octet de plus le refuse ; une clé dans l'URL est refusée.
- (b) :
  - seul `STOP planned_end_of_process` se reprend ; un journal neuf (aucun enregistrement) est accepté ;
  - refusés : les STOP `incident:RpcError`, `incident:SourceError`, `credit_hard_stop_24500` et
    `end_of_test_86400` ; un journal qui finit sur START, sur STEP ou sur ERROR ;
  - `loaded=0` : le START écrit par le processus est accepté ; `loaded=1` : un START lu sur le disque est refusé ;
  - un STOP de raison inconnue (par exemple `manual_stop`) est refusé : la condition 2 est une liste blanche. Ce test a
    été ajouté après la survie du mutant `rule_any_stop_accepted` au premier passage (133/134) ;
  - un ERROR, ou un STOP `incident:*`, `credit_hard_stop_*` ou `end_of_test_86400`, suivi d'un pas puis d'un arrêt
    prévu, est refusé ; des arrêts prévus au milieu du journal sont acceptés ;
  - un journal tué entre son ERROR et son STOP est refusé (`ERROR`) ;
  - après l'arrêt dur des crédits, le processus suivant (rejeu depuis le disque) est refusé sans appel ;
  - après un incident : rejeu identique, puis refus du Runner sans appel ni écriture ;
  - processus tué (STOP final retiré) : rejeu identique, puis refus sans appel ; le même journal avec son STOP prévu
    reprend ;
  - en ligne de commande : refus d'un journal tué, puis d'un journal arrêté sur incident, avant le rejeu (piège) et
    sans toucher au grand livre.
- (c) :
  - frontière start + 86 399 s acceptée, start + 86 400 s refusée ;
  - un processus lancé 70 s avant la fin fait 3 pas, puis STOP `end_of_test_86400` ;
  - un sondage qui commencerait exactement à start + 86 400 s n'a pas lieu. Ce cas a été ajouté après la survie du
    mutant `end_of_test_strict` au premier passage (126/127) ;
  - `run`, `collect-gsfa` et `ordercheck` tardifs sont refusés sans appel, sans grand livre et sans sortie.
- Refus de schéma étendu à `livepaper-v0.1.4`.
- Le test 0.1.4 « la reprise après incident ne perd rien » devient « le journal n'est jamais repris ».
- Tests : 46 réussis et 1 échec voulu (`test_the_authorized_text_is_inscribed`), avec `-W error`, livesim 0.3.1 et
  0.3.2.
- Mutants : 134/134 détectés, dont 21 nouveaux par rapport à la 0.1.4 (le runner désélectionne le test en attente, par son nom).
  Résultat dans `MUTATIONS_livepaper_v0_1_5.json`.
