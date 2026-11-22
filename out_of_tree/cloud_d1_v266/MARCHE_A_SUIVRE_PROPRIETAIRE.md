# W1 — calcul officiel sur Google Cloud (voie B) : marche à suivre du propriétaire

Paquet cloud **v2.6.6 (option A2, brouillon)**. C'est v2.6.5 plus deux changements : vous déposez vous-même les ancres (`progress`, puis `anchor`), et il n'y a plus de jeton relais.

> **Exception limitée.** Ce paquet ne sert qu'au **seul calcul officiel W1** :
> - une seule machine, `w1-eval` (`n2-highmem-16`, `DEADLINE` à 49 h au plus, suppression automatique) ;
> - un bucket dédié ;
> - la chaîne fixe selfcheck → gate → export → series → trials → evaluate → ledger → dossier, sur l'arbre gelé.
>
> Il n'y a **aucun autre calcul** : ni paperstream, ni CPMM, ni sauvegarde. Le plafond est de 66 $ TTC, avec l'alerte de
> budget. **Ce n'est PAS une autorisation de dépense** tant que vous n'avez pas dit OUI à RUGGER 04. Tout se fait dans **Cloud Shell**, dans VOTRE projet Google Cloud. Aucun agent n'a accès à
votre compte. Chaque commande se lance telle quelle. Si un message commence par `STOP:`, n'allez pas plus loin et
transmettez la ligne à RUGGER 04.

**À ne faire qu'après les trois éléments suivants :**
1. le message de validation (PASS) de RUGGER 02 sur ce paquet v2.6.6 ;
2. **votre accord explicite** sur l'amendement C1 (correction du contrôle du ledger pour les lignes réétiquetées) et
   sur la dépense, avec le plafond de 66 $ TTC (décision du 20/11 : « sans lancement ni engagement financier » pour
   l'instant) ;
3. la sauvegarde W1 terminée et vérifiée (lots 6 et 7).

## Avant de commencer (aucune dépense)

1. **Tarif.** Calculateur de prix Google Cloud : machine `n2-highmem-16`, région `us-central1` (Iowa), à la
   demande, **49 heures**, disque « Balanced » de 200 Go. Attendu : environ 1,05 $/h, soit environ 54,3 $ hors taxes
   au maximum (49 h × 1,048112 $ + disque ≈ 1,5 $ + stockage ≈ 1,5 $), soit ≈ 65,2 $ TTC. La durée prévue est de 36 à 43 h
   (48 à 57 $ TTC). **Si le total pour 49 h, taxes comprises, dépasse 66 $, ne lancez rien** et prévenez RUGGER 04.
2. **Alerte de budget.** Console → Facturation → Budgets et alertes → créer un budget de **66 $** sur ce projet,
   seuils 50 %, 90 % et 100 %. Une alerte vous prévient par courriel ; elle n'arrête rien toute seule.
3. **Fichiers.** Dans Cloud Shell, menu ⋮ → Importer : `create_vm.sh` et `startup.sh`, dans le même dossier.
   **Avant toute modification**, lancez `sha256sum create_vm.sh startup.sh` et comparez :
   - `create_vm.sh` : `5feb06720aa1bc11f5b98ec0ca206e1a0fb0c80b3fca824ce3a9763605633dc7`
   - `startup.sh` : `ad229563c4b35f5a107026ecfe20d5a058df4ac60ea28eab42d65fab6be226a0`

   Si une valeur diffère, n'utilisez pas le fichier et prévenez RUGGER 04 (c'est une autre version).
