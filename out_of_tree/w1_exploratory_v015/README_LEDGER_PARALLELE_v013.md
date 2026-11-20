# w1x 0.1.3 — étape `ledger` avec le ledger parallèle (option P1, R02 0c51450f)

**Préparé, non exécuté sur W1. N'est lancé qu'après l'audit de RUGGER 02 et son PASS explicite.** Ce n'est pas la
chaîne officielle W1, et cela ne donne jamais le verdict W1.

## Ce qui change par rapport à 0.1.2

- **Aucun fichier de 0.1.2 n'est modifié** : `explore.py`, `reading.py`, `stream_export.py`, `stream_series.py`,
  `prove.py`, les tests et `README_EXPLORATOIRE.md` sont identiques octet pour octet. Le `MANIFEST_EXPLORATOIRE_v013.txt`
  reprend les sha256 de `MANIFEST_EXPLORATOIRE_v012.txt`.
  - La raison : le sha256 d'`explore.py` fait partie des identités vérifiées entre deux étapes. Le modifier ferait
    refuser l'état déjà écrit par les étapes 0.1.2 (`code_identities_changed_between_steps`).
- **Ajouts** : `w1x/ledger_par.py` et `w1x/tests/test_ledger_par.py`. Ce paquet demande w1aux v7.5.

## Voie retenue par RUGGER 02 : le contrôle hors de la chaîne (voie i, a751205f)

    python -B -m w1x.ledger_par control --root <OUT>/PRELIMINAIRE_PAS_LE_VERDICT_OFFICIEL_W1 --ledger-workers N \
        --out <dossier neuf HORS de la racine>
    python -B -m w1x.ledger_par compare --root <OUT>/PRELIMINAIRE_PAS_LE_VERDICT_OFFICIEL_W1 --control <ce dossier>

L'étape ledger 0.1.2 reste l'étape officielle de la chaîne exploratoire. Le contrôle :

- vérifie d'abord, sans rien écrire dans la racine :
  - que les identités de l'état sont celles du code qui tourne ;
  - que les sorties des étapes selfcheck à trials ont toujours leur sha256 ;
  - que le digest de chaque étape est inchangé ;
- refuse un dossier de sortie placé dans la racine, puis applique la garde mémoire des processus de calcul, sans
  dérogation ;
- calcule le ledger parallèle avec les mêmes entrées que l'étape explore (pools, run/bundles, série, sans rapport) ;
- écrit `<out>/ledger/` et `CONTROLE_LEDGER_PARALLELE.json`. Ce fichier contient le digest, les sha256 du code, la
  garde mémoire, les pics de mémoire du parent, de la PROBE et de chaque processus de calcul, le nombre d'événements
  des timelines gardées et la durée. Aucun résultat n'y figure.

La racine est identique avant et après (testé). Le contrôle peut donc tourner en lecture seule sur la racine en cours,
ou sur une copie de l'OUT vérifiée par sha256 contre les listes ancrées.

`compare` ne s'exécute qu'une fois l'étape ledger 0.1.2 terminée. Il revérifie les sorties de l'étape et les sha du
contrôle, puis compare `ledger/` octet pour octet. Il imprime `identical` et les deux digests ; son code de retour est
6 en cas d'écart.

## `step` : l'étape ledger d'explore, en parallèle (voie iii, EN RÉSERVE)

Cette voie n'est utilisable que sur une décision séparée de RUGGER 02, si l'étape 0.1.2 doit être abandonnée.

    python -B -m w1x.ledger_par step --ledger-workers 4 -- \
        --step ledger --out OUT --s0 467275745 --expect-sha <digest trials>

- Le lanceur appelle `w1x.explore.main`, **inchangé**, à l'intérieur de `w1aux.ledger_parallel.parallel_ledger(N)`.
  - L'étape, ses contrôles et sa garde mémoire (sans dérogation) sont ceux de 0.1.2.
  - Le dossier haché `ledger/` aussi : le digest de l'étape ledger est le même qu'en séquentiel (testé).
  - L'étape `reading` qui suit donne les mêmes fichiers (testé).
