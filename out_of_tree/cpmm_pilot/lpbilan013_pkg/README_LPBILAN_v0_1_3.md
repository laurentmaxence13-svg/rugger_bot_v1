# lpbilan 0.1.3 — lpbilan 0.1.2 + trou d'observation réel de chaque reprise

RUGGER 01, 26/11/2026. Réserve de R02 (03:20Z) sur lpbilan 0.1.2, acceptée par R04 (04:06Z). Ajout de publication
seulement. lpbilan 0.1.2 (5cdc592, PASS R02) n'est pas modifié.

- **C11 étendu** : chaque reprise publie deux durées.
  1. Du STOP au premier STEP suivant (`seconds`), comme en 0.1.2.
  2. Du dernier STEP avant le STOP au premier STEP suivant (`last_step_wall`, `observation_gap_s`) : le vrai trou
     d'observation, plus long d'au plus un sondage.
- Une borne manquante s'affiche « — » : STOP sans heure murale, STOP avant tout STEP, ou STOP sans STEP avant le cut.
  Le rendu ne fait plus `int(None)`.
- `SCHEMA = 'lpbilan-v0.1.3'`. Le reste est lpbilan 0.1.2, et aucune reprise n'entre dans les indicateurs.
- Non-régression sur le snapshot ancré 1e86638 (cut 1795653600, NOTES afc3c2f4, livepaper 0.1.4 sur le chemin).
  - Par rapport à la 0.1.2, seuls `schema` et les deux champs nouveaux de chaque reprise diffèrent. Les champs de la
    0.1.2 sont identiques. DECOMPOSITION.md est identique. BILAN.md change ses 3 lignes de reprise.

  | STOP | Dernier pas avant | Pas suivant | STOP → pas suivant | Trou d'observation |
  |---|---|---|---|---|
  | 20:30:02Z | 20:29:33Z | 20:30:37Z | 34,9 s | 63,9 s (= le GAP de 20:29:33Z) |
  | 22:20:35Z | 22:20:06Z | 22:20:57Z | 21,2 s | 50,4 s (**aucun GAP** : sous 2 × poll) |
  | 00:10:55Z | 00:10:26Z | 00:12:01Z | 65,1 s | 94,2 s (= le GAP de 00:10:26Z) |
- Tests : 23/23 avec `-W error` (livepaper 0.1.4 + livesim 0.3.2 sur le chemin).
- Mutants : 43/43 (`MUTATIONS_lpbilan_v0_1_3.json`), dont 4 nouveaux.
- PAPER_LIVE_DEMO : jamais un trade du Master, jamais compté pour 50/20, aucun verdict.
