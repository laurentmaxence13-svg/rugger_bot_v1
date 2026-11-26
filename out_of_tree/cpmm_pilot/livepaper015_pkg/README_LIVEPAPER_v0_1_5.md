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
- **(b) Pas de reprise après un arrêt définitif.** Un journal qui contient un STOP `incident:*` ou `credit_hard_stop_*`
  n'est jamais repris.
  - `check_resumable` est appelé dans `cli.run`, avant le transport, le grand livre et le rejeu, puis dans `Runner.run`.
  - Tout STOP du journal compte. Seule sa raison compte, pas le message d'un ERROR.
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
  - reprenables : `planned_end_of_process`, `end_of_test_86400` ;
  - non reprenables : `incident:RpcError`, `incident:SourceError`, `credit_hard_stop_24500`, et un incident ancien
    suivi d'un arrêt prévu ;
  - un ERROR dont le message contient « incident: » ne compte pas ;
  - après un incident : rejeu identique, puis refus du Runner sans appel ni écriture ;
  - après l'arrêt dur des crédits : un 2e `run` est refusé sans appel ;
  - en ligne de commande, le refus intervient avant le rejeu (piège) et sans toucher au grand livre.
- (c) :
  - frontière start + 86 399 s acceptée, start + 86 400 s refusée ;
  - un processus lancé 70 s avant la fin fait 3 pas, puis STOP `end_of_test_86400` ;
  - un sondage qui commencerait exactement à start + 86 400 s n'a pas lieu. Ce cas a été ajouté après la survie du
    mutant `end_of_test_strict` au premier passage (126/127) ;
  - `run`, `collect-gsfa` et `ordercheck` tardifs sont refusés sans appel, sans grand livre et sans sortie.
- Refus de schéma étendu à `livepaper-v0.1.4`.
- Le test 0.1.4 « la reprise après incident ne perd rien » devient « le journal n'est jamais repris ».
- Tests : 45 réussis et 1 échec voulu (`test_the_authorized_text_is_inscribed`), avec `-W error`, livesim 0.3.1 et
  0.3.2.
- Mutants : 127/127 détectés, dont 14 nouveaux (le runner désélectionne le test en attente, par son nom). Résultat dans
  `MUTATIONS_livepaper_v0_1_5.json`.
