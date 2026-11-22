# rtgate 0.1 — porte d'entrée fail-shut devant paperstream 0.4 pour un flux de type temps réel (tâche P3)

RUGGER 01, 22/11/2026.
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

- 21 tests sur les 3 pools publics de fixture : 24 slots à plusieurs événements sur C7F9.
- Les tests montrent qu'avec la porte, une livraison en ordre, inversée ou avec doublons redonne le rejeu gelé, au
  champ près.
- Ils montrent aussi que SANS la porte, une perte, un doublon ou un réordonnancement changent le résultat de
  `StreamTrade` sans aucune erreur.
- Mutants : 16/16 détectés (`MUTATIONS_rtgate_v0_1.json`).

Note des obstacles et plan de tests : `NOTE_P3_OBSTACLES_TEMPS_REEL_v0_1.md`.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<rtgate_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <rtgate_pkg>/rtgate/tests -p no:cacheprovider -q -W error`
