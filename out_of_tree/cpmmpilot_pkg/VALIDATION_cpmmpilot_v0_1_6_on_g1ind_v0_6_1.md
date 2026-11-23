# Validation de cpmmpilot 0.1.6 (f934bd2, MANIFEST 526f19ad) contre g1ind 0.6.1 (R01)

Le code de cpmmpilot 0.1.6 et son MANIFEST sont INCHANGÉS. Ce fichier remplace le pré-contrôle sur une copie locale par un rejeu contre la g1ind 0.6.1 publiée.

## Paquet g1ind vérifié

- Commit f31269e.
- `MANIFEST_g1ind_v0_6_1.txt` : 12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a. `sha256sum -c` : 0 écart.
- `report.py` : ecffb66a….
- Diff avec la 0.6 (3d9166d) : docstring, SCHEMA, plus `RUN_FAILURES['rent_lost_vs_closed_account'] = CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS)`. Rien d'autre.

## Résultats (hors ligne, `unshare -rn`, arbre gelé aff97638)

| Contrôle | Résultat |
|---|---|
| Tests | 28 sur 28 passent |
| Mutants | 35 sur 35 tués (`MUTATIONS_cpmmpilot_v0_1_6_on_g1ind061.json`, 9e70622b…) |
| Répétition SYNTHÉTIQUE | journal 7bfbc8248530ed4e9d436c6adc1733c92ad29bdea01cf3bde17e4476d3106a42, 26,6 s |

La répétition diffère de celle du pré-contrôle (e8c73c03) par le champ `schema` de g1ind, qui vaut désormais `g1ind-v0.6.1`. Ses décisions sont sans portée, car les données sont fabriquées.

L'import de g1ind se fait dans `step1.g1`, pas en tête de module, depuis la 0.1.6 (f934bd2).
