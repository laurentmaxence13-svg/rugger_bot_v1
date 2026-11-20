# W1 — option cloud D1 v2.6 : la chaîne complète sur une machine à grande mémoire (préparée, NON exécutée)

**Statut.** Texte et scripts seulement, jamais exécutés sur Google Cloud. Calcul hors ligne (HISTORICAL_REPLAY).
Aucun ordre, aucune signature, aucune clé de wallet. Le protocole W1 v2.6.2 et le code gelé ne sont pas modifiés :
la machine exécute le code gelé tel quel.

**Accord conditionnel du propriétaire du 15/11/2026 04:17Z (8cfead0e)** : voie B autorisée, budget total de
60 USD au plus, machine 16 vCPU / 128 Go, tarif à vérifier avant toute création, 48 h au plus après le lancement
avec arrêt automatique vérifié, bucket dédié, alerte budgétaire et mécanisme d'arrêt effectif mis en place avant,
et **validation préalable de la configuration, des coûts et des sécurités par RUGGER 02**. Les versions 2.6.1 à
2.6.3 de ce paquet (§2 ter) adaptent `create_vm.sh` à ces conditions. `startup.sh`, `r03_transfer.sh` et l'échantillon
d'identité sont inchangés : ce que R03 dépose dans `inbound/` ne change pas.

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
| Attente | 3 h puis arrêt définitif | `wait_minutes` (180 en v2.6, **600 depuis la v2.6.3**) puis **PAUSE** : la VM s'éteint et reprend à son prochain démarrage (`start`) |
| Second démarrage | refusé | admis après une PAUSE ; **refusé après un STOP** (définitif), 12 démarrages au plus |
| Machine | n2-highmem-8 (64 Go), disque 100 Go | `n2-highmem-16` (128 Go) ou `n2-highmem-32` (256 Go), disque 200 Go (v2.6.1) |
| Limite de durée | `max-run-duration=12h`, suppression | **`termination-time` = date limite absolue, 48 h au plus, SUPPRESSION de la VM et de son disque** (v2.6.1), contrôlée juste après la création ; la VM contrôle aussi la date elle-même |
| Entrées | le répertoire dayj de R03 | les **collectes** telles quelles (`data_<nom>.tar`) et `STEPS.json` (arguments des étapes et empreintes ancrées) |
| Contrôle croisé | échantillon d'identité (empreintes des FICHIERS) | échantillon d'identité **corrigé** (§2 bis) **et** `GATE.json` égal à celui de la session de R03 (sha attendu dans `STEPS.json`) |
| w1aux | v7.3 (63eb3412) | **v7.4** (MANIFEST 31222874, audit R02 46da9df2) |
| Jetons | inbound, outbound | inbound, outbound, et **relay** (lecture `outbound/` + création `anchors/`), ce dernier **seulement si R02 amende K-1 par écrit** |
| Nettoyage du bucket | suppression automatique à 7 jours | bucket **dédié** au calcul, distinct de la sauvegarde : suppression automatique à 7 jours rétablie (v2.6.1) ; `teardown` vide `inbound/`, `outbound/`, `anchors/` |
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

## 2 ter. Versions 2.6.1 à 2.6.3 (15/11) : mise en conformité avec les conditions du propriétaire

Seul `create_vm.sh` change (avec ses tests, cette notice, la marche à suivre et le MANIFEST).

| Condition du propriétaire | v2.6 auditée (8d14eaac) | v2.6.1 |
|---|---|---|
| « Aucun service payant ne doit rester actif après la limite » | à la date limite la VM était **arrêtée** ; son disque restait facturé jusqu'à `teardown` | à la date limite la VM **et son disque sont supprimés** (`--instance-termination-action=DELETE`) |
| « Arrêt automatique vérifié » | réglage demandé, jamais relu | `launch` relit `scheduling.terminationTime` et `scheduling.instanceTerminationAction` sur la VM créée ; valeur vide ou autre que DELETE : **la VM est supprimée aussitôt** et le script s'arrête ; sinon il affiche la date et l'action constatées |
| « 48 heures après le lancement » | date limite libre | `launch` refuse une date limite passée ou à plus de 48 h |
| Bucket dédié | bucket au choix, sans nettoyage | bucket dédié, objets supprimés d'office après 7 jours |
| Budget de 60 USD | disque de 300 Go | disque de 200 Go ; date limite proposée : **lancement + 40 h** (§3) |
| Nettoyage final | `teardown` s'arrêtait si un élément était déjà supprimé | `teardown` peut être relancé (après la suppression automatique aussi) et vérifie en plus qu'aucun compte de service ne reste |

