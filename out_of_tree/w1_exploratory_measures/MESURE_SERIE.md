# Mémoire de l'étape « série SOL/USD » en flux — mesure sur runs synthétiques agrandis (15/11/2026)

Demandée par RUGGER 02 (option ii) pour son verdict mémoire. **Aucune donnée collectée n'est lue** : chaque ligne
est la transaction Pyth archivée des tests gelés (`tests/fixtures/pyth_push`, 17 Ko de JSON, la taille d'une
transaction réelle du compte de prix), avec sa signature, son slot, sa date de bloc et sa date de publication
propres. **Toutes les lignes donnent un point** : pire cas pour le nombre de points. Segments de 5 000 lignes,
comme dans la collecte W1 (data/w1_sol_usd : 144 segments, 718 183 lignes, d'après son manifeste).

Mesuré, chaque cas dans un processus neuf, session de RUGGER 01 (16 Go, CPython 3.12.3, arbre gelé aff97638,
w1aux v7.4, paquet exploratoire v0.1.2 e620c1fe) :
- « flux » : `w1x.stream_series.series`, c'est-à-dire l'étape réelle (verify gelé, verify sur lignes allégées,
  `pyth_entries` et `sol_usd_series` gelés) ;
- « gel » : `w1_run.pyth_entries` puis `w1_run.sol_usd_series`, à 5 et 20 segments (au-delà il ne tient pas).

| Segments | Lignes | Flux : pic | Flux : durée | Gel : pic | Gel : durée | Fichiers identiques |
|---|---|---|---|---|---|---|
| 5 | 25 000 | 414,0 Mo | 78 s | 1 019,3 Mo | 29 s | oui |
| 20 | 100 000 | 483,3 Mo | 319 s | 3 934,5 Mo | 122 s | oui |
| 40 | 200 000 | 722,1 Mo | 647 s | non mesuré | — | — |
| 80 | 400 000 | 1 274,8 Mo | 1 322 s | non mesuré | — | — |

Pentes :
- flux : 0,95 Ko par ligne de 25 000 à 100 000 (le plancher d'environ 410 Mo, un segment de 5 000 lignes décodé,
  masque encore la croissance) ; 2,45 Ko de 100 000 à 200 000 ; **2,83 Ko par ligne de 200 000 à 400 000** ;
- gel : 39,8 Ko par ligne ;
- durée en flux : 3,3 ms par ligne (trois lectures du run et l'empreinte de chaque ligne).

Projection pour 718 183 lignes, en prolongeant la dernière pente depuis le dernier point mesuré :
1 274,8 Mo + 2,83 Ko × 318 183 = **environ 2,15 Go** (3,2 Go avec une marge de 1,5), et environ 40 minutes.

Limites :
- lignes synthétiques toutes identiques à leur clé près : une transaction réelle peut être plus grosse ou plus
  petite ; le plancher dépend du plus gros segment (14,8 Mo gz dans data/w1_sol_usd, contre 13,6 Mo dans le run
  d'étude où R03 a mesuré 285 Mo) ;
- un point par ligne est un majorant : les mises à jour non plus récentes ne donnent pas de point ;
- l'identité avec le gel n'est montrée ici que jusqu'à 100 000 lignes ; sur données réelles elle l'est par R03 sur
  les quatre runs d'étude (au plus 6 178 lignes).

Reproduire : `measure_series.py` (docstring), `PYTHONPATH` comme pour les tests du paquet, `RUGGER_NO_DOTENV=1`.
Résultats bruts : `RESULTS_SERIES_20261115.jsonl`.
