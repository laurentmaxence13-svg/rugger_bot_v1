# latelab 0.1 — entrées tardives sur W1 (piste 1 et 2 du plan v0.2) — ÉCRIT, NON EXÉCUTÉ

Avant toute exécution, il faut le PASS de R02 sur le code (condition 8 de 53ae2cae) et l'ancrage de la grille. Toute
sortie est ancrée par R02 avant d'être lue. Les règles retenues ne sont que des hypothèses, qui se confirment sur W2
seulement.

La conception complète est dans la docstring de `latelab/study.py` :
- **réemploi sans modification** : `statelab.points`, `statelab.exits.run_rule`, `causal_fee_rate`, `cluster_key`,
  `w1aux.lazy` ;
- **pare-feu HW1** : âges 120 et 300 s seulement ; le seul critère de sélection est le palier causal ;
- **grille** : L1 à L4, sortie TP 7 / SL 5 puis horloge à `EXIT_CLOCK_S` (30 s, à confirmer par R02) ;
- **rendement** : loyer perdu ; « compte fermé » publié à part ;
- **contrôles** : IC par grappes, planchers, classement par borne basse ; crible des 2 premières cellules ancrées.

## Commandes (R03, après le PASS de R02)

    PYTHONPATH=<aff97638>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg> RUGGER_NO_DOTENV=1 \
      python -B -m latelab.study discover --pools <export W1> --manifest-sha256 <ancré> --out <OUT1>
    # après l'ancrage de OUT1/LATELAB.json par R02 :
      python -B -m latelab.study screen --pools <export W1> --manifest-sha256 <ancré> --cells <top2 ancré> \
        --discovery OUT1/LATELAB.json --discovery-sha256 <ancré> --out <OUT2>

## Preuves

- 9 tests sous CPython 3.12.3 avec `-W error`, dont un rejeu réel de `run_rule` sur un pool du pack gelé et un
  passage complet sur ce pack.
- Défauts volontaires : 12 détectés sur 12 (`MUTATIONS_latelab_v0_1.json`).
