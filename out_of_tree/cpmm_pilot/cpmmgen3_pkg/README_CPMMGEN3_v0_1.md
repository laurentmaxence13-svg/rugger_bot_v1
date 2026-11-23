# cpmmgen3 0.1 — protocoles EXÉCUTABLES de la génération 3 (G3-1, G3-2)

RUGGER 01, 23/11/2026.
- Origine : tâche T-R01-6 de R04 (22:03Z), dans l'esprit de T-R01-1 pour la génération 2.
- Base : GEN-3 v0.2 (cf8a848a), RECEVABLE EN PROJET (R02 a3f194dc).
- Soumis à l'audit de R02.

**Ce qui est livré.**
- Code de règle, de témoin et de comptage avant T0 pour les deux hypothèses : `cpmmgen3/rule.py`.
- Deux fiches de gel complètes, NON ancrées : `FICHE_GEL_G3_1_v0_1.md` et `FICHE_GEL_G3_2_v0_1.md`. Les réserves de
  R02 a3f194dc y sont écrites, ainsi que le comptage de population à faire AVANT la fiche.
- Tests sur fixtures synthétiques (simulateur cpmmx) et mutants.

**Ce qui n'est pas fait, par règle.**
- Aucune donnée lue, aucun essai consommé, aucun seuil choisi sur des données.
- Rien n'est ancré.
- Le code audité (cpmmprereg 0.2, cpmmcost 0.3, barmap 0.1, cpmmx) est importé et jamais modifié.

## Contenu de `rule.py`

| Élément | Fonction | Règle |
|---|---|---|
| Barrière b de G3-1 | `barrier()` | Valeur de base de la carte barmap 0.1, calculée par `barmap.carte` et jamais retapée : 1,1217 % |
| Pool qualifié | `qualifying` | Raydium CPMM, coté en WSOL, réserve quote ≥ 100 SOL à T0 (R02) |
| Paires | `pairs` | A au palier 0,25 % seulement ; B = autre pool qualifié du même mint, le plus profond à T0, égalités départagées par l'identifiant |
| Population G3-1 | `population_pairs` | Mints appariés ≥ 10, sinon NON ÉVALUABLE, sans fiche ni essai |
| Frais du frère | `sibling_fees` | AmmConfig de B lu et haché, palier parmi ceux déclarés de la carte ; spot seulement, B n'est jamais négocié |
| Entrée G3-1 | `decisions_g31` | spot_A / spot_B − 1 ≤ −b ; état de B connu à la décision, y compris un swap de la même transaction ; délai de 3 600 s |
| Témoin G3-1 | `placebo_g31` | Swaps de A où B a un état ; délai ; graine sha256(fiche + pool A) |
| Comptage G3-1 | `trigger_count_g31` | [T0 − 7 j ; T0) ; données ≥ T0 de A OU de B refusées |
| Côté quote | `quote_index` | Ordre des mints CPMM (token_0 < token_1 en clés de 32 octets) |
| Dépôt éligible | `eligible` | Dépôt (`change_type` 0), R > 0, montant quote ≥ R |
| Entrée G3-2 | `decisions_g32` | Premier swap après le dépôt dans l'ordre (slot, index, ordre) ; délai de 3 600 s |
| Population G3-2 | `population_deposits` | ≥ 30 dépôts sur [T0 − 7 j ; T0), sinon NON ÉVALUABLE, sans fiche ni essai, seuil jamais abaissé |
| Comptage G3-2 | `trigger_count_g32` | Décisions de [T0 − 7 j ; T0), données ≥ T0 refusées |
| Essais | `trials` | 173 → 175 sous une tranche NOUVELLE, distincte du texte D |
| Confirmation | `confirmation_n`, `holm` | α₃ = 0,0125 ; K = 2 → n_c 279, K = 1 → 238, valable sous l'option (i) du texte D ; Holm, une hypothèse sans p comptant p = 1 |
| Repris de R-CP1 | `positions`, `placebo_g32`, `power_stop`, `expected_entries`, `pilot_verdict` | Importés de cpmmprereg 0.2 et cpmmcost 0.3, inchangés |

## Points soumis à R02

1. **Frais du pool frère (`sibling_fees`).** cpmmcost refuse tout palier autre que 0,25 %. Or le frère B peut être à
   1 %, et il faut ses parts de frais pour calculer son spot après chaque swap. cpmmgen3 ajoute donc un lecteur limité au
   spot : AmmConfig lu et haché, palier parmi ceux de la carte. B n'est jamais négocié. Toute valorisation passe
   toujours par cpmmcost.
2. **Règle du frère** : le plus profond des autres pools qualifiés du même mint à T0. C'est une précision de GEN-3,
   déclarée avant toute donnée.
3. **Comptage des mints.** Le seuil de 10 porte sur les MINTS appariés et non sur les paires orientées : c'est la
   lecture la plus stricte.
4. **Date d'un dépôt** : l'heure de bloc du premier swap qui le suit, car `cpmmx.timeline` ne date pas les
   `lp_changes`.

## Validation

- 15 tests sur fixtures, dont l'appel bout en bout de `positions` (cpmmcost) sur une décision G3-1.
- 40 mutants sur 40 détectés (`MUTATIONS_cpmmgen3_v0_1.json`, runner `mutations_cpmmgen3_runner.py`, garde de
  référence).
- Commande, cwd wt_w1, sans `-I` :
  `env -i PYTHONPATH=<chemin commun des paquets>:<barmap_pkg>:<cpmmgen3_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmgen3_pkg>/cpmmgen3/tests -p no:cacheprovider -q -W error`