4. **Valeurs à remplir** en haut de `create_vm.sh` (bouton « Ouvrir l'éditeur ») :

| Champ | Valeur |
|---|---|
| `PROJECT` | l'identifiant de votre projet |
| `BUCKET` | un nom **nouveau**, réservé à ce calcul (pas celui de la sauvegarde), par exemple `w1-calcul-` suivi de quelques caractères de votre choix |
| `IMAGE` | le nom affiché par : `gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project=ubuntu-os-cloud --format='value(name)'` (à transmettre à RUGGER 04) |
| `MACHINE` | `n2-highmem-16` |
| `DEADLINE` | la date limite, à fixer **juste avant l'étape 3** : résultat de `date -u -d '+49 hours' +%FT%TZ` (49 h au plus, refusé au-delà : plafond de 66 $ TTC) |
| `INBOUND_SUMS_SHA` | transmis par RUGGER 04 (ancré par RUGGER 02) |
| `CODE_COMMIT` | transmis par RUGGER 04 |

Pour l'étape 1, mettez déjà une date limite provisoire (la même commande) ; vous la referez avant l'étape 3.
**Après l'étape 3, ne modifiez plus `DEADLINE`** : l'étape 5 s'en sert pour remettre la suppression automatique.

## Les étapes

| # | Commande | Ce que vous devez voir | Ensuite |
|---|---|---|---|
| 1 | `bash create_vm.sh setup` | `setup OK` | — |
| 2 | `bash create_vm.sh token inbound` | un jeton (longue chaîne) | **vous-même**, au moment où RUGGER 04 vous le dit, vous le déposez comme *network secret* de l'environnement de RUGGER 03, dans les réglages de l'environnement, comme le décrit la fiche R02 v1.1 (e2a93ea8). Ne le collez jamais dans une conversation. Puis tapez `clear`. Personne ne vous le redemande : RUGGER 03 dépose les données (4,7 Go) avec ce secret. |
| 3 | refaire `DEADLINE`, puis `bash create_vm.sh launch` | `automatic deletion confirmed: …` | transmettre cette ligne à RUGGER 04. **La dépense commence ici.** Si la ligne n'apparaît pas, la machine a été supprimée par le script : transmettre le message. |
| 4 | `bash create_vm.sh progress`, à chaque demande de RUGGER 04 (une fois par étape) | une ligne `PROGRESS {…}` : l'étape, son digest, le sha de DAYJ_STATE.json, ses fichiers, des détails sans aucun P&L | copiez la ligne à RUGGER 04 (ce n'est pas un secret). RUGGER 02 l'ancre, puis RUGGER 04 vous renvoie une commande `bash create_vm.sh anchor <étape> <sha>` : lancez-la telle quelle. Elle affiche `anchor deposited for …` et refuse d'écraser une ancre déjà déposée. Si vous vous trompez en recopiant, la machine se met en pause, sans risque. **Il n'y a plus de jeton relais.** |
| 5 | `bash create_vm.sh start`, seulement si RUGGER 04 le demande | `automatic deletion confirmed (start): …` | la machine s'éteint d'elle-même après 10 h sans validation (elle ne coûte alors que son disque) ; cette commande remet la suppression automatique, la contrôle, puis relance la machine. Transmettre la ligne à RUGGER 04. Si elle affiche `STOP:`, la machine n'a pas redémarré : transmettre le message. |
| 6 | `bash create_vm.sh token outbound`, à la fin | un jeton | même geste qu'à l'étape 2 (*network secret*, jamais dans une conversation). RUGGER 03 télécharge les résultats, RUGGER 02 les vérifie. |
| 7 | `bash create_vm.sh teardown`, **seulement quand RUGGER 04 confirme que RUGGER 03 a téléchargé les résultats et que RUGGER 02 les a vérifiés** — ou à la date limite | `teardown OK` | puis la commande `gcloud storage buckets delete …` affichée, et relever la dépense réelle : Facturation → Rapports. |

`bash create_vm.sh status` montre à tout moment où en est la machine (lecture seule).

## Option (i) : déposer à l'avance 2 ancres, entre l'étape 2 et l'étape 3