**v2.6.2 : correction C-1 de RUGGER 02 (audit de la v2.6.1, 51e0d72c).** Un arrêt efface la suppression
automatique (citation ci-dessous). En v2.6.1, après une PAUSE, `start` relançait donc la VM **sans** suppression
automatique, et une étape pouvait déborder la date limite (`startup.sh` ne contrôle la date qu'entre deux étapes).
`start` fait maintenant, dans cet ordre :
1. refus si la date limite est passée, ou postérieure à la création de la VM + 48 h (la date limite du fichier ne
   peut pas repousser la limite fixée au lancement au-delà des 48 h du propriétaire) ;
   - v2.6.3 (demande de R02) : refus si le statut de la VM n'est pas TERMINATED (une VM qui tourne déjà n'est pas
     touchée), et refus si sa sortie série contient une ligne « STOP: » (STOP définitif : inutile de payer un
     démarrage que `startup.sh` refuserait) ; si la sortie série est illisible, ce second contrôle ne bloque pas ;
2. `set-scheduling` (même date limite, action DELETE) **avant** le démarrage ; refus de démarrer si la commande
   échoue ;
3. relecture : refus de démarrer si la date est vide, si l'action n'est pas DELETE ou si la date relue ne désigne
   pas le même instant que la date limite ;
4. démarrage, puis nouvelle relecture : si le réglage a disparu, **la VM est supprimée aussitôt** ;
5. affichage de « automatic deletion confirmed (start): … ».
**v2.6.3, décision de R02 (15/11 04:38Z) : `WAIT_MINUTES=600`.** La VM attend une ancre 10 h au lieu de 3 h avant
de s'éteindre, pour couvrir une nuit sans passer par `start`, chemin jamais vérifié sur Google Cloud. Le pire cas
de dépense ne change pas : il est déjà calculé sur 40 h de marche continue, borné par la date limite.

`launch` compare aussi, désormais, l'instant relu à la date limite (comparaison en secondes, indépendante de la
notation). Si Google refuse `set-scheduling` sur une VM arrêtée, ou rend la date dans une notation illisible : pas
de redémarrage, puis `teardown` (défaut sûr ; la chaîne serait alors à reprendre sur une nouvelle VM).

