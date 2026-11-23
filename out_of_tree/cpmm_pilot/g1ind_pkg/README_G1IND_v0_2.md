# g1ind 0.2 — rapport DESCRIPTIF du pilote CPMM autour de la fonction G-1 gelée

RUGGER 01, 23/11/2026.
- Origine : T-R01-4, décision de R04 de 21:30Z. Le périmètre (1) à (7) est celui du message R01 → R04 de 21:27Z.
- Base : la note g1verif, commit 071bb01.
- Appelant : R03, depuis cpmmpilot 0.1.1.
- Soumis à l'audit de R02.
- **v0.2** : applique les décisions K01 et K02 de R02 (f41c6cb0, 21:30Z). La v0.1 (c300593) est remplacée ; ses
  fichiers MANIFEST, MUTATIONS et README v0_1 sont conservés pour l'historique.

## Ce que fait le module

**Une seule décision : celle de la fonction gelée.**
- G-1 est `cpmmcost.model.pilot_verdict` (cpmmcost 0.3, 7deb7b7), appelée une fois, telle quelle.
- g1ind ne rend aucun autre mot de verdict. Le témoin reste un comparateur sans verdict.

| # | Sortie | Règle |
|---|---|---|
| 1 | `g1` | Dict de `pilot_verdict` sur TOUTES les lignes primaires, les non valorisées valant 0 (K01). Seul `meaning` est remplacé par la phrase de la fiche (K02 option a, décidée par R02). |
| 2 | `unpriced` | K01 (R02 f41c6cb0 ; R-0.3 2792655a, b31a3c47, d34c2c4e) : une ligne non valorisée est une position ENTRÉE vendue 0. Elle est COMPTÉE dans la moyenne et dans les planchers de G-1 ; son nombre et ses motifs sont publiés. |
| 3 | `metrics_b31a3c47` | Voir le détail ci-dessous. |
| 4 | `paired_gap` | Moyenne primaire − témoin, sur les pools présents dans les DEUX bras. Statistique de c2 de `confirmation_verdict`, bootstrap par pool, graine de la fiche, bornes unilatérales à 95 %. DESCRIPTIF : c2 n'est une condition qu'à la confirmation. |
| 5 | `robustness` | Liste fermée des 7 sensibilités b31a3c47. Voir le détail ci-dessous. |
| 6 | `power.flag` | « sous la cible de puissance » si n_entered < `cpmmprereg.n_required()` = 155. |
| 7 | — | Tout le document passe le contrôle du vocabulaire fermé (mêmes mots que `plbench.FORBIDDEN_WORDS`, testé). Le mot trouvé n'est jamais répété dans l'erreur. |

**Valeur d'une ligne non valorisée (K01).**
- Formule gelée de closedacct sans vente : r = (− coût − rente) / mise, avec coût = mise + transactions d'achat, de
  vente et de fermeture WSOL, aux échecs de la série. Pas de nettoyage, la rente de 2 039 280 lamports est perdue.
- Au primaire : −102 354 280 lamports, soit r = −1,0235. Avec la sensibilité « 1 échec » (1, 1, 1) :
  −102 564 280 lamports.
- C'est la plus défavorable des lectures gelées d'une valeur nulle. La lecture en compte fermé rendrait la rente
  moins le nettoyage. À confirmer par R02.
- Le témoin suit la même règle.
- Pour le DD, la perte est placée à la sortie la plus tardive que la règle permet : décision + 1 800 s + latence
  d'horloge.

**Détail de (3), métriques b31a3c47.** Elles portent sur la même population que la moyenne de G-1 : toutes les
lignes, refus de garde et lignes valorisées à 0 compris.
- Gain si r > 0, perte si r ≤ 0.
- PF net = Σr⁺ / |Σr⁻|, NON MESURÉ sans r négatif.
- Identité de l'espérance contrôlée.
- DD dans l'ordre de SORTIE, en mises et en SOL.
- Frais ventilés à partir de `decomposition_share_of_stake`, sur les positions entrées et valorisées. Le frais moyen
  des refus de garde et le nombre de lignes valorisées à 0 sont donnés à part.