Avec v2.6.6, le plus simple est d'utiliser la même commande qu'à l'étape 4. Cela donne 2 commandes :
`bash create_vm.sh anchor series VALEUR_SERIES`, puis `bash create_vm.sh anchor trials VALEUR_TRIALS`. Elles contrôlent
les 64 caractères hexadécimaux et refusent d'écraser une ancre. La copie manuelle ci-dessous reste possible.

Ce dépôt n'est pas obligatoire. Il vous évite 2 jetons relais. RUGGER 04 vous transmet 2 valeurs de 64 caractères
hexadécimaux, ancrées par RUGGER 02 :
- `VALEUR_SERIES`, le digest de l'étape export de la phase 1 locale ;
- `VALEUR_TRIALS`, le digest de l'étape series.

Dans Cloud Shell, remplacez `MON_BUCKET` par le nom de `BUCKET` et `VALEUR_…` par ces valeurs, puis lancez :

```
printf '%s\n' VALEUR_SERIES > expect_series.txt
printf '%s\n' VALEUR_TRIALS > expect_trials.txt
grep -cxE '[0-9a-f]{64}' expect_series.txt expect_trials.txt
gcloud storage cp --no-clobber expect_series.txt expect_trials.txt gs://MON_BUCKET/anchors/
```

- **Ce que vous devez voir.** La commande `grep` affiche `expect_series.txt:1` et `expect_trials.txt:1`. Si l'une des
  deux affiche `:0`, la valeur est mal copiée : n'envoyez rien.
- **Pas d'écrasement.** `--no-clobber` n'écrase jamais une ancre déjà présente. Si une ancre existe déjà, transmettez le
  message à RUGGER 04, sans rien forcer.
- **Garde zlib.** La machine contrôle elle-même la version de zlib avant toute étape. Si elle n'est pas `1.3`, elle
  s'éteint en PAUSE (`zlib_runtime_version_is_not_1.3:…`), sans rien calculer. Transmettez alors la ligne à RUGGER 04.
- **Les 5 autres ancres** (gate, export, evaluate, ledger, dossier) sont déposées par vous, avec l'étape 4 (`progress`, puis `anchor`).

## Règle de fin : l'étape 7, au plus tard à la date limite

- Si la machine **tourne encore** à la date limite, Google la supprime avec son disque, automatiquement.
- Si elle est **déjà éteinte** (attente, fin du calcul ou échec), Google ne la supprime pas. Passé la date limite,
  l'étape 5 refuse de la relancer et la machine refuse elle-même de travailler ; mais son disque coûte encore
  environ 0,65 $ par jour tant que l'étape 7 n'est pas faite.
- Donc : **lancez l'étape 7 dès que RUGGER 04 vous dit que les résultats sont téléchargés et vérifiés, et de toute
  façon au plus tard à la date limite, même si rien n'est fini.** Pas avant : elle efface les résultats restés
  sur Google Cloud. Elle peut être relancée sans risque ; `teardown OK` signifie : plus de machine, plus de
  disque, plus de compte de service, plus de fichier.
- La sauvegarde de la collecte W1 (opération séparée, bucket séparé) doit être faite et vérifiée avant l'étape 7.
- En cas d'alerte de budget, de doute ou d'anomalie : étape 7 tout de suite.

## Vos interventions, en tout (environ 15, courtes)

1. `setup` ;
2. l'alerte de budget à 66 $ ;
3. le jeton inbound, déposé comme *network secret* (1, éventuellement 2 si l'envoi dépasse une heure) ;
4. `launch` ;
5. éventuellement, les 2 ancres de l'option (i) ;
6. pour chaque étape restante : `progress`, puis `anchor` ;
7. le jeton outbound, déposé comme *network secret* ;
8. `teardown`.

Au total, 2 ou 3 jetons, jamais dans une conversation, et plus aucun jeton relais.

## Ce que vous ne faites jamais

Coller un jeton dans une conversation, un courriel, GitHub ou un fichier ; créer une clé de compte de service ;
réutiliser le bucket de la sauvegarde ; lancer une étape sans le message de RUGGER 04 correspondant.
