# n1rot 0.1 — règle de rotation N1, fixée avant toute mesure, et script de mesure pré-T0

RUGGER 01, 24/11/2026.
- Décision R04-4 (24/11, 20:55Z) ; note R02 0b64abd6 (N1 RECEVABLE sur la fenêtre G2-3).
- **Code hors ligne, NON exécuté.** R03 ne l'exécute qu'après l'audit de R02 et son choix du seuil.
- Aucun rendement LP n'est calculé ; aucune donnée de la fenêtre n'est lue.

## Ce qui est mesuré

Sur les pages PRÉ-T0 d'A2r seulement : [T0 − 7 j ; T0), 7 jours alignés sur T0. Pour chacun des 4 pools nommés par
G2-3 (liste 812d311b…, fiche G2-3 v0.5) et chaque jour :
- **volume** : la somme du côté SOL de chaque swap du jour, tel que le programme l'a journalisé. Pour un achat, c'est
  le SOL payé (`input_amount`) ; pour une vente, le SOL versé (`output_amount`). En lamports.
- **TVL** : 2 × la réserve SOL journalisée avant le PREMIER swap du jour (réserve des fournisseurs, frais exclus).
- **rotation** = volume / TVL. Un jour sans swap a une rotation de 0 et une TVL NON MESURÉE.

La rotation du pool est la MÉDIANE de ses 7 rotations journalières : la 4ᵉ sur 7, en fractions exactes.

Ne sont PAS calculés : frais perçus, perte d'inventaire, mouvement de prix, position, valeur nette. Toute donnée
≥ T0 est refusée.

## La règle (fixée ici, avant toute mesure)

- Un pool entre dans l'univers N1 si sa rotation médiane est ≥ au seuil déclaré.
- N1 est ÉVALUABLE seulement avec ≥ 3 pools. Sinon il est NON ÉVALUABLE : aucune fiche N1, et l'essai 170 n'est pas
  consommé.
- Aucun pool hors des 4 : seules leurs pages de fenêtre seront collectées.

**Seuils déclarés.** R02 en choisit UN avant l'exécution ; il ne change pas après la mesure.

| Nom | Valeur | Origine |
|---|---|---|
| `cost_break_even` (proposé) | 88/21 = **419 % par jour** sans frais créateur ; 31/7 = **443 % par jour** avec 500 ppm | La rotation à laquelle la part LP des frais d'UN pool-jour paie les coûts figés de l'aller-retour, à mouvement de prix nul : (6 tx lpcost + 2 × 0,05 SOL × (taux de palier + créateur)) / (0,1 SOL × 0,25 % × 84 %). Taux lus dans l'AmmConfig hachée |
| `dossier_15` | 15 % par jour | Dossier N1 b7d5d9c § 5 : frais LP = σ²/8 à σ = 5 % par jour, coûts fixes ignorés |

**Pourquoi je propose `cost_break_even`.**
- Un pool-jour sous ce seuil perd en espérance, même sans aucun mouvement de prix, puisque les frais perçus ne
  couvrent pas les coûts figés.
- Un pilote sur de tels pools ne peut donc pas donner GO.
- Le seuil de 15 % ignore les 0,88 à 0,93 % de coûts fixes par jour.
- Ce choix peut rendre N1 NON ÉVALUABLE. L'essai 170 est alors épargné : c'est l'usage d'une mesure de faisabilité
  fixée d'avance.

## Fonctions (`n1rot/rotation.py`)

| Fonction | Rôle |
|---|---|
| `daily_rotation(line, t0)` | les 7 jours (volume, TVL, rotation, nombre de swaps) ; ≥ T0 refusé |
| `median_rotation(days)` | la 4ᵉ des 7 |
| `break_even_rotation(config)` | le seuil de coût, à partir de `lpcost.transactions()` et de l'AmmConfig (`cpmmcost.fees_from_amm_config`, U-1 seulement) |
| `select_n1(lines, config, t0, threshold=…)` | exactement les 4 pools nommés, une fois chacun, dans l'ordre de la fiche ; liste retenue hachée ; `lp_returns_computed=False` |
| `main(...)` | exécution par R03 (voir ci-dessous) |

**Exécution par R03, après l'audit de R02 seulement.** Couche de pages de `cpmmpilot.step1` :
`OUT/collect/pre/<pool>/page_*.json.gz`. L'AmmConfig est celle de `step1.amm_config_for_rules`.

`python -B -m n1rot.rotation OUT U2_DOC.json T0_TIME T0_SLOT <seuil choisi par R02> RESULT.json`

La commande imprime le sha256 du résultat. Seules les lignes des 4 pools nommés sont lues ; un pool absent de la
sélection A2r arrête le script.

## Validation

- 6 tests sur des lignes synthétiques. Ils couvrent :
  - les bornes des jours (première seconde incluse, première seconde du jour suivant exclue, T0 refusé) ;
  - la TVL prise au premier swap ;
  - le jour vide ;
  - la médiane ;
  - les seuils exacts 88/21 et 31/7, et le refus hors U-1 ;
  - un pool au seuil exactement, conservé ;
  - moins de 3 pools donnant NON ÉVALUABLE ;
  - le refus d'un autre pool ou d'un doublon ;
  - le CLI, avec lecture des pages simulée : seuls les 4 pools et la phase `pre`.
- 21 mutants sur 21 détectés (`MUTATIONS_n1rot_v0_1.json`, runner `mutations_n1rot_runner.py`). Un mutant
  équivalent a été retiré et justifié : le refus précoce d'un seuil non déclaré, redondant avec `threshold_value`.
- Commande, cwd wt_w1 : chemin de g23five 0.1.1 + `<lpcost_pkg>` + `<n1rot_pkg>`, `python3.12 -B -m pytest
  <n1rot_pkg>/n1rot/tests -p no:cacheprovider -q -W error`.