- Le DD exige les timelines (`lines`). Sans elles, il est NON MESURÉ : il n'y a jamais de repli sur l'ordre d'entrée.

**Détail de (5), sensibilités.** Chaque valeur est une moyenne, ou NON MESURÉ quand l'entrée n'est pas fournie.
- **Fournies par cpmmpilot**, avec les fonctions gelées `cpmmprereg.positions(...)`. g1ind vérifie, ligne par ligne,
  les MÊMES décisions et le paramètre déclaré :
  - `latency_10_slots` : latency_slots = 10 ;
  - `one_failure_per_tx` : au moins 1 échec à l'achat ET à la vente ;
  - `rent_lost_vs_closed_account` : cleanup = MAX_CLEANUP_ATTEMPTS = 3 ;
  - `guard_5_percent` : garde à 50 000 ppm.
- **Calculées par g1ind** :
  - `without_5_best_pools` (b31a3c47), avec aussi la lecture « sans les 5 meilleures positions » de c5 ;
  - `half_1_half_2` : coupure `cut_time` ancrée, sur decision_time < coupure.
- **`frozen_mev_grid`** : NON MESURÉ. mevsens 0.1 est un modèle de sandwich sur la courbe LaunchLab, et aucune
  adaptation CPMM auditée n'existe.

**Si G-0 n'est pas passé** (G-1 = STOP), aucun chiffre n'est publié.

## Ordre de sortie, pour le DD

| Cas | Heure de sortie retenue |
|---|---|
| Sortie à l'horloge | Le temps déclaré par `cpmmprereg.exit_point` (échéance + latence d'horloge). |
| Sortie TP / SL | Heure de bloc du swap déclencheur (slot = déclaré − latence) + `hrr.clock_exit_latency_s(latence)`, la même convention que l'horloge. |
| Refus de garde | Heure de la décision : le frais est payé alors. |

À égalité, on départage par slot de décision, puis par pool.

## Appel par cpmmpilot 0.1.1 (R03)

```python
from g1ind import report as G1
doc = G1.report(name, primary, placebo, g0_passed=<certificat G-0 de l'étape 0>,
                freeze_sheet_sha256=sheets[name], cut_time=<coupure ancrée>, lines=timelines,
                sensitivities=dict(latency_10_slots=R.positions(line, cfg, idx, latency_slots=10), ...))
```

- `primary` et `placebo` sont les lignes BRUTES de `positions`. g1ind valorise lui-même à 0 les lignes non valorisées,
  y compris dans chaque sensibilité.
- `name` vaut 'RCP1' ou 'B1'.

## Points soumis à R02

- **K01 et K02** : décidés (f41c6cb0) et appliqués. Reste à confirmer la lecture « sans vente, rente perdue » de la
  valeur 0.
- **Écart de texte sur la sensibilité « 1 échec ».**
  - `cpmmcost.SENSITIVITY_FAILURES = Failures(1, 1, 1)`.
  - La docstring de `cpmmprereg.positions` donne `Failures(1, 1, 0)`.
  - g1ind accepte les deux (au moins 1 à l'achat et à la vente). Le triplet utilisé est à ancrer par R02.
- **Grille MEV** : NON MESURÉ sur CPMM, à confirmer.

## Validation

- 13 tests sur fixtures, dont K01 (valeur exacte, comptage dans les planchers, témoin, sensibilités), dont un bout à bout avec le code gelé (cpmmx, cpmmprereg, cpmmcost) sur un pool synthétique.
- 40 mutants sur 40 détectés, dont 8 sur K01 (`MUTATIONS_g1ind_v0_2.json`, runner `mutations_g1ind_runner.py`, garde de référence).
- Commande, cwd wt_w1, sans `-I` :
  `env -i PYTHONPATH=<chemin commun des paquets>:<plbench deps>:<g1ind_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <g1ind_pkg>/g1ind/tests -p no:cacheprovider -q -W error`
- Aucune donnée lue, aucun essai consommé, aucun code audité modifié.
