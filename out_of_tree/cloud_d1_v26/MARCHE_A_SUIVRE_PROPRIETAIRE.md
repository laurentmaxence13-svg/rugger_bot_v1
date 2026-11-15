# W1 — calcul officiel sur Google Cloud (voie B) : marche à suivre du propriétaire

Paquet cloud v2.6.1. Tout se fait dans **Cloud Shell**, dans VOTRE projet Google Cloud. Aucun agent n'a accès à
votre compte. Chaque commande se lance telle quelle. Si un message commence par `STOP:`, n'allez pas plus loin et
transmettez la ligne à RUGGER 04.

**À ne faire qu'après le message de validation de RUGGER 02** (votre condition n° 1).

## Avant de commencer (aucune dépense)

1. **Tarif.** Calculateur de prix Google Cloud : machine `n2-highmem-16`, région `us-central1` (Iowa), à la
   demande, 40 heures, disque « Balanced » de 200 Go. Attendu : environ 1,05 $/h et environ 45 $ hors taxes au
   total. **Si le total, taxes comprises, dépasse 60 $, ne lancez rien** et prévenez RUGGER 04.
2. **Alerte de budget.** Console → Facturation → Budgets et alertes → créer un budget de **60 $** sur ce projet,
   seuils 50 %, 90 % et 100 %. Une alerte vous prévient par courriel ; elle n'arrête rien toute seule.
3. **Fichiers.** Dans Cloud Shell, menu ⋮ → Importer : `create_vm.sh` et `startup.sh`, dans le même dossier.
4. **Valeurs à remplir** en haut de `create_vm.sh` (bouton « Ouvrir l'éditeur ») :

| Champ | Valeur |
|---|---|
| `PROJECT` | l'identifiant de votre projet |
| `BUCKET` | un nom **nouveau**, réservé à ce calcul (pas celui de la sauvegarde), par exemple `w1-calcul-` suivi de quelques caractères de votre choix |
| `IMAGE` | le nom affiché par : `gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project=ubuntu-os-cloud --format='value(name)'` (à transmettre à RUGGER 04) |
| `MACHINE` | `n2-highmem-16` |
| `DEADLINE` | la date limite, à fixer **juste avant l'étape 3** : résultat de `date -u -d '+40 hours' +%FT%TZ` |
| `INBOUND_SUMS_SHA` | transmis par RUGGER 04 (ancré par RUGGER 02) |
| `CODE_COMMIT` | transmis par RUGGER 04 |

Pour l'étape 1, mettez déjà une date limite provisoire (la même commande) ; vous la referez avant l'étape 3.

## Les étapes

| # | Commande | Ce que vous devez voir | Ensuite |
|---|---|---|---|
| 1 | `bash create_vm.sh setup` | `setup OK` | — |
| 2 | `bash create_vm.sh token inbound` | un jeton (longue chaîne) | le coller **uniquement** dans le formulaire sécurisé de RUGGER 03, puis taper `clear`. RUGGER 03 dépose les données (4,7 Go). S'il lui faut plus d'une heure, il vous redemande un jeton. |
| 3 | refaire `DEADLINE`, puis `bash create_vm.sh launch` | `automatic deletion confirmed: …` | transmettre cette ligne à RUGGER 04. **La dépense commence ici.** Si la ligne n'apparaît pas, la machine a été supprimée par le script : transmettre le message. |
| 4 | `bash create_vm.sh token relay`, à chaque demande de RUGGER 04 | un jeton | même geste qu'à l'étape 2. Il sert à RUGGER 03 pour faire passer les validations de RUGGER 02 à la machine, étape par étape. |
| 5 | `bash create_vm.sh start`, seulement si RUGGER 04 le demande | `started` | la machine s'éteint d'elle-même après 3 h sans validation (elle ne coûte alors que son disque) ; cette commande la relance. |
| 6 | `bash create_vm.sh token outbound`, à la fin | un jeton | même geste. RUGGER 03 télécharge les résultats, RUGGER 02 les vérifie. |
| 7 | `bash create_vm.sh teardown` | `teardown OK` | puis la commande `gcloud storage buckets delete …` affichée, et relever la dépense réelle : Facturation → Rapports. |

`bash create_vm.sh status` montre à tout moment où en est la machine (lecture seule).

## Règle de fin : l'étape 7, au plus tard à la date limite

- Si la machine **tourne encore** à la date limite, Google la supprime avec son disque, automatiquement.
- Si elle est **déjà éteinte** (attente, fin du calcul ou échec), Google ne la supprime pas : elle ne peut plus
  redémarrer, mais son disque coûte encore environ 0,65 $ par jour tant que l'étape 7 n'est pas faite.
- Donc : **lancez l'étape 7 dès que RUGGER 04 vous dit que les résultats sont vérifiés, et de toute façon au plus
  tard à la date limite, même si rien n'est fini.** Elle peut être relancée sans risque ; `teardown OK` signifie :
  plus de machine, plus de disque, plus de compte de service, plus de fichier.
- En cas d'alerte de budget, de doute ou d'anomalie : étape 7 tout de suite.

## Ce que vous ne faites jamais

Coller un jeton dans une conversation, un courriel, GitHub ou un fichier ; créer une clé de compte de service ;
réutiliser le bucket de la sauvegarde ; lancer une étape sans le message de RUGGER 04 correspondant.
