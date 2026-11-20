# latesel 0.1 — un filtre causal sur une entrée tardive latelab (conditions R02 du 20/11, note 9cd033ad)

**Hypothèses figées AVANT toute sortie latelab.** Sortie à l'horloge de 60 s, loyer perdu.

| Code | Entrée | On garde si |
|---|---|---|
| T1 | `age:120` | unique_buyers ≥ tercile haut de la moitié 1 |
| T3p | `age:300` | top5_holder_share ≤ médiane de la moitié 1 |

- T2 est retiré.
- **Filtres** :
  - ils se calculent dans latesel, à partir des seuls événements jusqu'à la décision (côté, payeur, montants) ;
  - créateur exclu ;
  - jamais `native_features` ni un état de courbe : le test du pare-feu interdit state_after, state_before, real_base,
    real_quote et native_features.
- **Réemploi sans modification** : latelab 0.4 (moitiés, résumé, IC par grappes, planchers, règle CLOCK60),
  `statelab.exits.run_rule`, `statelab.points.decision_points`, `w1aux.lazy`.

**Exécution, réservée à R03 et chaque fois après l'ancrage de R02.**

1. `quantiles`, sur la moitié 1. Pas de rejeu, aucun rendement : 2 seuils et des comptes. 0 essai. R02 ancre la
   sortie.
2. `screen`, sur la moitié 2, avec `--quantiles` ancré et son sha. Elle compte 2 essais (T1, T3p). Une hypothèse
   passe si le net > 0, avec n ≥ 30 et au moins 20 grappes. Ce n'est jamais une preuve.

```
PYTHONPATH=<aff97638>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg 0.4>:<latesel_pkg> RUGGER_NO_DOTENV=1 \
  python -B -m latesel.select quantiles --pools <export W1> --manifest-sha256 <ancré> --out <DOSSIER NEUF>
```

**Choix de l'emplacement L (Dossier B v1.3 de R02).** Au plus un candidat parmi {top1 latelab, T1, T3p} qui passent
leur crible : celui dont la borne basse de l'IC 95 % sur la moitié 2 est la plus haute.

**Preuves.** 8 tests réussis. Défauts volontaires : 13 sur 13 détectés (`MUTATIONS_latesel_v0_1.json`).

## Tests 0.2 (audit R02 de la 0.1) — `select.py` inchangé (sha 320bef32)

- **Nouveau test.** Si toutes les moitiés sont en 2, les quantiles ont n_points = 0. C'est le test miroir de celui du crible.
- **Défauts volontaires** : 15 sur 15 détectés, dont les 2 défauts de R02 (« tercile strict » et « quantiles sur
  les deux moitiés ») ; voir `MUTATIONS_latesel_v0_2.json`.
- **Tests** : 9 réussis.
- **Exécution** : celle de la 0.1 reste valable, avec le même code.
