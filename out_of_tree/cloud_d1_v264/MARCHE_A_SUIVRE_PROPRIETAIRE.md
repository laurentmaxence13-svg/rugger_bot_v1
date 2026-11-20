# W1 — calcul officiel sur Google Cloud (voie B) : marche à suivre du propriétaire

Paquet cloud **v2.6.4 (option A2)**. Tout se fait dans **Cloud Shell**, dans VOTRE projet Google Cloud. Aucun agent n'a accès à
votre compte. Chaque commande se lance telle quelle. Si un message commence par `STOP:`, n'allez pas plus loin et
transmettez la ligne à RUGGER 04.

**À ne faire qu'après les trois éléments suivants :**
1. le message de validation (PASS) de RUGGER 02 sur ce paquet v2.6.4 ;
2. **votre accord explicite** sur l'amendement C1 (correction du contrôle du ledger pour les lignes réétiquetées) et
   sur la dépense, avec le plafond de 66 $ TTC (décision du 20/11 : « sans lancement ni engagement financier » pour
   l'instant) ;
3. la sauvegarde W1 terminée et vérifiée (lots 6 et 7).

## Avant de commencer (aucune dépense)

1. **Tarif.** Calculateur de prix Google Cloud : machine `n2-highmem-16`, région `us-central1` (Iowa), à la
   demande, **50 heures**, disque « Balanced » de 200 Go. Attendu : environ 1,05 $/h, soit environ 54 $ hors taxes
   au maximum (50 h). La durée prévue est de 36 à 43 h, soit 48 à 57 $ TTC. **Si le total pour 50 h, taxes comprises,
   dépasse 66 $, ne lancez rien** et prévenez RUGGER 04.
2. **Alerte de budget.** Console → Facturation → Budgets et alertes → créer un budget de **66 $** sur ce projet,
   seuils 50 %, 90 % et 100 %. Une alerte vous prévient par courriel ; elle n'arrête rien toute seule.
3. **Fichiers.** Dans Cloud Shell, menu ⋮ → Importer : `create_vm.sh` et `startup.sh`, dans le même dossier.
   **Avant toute modification**, lancez `sha256sum create_vm.sh startup.sh` et comparez :
   - `create_vm.sh` : `0a4d4d66dea974a7172c2eb9f603a198601c4cc07c1ee2ca2c566bf1473666e3`
   - `startup.sh` : `b9d34c876b38ae32b31be8be1012874aaf48a5ad1da3ab8dbe65288982387805`

   Si une valeur diffère, n'utilisez pas le fichier et prévenez RUGGER 04 (c'est une autre version).
4. **Valeurs à remplir** en haut de `create_vm.sh` (bouton « Ouvrir l'éditeur ») :

| Champ | Valeur |
|---|---|
| `PROJECT` | l'identifiant de votre projet |
| `BUCKET` | un nom **nouveau**, réservé à ce calcul (pas celui de la sauvegarde), par exemple `w1-calcul-` suivi de quelques caractères de votre choix |
| `IMAGE` | le nom affiché par : `gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project=ubuntu-os-cloud --format='value(name)'` (à transmettre à RUGGER 04) |
| `MACHINE` | `n2-highmem-16` |
| `DEADLINE` | la date limite, à fixer **juste avant l'étape 3** : résultat de `date -u -d '+50 hours' +%FT%TZ` (50 h au plus, refusé au-delà) |
| `INBOUND_SUMS_SHA` | transmis par RUGGER 04 (ancré par RUGGER 02) |
| `CODE_COMMIT` | transmis par RUGGER 04 |

Pour l'étape 1, mettez déjà une date limite provisoire (la même commande) ; vous la referez avant l'étape 3.
**Après l'étape 3, ne modifiez plus `DEADLINE`** : l'étape 5 s'en sert pour remettre la suppression automatique.

## Les étapes

| # | Commande | Ce que vous devez voir | Ensuite |
|---|---|---|---|
| 1 | `bash create_vm.sh setup` | `setup OK` | — |
| 2 | `bash create_vm.sh token inbound` | un jeton (longue chaîne) | le coller **uniquement** dans le formulaire sécurisé de RUGGER 03, puis taper `clear`. RUGGER 03 dépose les données (4,7 Go). S'il lui faut plus d'une heure, il vous redemande un jeton. |
| 3 | refaire `DEADLINE`, puis `bash create_vm.sh launch` | `automatic deletion confirmed: …` | transmettre cette ligne à RUGGER 04. **La dépense commence ici.** Si la ligne n'apparaît pas, la machine a été supprimée par le script : transmettre le message. |
| 4 | `bash create_vm.sh token relay`, à chaque demande de RUGGER 04 | un jeton | même geste qu'à l'étape 2. Il sert à RUGGER 03 pour faire passer les validations de RUGGER 02 à la machine, étape par étape. |
| 5 | `bash create_vm.sh start`, seulement si RUGGER 04 le demande | `automatic deletion confirmed (start): …` | la machine s'éteint d'elle-même après 10 h sans validation (elle ne coûte alors que son disque) ; cette commande remet la suppression automatique, la contrôle, puis relance la machine. Transmettre la ligne à RUGGER 04. Si elle affiche `STOP:`, la machine n'a pas redémarré : transmettre le message. |
| 6 | `bash create_vm.sh token outbound`, à la fin | un jeton | même geste. RUGGER 03 télécharge les résultats, RUGGER 02 les vérifie. |
| 7 | `bash create_vm.sh teardown`, **seulement quand RUGGER 04 confirme que RUGGER 03 a téléchargé les résultats et que RUGGER 02 les a vérifiés** — ou à la date limite | `teardown OK` | puis la commande `gcloud storage buckets delete …` affichée, et relever la dépense réelle : Facturation → Rapports. |

`bash create_vm.sh status` montre à tout moment où en est la machine (lecture seule).

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

## Ce que vous ne faites jamais

Coller un jeton dans une conversation, un courriel, GitHub ou un fichier ; créer une clé de compte de service ;
réutiliser le bucket de la sauvegarde ; lancer une étape sans le message de RUGGER 04 correspondant.
