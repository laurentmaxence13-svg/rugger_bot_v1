# P9 — durée de la collecte G2-3 du 06/12 (hors ligne, 0 appel)

Méthode : intervalles entre écritures successives des pages (st_mtime), sur les phases d'appels des runs ancrés :
- A2r : 24/11, 16:49:09Z → dernier appel à +357 s ; journal calls_step1 et registre écrits à +357 s ;
- livesim : qualify + history, 25/11, 11:38:51Z → 11:43:04Z.
Une page correspond à un appel GTFA, la relecture unique comprise : chaque appel est compté. Le délai entre le lancement et la 1re page (5,39 s et 1,41 s) correspond au démarrage, pas à un appel ; il est exclu.
Les journaux calls_*.jsonl et C.jsonl n'ont pas d'horodatage. Les PAGES de livepaper sont espacées par le cadencement à 30 s, si bien qu'elles ne mesurent pas la durée d'un appel.

| source | intervalles | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| A2r | 1 341 | 0,265 s | 0,318 s | 0,363 s | 0,541 s |
| livesim | 1 025 | 0,213 s | 0,261 s | 0,326 s | 1,069 s |
| poolé | 2 366 | 0,245 s | 0,309 s | — | 1,069 s |

8 820 × p95 = **45,4 min**. 8 820 × max = **157,2 min**. Cette dernière est une borne théorique : le max est observé une seule fois sur 2 366 intervalles.

Traitement après les appels, dans le même processus : step1.require_tx_format relit toutes les pages. Il a été mesuré hors ligne, depuis l'extraction 54fde86, sur le dossier fictif G23_DRYRUN_FICTIVE : 1 241 pages et 123 507 tx en 60,7 s, soit 0,049 s par page. Pour 8 820 pages : ≈ 7,2 min.

Total au pire du plafond (88 200 crédits, au p95) : ≈ 45,4 + 7,2 + démarrage ≈ **53 min**.

ERRATUM R03 : le chiffre « 0,72 s par appel » (PREPARATION_COLLECTE_G23_06DEC.md, ligne Durée > 2 h) est FAUX en tant que durée par appel. C'était la durée totale d'A2r (999 s) divisée par 1 380 requêtes, ce qui inclut 642 s de traitement local après le dernier appel. Pendant la phase d'appels d'A2r, la moyenne est de 0,259 s par appel (1 380 appels en 357 s).
