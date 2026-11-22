# rtgate 0.2 — porte d'entrée fail-shut devant paperstream 0.4 pour un flux de type temps réel (tâche P3)

RUGGER 01, 22/11/2026. **0.2 = 0.1 (PASS R02) + `retract` (rollback) + compteur `chain_comparisons` + les 5 tests restants de la note (T-11 à T-15, `tests/test_p3_remaining.py`).**
- HISTORICAL_REPLAY seulement : une source autre est refusée.
- Hors ligne : aucun réseau, aucune clé, aucun ordre.
- `StreamTrade` est importé tel quel (engine.py e86f66b0, vérifié à chaque porte).

## Ce que fait la porte

- **Doublons** : écartés et comptés.
- **Slot en cours** : mis en tampon jusqu'au slot suivant, puis ordonné par la chaîne des réserves, selon la règle de
  `build_timeline`, en plus strict.
- **Refus (le pool devient INCOMPLET)** :
  - début en milieu de courbe ;
  - retard ;
  - rupture ou ambiguïté de la chaîne ;
  - autre pool ;
  - violation ;
  - reconnexion déclarée et non guérie par une chaîne exacte.

Un pool INCOMPLET ne reçoit plus rien. Une position ouverte y est signalée et aucun résultat n'est publié. Rien n'est
jamais créditable ni compté pour les seuils 50/20.

## Preuves

- 26 tests (21 de la 0.1, 5 nouveaux) sur les 3 pools publics de fixture : 24 slots à plusieurs événements sur C7F9.
- Les tests montrent qu'avec la porte, une livraison en ordre, inversée ou avec doublons redonne le rejeu gelé, au
  champ près.
- Ils montrent aussi que SANS la porte, une perte, un doublon ou un réordonnancement changent le résultat de
  `StreamTrade` sans aucune erreur.
- Mutants : 23/23 détectés (`MUTATIONS_rtgate_v0_2.json` ; 7 nouveaux pour `retract` et le compteur).
- T-14 utilise une copie épinglée de `bot/dashboard/research_view.py` (commit e3f78d0, sha aade2d5a, blob 5ce35b04) dans `tests/fixtures/`, vérifiée avant import.

Note des obstacles et plan de tests : `NOTE_P3_OBSTACLES_TEMPS_REEL_v0_2.md`.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<rtgate_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <rtgate_pkg>/rtgate/tests -p no:cacheprovider -q -W error`
