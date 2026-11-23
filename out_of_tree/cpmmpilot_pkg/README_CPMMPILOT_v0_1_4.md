# cpmmpilot 0.1.4 — décisions R02 du 23/11 (21:41Z et 21:44Z), toujours HORS LIGNE

- **K-6 :** l'écart au témoin est RETIRÉ de cpmmpilot, sur décision de R02.
  - Aucun chiffre d'écart n'est publié.
  - L'écart apparié par pool, avec son IC, sera calculé par g1ind après son PASS, appelé depuis step1.
  - La fonction `paired_difference` de la 0.1.3 est supprimée.
  - `G1.json` indique : `difference = NOT PUBLISHED by cpmmpilot (R02)`.
- **K01, règle UNIQUE retenue par R02 :**
  - `step1.zero_sale(row, failures)` vaut −(STAKE + (4 + achat + vente + nettoyage échoués) × 105 000).
  - En primaire : −100 420 000, soit −1,0042.
  - Avec `Failures(1, 1, 1)` : −100 735 000.
  - Pas de perte de loyer : le mode est le compte fermé (C-a).
  - C'est la SOURCE UNIQUE de cette valeur.
- **Mutants :** 27 sur 27 tués.
  - `paired_global_means` est retiré, puisque la fonction n'existe plus.
  - `zero_sale_failures_ignored` est ajouté.
- **Tests :** 26 sur 26.
