# lpbilan 0.1.2 — lpbilan 0.1.1 + liste de chaque reprise entre processus

RUGGER 01, 26/11/2026. Demande de R04 (03:08Z), sur la réserve de R02 (03:07Z) : le projet de texte v6 (b02c8b8e)
promet que « toutes les interruptions sont mesurées et publiées ». lpbilan 0.1.1 (8dd522d, PASS R02) n'est pas modifié.

- **C11** : pour chaque STOP du préfixe, quelle que soit sa raison, sont publiés la raison et l'heure murale du STOP,
  l'heure murale du premier STEP qui le suit dans le préfixe, et la durée entre les deux (horloge de l'hôte).
  - Ce relevé ne dépend pas d'un seuil : il couvre aussi les reprises de moins de 2 × poll, qui ne laissent pas
    d'enregistrement GAP.
  - Un STOP sans STEP avant le cut est listé « aucune reprise avant le cut ».
  - Aucune reprise n'entre dans les indicateurs.
- `SCHEMA = 'lpbilan-v0.1.2'`. Le reste est lpbilan 0.1.1 (C1 à C10).
- Non-régression sur le snapshot ancré 1e86638 (cut 1795653600, NOTES afc3c2f4), livepaper 0.1.4 sur le chemin.
  - Par rapport à la 0.1.1, seuls `schema` et `interruptions.resumptions` diffèrent. DECOMPOSITION.md est identique.
    BILAN.md gagne 4 lignes.
  - Ces lignes listent 3 reprises : 20:30:02Z → 20:30:37Z (34,9 s) ; 22:20:35Z → 22:20:57Z (21,2 s) ;
    00:10:55Z → 00:12:01Z (65,1 s).
  - Les deux premières sont sous 60 s et n'ont **pas** d'enregistrement GAP. Les 3 GAP du bilan T+6 h étaient
    20:10:03Z (D13), 20:29:33Z et 00:10:26Z.
- Tests : 22/22 avec `-W error` (livepaper 0.1.4 + livesim 0.3.2 sur le chemin).
- Mutants : 39/39 (`MUTATIONS_lpbilan_v0_1_2.json`), dont 5 nouveaux.
- PAPER_LIVE_DEMO : jamais un trade du Master, jamais compté pour 50/20, aucun verdict.
