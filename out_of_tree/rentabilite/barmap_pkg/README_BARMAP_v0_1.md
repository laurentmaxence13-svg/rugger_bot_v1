# barmap 0.1 — T-R01-2 : carte du seuil de rentabilité (aucune donnée lue)

- **Ce que fait le paquet.**
  - `barmap/carte.py` calcule l'avantage brut minimal d'un net nul sur une grille DÉCLARÉE : palier, réserve,
    priorité, taux d'échec, loyer, WSOL.
  - La valeur est exacte sur `cpmmx.curve`, par dichotomie. Pour LaunchLab, on prend `fee_for` et les constantes de
    papercost.
  - La latence est NON MESURÉE : ce n'est pas un frais.
- **Sorties.**
  - `CARTE_SEUIL_RENTABILITE_v0_1.md` : table et leviers.
  - `CARTE_SEUIL_v0_1.json` : `document()`, reproductible à l'octet.
- **Preuves.**
  - 6 tests. Ils couvrent :
    - la concordance avec `cpmmcost.bar` (1,12 % à 100 SOL, 2,92 % à 10 SOL) ;
    - la moyenne LaunchLab de W1, ≈ 3,66 % ;
    - le net nul au point mort ;
    - la monotonie de chaque levier ;
    - le coût géométrique des échecs ;
    - la reproductibilité.
  - **15/15 mutants détectés**, avec la garde de base.
- **Commande**, depuis l'arbre gelé, SANS `-I` :
  `env -i PYTHONPATH=<wt_w1>:<cpmmx_pkg>:<barmap_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <barmap_pkg>/barmap/tests -p no:cacheprovider -q -W error`