- Avant l'étape, le lanceur applique une **seconde garde mémoire, sans dérogation**. Il faut :
  MemAvailable ≥ 1,5 × (projection du ledger séquentiel + N × projection du plus gros pool).
  - Le coefficient est celui que dayj a mesuré pour le ledger : 27 Ko par signature exportée.
  - Si la garde refuse : arrêt, sans dérogation.
- Le lanceur refuse :
  - N < 2 (pour un seul processus, utiliser explore) ;
  - toute autre étape que `ledger` ;
  - un enregistrement déjà présent.
- Après l'étape, il écrit `LEDGER_PARALLELE.json` à la racine du dossier marqué, hors de `ledger/` (donc hors du
  digest), avec :
  - le nombre de processus et le nombre d'appels dérivés ;
  - les sha256 du code ;
  - la garde mémoire ;
  - les pics de mémoire (parent et plus gros processus de calcul) et la durée.

  Aucun chiffre de résultat n'y figure.
- La sortie standard reprend la ligne d'explore, puis une ligne technique.

## `prove` : identité et mémoire sur des données déjà ouvertes (le pilote)

    python -B -m w1x.ledger_par prove --pools <pools> --bundles <bundles> [--series <série>] --workers 4 --out <dossier neuf>

- Deux processus neufs exécutent l'un le ledger v7.4 séquentiel (chargé d'un bloc), l'autre le ledger parallèle.
- Les fichiers sont comparés octet pour octet.
- La commande imprime seulement :
  - `identical`, les sha256 des deux ledgers et l'égalité des codes de retour ;
  - le nombre de processus et d'appels, et les durées ;
  - les pics de mémoire : celui du parent, celui du parent juste après la PROBE, celui de chaque processus de calcul,
    et celui du ledger séquentiel ;
  - le nombre d'événements des timelines gardées par la PROBE.
  - Le pic du plus gros processus est le `ru_maxrss` des enfants. Le RSS compte les pages partagées : c'est un majorant.
- Elle n'imprime aucun P&L, aucun rendement, aucun nombre de cycles, aucun verdict.

## Tests

    cd <checkout gelé aff97638>
    PYTHONPATH=<checkout>:<w1aux v7.5>:<ce paquet> RUGGER_NO_DOTENV=1 \
      python -B -m pytest <ce paquet>/w1x/tests -p no:cacheprovider -q -W error

8 nouveaux tests :

- chaîne complète sur le pack gelé : étape ledger en séquentiel et en parallèle (2 processus), avec le même état, le
  même digest, les mêmes fichiers et la même lecture ;
- contrôle hors de la chaîne, puis comparaison octet pour octet avec l'étape 0.1.2 (`identical`) :
  - racine inchangée ;
  - refus d'un dossier placé dans la racine, d'une racine qui n'en est pas une, d'identités différentes et d'un
    contrôle modifié ;
- contrôle refusé si une sortie antérieure a changé ;
- les refus du lanceur et sa garde mémoire ;
- le calcul de cette garde ;
- `prove` sur le pack gelé, sans aucun résultat sur la sortie standard ;
- `explore.py` identique à 0.1.2, et des identités qui ne couvrent pas le lanceur ;
- `RUGGER_NO_DOTENV=1` exigé.

## Ce qui n'est pas vérifié

- Aucune preuve sur des données réelles : `prove` est à lancer par RUGGER 03 sur le pilote, après l'accord de R02.
- **Mémoire à l'échelle de W1 : non mesurée.** La PROBE garde les timelines des pools avec entrée. Chaque processus
  de calcul tient une archive et les résultats mémoïsés de son observateur jusqu'au dernier index.
- Gain de temps : environ N fois moins, si les processus disposent d'un cœur entier chacun. Avec des vCPU en
  hyperthreading, le gain est moindre. Il n'a pas été mesuré sur W1.
- Les pools très gros limitent le gain : chaque couple (pool, bundle L1) est traité par un seul processus. Les
  4 bundles d'un même pool peuvent tourner en même temps, mais pas les morceaux d'un même couple.
