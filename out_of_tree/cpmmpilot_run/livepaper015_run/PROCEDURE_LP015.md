# Procédure livepaper 0.1.5, texte v7 31dfed47 (R03, 28/11) — À APPROUVER PAR R02 AVANT LE SETUP

## Règles fixes (réserves R02, 28/11 12:26Z)
- **R-1 : UN SEUL setup.** Un setup qui ne se termine pas par SETUP_DONE est un INCIDENT au sens du texte v7, et le test s'arrête DÉFINITIVEMENT. Sont concernés GSFA_FAIL, ORDERCHECK_FAIL, PREPARE_FAIL, INTEGRITY_FAIL, MANIFEST_FAIL et PRE_PAGES_FAIL. Il n'y a jamais de second dossier ni de second registre.
  Seule exception : un refus AVANT tout appel (OUT_EXISTS, BAD_START, START_TOO_CLOSE, START_TOO_FAR) n'a rien consommé. Il est publié, et R02 décide.
- **R-2 : la décision se lit dans le journal**, jamais dans le code retour (c'est celui de tee). Lignes lues : SETUP_LOG.txt (SETUP_DONE / *_FAIL) ; RUN_LOG.txt (INTEGRITY_FAIL, no call, rc=) ; dernier enregistrement de J.jsonl.
- **R-3 : la chaîne s'appelle uniquement par `bash /home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/<OUT>/chain_resume015.sh`**, sans autre texte dans la commande (à cause de la garde pgrep -f).

## Étapes
1. R02 approuve ce plan de réveils.
2. Setup, une seule fois, en arrière-plan : `bash .../livepaper015_run/setup_livepaper015.sh <OUT> <START>`, avec START = heure du setup + 7 200 s, arrondie à la minute.
3. Inscription des 5 valeurs dans des copies placées dans <OUT> :
   - <OUT>/launch_livepaper015_run.sh et <OUT>/chain_resume015.sh ;
   - valeurs : OUT, START, POOLS_RUN, SEED, ORDERCHECK.
   Ensuite : commit, delta envoyé à R02 et ancrage d'ORDERCHECK.
4. GO du run par R02, avant START.
5. Processus 1 : `bash <OUT>/launch_livepaper015_run.sh`, en arrière-plan avec timeout 7 200 000. Le lanceur attend START lui-même et refuse s'il a plus de 60 s de retard.
6. Enchaînement : voir le plan de réveils ci-dessous.
7. Fin du test : STOP end_of_test_86400, ou tout STOP définitif. Puis désactivation du déclencheur, publication (J, L, C, timing, SHA256SUMS des PAGES, interruptions mesurées) et envoi des sha à R02.

## Plan de réveils (S = START)
- Chaque processus dure au plus 110 min (6 600 s) et finit sur un STOP planned_end_of_process. La fin du test vient au plus tard à S + 86 400 (end_of_test_86400).
- Horaires NOMINAUX à latence de reprise nulle. La fin du processus k (k = 1 à 13) est à S + 6 600·k :
  1 : S+1h50 ; 2 : S+3h40 ; 3 : S+5h30 ; 4 : S+7h20 ; 5 : S+9h10 ; 6 : S+11h00 ; 7 : S+12h50 ;
  8 : S+14h40 ; 9 : S+16h30 ; 10 : S+18h20 ; 11 : S+20h10 ; 12 : S+22h00 ; 13 : S+23h50.
  Le processus 14 court jusqu'à S + 86 400 et s'arrête sur end_of_test_86400.
- Les horaires RÉELS se calculent à partir des fins réelles : le processus k+1 démarre à la fin réelle de k plus la latence de reprise. Chaque latence est mesurée et publiée (RUN_LOG : « rc= … end » puis « run_start »).
- **Réveil principal** : la notification de fin de la tâche d'arrière-plan du processus k. R03 lance alors IMMÉDIATEMENT `bash <OUT>/chain_resume015.sh`, en arrière-plan avec timeout 7 200 000. La chaîne fait elle-même toutes les gardes 1 à 4 et lance le processus k+1.
- **Réveil de secours : UN SEUL déclencheur**, un rappel horaire lié à cette session, créé juste après le GO du run. Texte exact :
  > « Rappel livepaper 0.1.5 (v7 31dfed47, dossier <OUT>, START <S>). (1) Si un processus `livepaper.cli run` ou une tâche chain/lanceur est en cours : ne rien faire. (2) Sinon, lire le dernier enregistrement de <OUT>/J.jsonl. S'il s'agit d'un STOP planned_end_of_process et que l'heure est < START + 86 400 : lancer une seule fois `bash <OUT>/chain_resume015.sh` en arrière-plan, timeout 7 200 000, et noter la latence. (3) Si J.jsonl contient un STOP end_of_test_86400, incident:*, credit_hard_stop_* ou un ERROR, ou si l'heure est ≥ START + 86 400 : DÉSACTIVER ce rappel (update_trigger enabled=false), ne rien lancer, publier et prévenir R02. (4) Tout autre état : ne rien lancer, prévenir R02. »
- Le déclencheur est désactivé à end_of_test_86400 ou à tout STOP définitif, puis supprimé après la publication. Il n'y en a jamais un deuxième.
- Interaction avec le 06/12 : la collecte G2-3 du 06/12 passe en priorité. Le test doit finir avant le 06/12 à 10:21Z, donc S ≤ 05/12 09:00Z. Sinon, pas de lancement.

## Crédits
Registre neuf : 25 000 crédits, arrêt dur à 24 500. Le setup GSFA est compté sur ce même registre. Référence 0.1.2 : 4 514 crédits pour environ 7 h (GSFA compris). C'est un ordre de grandeur, pas une prévision. L'arrêt dur reste la seule garantie.
