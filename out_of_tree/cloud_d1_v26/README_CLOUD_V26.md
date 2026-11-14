# W1 — option cloud D1 v2.6 : la chaîne complète sur une machine à grande mémoire (préparée, NON exécutée)

**Statut.** Texte et scripts seulement, jamais exécutés sur Google Cloud. Rien n'est créé ni dépensé sans le GO
explicite du propriétaire, après l'audit de RUGGER 02. Calcul hors ligne (HISTORICAL_REPLAY). Aucun ordre, aucune
signature, aucune clé de wallet. Le protocole W1 v2.6.2 et le code gelé ne sont pas modifiés : la machine exécute
le code gelé tel quel.

## 1. Pourquoi

Le 14/11 à 22:16Z, l'étape `export` de la chaîne officielle a été tuée par manque de mémoire dans la session de
RUGGER 03 (rc=137) : `export_pools` gelé charge les 2 236 619 transactions de la fenêtre, environ 78 Gio, pour
13,35 Gio disponibles. L'étape `series` a le même défaut (718 183 transactions SOL/USD, environ 26 Gio mesurés par
R03), et `evaluate` demande 56 Ko par signature exportée avec une marge de 1,5 (garde mémoire de dayj).
RUGGER 02 (b98ce7e5, 6ff071be) recommande d'exécuter le code gelé tel quel sur une machine plus grande plutôt que
d'amender le protocole.

## 2. Ce qui change par rapport à la v2.5 auditée