**Limite à connaître (documentation Google « Limit the run time of a VM », lue le 15/11 par extraits).** La date
limite n'agit que sur une VM **en marche** : « The termination timestamp is automatically cleared whenever a VM is
stopped or suspended ». Or la VM s'éteint d'elle-même dans trois cas : PAUSE (pas d'ancre dans le délai), fin de la
chaîne, STOP définitif. Dans ces cas :
- elle ne coûte plus de calcul ; une fois la date passée, `start` refuse de la redémarrer et `startup.sh` refuse
  de travailler (on ne compte pas sur Google pour ce refus, puisque la date est effacée à l'arrêt) ;
- **son disque (200 Go, environ 0,03 $/h, soit 0,65 $ par jour) reste facturé jusqu'à `teardown`**.
Donc la suppression automatique couvre le cas « la VM tourne encore à la date limite » ; dans les autres cas, c'est
**`bash create_vm.sh teardown`, à lancer par le propriétaire dès la fin et au plus tard à la date limite**, qui
supprime tout et le vérifie (aucune VM, aucun disque, aucun compte de service, aucun objet). C'est la dernière
ligne de la marche à suivre. Rendre ce dernier cas automatique demanderait que la VM reste allumée jusqu'à la
date limite (dépense inutile) ou qu'elle ait le droit de se supprimer elle-même (droit Compute en plus) : **les
deux options sont refusées par R02, qui accepte ce reliquat** (moins de 1 $ par jour, `teardown` obligatoire au
plus tard à la date limite, rappelé par R04, publié dans le compte rendu au propriétaire). `teardown` ne se lance
qu'après le téléchargement des résultats par R03 et la vérification de R02, ou à la date limite ; la sauvegarde de
la collecte W1 doit être vérifiée avant.

Contrepartie de la suppression à la date limite (R02, 15/11) : si la date limite tombe en cours de chaîne, les
sorties intermédiaires restées sur la VM sont perdues ; seuls les fichiers déjà publiés dans `outbound/` restent
(7 jours). La sauvegarde de la collecte W1 est indépendante et doit être faite et vérifiée avant.

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
- **Plafond fixé par le propriétaire le 15/11 : 60 USD au total.** Pire cas avec `n2-highmem-16` et une date
  limite à **lancement + 40 h**, la VM tournant sans aucune pause :
  - calcul : 40 h × 1,048112 $ = 41,92 $ ;
  - disque de 200 Go (pd-balanced, environ 0,10 $ par Go et par mois) : environ 1,10 $ pour 40 h ;
  - stockage (environ 10 Go pendant 7 jours au plus) et téléchargement des résultats par R03 (quelques Go,
    environ 0,12 $ par Go) : environ 1,50 $ ;
  - **total d'environ 44,5 $ hors taxes, soit environ 53 $ avec une TVA de 20 %** si elle s'applique au compte.
  À 48 h, le même calcul donne environ 53 $ hors taxes et 64 $ avec 20 % de TVA : au-dessus de 60 $. D'où 40 h
  (validé par R02 le 15/11). Les tarifs du disque, du stockage et du téléchargement sont des ordres de grandeur
  non relevés sur la page officielle : **le propriétaire vérifie le total, taxes comprises, dans le calculateur
  de prix ; au-dessus de 60 $, pas de lancement** (condition 2 du propriétaire).
- **Garde-fous de dépense** :
  - `DEADLINE` : à cette date la VM, si elle tourne encore, est supprimée d'office avec son disque
    (`--termination-time`, action DELETE, contrôlée par `launch`), et elle refuse elle-même de lancer une étape
    après. Dépense maximale de calcul = (DEADLINE − lancement) × tarif horaire. Voir la limite au §2 ter.
  - `teardown` par le propriétaire dès la fin, et au plus tard à la date limite.
  - une alerte de budget (gratuite), à créer par le propriétaire dans la console Facturation → Budgets et alertes,
    au montant du plafond, avec des seuils à 50 %, 90 % et 100 %. Une alerte prévient, elle n'arrête rien.
  - aucune autre ressource payante : une VM, son disque, le bucket.

## 3 bis. Valeurs à remplir dans `create_vm.sh` (décisions du 14/11, R02 fd5537fd et suites)

- **`BUCKET` : un bucket DÉDIÉ à ce calcul, distinct de celui de la sauvegarde (`w1-backup/`). EXIGÉ par R02.**
  La VM et le compte `w1-url-signer` ont le rôle `objectAdmin` sur LEUR bucket : ils ne doivent avoir aucun droit
  sur la copie scellée de W1. Le propriétaire choisit le nom ; `setup` crée le bucket s'il n'existe pas.
- `MACHINE` : **`n2-highmem-16`** (128 Go). Comptage de R03 (w1_count.json 0f408a1f) : 322 146 signatures
  retenues, 2 273 pools ; projections : export 70 à 80 Go, series 26 Go, evaluate 26 Gio exigés par la garde.
- `DEADLINE` : **lancement + 40 h** (v2.6.1 ; `launch` refuse plus de 48 h), à fixer juste avant `launch` :
  `date -u -d '+40 hours' +%FT%TZ`.
- Plafond de dépense fixé par le propriétaire : **60 USD au total** ; alerte de budget à créer **avant** le
  lancement ; tarif à revérifier par le propriétaire.
- `workers` : 8 (valeur du script), accepté par R02 pour cette machine.
- Jeton `relay` : admis par R02 (amendement de K-1) : R03 ne dépose une ancre qu'après le message d'ancrage de
  R02, en le citant, et lui envoie le code HTTP et la valeur ; une ancre déposée avant l'ancrage vaut STOP.
- `PROJECT`, `IMAGE`, `INBOUND_SUMS_SHA`, `CODE_COMMIT` : comme en v2.5.

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
   `bash create_vm.sh start` la relance une fois l'ancre déposée, après avoir remis et contrôlé la suppression
   automatique (§2 ter) ; la valeur `DEADLINE` du fichier ne doit pas avoir changé depuis `launch`. `bash create_vm.sh status` montre où elle en est.

**Fin**
10. `bash create_vm.sh token outbound` → R03 : `r03_transfer.sh get` → R02 vérifie tous les digests (C3).
11. `bash create_vm.sh teardown` : VM, disque, comptes de service, `inbound/`, `outbound/`, `anchors/`.
    **Dès la fin, et au plus tard à la date limite, quoi qu'il soit arrivé** (§2 ter). Puis suppression du bucket
    vide et relevé de la dépense réelle (Facturation → Rapports), à transmettre à R04.

La marche à suivre du propriétaire, pas à pas, est dans `MARCHE_A_SUIVRE_PROPRIETAIRE.md`.

**Charge pour le propriétaire.** Un jeton d'une heure à chaque phase d'échange et, sans le jeton `relay`, une
commande `anchor` par étape : de l'ordre de dix à vingt interventions courtes réparties sur la durée de la chaîne.
Avec le jeton `relay`, un renouvellement de jeton par heure d'activité.

## 5. Ce que R03 dépose dans `inbound/`

`r03_transfer.sh prepare W1AUX_PKG CODE_REPO CODE_REF P0_REGISTRY CLOUD_PKG STEPS_JSON OUT_DIR NOM=CHEMIN…`

| Fichier | Contenu | Contrôle sur la VM |
|---|---|---|
| `w1code.bundle` | bundle git du commit d'arbre **aff97638** | `HEAD^{tree}` = aff97638 |
| `w1aux_v78.tar` | w1aux v7.8 complet (v2.6.4) | sha du manifeste = **426ed6cb** ; ne contient que `w1aux/` |
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
  invalides, commandes exactes de `setup` (cycle de vie de 7 jours, aucune clé, aucun rôle projet), les
  trois frontières de jeton (inbound : création sous `inbound/` ; outbound : lecture sous `outbound/` ; relay :
  lecture sous `outbound/` et création sous `anchors/`), options de `launch` (action DELETE, disque de 200 Go),
  refus d'une date limite passée ou à plus de 48 h, suppression immédiate de la VM si la suppression automatique
  n'est pas constatée (vide, autre action, autre instant, notation illisible), `start` (réglage remis avant le
  démarrage, relu avant et après, dix cas de refus sans démarrage, suppression si le réglage disparaît après le
  démarrage, refus après la date limite), contrôles et non-écrasement de `anchor`, périmètre de `teardown`.
- `startup.sh` réel contre un « bucket » local ; seuls dayj, metrics et l'échantillon d'identité sont remplacés
  par des doubles qui enregistrent leurs appels : premier démarrage (entrées, selfcheck, PAUSE), deux ancres =
  deux étapes avec le bon `--expect-sha` et les bons arguments, fin de chaîne (metrics, tar sans checkpoint,
  `RESULT.json`), aucun travail après la fin, `GATE.json` différent = STOP définitif, ancre mal formée, date limite
  dépassée, trop de démarrages, douze altérations des entrées ou des arguments toutes refusées, reprise de trials.
- 13 défauts volontaires introduits dans les scripts : 12 détectés ; le treizième (un seul des deux contrôles de la
  date limite retiré) est couvert par l'autre contrôle, et le retrait des deux est détecté.
- v2.6.1 : 10 défauts volontaires de plus dans `create_vm.sh` (contrôle de la suppression automatique retiré,
  action non contrôlée, VM non conforme laissée en marche, date limite au-delà de 48 h acceptée, date limite
  passée acceptée, action STOP au lieu de DELETE, `teardown` non rejouable, compte de service restant accepté,
  nettoyage du bucket à 70 jours, disque de 300 Go) : 10 détectés (le neuvième après ajout d'un contrôle du
  contenu de la règle de nettoyage).
- v2.6.2 : 10 défauts volontaires dans `start` et dans le contrôle commun (réglage non remis, échec de
  `set-scheduling` ignoré, pas de contrôle avant le démarrage, pas de contrôle après, réglage perdu toléré,
  redémarrage après la date limite, date limite repoussée au-delà de la création + 48 h, instant non comparé,
  action non comparée, action STOP) : 10 détectés. v2.6.3 : 2 de plus (statut non contrôlé, STOP définitif non
  contrôlé) : 2 détectés.
- Échantillon d'identité rejoué avec w1aux v7.3 et v7.4 : voir `IDENTITY_V26_RUNS.txt`.

## 8. Ce qui n'est pas vérifié

- Aucune commande n'a tourné sur Google Cloud : l'option `--termination-time` sur `instances create` et sur
  `instances set-scheduling` (VM arrêtée), le nom et le format des champs `scheduling.terminationTime`,
  `scheduling.instanceTerminationAction` et `creationTimestamp`, la présence de
  `gcloud` sur l'image, l'accès privé aux API, le jeton `relay` à deux règles sont à constater au premier
  lancement réel. Si l'option ou les champs diffèrent, `launch` échoue ou supprime la VM aussitôt : aucun calcul
  ne démarre sans suppression automatique constatée (défaut sûr, mais le lancement serait alors à corriger).
- Le comportement de la date limite sur une VM éteinte vient de la documentation Google (extraits lus par un
  moteur de recherche le 15/11, la page elle-même n'étant pas accessible depuis la session de R01), pas d'un
  essai.
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
