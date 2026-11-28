# Essai à blanc livepaper 0.1.5 — lanceur, chaîne et préparation (R03, 28/11, HORS RÉSEAU : unshare -rn, proxy mort)

Paquet : git archive de 9800986, MANIFEST 9ac7089c, sha256sum -c 0 écart. Tests 48/48 (-W error, hors réseau). Les dépendances de test sont dans TESTDEPS_015.txt et ne figurent pas dans le PYTHONPATH du run.
Copies d'essai : seuls OUT, START, POOLS_RUN, SEED et ORDERCHECK sont remplis, avec les valeurs fictives de cet essai. START = 1795868677 (fictif).

1. setup_livepaper015.sh :
   - intégrité OK : manifest, v7 31dfed47, pythonpath 488b8773, eligible 184576ea, L c96353b9, pages pré-départ 951b8479 (avec sha256sum -c) ;
   - prepare OK : POOLS_RUN 069e5456, SEED 0d4a3ee8 ;
   - collect-gsfa : RpcError network_error au 1er appel, puis « GSFA_FAIL: STOP, no ordercheck, no run » (rc 6) ;
   - registre neuf : 1 crédit compté pour l'appel en échec.
2. GSFA FICTIF : copie du GSFA de 0.1.2, contrôlée contre ses SHA256SUMS. ordercheck hors réseau : verdict a-ok, ORDERCHECK 815b94fd, identique octet pour octet à celui de 0.1.2 (déterministe).
3. launch_livepaper015_run.sh :
   - intégrité OK ;
   - attente jusqu'à START, puis run_start à 12:24:37Z, à l'heure exacte de START ;
   - 1er appel : network_error, journalisé START, ERROR, puis STOP incident:RpcError (D14 corrigé : l'échec est enregistré).
4. Relance directe du lanceur : SourceError journal_stopped_for_good:ERROR avant tout transport. Aucun crédit débité ; le registre reste à 2.
5. chain_resume015.sh : « 1 incident/credit-stop STOP: NO resume » (rc 10).
6. STOP_R03_v015.txt présent : le lanceur répond « no call » et la chaîne rc 11.

Remarque : pgrep -f sert à détecter un processus vivant. Il compare la ligne de commande de TOUS les processus. Une commande appelante qui contient le texte « launch_livepaper015_run.sh » ou « livepaper.cli run » fait donc refuser la chaîne (rc 8, faux positif, sans danger : le refus est le comportement sûr). En exploitation, appeler la chaîne seulement par « bash <chemin>/chain_resume015.sh ».
