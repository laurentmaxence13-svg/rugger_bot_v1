# cpmmpilot 0.1.3 — K-6 de la revérification R02 (01512bee), toujours HORS LIGNE

Les README 0.1, 0.1.1 et 0.1.2 restent valables.

- **K-4 (règle K01) et K-5 (règle K02) :** traités dès la 0.1.2 (a1881f4). Une position non valorisable est comptée comme une vente à 0 dans pilot_verdict ; `meaning` est retiré et remplacé par `sheet_sentence` ; le vocabulaire fermé est contrôlé.
- **K-6 :** `step1.paired_difference` calcule l'écart au témoin APPARIÉ PAR POOL (certificat d34c2c4e).
  - Calcul : on prend, pour chaque pool présent dans les deux bras, la moyenne des nets de la règle moins celle des nets du témoin, puis la moyenne de ces écarts sur les pools appariés.
  - Intervalle de confiance à 95 % bilatéral : bootstrap groupé par pool, 10 000 tirages, graine = int(sha de la fiche[:8], 16).
  - Publication : le nombre de pools appariés et de pools présents dans un seul bras, sous `placebo.paired_by_pool`, sans décision.
  - Comme la règle K01, la conversion en vente nulle des lignes non valorisables s'applique aussi au témoin, par symétrie. Leur nombre est publié.
- **Mutants :** 27 sur 27 sont tués (`MUTATIONS_cpmmpilot_v0_1_3.json`). Le nouveau mutant est `paired_global_means`.
- **Tests :** 26 sur 26.
