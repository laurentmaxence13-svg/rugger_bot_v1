# cpmmpilot 0.1.2 — K01 et K02 (décisions R02 f41c6cb0, défauts S01 et S02 relevés par R01), toujours HORS LIGNE

Les README 0.1 et 0.1.1 restent valables pour tout le reste.

- **S01 et S02 (R01)**
  - Ces deux défauts étaient déjà corrigés en 0.1.1. G-1 appelle `cpmmcost.model.pilot_verdict(positions, *, g0_passed, freeze_sheet_sha256)`.
  - Il n'y a ni recherche dans le module de règle, ni paramètre `placebo_`.
- **K01 (R02)**
  - Une position ENTRÉE dans un pool admis par `pool_gate`, mais non valorisable (CostError de `cpmmcost.position`), prend une VALEUR DE VENTE DE 0 et reste COMPTÉE.
  - Coût : mise + achat + vente + fermeture WSOL + nettoyage, soit 100 000 000 + 4 × 105 000 = 100 420 000 lamports, ou net_return = −1,0042. Ce sont les coûts de `cpmmcost.position` avec 0 échec et le compte fermé.
  - Le nombre de ces positions (`unpriced_counted_at_zero_sale`) et leurs motifs (`unpriced_reasons`) sont publiés.
  - **À confirmer par R02 :** la composition exacte des coûts d'une vente nulle (4 transactions, sans perte de loyer).
- **K02 (R02)**
  - `meaning` est retiré de la sortie de pilot_verdict et remplacé par la phrase de la fiche (`sheet_sentence`).
  - `assert_closed_vocabulary` s'applique à G1.json. Les mots sont les mêmes que `plbench.bench.FORBIDDEN_WORDS`, et un test lit le source de plbench pour le vérifier.
- **Mutants**
  - 26 mutants sur 26 sont tués, avec la garde de base (`MUTATIONS_cpmmpilot_v0_1_2.json`).
  - 4 sont nouveaux : `unpriced_dropped`, `zero_sale_without_tx`, `meaning_kept`, `vocabulary_unchecked`.
- **Tests**
  - 25 sur 25 sous `-W error`.
  - Le PYTHONPATH ajoute `plbench_pkg` (claude/r01-w1-tooling), qui ne sert qu'au test de parité du vocabulaire.
