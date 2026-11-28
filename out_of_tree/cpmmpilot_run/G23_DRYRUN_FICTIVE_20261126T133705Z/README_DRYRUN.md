# DOSSIER FICTIF d'exécution à blanc de la chaîne G2-3 (R03, 26/11, P1 du pré-mortem) — PAS les données du 06/12

- Disposition EXACTE de la collecte du 06/12 (g23_collect) : `window/collect/window/<pool>/page_*.json.gz` + `STATE.json`, pour les 4 pools pilotes.
- Contenu : les pages PRÉ-T0 d'A2r (STEP1A2R_20261124T164909Z/pre_pages), copiées à l'identique. Elles couvrent une fenêtre FICTIVE de 7 jours, [1794910886 ; 1795515686), entièrement antérieure à T0 = 24/11 10:21:26Z.
  - Avant la copie, ces pages ont été vérifiées contre SHA256SUMS_PRE_PAGES (8fb3cac4) : 0 écart.
  - Aucune lecture de la fenêtre du pilote, aucun appel, 0 crédit.
- Différences avec la vraie collecte :
  - fenêtre de 7 j au lieu de 12 j (start et end à passer en paramètres) ;
  - aucun G23_COLLECT_RESULT.json ni ledger_g23.json réels. Rien ici ne doit servir de résultat.
- Continuité : voir `CONTINUITY_REPORT.json`.
