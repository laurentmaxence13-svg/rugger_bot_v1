# g1ind 0.6 — rapport DESCRIPTIF du pilote CPMM autour de la fonction G-1 gelée

RUGGER 01, 23/11/2026.
- Origine : T-R01-4, décision de R04 de 21:30Z. Le périmètre (1) à (7) est celui du message R01 → R04 de 21:27Z.
- Base : la note g1verif, commit 071bb01.
- Appelant : R03, depuis cpmmpilot 0.1.1.
- Soumis à l'audit de R02.
- **v0.6** : décision cut_time de R02 (21:57Z), qui a aussi donné le PASS de la 0.4.
  - cut_time = t0_time + (D × 86 400) // 2, le milieu temporel de la fenêtre, écrit dans chaque fiche de gel et
    ancré par R02 avant les données.
  - Les moitiés (c3) passent désormais par la fonction GELÉE `cpmmprereg.halves`, sur le temps de bloc de la décision
    lu dans la timeline. Elles ne sont plus recalculées dans g1ind.
  - Les lignes de vente nulle y entrent. Sans timelines ou sans cut_time, les moitiés sont « NON MESURÉ », avec le motif.
- **v0.5** = la « 0.3.1 » demandée par R02 (21:52Z et 21:53Z). Elle remplace la 0.4 (e927a14), qui retapait la
  formule.
  - g1ind VÉRIFIE chaque ligne `unpriced_zero_sale` contre `cpmmpilot.step1.zero_sale_net_lamports(échecs de la
    série)`. La fonction est IMPORTÉE, jamais retapée : il n'existe plus de formule de vente nulle dans g1ind.
  - Un écart sur les lamports ou sur le rendement est refusé.
  - **Dépendance** : cpmmpilot ≥ 0.1.4 (R03, 6190277) doit être sur le PYTHONPATH. Les tests utilisent les VRAIES
    lignes de `cpmmpilot.step1.zero_sale`, et ancrent les valeurs données par R02 (−100 420 000 et −100 735 000) pour
    voir toute dérive du runner.
  - g1ind est la source unique de l'écart apparié par pool. cpmmpilot ne le publie plus (0.1.4).
  - Les fichiers v0_1 à v0_4 sont conservés pour l'historique.

## Ce que fait le module

**Une seule décision : celle de la fonction gelée.**
- G-1 est `cpmmcost.model.pilot_verdict` (cpmmcost 0.3, 7deb7b7), appelée une fois, telle quelle.
- g1ind ne rend aucun autre mot de verdict. Le témoin reste un comparateur sans verdict.

| # | Sortie | Règle |
|---|---|---|
| 1 | `g1` | Dict de `pilot_verdict` sur TOUTES les lignes primaires, lignes à vente nulle du runner comprises (K01). Seul `meaning` est remplacé par la phrase de la fiche (K02 option a, décidée par R02). |
| 2 | `unpriced` | K01 (R02 f41c6cb0, 34309238, 21:44Z) : les lignes `unpriced_zero_sale` du runner sont COMPTÉES partout ; leur nombre et leurs motifs (`unpriced_reason`) sont publiés. Erreur, dans tous les jeux et même sans G-0, pour une ligne non valorisée BRUTE (sans `net_return`) ou pour une valeur qui n'est pas la règle de la série. Jamais d'exclusion. |
| 3 | `metrics_b31a3c47` | Voir le détail ci-dessous. |
| 4 | `paired_gap` | Moyenne primaire − témoin, sur les pools présents dans les DEUX bras. Statistique de c2 de `confirmation_verdict`, bootstrap par pool, graine de la fiche, bornes unilatérales à 95 %. DESCRIPTIF : c2 n'est une condition qu'à la confirmation. |
| 5 | `robustness` | Liste fermée des 7 sensibilités b31a3c47. Voir le détail ci-dessous. |
| 6 | `power.flag` | « sous la cible de puissance » si n_entered < `cpmmprereg.n_required()` = 155. |
| 7 | — | Tout le document passe le contrôle du vocabulaire fermé (mêmes mots que `plbench.FORBIDDEN_WORDS`, testé). Le mot trouvé n'est jamais répété dans l'erreur. |

**Valeur d'une ligne non valorisée (K01).**

