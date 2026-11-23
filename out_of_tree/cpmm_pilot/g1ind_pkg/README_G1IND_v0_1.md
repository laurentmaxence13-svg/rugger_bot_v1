# g1ind 0.1 — rapport DESCRIPTIF du pilote CPMM autour de la fonction G-1 gelée

RUGGER 01, 23/11/2026.
- Origine : T-R01-4, décision de R04 de 21:30Z. Le périmètre (1) à (7) est celui du message R01 → R04 de 21:27Z.
- Base : la note g1verif, commit 071bb01.
- Appelant : R03, depuis cpmmpilot 0.1.1.
- Soumis à l'audit de R02.

## Ce que fait le module

**Une seule décision : celle de la fonction gelée.**
- G-1 est `cpmmcost.model.pilot_verdict` (cpmmcost 0.3, 7deb7b7), appelée une fois, telle quelle.
- g1ind ne rend aucun autre mot de verdict. Le témoin reste un comparateur sans verdict.

| # | Sortie | Règle |
|---|---|---|
| 1 | `g1` | Dict de `pilot_verdict` sur les lignes valorisées. Seul `meaning` est remplacé par la phrase de la fiche (K02 option a, en attente de R02). |
| 2 | `unpriced` | Lignes non valorisées exclues de G-1, publiées avec leur motif (K01, en attente de R02). |
| 3 | `metrics_b31a3c47` | Voir le détail ci-dessous. |
| 4 | `paired_gap` | Moyenne primaire − témoin, sur les pools présents dans les DEUX bras. Statistique de c2 de `confirmation_verdict`, bootstrap par pool, graine de la fiche, bornes unilatérales à 95 %. DESCRIPTIF : c2 n'est une condition qu'à la confirmation. |
| 5 | `robustness` | Liste fermée des 7 sensibilités b31a3c47. Voir le détail ci-dessous. |
| 6 | `power.flag` | « sous la cible de puissance » si n_entered < `cpmmprereg.n_required()` = 155. |
| 7 | — | Tout le document passe le contrôle du vocabulaire fermé (mêmes mots que `plbench.FORBIDDEN_WORDS`, testé). Le mot trouvé n'est jamais répété dans l'erreur. |

**Détail de (3), métriques b31a3c47.** Elles portent sur la même population que la moyenne de G-1 : les lignes
valorisées, refus de garde compris.
- Gain si r > 0, perte si r ≤ 0.
- PF net = Σr⁺ / |Σr⁻|, NON MESURÉ sans r négatif.
- Identité de l'espérance contrôlée.
- DD dans l'ordre de SORTIE, en mises et en SOL.
- Frais ventilés à partir de `decomposition_share_of_stake`, sur les positions entrées. Le frais moyen des refus de
  garde est donné à part.
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

- `primary` et `placebo` sont les lignes BRUTES de `positions` ; g1ind sépare lui-même les lignes valorisées.
- `name` vaut 'RCP1' ou 'B1'.

## Points soumis à R02

- **K01 et K02** : g1ind applique « exclure et publier » et « option a ». Il s'alignera sur la décision de R02.
- **Écart de texte sur la sensibilité « 1 échec ».**
  - `cpmmcost.SENSITIVITY_FAILURES = Failures(1, 1, 1)`.
  - La docstring de `cpmmprereg.positions` donne `Failures(1, 1, 0)`.
  - g1ind accepte les deux (au moins 1 à l'achat et à la vente). Le triplet utilisé est à ancrer par R02.
- **Grille MEV** : NON MESURÉ sur CPMM, à confirmer.

## Validation

- 13 tests sur fixtures, dont un bout à bout avec le code gelé (cpmmx, cpmmprereg, cpmmcost) sur un pool synthétique.
- 32 mutants sur 32 détectés (`MUTATIONS_g1ind_v0_1.json`, runner `mutations_g1ind_runner.py`, garde de référence).
- Commande, cwd wt_w1, sans `-I` :
  `env -i PYTHONPATH=<chemin commun des paquets>:<plbench deps>:<g1ind_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <g1ind_pkg>/g1ind/tests -p no:cacheprovider -q -W error`
- Aucune donnée lue, aucun essai consommé, aucun code audité modifié.
