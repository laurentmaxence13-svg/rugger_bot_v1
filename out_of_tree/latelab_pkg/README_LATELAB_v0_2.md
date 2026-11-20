# latelab 0.2 — entrées tardives sur W1 (décision R02 04ecafed) — ÉCRIT, NON EXÉCUTÉ

Trois conditions avant toute exécution :
- C-D figé (dossier A v1.6, § 10), puis ancré par R02 ;
- PASS de R02 sur ce code ;
- ancrage de chaque sortie par R02 avant lecture.

Ce que fait l'outil :
- **cellules** : L1 (`age:120`) et L3 (`age:300`), sans aucune sélection ; le palier n'est pas lu ;
- **sortie** : à l'horloge, 60 s ;
- **découverte** : sur la moitié 1, coupe au slot de création 468 484 945 ;
- **crible** : la seule meilleure cellule (`top1` ancré), rejouée sur la moitié 2 ;
- **comptage** : N + 2, puis + 1 ;
- **placebo** : descriptif seulement.

Conception détaillée : la docstring de `latelab/study.py`.

## Commandes (R03)

    PYTHONPATH=<aff97638>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg> RUGGER_NO_DOTENV=1 \
      python -B -m latelab.study discover --pools <export W1> --manifest-sha256 <ancré> --out <OUT1>
    # après l'ancrage de OUT1/LATELAB.json :
      python -B -m latelab.study screen --pools <export W1> --manifest-sha256 <ancré> --cell <top1 ancré> \
        --discovery OUT1/LATELAB.json --discovery-sha256 <ancré> --out <OUT2>

## Preuves

- 9 tests sous CPython 3.12.3 avec `-W error`, dont un rejeu réel de `run_rule` sur un pool du pack gelé et un
  passage complet sur ce pack.
- Le pare-feu est testé : le code ne nomme ni fee_rate, ni tier, ni take_profit, ni stop_loss, ni aucune variable ou
  déclencheur HW1.
- Défauts volontaires : 12 détectés sur 12 (`MUTATIONS_latelab_v0_2.json`).