| Point | v2.5 | v2.6 |
|---|---|---|
| Étapes sur la VM | à partir de `trials` ou `evaluate` | **toute la chaîne** : selfcheck, gate, export, series, trials, evaluate, ledger, dossier |
| Enchaînement | `chained` accepté (C1-C5) | **une étape par ancrage** (R02 d38f6580) : après chaque étape la VM publie `DAYJ_STATE.json` et attend `anchors/expect_<étape>.txt` |
| Attente | 3 h puis arrêt définitif | `wait_minutes` (180 par défaut) puis **PAUSE** : la VM s'éteint et reprend à son prochain démarrage (`start`) |
| Second démarrage | refusé | admis après une PAUSE ; **refusé après un STOP** (définitif), 12 démarrages au plus |
| Machine | n2-highmem-8 (64 Go), disque 100 Go | `n2-highmem-16` (128 Go) ou `n2-highmem-32` (256 Go), disque 300 Go |
| Limite de durée | `max-run-duration=12h`, suppression | **`termination-time` = date limite absolue**, arrêt (le disque reste jusqu'à `teardown`) ; la VM la contrôle aussi elle-même |
| Entrées | le répertoire dayj de R03 | les **collectes** telles quelles (`data_<nom>.tar`) et `STEPS.json` (arguments des étapes et empreintes ancrées) |
| Contrôle croisé | échantillon d'identité (empreintes des FICHIERS) | échantillon d'identité **corrigé** (§2 bis) **et** `GATE.json` égal à celui de la session de R03 (sha attendu dans `STEPS.json`) |
| w1aux | v7.3 (63eb3412) | **v7.4** (MANIFEST 31222874, audit R02 46da9df2) |
| Jetons | inbound, outbound | inbound, outbound, et **relay** (lecture `outbound/` + création `anchors/`), ce dernier **seulement si R02 amende K-1 par écrit** |
| Nettoyage du bucket | suppression automatique à 7 jours | **aucune** suppression automatique ; `teardown` ne touche que `inbound/`, `outbound/`, `anchors/` (pas la sauvegarde `w1-backup/`) |
| URL signées (repli) | présentes | retirées de ce paquet |

## 2 bis. Défaut de la v2.5 trouvé en préparant la v2.6 : l'échantillon d'identité dépendait de la machine

En rejouant l'échantillon d'identité le 14/11, deux des trois empreintes de référence de la v2.5 ne sont plus
retrouvées dans la session de R01 (`w1_report.json` 44aaa9e3 → beddda5d ; `ledger.json` fd68eea7 → 7285d7fb), alors
que celle des bundles est inchangée (ba14a5db). Cause établie : le rapport gelé consigne son environnement
(`harness.runtime_record` : `platform.platform()`, donc la version du noyau, la chaîne de compilation de
l'interpréteur et les distributions installées), et le registre cite le sha du fichier de rapport. Le noyau de la
session est passé de `6.18.44-fc-v378` à `6.18.44-fc-v470`. w1aux v7.3 et v7.4 donnent aujourd'hui les mêmes
empreintes de fichiers : la v7.4 n'y est pour rien.

Conséquence : **sur une VM Google Cloud (autre noyau), le contrôle d'identité de la v2.5 se serait arrêté** sur
`identity_sample`, sans que rien ne soit faux. Ce défaut n'avait pas été vu faute de répétition à blanc.

Correction en v2.6 : `identity_check_v26.py` compare trois empreintes **indépendantes de la machine** :
- `bundles_sums_sha256` : inchangée, **ba14a5db…** ;
- `w1_report_core_sha256` : le rapport sans sa clé `runtime`, en JSON canonique : **10e18960…** ;
- `ledger_core_sha256` : le registre sans le sha cité du fichier de rapport : **c810727c…**.
Mesuré dans la session de R01 avec w1aux v7.3 et v7.4 (mêmes valeurs). **À reproduire par R03 dans sa session et à
ancrer par R02 avant tout usage.** Les empreintes de fichiers restent imprimées, pour information.

Remarque : le rapport officiel W1 portera de la même façon l'environnement de la machine qui l'aura produit ; cela
ne touche ni la décision ni les chiffres, mais son sha de fichier n'est pas comparable d'une machine à l'autre.

Inchangé : bucket privé contrôlé, comptes de service sans rôle projet ni clé, aucune IP publique, pas de NAT,
VM protégée, pas de clé SSH, contrôles des fichiers reçus (liste exacte, empreintes, aucun pickle, aucun wheel qui
masque un module), arbre aff97638, CPython 3.12.3 x86_64, registre P0 f1f26e36, conditions K-2 à K-7.

## 3. Dimensionnement et coût

- **Mémoire nécessaire** (à confirmer par le comptage N de R03, autorisé par R02) :
  - export : environ 78 Gio de transactions, plus le tri et les archives ;
  - series : environ 26 Gio ;
  - evaluate : (150 Mo + 56 Ko × N) × 1,5. Pour N = 1 000 000 : 80 Gio. Pour N = 2 000 000 : 160 Gio.
  - Donc `n2-highmem-16` (128 Go) si N ≤ environ 1 400 000, sinon `n2-highmem-32` (256 Go). **R02 tranche.**
- **Tarif officiel, à la demande, relevé le 14/11/2026** sur
  `https://cloud.google.com/products/compute/pricing/general-purpose` : n2-highmem-16 **1,048112 $/h**,
  n2-highmem-32 **2,096224 $/h**, hors taxes. La page consultée ne nomme pas la région sur l'extrait lu ; ces
  montants sont exactement le double et le quadruple du tarif us-central1 de la n2-highmem-8 retenu en v2.5
  (0,524 $/h). **À revérifier par le propriétaire dans le calculateur de prix avant son GO.**
- **Durée** : inconnue à cette échelle ; aucune étape n'a jamais tourné sur 2,2 millions de transactions. La VM
  n'est facturée que lorsqu'elle tourne ; pendant une PAUSE elle est éteinte (seul le disque est facturé).
- **Plafond à présenter au propriétaire** (formule de R02, d38f6580) :
  `2 × (durée estimée de la chaîne + attente des audits, au moins 12 h) × tarif horaire + disque + stockage`.
  Exemple avec une chaîne de 10 h sur n2-highmem-32 : 2 × 22 h × 2,10 $ = 92 $, plus le disque de 300 Go et le
  stockage (quelques dollars) : **plafond de l'ordre de 100 $**. Sur n2-highmem-16 : de l'ordre de 50 $.
  Le propriétaire fixe le montant final.
- **Garde-fous de dépense** :
  - `DEADLINE` : la VM est arrêtée d'office à cette date (`--termination-time`), quoi qu'il arrive, et refuse
    elle-même de lancer une étape après. Dépense maximale de calcul = (DEADLINE − lancement) × tarif horaire.
  - une alerte de budget (gratuite), à créer par le propriétaire dans la console Facturation → Budgets et alertes,
    au montant du plafond, avec des seuils à 50 %, 90 % et 100 %. Une alerte prévient, elle n'arrête rien.
  - aucune autre ressource payante : une VM, son disque, le bucket.

## 4. Déroulé

**Avant** (hors ligne, sans dépense)
1. R03 prépare `inbound/` : `r03_transfer.sh prepare …` (§5). R02 ancre le sha de `INBOUND_SHA256SUMS`.
2. R02 audite ce paquet et fixe `MACHINE`.

**Avec le GO du propriétaire**
3. Propriétaire, Cloud Shell : remplir les champs de `create_vm.sh`, puis `bash create_vm.sh setup`.
4. `bash create_vm.sh token inbound` → saisie dans le formulaire sécurisé de R03 → R03 : `r03_transfer.sh put`
   (environ 5 Go). Le propriétaire supprime ensuite le secret (K-3).
5. `bash create_vm.sh launch`. La VM vérifie ses entrées, rejoue l'échantillon d'identité, exécute `selfcheck`,
   publie `SELFCHECK.json` et `DAYJ_STATE.json`, puis attend l'ancre de `gate`.

**Boucle, une fois par étape** (gate, export, series, trials, evaluate, ledger, dossier)
6. R03 lit l'état publié (`r03_transfer.sh state`) et le transmet à R02.
7. R02 ancre le digest de l'étape terminée.
8. L'ancre est déposée : soit par le propriétaire (`bash create_vm.sh anchor <étape suivante> <sha256>`), soit par
   R03 (`r03_transfer.sh anchor`, jeton `relay`, si R02 l'a admis).
9. La VM exécute l'étape suivante. Si aucune ancre n'arrive en `WAIT_MINUTES`, elle s'éteint (PAUSE) :
   `bash create_vm.sh start` la relance une fois l'ancre déposée. `bash create_vm.sh status` montre où elle en est.

**Fin**
10. `bash create_vm.sh token outbound` → R03 : `r03_transfer.sh get` → R02 vérifie tous les digests (C3).
11. `bash create_vm.sh teardown` : VM, disque, comptes de service, `inbound/`, `outbound/`, `anchors/`.

**Charge pour le propriétaire.** Un jeton d'une heure à chaque phase d'échange et, sans le jeton `relay`, une
commande `anchor` par étape : de l'ordre de dix à vingt interventions courtes réparties sur la durée de la chaîne.
Avec le jeton `relay`, un renouvellement de jeton par heure d'activité.

## 5. Ce que R03 dépose dans `inbound/`

`r03_transfer.sh prepare W1AUX_PKG CODE_REPO CODE_REF P0_REGISTRY CLOUD_PKG STEPS_JSON OUT_DIR NOM=CHEMIN…`

| Fichier | Contenu | Contrôle sur la VM |
|---|---|---|
| `w1code.bundle` | bundle git du commit d'arbre **aff97638** | `HEAD^{tree}` = aff97638 |
| `w1aux_v74.tar` | w1aux v7.4 complet | sha du manifeste = **31222874** ; ne contient que `w1aux/` |
| `wheels/*.whl` | `requirements-dayj.txt`, versions exactes | sha256 dans les SUMS ; aucun module masqué |
| `identity_check_v26.py`, `IDENTITY_REFERENCE_V26.json` | échantillon d'équivalence corrigé (§2 bis) | trois empreintes indépendantes de la machine égales |
| `data_<nom>.tar` | une collecte ou un fichier, tel quel (LaunchLab, SOL/USD, pilote, autres runs du mois, résumé des blocs, relevé du propriétaire, rapport d'étude) | extraits dans `data/<nom>/` ; chemins relatifs, fichiers ordinaires, aucun pickle |
| `STEPS.json` | arguments de chaque étape et empreintes ancrées | clés exactes ; aucun argument réservé (`--out`, `--step`, `--s0`, `--expect-sha`, `--resume`…) |
| `p0_trials.jsonl` | registre P0 **f1f26e36** | sha256 dans les SUMS |
| `INBOUND_SHA256SUMS` | sha256 de tous les fichiers | **son propre sha est ancré par R02 et passé en métadonnée** |

`STEPS.json` :
```json
{"args": {"selfcheck": ["--workers", "{workers}"],
          "gate": ["--window-dir", "{data}/launchlab", "--coverage-summary", "{data}/summary/blocks_summary.json",
                   "--summary-sha256", "<55730dd9…>", "--after-reading", "{data}/reading/<nom exact du relevé>"],
          "export": ["--window-dir", "{data}/launchlab", "--pilot-dir", "{data}/pilot", "--other-run", "{data}/…"],
          "series": ["--sol-usd-dir", "{data}/sol_usd", "--study-report", "{data}/study/<rapport>"],
          "trials": ["--workers", "{workers}"],
          "evaluate": ["--registry", "{registry}"]},
 "expect_files": {"data/launchlab/manifest.json": "<115e0638…>", "data/sol_usd/manifest.json": "<28a768ac…>",
                  "data/summary/blocks_summary.json": "<55730dd9…>", "…": "…"},
 "expect_gate_json_sha256": "<e2c8d0b8…>"}
```
Les arguments sont ceux que R03 a utilisés dans sa session (COMMANDES_JOUR_J.md), avec `{data}`, `{in}`,
`{workers}` et `{registry}` remplacés sur la VM. Le nom du fichier de relevé doit être le même que dans la
session : il entre dans `GATE.json`, dont le sha doit être identique sur les deux machines.

Jamais déposés : `.env`, clés, URL d'endpoint, venv, P0 (holdout), checkpoints. `prepare` cherche des motifs de
secret dans les manifestes, états et journaux d'appels des collectes (pas dans les segments de transactions, qui
sont des données de chaîne brutes) et s'arrête à la première correspondance, sans jamais afficher la valeur.

## 6. Arrêts de la VM

- **STOP (définitif)** : empreinte des SUMS différente, fichier en trop ou altéré, lien symbolique, pickle, chemin
  de tar dangereux, wheel qui masque un module, interpréteur différent, arbre différent, manifeste w1aux différent,
  fichier ancré différent, échantillon d'identité différent, `selfcheck` différent de 4aee76a3, `GATE.json`
  différent de celui de la session, ancre mal formée, argument d'étape interdit, date limite dépassée, plus de 12
  démarrages, ou tout échec d'une étape. Le journal est publié, la VM s'éteint, et tout démarrage ultérieur refuse
  de travailler. Reprendre demande un diagnostic et une nouvelle VM.
- **PAUSE (reprise possible)** : pas d'ancre dans le délai. Aucune étape n'est relancée ni sautée : dayj refuse une
  étape déjà faite et un `--expect-sha` qui n'est pas le digest de l'étape précédente.
- **trials interrompu** (VM arrêtée en cours d'étape) : repris avec `--resume` (même `registered_at`, sorties
  partielles mises en quarantaine), comme en v2.5.

## 7. Tests hors ligne (aucun réseau, aucun compte Google)

`bash test_cloud_v26.sh <python 3.12.3> <dépôt contenant un commit d'arbre aff97638> <ref> <paquet w1aux v7.4>`
→ `ALL OK`.
- `create_vm.sh` avec de faux `gcloud` et `curl` : refus tant qu'un champ reste à remplir, machine ou date limite
  invalides, commandes exactes de `setup` (aucune suppression automatique, aucune clé, aucun rôle projet), les
  trois frontières de jeton (inbound : création sous `inbound/` ; outbound : lecture sous `outbound/` ; relay :
  lecture sous `outbound/` et création sous `anchors/`), options de `launch`, contrôles et non-écrasement de
  `anchor`, périmètre de `teardown`.
- `startup.sh` réel contre un « bucket » local ; seuls dayj, metrics et l'échantillon d'identité sont remplacés
  par des doubles qui enregistrent leurs appels : premier démarrage (entrées, selfcheck, PAUSE), deux ancres =
  deux étapes avec le bon `--expect-sha` et les bons arguments, fin de chaîne (metrics, tar sans checkpoint,
  `RESULT.json`), aucun travail après la fin, `GATE.json` différent = STOP définitif, ancre mal formée, date limite
  dépassée, trop de démarrages, douze altérations des entrées ou des arguments toutes refusées, reprise de trials.
- 13 défauts volontaires introduits dans les scripts : 12 détectés ; le treizième (un seul des deux contrôles de la
  date limite retiré) est couvert par l'autre contrôle, et le retrait des deux est détecté.
- Échantillon d'identité rejoué avec w1aux v7.3 et v7.4 : voir `IDENTITY_V26_RUNS.txt`.

## 8. Ce qui n'est pas vérifié

- Aucune commande n'a tourné sur Google Cloud : `--termination-time`, la présence de `gcloud` sur l'image, l'accès
  privé aux API, le jeton `relay` à deux règles, le comportement de la date limite après un arrêt et un
  redémarrage sont à constater lors d'une répétition à blanc (`launch` avec des entrées factices) si le
  propriétaire l'autorise.
- La durée et la mémoire réelles de chaque étape à l'échelle de W1 sont inconnues ; le dimensionnement repose sur
  les mesures de R03 et sur la projection de dayj.
- Les trois empreintes « cœur » de l'échantillon d'identité n'ont été mesurées que dans la session de R01, sous
  un seul noyau ; leur indépendance vis-à-vis de la machine est établie par construction (seule la clé `runtime`
  et le sha cité sont retirés), pas encore par une mesure sur une autre machine.
- `r03_transfer.sh prepare` n'a pas été rejoué en entier hors ligne dans cette version (le téléchargement des
  wheels et le contrôle PyPI demandent le réseau) ; ses contrôles sont ceux de la v2.5, plus le découpage des
  collectes.
- La sortie finale (`dayj_cloud_out.tar`) contient les pools exportés : plusieurs gigaoctets à télécharger par R03
  (sortie facturée au gigaoctet).
