# W1 — chaîne EXPLORATOIRE v0.1.2 (préparée, NON exécutée sur W1)

**Ce paquet n'est pas la chaîne officielle W1 et ne donne jamais le verdict W1.** Il ne remplace pas le gel
(protocole R10). Il ne s'exécute sur W1 qu'après l'accord explicite du propriétaire (lecture de W1 avant son
verdict officiel) et le PASS de RUGGER 02. Hors ligne, aucun réseau, aucun ordre, aucune clé.

Cadre : directive du propriétaire du 15/11/2026 10:30Z (« priorité aux résultats économiques », b9e596e3) ;
méthode de RUGGER 02 2ee87535, additif 3.

## 1. Pourquoi

La chaîne officielle (w1aux.dayj) s'arrête à l'export : `export_pools` et `pyth_entries` gelés chargent toutes
les transactions (environ 78 Gio et 26 Gio, pour 13,35 Gio disponibles). `evaluate` dépasse aussi la mémoire
(17,8 Go projetés). En revanche `trials` (8,3 Go projetés, 12,5 Go avec la marge de 1,5) et `ledger` (8,6 Go,
13,0 Go avec marge) tiennent, de peu, et le ledger sait travailler sans le rapport d'`evaluate`.

## 2. Ce qui tourne

| Étape | Ce qui s'exécute | Différence avec la chaîne officielle |
|---|---|---|
| `selfcheck` | l'étape selfcheck de dayj v7.4, inchangée | aucune |
| `export` | `w1_collection.export` GELÉ, dans `stream_export.streaming_export()` (sha 38cc8235, inchangé depuis l'option 1316f60d) ; puis le comptage des exclusions de dayj et son arrêt à 5 % | l'export lit la fenêtre en trois passes au lieu de tout charger ; fichiers identiques octet pour octet (tests) |
| `series` | `pyth_entries` et `sol_usd_series` GELÉS, dans `stream_series.streaming_series()` | les lignes lues sont allégées et portent les valeurs calculées par les décodeurs gelés ; fichiers identiques octet pour octet (tests) |
| `trials` | l'étape trials de dayj v7.4, inchangée : `run_trials` gelé par lazy + parallel, garde mémoire, reprise | aucune ; **aucune dérogation mémoire possible** (l'option n'existe pas ici) |
| `ledger` | `w1aux.ledger` SANS `--report` | pas de décision W1 citée (il n'y en a pas) |
| `reading` | `w1x.reading` : la liste fermée de chiffres fixée par R02 | nouveau ; n'existe pas dans la chaîne officielle |
| `gate`, `evaluate`, `dossier` | **refusées** ; `w1_run.evaluate` et `w1_eval.evaluate_w1` lèvent une erreur si quoi que ce soit les appelle pendant une étape | — |

La porte de couverture n'est pas recalculée : `export` exige le `GATE.json` de l'étape officielle et son sha256
ancré par R02, vérifie qu'il s'agit d'un PASS et qu'il porte sur cette fenêtre (sha du manifeste).

## 3. Marquage et empreintes

Les pools, la série et les bundles gardent **exactement** les octets que la chaîne officielle écrirait : c'est
ce qui permettra à R02 de comparer leurs sha256 à ceux de la chaîne officielle si elle tourne un jour (égalité =
même calcul ; écart = STOP). Le marquage « PRÉLIMINAIRE — PAS LE VERDICT OFFICIEL W1 » est donc porté par :
- le dossier : tout est écrit sous `<out>/PRELIMINAIRE_PAS_LE_VERDICT_OFFICIEL_W1/` ;
- `EXPLORATORY_STATE.json` (jamais `DAYJ_STATE.json` ; un dossier de dayj est refusé) ;
- `SHA256SUMS_PRELIMINAIRE.json` : toutes les sorties et leur sha256, réécrit après chaque étape ;
- les deux fichiers de lecture.

La sortie standard ne porte que l'étape, son digest, sa durée et des détails techniques (mémoire, processus,
exclusions, points de la série, verdict d'intégrité du ledger). **Jamais un rendement ni un P&L** : ils ne sont
que dans `lecture/LECTURE_PRELIMINAIRE.json` et `.md`.

## 4. Ce qui est lu (et rien d'autre)

Voir le docstring de `w1x/reading.py`, qui reprend les définitions de R02 (Q1 à Q7 pour le bras MASTER ; cycles,
net moyen et décomposition totale pour RÉFÉRENCE et PLACEBO ; rien sur les bras V2, les sensibilités ni les
hypothèses ; aucune ventilation par créateur, signal ou état ; SOL seulement).

**Point soumis à R02 : la population.** `reading` porte sur les pools créés dans la plage d'évaluation
[467 678 545 ; 469 291 345), c'est-à-dire la population de la décision gelée (`w1_eval.w1_split` : la plage
d'échauffement ne sert qu'à l'historique des créateurs). Les pools hors plage sont seulement comptés. Le ledger,
lui, couvre tous les pools rejoués : ses totaux par bras ne sont donc pas ceux de la lecture.

## 5. Commandes (RUGGER 03, depuis le checkout de l'arbre gelé aff97638, CPython 3.12)

```bash
export RUGGER_NO_DOTENV=1
export PYTHONPATH=<checkout gelé>:<dossier parent de w1aux v7.4>:<ce paquet>
python -B -m w1x.explore --step selfcheck --out OUT --s0 467275745 --workers 4
python -B -m w1x.explore --step export  --out OUT --s0 467275745 --expect-sha <digest selfcheck> \
    --window-dir <run LaunchLab W1> --pilot-dir <pilote> --other-run <autres runs du mois> \
    --gate-json <GATE.json officiel> --gate-json-sha256 <sha ancré par R02>
python -B -m w1x.explore --step series  --out OUT --s0 467275745 --expect-sha <digest export> \
    --sol-usd-dir <run SOL/USD W1> --study-report <rapport d'étude ancré e3d92847>
python -B -m w1x.explore --step trials  --out OUT --s0 467275745 --expect-sha <digest series> --workers 4
python -B -m w1x.explore --step ledger  --out OUT --s0 467275745 --expect-sha <digest trials>
python -B -m w1x.explore --step reading --out OUT --s0 467275745 --expect-sha <digest ledger>
```
`OUT` doit être un dossier neuf, distinct du dossier de dayj. Après une interruption de `trials` : même commande
avec `--resume` (comme en jour J : même `registered_at`, sorties partielles mises en quarantaine).

Preuves d'identité sur des données réelles déjà ouvertes (aucun rendement, un export et une série seulement) :
```bash
python -B -m w1x.prove export --window-dir <pilote W1 ou pack P0 ouvert> --out <dossier neuf>
python -B -m w1x.prove series --run-dir <run Pyth ouvert> --study-report <rapport ancré> --out <dossier neuf>
```
Chaque commande exécute la fonction gelée et la fonction en flux dans deux processus, compare tous les fichiers
octet pour octet, et imprime `identical`, les sha256, la mémoire de pointe et la durée de chacun (pour la
projection par transaction demandée par R02, plafond de 8 Go). v0.1.1 : pour la voie en flux, `phases` donne la
mémoire de pointe atteinte à la fin de chaque phase (maximum courant : la phase où il monte est celle qui
domine). À lancer d'un processus neuf.

v0.1.2 : `python -B -m w1x.prove subset --run-dir <run vérifié> --tx-segments N --out <dossier neuf>` fabrique
un run plus petit, fait des N premiers segments tx (fichiers copiés tels quels, liste des signatures réécrite,
ni ancre ni journal d'appels, manifeste marqué `w1x_subset`), qui doit passer `bf.verify`. Il ne sert qu'à mesurer
la mémoire sur plusieurs tailles de données réelles déjà ouvertes (le pilote : 4, 8 puis 13 segments) ; ce n'est
jamais une collecte.

Mémoire, d'après les preuves de R03 du 15/11 (toutes identiques) et mes mesures synthétiques :
- la série en flux lit chaque **segment** entier avec le lecteur gelé avant de l'alléger : son pic vaut au moins
  un segment décodé (environ 14 Mo de RAM par Mo gz, mesure de R03). Un run d'un seul segment a donc le même pic
  dans les deux voies (c'est le cas des quatre runs d'étude). Par transaction, mesuré au traceur d'allocation :
  ligne allégée 1 560 octets, point 494 octets, série et texte JSON 395 octets de plus par point ;
- l'export en flux ne garde aucune transaction de la fenêtre ; grandissent avec la fenêtre la vérification gelée
  (listes et ensembles de signatures) et les transactions de création des pools créés.

## 6. Tests (aucun réseau)

```bash
cd <checkout gelé>
PYTHONPATH=<checkout>:<parent de w1aux v7.4>:<ce paquet> RUGGER_NO_DOTENV=1 \
  python -B -m pytest <ce paquet>/w1x/tests -p no:cacheprovider -q
```
→ 64 tests : `stream_export` 10 (repris de l'option, seule la ligne d'import change) ; `stream_series` 28 ;
`reading` 12 ; `explore` 12 (dont la chaîne complète sur le pack gelé : bundles 4aee76a3, ledger PASS sans
rapport, lecture) ; `prove` 3 (65 tests avec la v0.1.2).

Défauts volontaires :
- `stream_series.py` : 13 introduits, 13 détectés (erreur de décodage levée hors de l'ordre du gel, drapeau
  d'erreur perdu, empreinte prise sur la ligne allégée, date de bloc perdue, vérification non comparée, sortie
  existante écrasée, lignes non allégées, fonctions non restaurées, bloc réentrant, erreur avalée, segments
  complets gardés en mémoire, ligne complète gardée dans la ligne allégée, autre flux de prix accepté). Un
  quatorzième, équivalent, m'a fait retirer un garde inutile.
- `reading.py` : 22 introduits, 22 détectés (quantile de rang supérieur, résultat nul compté comme gain, facteur
  de profit sans valeur absolue, population non restreinte, borne incluse, autres essais lus, grappe = pool,
  motifs inconnus non regroupés, résidu masqué, cycle non vérifié accepté, ledger avec rapport accepté, autre
  bundle accepté, autre graine, 1 000 tirages, ledger et bundle non comparés, brut = net, quatre grappes, six
  meilleures positions, écarts ignorés, moyenne des moyennes de grappes, intervalle à 90 %, positions ouvertes
  mal comptées). Un vingt-troisième est équivalent par construction.
- `explore.py` : 24 introduits, 24 détectés (évaluation appelable, étapes officielles non refusées, garde
  mémoire absente ou dérogée, quatre contrôles de la porte, vérification non comparée, étapes hors des blocs en
  flux, sorties hors du dossier marqué, dossier de dayj accepté, empreintes non écrites, tout détail imprimé,
  état sous le nom de dayj, digest précédent non exigé, identités sans ce paquet, ledger en échec ou citant un
  rapport accepté, dossier de ledger réutilisé, ledger lancé avec un rapport).

## 7. Ce qui n'est pas vérifié

- **Preuves sur données réelles (R03, 15/11) : identité acquise** pour l'export sur le pilote W1 et pour la série
  sur les quatre runs d'étude Pyth. **Limite, dans les termes de R02 : aucune preuve d'identité sur une fenêtre
  réelle de la taille de W1** ; aucun export sur la fenêtre brute P0 (elle contient la partie réservée). Preuves
  admises : pilote, pack gelé, synthétiques et cas adverses.
- **Mémoire et durée à l'échelle de W1 : inconnues.** `stream_export` n'a tourné que sur de petites fenêtres ;
  la série allégée garde une ligne par transaction (ordre de grandeur : 1 Ko, soit environ 1 Go pour 718 183
  transactions, non mesuré) ; les réserves de `trials` et `ledger` sont faibles (9 % et 5 %) et reposent sur des
  constantes mesurées sur des packs synthétiques. Si la garde mémoire refuse : arrêt, sans dérogation.
- Le bootstrap donne des bornes identiques à 10⁻¹² près, pas au dernier bit, selon l'ordre des additions
  flottantes d'une réécriture indépendante.
- `reading` ne recalcule rien du ledger : il suppose ses lignes justes (le ledger les a re-dérivées et son
  verdict doit être PASS, 0 écart).
