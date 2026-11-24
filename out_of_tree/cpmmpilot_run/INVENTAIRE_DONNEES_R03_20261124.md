# Inventaire des données détenues par R03 — 24/11/2026, environ 13:00Z

Cet inventaire a été dressé à la demande de R04. C'est un inventaire seulement : il ne contient aucune analyse ni aucune lecture de rendement, et il n'a fait aucun appel réseau.

**Non lus et non inventoriés** (interdits ou scellés) : P0_SCELLE_20261107, le dossier p0/, l'export P0 brut (sauvegarde_20261110) et le holdout 9f19ccac.

**Lecture des colonnes « Hors conteneur »** : « oui » veut dire que les données brutes sont aussi hors du conteneur ; « partiel » qu'une partie seulement l'est ; « non » qu'elles n'existent que dans le conteneur et seraient perdues si le scratchpad disparaissait. Le scratchpad a survécu à tous les redémarrages, dont celui de 12:51Z aujourd'hui.

## Données brutes de marché

| Jeu | Période | Enregistrements | Champs présents | sha / ancre | Hors conteneur |
|---|---|---|---|---|---|
| W1 LaunchLab exploratoire (w1x_out/…/pools, 251 Mo gz) | 09/11 10:05Z → 14/11 10:33Z | 2 273 pools, tous complets ; 322 146 signatures, dont 185 861 en échec (err ≠ null) ; 136 285 corps de transaction | fee, computeUnitsConsumed et costUnits ; err et status ; pre/postBalances et pre/postTokenBalances (réserves recalculables) ; logMessages, innerInstructions. ComputeBudget présent dans 48 448 corps, ce qui permet d'en déduire le prix de priorité. Les signatures en échec n'ont pas de corps (57,7 %). | bundle 3409bf9d ; pools ebe1959d ; SHA256SUMS_PRELIMINAIRE 7e9e7cdb | brut : oui (GCS lots 1 à 5, plan 8969e61a) ; dérivés : 10 697 objets (0,93 Go) seulement ici |
| Série SOL/USD (sol_usd_series.json.gz) | fenêtre W1 | points SOL/USD et critères d'acceptation | label, points, acceptance | 7458f615 | à vérifier (probablement dans le lot W1) |
| CPMM, étage a, 10/11 (cpmm_vectors, 38 Mo) | 10/11 | 4 pools WSOL, 100 transactions, 376 fichiers bruts | transactions complètes (hôte public) | MANIFEST 8895cbee ; liste 4a9ab91b ; graine 38da278b | non |
| CPMM, étage b, 11/11 (cpmm_vectors_b, 133 Mo) | 11/11 | 8 044 fichiers bruts ; arrêt au plafond de 4 000 getTransaction | transactions complètes | MANIFEST 5e41fa1b | non |
| Pilote CPMM U-2, 24/11 (pilot_run/TIME1R_…/u2/raw, 46 Mo) | instantané à T0 (24/11 10:21:26Z) | 152 106 pools CPMM WSOL (6 configs) ; 1 522 lots de coffres ; 44 transactions de création | comptes de pools (0..413), coffres SPL, transactions de création complètes | L 110dabe1 ; U2 3ca0260a | partiel : les 44 GTFA, U2, LIST_L, registres et calls sont dans le dépôt ; les pages gPA et coffres (46 Mo) ne sont qu'ici |
| Pilote CPMM, étape 1A, 24/11 | [T0 − 24 h ; T0) | décomptes de signatures pour 24 pools (aucune signature écrite) | per_pool, R̂ | COUNT_24H c852ec12 | oui (dépôt) |
| Run U-2 stoppé (429), 24/11 09:23Z (pilot_run/TIME1_…/u2/raw, 41 Mo) | instantané | gPA complet + 155 lots de coffres | — | preuves 3af7334 | partiel : preuves dans le dépôt, pages ici seulement (à ne jamais réutiliser, D4) |

## Sorties dérivées (calculs déjà faits, réutilisables sans collecte)

| Jeu | Contenu | sha | Hors conteneur |
|---|---|---|---|
| out3 (paperstream 0.4) | état et sorties du run W1 0.4 | 56ff15ec | partiel (preuves 91ddb11e remises) |
| ps051 / ps0521 | runs W1 0.5.1 et 0.5.2.1 (points de reprise de 400 Mo chacun) | cc2af356 / cb287a2d | preuves remises ; points de reprise ici seulement |
| w1decomp 0.2 | décomposition des pertes W1 | df0d9cbb | archive de preuves 91ddb11e |
| dashx 0.2 | tableau de bord W1 | ef6b5b44 | archive de preuves 91ddb11e |

## Calculs possibles sans nouvelle collecte (indication, pas une analyse)

- **W1 LaunchLab.** Réserves avant et après, frais réseau, frais de priorité et statut d'échec sont présents sur 136 285 corps. En revanche, les 185 861 signatures en échec n'ont pas de corps.
- **CPMM étages a et b.** Les volumes sont faibles : 100 transactions pour a, et b s'est arrêté au plafond. Ces jeux ne suffisent pas pour un verdict économique (C-1 exige au moins 1 000 swaps).
- **Pilote CPMM.** La collecte « pre » et la fenêtre restent à faire : c'est la partie A2r et la suite.