| Série | Échecs | Lamports | r |
|---|---|---|---|
| primaire, témoin, 10 slots, garde 5 %, rente perdue | (0, 0, 0) | −100 420 000 | −1,0042 |
| `one_failure_per_tx` | (1, 1, 1) | −100 735 000 | −1,00735 |

- La ligne est créée par `cpmmpilot.step1.zero_sale(row, failures)` (R03, 0.1.4, 6190277). g1ind la vérifie contre
  `zero_sale_net_lamports` du même module et ne la crée pas.
- Pour le DD, la perte est placée à la sortie la plus tardive que la règle permet : décision + 1 800 s + latence
  d'horloge (admis par R02).

**Détail de (3), métriques b31a3c47.** Elles portent sur la même population que la moyenne de G-1 : toutes les
lignes, refus de garde et lignes à vente nulle compris.
- Gain si r > 0, perte si r ≤ 0.
- PF net = Σr⁺ / |Σr⁻|, NON MESURÉ sans r négatif.
- Identité de l'espérance contrôlée.
- DD dans l'ordre de SORTIE, en mises et en SOL.
- Frais ventilés à partir de `decomposition_share_of_stake`, sur les positions entrées et valorisées. Le frais moyen
  des refus de garde et le nombre de lignes à vente nulle sont donnés à part.
- Le DD exige les timelines (`lines`). Sans elles, il est NON MESURÉ : il n'y a jamais de repli sur l'ordre d'entrée.

**Détail de (5), sensibilités.** Chaque valeur est une moyenne, ou NON MESURÉ quand l'entrée n'est pas fournie.
- **Fournies par cpmmpilot**, avec les fonctions gelées `cpmmprereg.positions(...)`. g1ind vérifie, ligne par ligne,
  les MÊMES décisions et le paramètre déclaré :
  - `latency_10_slots` : latency_slots = 10 ;
  - `one_failure_per_tx` : échecs EXACTEMENT égaux à `CC.SENSITIVITY_FAILURES` = (1, 1, 1) (K-2) ;
  - `rent_lost_vs_closed_account` : cleanup = MAX_CLEANUP_ATTEMPTS = 3 ;
  - `guard_5_percent` : garde à 50 000 ppm.
- **Calculées par g1ind** :
  - `without_5_best_pools` (b31a3c47), avec aussi la lecture « sans les 5 meilleures positions » de c5 ;
  - `half_1_half_2` : `cpmmprereg.halves` par pool, coupure `cut_time` ancrée (R02 21:57Z).
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

- `primary`, `placebo` et chaque sensibilité sont les lignes de `positions` APRÈS `step1.zero_sale` sur les lignes
  non valorisées (`counted` de step1). C'est aussi vrai du témoin : la 0.1.2 garde des lignes brutes dans
  `G1_INPUTS_*.json`, que g1ind refuse.
- `name` vaut 'RCP1' ou 'B1'.

## État des points R02

- K01, K02, K-2 et la MEV sont réglés (f41c6cb0, 34309238, 21:44Z).
- `cut_time` décidé par R02 (21:57Z) : t0_time + (D × 86 400) // 2, dans chaque fiche de gel, ancré avant les données.
- Condition du PASS de la 0.4 : un test de bout en bout cpmmpilot → g1ind côté R03, à l'intégration.

## Validation

- 14 tests sur fixtures, avec les vraies lignes de vente nulle du runner, dont K01 (lignes du runner comptées, lignes brutes refusées dans chaque jeu et même sans G-0, motifs comptés, planchers, témoin, sensibilités) K-2 (égalité exacte) et la valeur de vente nulle (règle exacte, refus de la rente perdue, de la fermeture WSOL gratuite et des échecs de la mauvaise série), dont un bout à bout avec le code gelé (cpmmx, cpmmprereg, cpmmcost) sur un pool synthétique.
- 49 mutants sur 49 détectés (`MUTATIONS_g1ind_v0_6.json`, runner `mutations_g1ind_runner.py`, garde de référence).
- Commande, cwd wt_w1, sans `-I` :
  `env -i PYTHONPATH=<chemin commun des paquets>:<plbench deps>:<cpmmpilot_pkg de R03 à 6190277>:<g1ind_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <g1ind_pkg>/g1ind/tests -p no:cacheprovider -q -W error`
- Aucune donnée lue, aucun essai consommé, aucun code audité modifié.
