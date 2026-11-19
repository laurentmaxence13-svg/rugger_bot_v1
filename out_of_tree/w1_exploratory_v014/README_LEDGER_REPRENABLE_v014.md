# w1x 0.1.4 — étape `ledger` reprenable après un redémarrage (P1-bis, R02 bac856e7)

**Préparé, non exécuté sur W1. N'est lancé qu'après l'audit de RUGGER 02 et son PASS explicite.** Ce n'est pas la
chaîne officielle W1, et cela ne donne jamais le verdict W1. Le paquet demande w1aux v7.6.

## Ce qui change par rapport à 0.1.3

- **`explore.py` 0.1.2 reste identique** (a182c148), ainsi que `reading.py`, `stream_export.py` et
  `stream_series.py`. Les identités vérifiées entre deux étapes ne changent donc pas.
- **`w1x/ledger_par.py`** reçoit l'option `step --resumable`. Les modes `--ledger-workers N`, `control`, `compare` et
  `prove` sont inchangés.
- **Ajout** : `w1x/tests/test_ledger_par_resume.py`.

## Commande (voie iii activée par R02 pour cette variante)

    python -B -m w1x.ledger_par step --resumable -- \
        --step ledger --out OUT --s0 467275745 --expect-sha <digest trials>

- **Calcul** : `w1x.explore.main` tourne **inchangé**, à l'intérieur de
  `w1aux.ledger_resume.resumable_ledger(<racine>/ledger_resume, 'trials:<digest trials>')`.
- **Processus et mémoire** : un seul processus, sans fork. Il n'y a pas de garde workers, c'est celle de l'étape
  explore qui s'applique, sans dérogation.
- **Après un redémarrage** : **la même commande reprend**. Les résultats déjà écrits sont relus, après contrôle de
  leur clé et de leur sha256, et seul le reste est calculé.
- **Fin de l'étape** : `ledger/` et le digest de l'étape sont ceux du ledger 0.1.2 séquentiel (testé).
  `LEDGER_PARALLELE.json` donne alors :
  - `mode = resumable_one_process` ;
  - `resume_dir` : `ledger_resume/`, hors de `ledger/`, qui n'entre dans aucun digest d'étape, ni dans
    `SHA256SUMS_PRELIMINAIRE.json`, ni dans le hachage de la lecture (R02 95c5e9e7, testé) ;
  - le nombre de reprises (`resumes`) ;
  - les appels repris, calculés et rejetés ;
  - les fichiers temporaires supprimés ;
  - les événements gardés par la PROBE ;
  - les pics de mémoire après la PROBE et après le calcul ;
  - les sha256 du code.
- **Refus** :
  - `--resumable` avec `--ledger-workers` ;
  - une autre étape que `ledger` ;
  - un enregistrement déjà présent ;
  - un cache lié à un autre digest trials ou à un autre code.

## Tests

    cd <checkout gelé aff97638>
    PYTHONPATH=<checkout>:<w1aux v7.6>:<ce paquet> RUGGER_NO_DOTENV=1 \
      python -B -m pytest <ce paquet>/w1x/tests -p no:cacheprovider -q -W error

Deux tests de plus que 0.1.3 :

- chaîne complète sur le pack gelé :
  - l'étape reprenable est tuée par SIGKILL au 3e appel, sans fichier, sans état ni enregistrement ;
  - la même commande reprend 2 appels et en calcule 2 ;
  - l'état, le digest et `ledger/` sont identiques au ledger 0.1.2 séquentiel, et la lecture qui suit aussi ;
  - `ledger_resume/` n'apparaît dans aucune sortie hachée d'étape ni dans `SHA256SUMS_PRELIMINAIRE.json`, et
    les digests de toutes les étapes sont égaux à ceux de la chaîne séquentielle ;
- refus :
  - les deux modes à la fois ;
  - la garde mémoire de l'étape explore quand la mémoire manque ;
  - un cache d'un autre run de trials.

## Ce qui n'est pas vérifié

- **La durée totale.** Elle est la même qu'en séquentiel : au plus 130 h, et inconnue sous cette borne. Chaque
  redémarrage ne coûte que l'appel en cours, plus la PROBE de la reprise. La PROBE est une passe linéaire sans
  observateur, mais elle n'est pas mesurée sur W1.
- **Le plus gros appel.** S'il dure plus longtemps que l'intervalle entre deux redémarrages, il ne finira jamais.
  Aucun appel n'est découpé.
