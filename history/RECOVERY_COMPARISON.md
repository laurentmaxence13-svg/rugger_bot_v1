# Récupération depuis le partage de la conversation originale

Source : snapshot partagé, titre exact **Configurer rugger_bot_v1**, version 1,
**10 tours visibles**. SHA256 du JSON source :
`a990b4466e772762af1fecd0b220659997812a0e78f835d721b49221c5f95f56`.
Il s'agit d'un historique partagé ; aucune VM ni dossier Cloud n'a été restauré.
L'exhaustivité de toute la conversation d'origine au-delà des dix tours contenus
n'est pas démontrée.

## Travaux déjà conservés dans le dépôt

Les tours précédents retracent les livraisons P1/P2/P3, les PR #18 à #21 et leurs
résultats. La dernière base de code publiée citée par le snapshot est la fusion
PR #21 `7ddddb9f73339242fbcb5b9bf10fa329c82fa700`, effectivement présente dans Git.
Les développements P3 de ce stade figurent déjà dans le dépôt ; ils ne doivent
pas être réappliqués depuis des diffs historiques sur la version courante.

## Deux modifications supplémentaires effectivement récupérées

Dernier tour, index 9, élément `fileChange` index 4, statut `completed` :

1. **P3_PR21_REVIEW.md** : fichier ajouté complet, reconstruit sans perte en
   retirant uniquement le préfixe `+` du diff, **34 lignes**. SHA256 reconstruit :
   `842b4d93bbf3ba30ead7264eec4d93bac24bd8a8c38e65c2b31b683788ef931f`.
   Le fichier est absent du worktree et des références Git locales inspectées.
   Il rapporte la revue historique 1 342/1/242, les archives 5/397 et la fusion
   de PR #21 ; ses références aux logs Cloud ne récupèrent pas ces logs.
2. **collect.py** : diff complet présent dans le snapshot, **20 lignes**,
   sauvegardé exactement dans `collect.py.snapshot.diff`. Sa copie avec en-têtes
   Git et chemin résolu est `collect.py.recovered.patch`.
   Il ajoute l'alias nommé `CANONICAL_RPC_URL=https://api.mainnet.solana.com`,
   le paramètre `_rpc(..., rpc_url=RPC_URL)`, une vérification de deux URL et
   `endpoint_kind` dans le reçu.
   Le symbole et le comportement optionnel sont absents du code actuel et des
   références Git locales inspectées. **Aucun patch n'a été appliqué.**

L'absence locale prouve que ces deux modifications ne sont pas intégrées dans
notre dépôt courant ; elle ne certifie pas l'absence de tout commit distant
inconnu. Le dernier tour partagé n'a pas de message final ni de livraison Git
ultérieure attestée.

## Pourquoi conserver le patch sans l'appliquer

`git apply --check collect.py.recovered.patch` réussit sur le code courant ;
`git apply --reverse --check` échoue : le changement n'est pas déjà appliqué.
Mais l'ancien patch ne modifie pas les politiques de transport
`ReadOnlySession.post` et `CampaignSession.post`, qui refusent encore cette URL
supplémentaire. Un contrôle hors réseau confirme **zéro appel transport** et le
refus de l'endpoint par les deux classes. L'option ajoutée serait donc refusée
avant requête : ce travail retrouvé n'est pas un correctif d'endpoint validé.
Aucun accès à cet endpoint n'a été testé ici ; sa disponibilité n'est pas déduite
de son nom dans le patch.

## Dernière intention de travail retrouvée

Les instructions utilisateur originales sont extraites dans
`last_original_user_instructions.md`, les derniers messages d'agent dans
`last_original_agent_messages.md`. L'agent préparait un contrôle sur un candidat
choisi sans consulter ses cotations, avec banque fraîche, conservation des
refus, petite vente de contrôle prédéfinie et replay contrefactuel des flux
externes dans l'ordre. Le snapshot ne contient pas de protocole final de cette
campagne ni de résultats prouvant son exécution.

Les validations rapportées dans ces messages restent historiques. Elles ne
remplacent pas les contrôles exécutés dans la session actuelle. Les instructions
historiques de fusion de PR #21 ne sont pas une autorisation de fusion de PR #22.

Fichiers et empreintes d'origine : `recovery-manifest.json`. Aucun `.env`, secret,
base utilisateur, état VM ou autre fichier Cloud non inclus n'a été récupéré.
