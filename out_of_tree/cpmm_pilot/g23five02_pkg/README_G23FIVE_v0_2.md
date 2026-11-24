# g23five 0.2 — blocs de `block_days` jours consécutifs (pour N1 seulement)

RUGGER 01, 24/11/2026.
- Décision R04-6 (21:27Z) ; précision R02 (21:18Z) : la longueur de bloc de 2 jours vaut pour N1 SEULEMENT.
- **La fiche G2-3 reste sur g23five 0.1.1**, inchangé, dans `cpmm_pilot/g23five_pkg/`. Ce paquet-ci (`g23five02_pkg`)
  en est une copie séparée, qui ne modifie pas 0.1.1.

**Seul changement.** Un paramètre `block_days`, à 1 par défaut, dans `blocks(rows, t0, d_days, block_days)` et dans
`report(..., block_days)`.
- Un bloc = `block_days` jours CONSÉCUTIFS d'un même pool : clé = jour // block_days, jours alignés sur T0.
- D doit être un multiple de block_days ; sinon `block_days_must_divide_d_days`.
- Le même découpage sert aux bornes principales, à la garde « sans le pool le plus fourni » et à l'écart au témoin.
- Les planchers comptent toujours des POOL-JOURS, pas des blocs.
- `block_days` est publié dans le rapport.

**Validation.**
- 15 tests : les 13 de 0.1.1, inchangés, plus 2 nouveaux.
  - « 1 = identique à 0.1.1 » : le module 0.1.1 ancré est chargé depuis son répertoire, son sha 52b9d2b0… est vérifié,
    et les rapports doivent être égaux à `schema` et `block_days` près, avec et sans témoin.
  - Les blocs de 2 jours sont égaux à un calcul direct ; même découpage pour la garde et pour l'écart ; planchers
    inchangés ; refus de 0, 5, 2.0 et −2 avec D = 12.
- 48 mutants sur 48 détectés : les 40 de 0.1.1 et 8 nouveaux (`MUTATIONS_g23five_v0_2.json`). Le runner copie 0.1.1 à
  côté des mutants pour le test d'identité.
