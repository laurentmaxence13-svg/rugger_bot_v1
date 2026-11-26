# lpbilan 0.1.1 — lpbilan 0.1 + lecture des enregistrements ERROR et CATCHUP (livepaper 0.1.4)

RUGGER 01, 26/11/2026. Réserve (2) de R02 sur livepaper 0.1.4 (PASS DE CODE 02:57:05Z) : lpbilan doit lire ERROR et
CATCHUP avant tout bilan d'une reprise. lpbilan 0.1 (3afa3b2, PASS R02) n'est pas modifié.

- **C10** : ERROR et CATCHUP sont publiés et ne servent jamais aux indicateurs.
  - Pour chaque ERROR du préfixe : type, message expurgé, heure.
  - Pour chaque CATCHUP : pool, résultat, signatures, slot de réception.
  - Le nombre de RECEIVED dont `index_source = gsfa_rank_catchup`.
- Les ERROR et STOP qui suivent le dernier STEP ≤ cut entrent dans le préfixe si leur heure murale est ≤ cut. En 0.1,
  seuls les STOP y entraient.
- Le journal se lit avec le `livepaper.journal` du chemin. La 0.1.4 connaît ERROR et CATCHUP ; la 0.1.2 les refuse comme
  une chaîne cassée. Il faut donc lancer avec livepaper 0.1.4 sur le chemin, qui lit aussi les journaux 0.1.2.
- `SCHEMA = 'lpbilan-v0.1.1'`. Le reste est lpbilan 0.1, octet pour octet (conventions C1 à C9).
- Non-régression sur le snapshot ancré 1e86638 (cut 1795653600, NOTES afc3c2f4), avec livepaper 0.1.4 sur le chemin :
  - BILAN.json : ne diffèrent que `schema` et les trois champs nouveaux d'`interruptions` (vides ou zéro) ;
  - DECOMPOSITION.md : identique ;
  - BILAN.md : deux lignes ajoutées (« Incidents (ERROR) : 0. », « Rattrapages (CATCHUP) : 0 ; … : 0. »).
- Tests : 19/19 avec `-W error` (livepaper 0.1.4 + livesim 0.3.2 sur le chemin).
- Mutants : 34/34 (`MUTATIONS_lpbilan_v0_1_1.json`), dont 4 nouveaux.
- PAPER_LIVE_DEMO : jamais un trade du Master, jamais compté pour 50/20, aucun verdict.
