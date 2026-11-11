# Sauvegarde seule de la collecte W1 sur un stockage privé Google Cloud (v1, 2026-11-11)

Texte uniquement. Aucun agent n'exécute ces commandes ; elles n'ont JAMAIS été exécutées sur Google Cloud
(seulement testées hors ligne avec de faux outils). Rien ne doit être lancé avant l'audit de RUGGER 02 et
l'accord final du propriétaire. Le paquet cloud v2.5 gelé n'est pas modifié : ceci est un fichier séparé.

## Ce que fait `backup_only.sh` (dans Cloud Shell, projet du propriétaire)

| Commande | Effet |
|---|---|
| `setup` | crée un bucket privé (us-central1, accès uniforme, accès public interdit) et UN compte de service qui ne peut que créer des objets dans ce bucket ; vérifie les réglages ; aucune clé, aucun rôle au niveau du projet, aucune VM, aucun disque |
| `token` | affiche un jeton d'une heure, réduit à la création d'objets sous `w1-backup/` ; le propriétaire le saisit dans le formulaire sécurisé de RUGGER 03, jamais dans une conversation |
| `verify` | liste ce qui est arrivé : noms, tailles, sommes de contrôle de Google |
| `sha256 SHA256SUMS` | recalcule le sha256 de chaque objet et le compare à la liste ancrée par RUGGER 02 |
| `delete DELETE-W1-BACKUP` | supprime les objets, le compte de service et le bucket, puis vérifie qu'il ne reste rien |

Le script refuse toute commande tant qu'un champ `__FILL` reste à remplir (identifiant du projet, nom du bucket).

## Pourquoi la copie reste scellée

Le jeton ne permet ni de lire, ni de lister, ni d'écraser, ni de supprimer : seul le propriétaire peut relire
la copie. Aucun agent ne peut donc consulter W1 par ce chemin avant le verdict officiel (exigence iv de R02).

## Avant le 14 novembre — étapes du propriétaire (après audit R02 et accord final)

1. Ouvrir Cloud Shell dans son projet, y déposer `backup_only.sh`, remplir les deux champs.
2. `bash backup_only.sh setup` (crée le bucket et le compte ; c'est le seul moment où une ressource est créée).
3. Le jour de la copie, après l'ancrage par R02 de la liste des sha256 : `bash backup_only.sh token`, puis saisie du
   jeton dans le formulaire sécurisé de R03 ; à renouveler chaque heure tant que l'envoi dure.
4. `bash backup_only.sh verify`, puis `bash backup_only.sh sha256 SHA256SUMS` avec la liste ancrée.

## Coût — indicatif, à confirmer par R04 et par le propriétaire sur la grille de prix avant l'accord final

- Stockage de 6 à 14 Go : quelques dizaines de centimes de dollar par mois.
- Envoi vers le bucket : gratuit. Téléchargement hors de Google Cloud (restauration) : facturé au Go.
- Aucune VM, aucun disque, aucun abonnement. Un compte de facturation actif est nécessaire sur le projet.

## Limites connues

- Les commandes `verify`, `sha256` et `delete` n'ont pas été éprouvées sur un vrai projet.
- La suppression différée de Google (« soft delete ») peut conserver des objets supprimés quelques jours, facturés.
- La sauvegarde progressive pendant la collecte dépend de la méthode de R03 et de l'avis de R02 sur le protocole.
