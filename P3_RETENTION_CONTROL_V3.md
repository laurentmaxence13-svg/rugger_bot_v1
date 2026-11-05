# Contrôle instrumental de conservation — protocole v3

27 octobre 2026. Un seul run interne, PAPER ONLY, nouveau plan
`benchmarks/p3_retention_control_v3/plan.json`, enregistré dans Git avant départ.
Commit source exact déclaré dans ce plan, SHA256 canonique retenu dans le journal.
L'ancienne v2 reste figée. Accès/conditions : `P3_SHORT_CONTROL_ACCESS.md`.

- Fenêtre : au plus 60 secondes monotones à partir du départ ; 20 tentatives
  réseau séquentielles maximum, prélevées avant dispatch, aucun retry/redirection.
- Une découverte GET `sort=new`, au plus 100 lignes retenues ; deux premiers mints
  distincts valides cotés WSOL, dans l'ordre reçu. Tous rejets/non-sélections restent
  conservés ; aucune représentativité de marché ou couverture exhaustive inférée.
- Taille fixe 1 SOL, slippage demandé 100 bps ; aucun ajustement après réponse.
- Lecture comptes et créations via RPC public, mêmes plafonds que v2, profil explicite
  `published_metadata_v1`. Aucun portefeuille, construction, signature ou envoi.
- Achat valide persisté avant demande de devis vente sur la quantité attendue.
  Refus logique HTTP200 = observation négative conservée, aucune vente fabriquée.
- Second snapshot après au moins 15 secondes monotones depuis la fin du dernier
  snapshot initial ; deadline globale toujours prioritaire. L'absence de suivi
  reste un manque. Aucun achat hypothétique injecté dans l'état futur observé.
- Arrêt après reçu de toute erreur HTTP non2xx, erreur de requête/transport/JSON,
  payload dangereux ou budget/deadline. Ne pas changer de fournisseur pour contourner
  un refus. Aucun appel de remplacement, compte créé ou quota payant activé.
- Export fermé vers nouveau bundle : garder ancre/hashes/tailles, copier seulement
  les preuves minimales autorisées dans le dépôt privé, aucune SQLite/.env/ledger.
- Restauration : récupérer les blobs depuis le dépôt privé dans un répertoire neuf,
  vérifier l'ancre hors réseau/DB, rejouer les analyses et normalisations disponibles.
  Ne pas dire que le transport fournisseur est validé si le run est bloqué.

Les lectures documentaires préalables sont distinctes du run de marché ; aucun
probe de marché n'a précédé le départ. Quotas documentaires non garantis, arrêt
au premier refus. Le résultat peut être nul ou incomplet : il doit rester tel quel.
Pas de corpus prolongé ni validation économique sur cet échantillon.
