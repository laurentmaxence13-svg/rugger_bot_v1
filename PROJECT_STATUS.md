# État du projet — préparation P3

## Mission courante — v2 exécutée et preuves archivées

- [PR #20](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/20)
  **fusionnée** : main `8167264931af3a22dcce32e9d1a821d275b51307`.
  Référence **1 304 / 1 / 242** reproduite ; deadline, annulations et enveloppe
  RPC corrigées après revue indépendante : **1 309 / 1 / 242** avant fusion.
  Voir [P3_PR20_REVIEW.md](P3_PR20_REVIEW.md).
- V2 existant exécuté depuis ce main, plan inchangé : **19/20 requêtes,
  25,909/60 s, 100 lignes, 2 candidats, 2 créations vérifiées, 4 snapshots,
  2 devis d'achat, 0 ventes disponibles**, 1 gap d'univers, 182 événements.
- Durabilité : **5 archives privées / 397 événements / 199 105 octets gzip**,
  restaurées via blobs GitHub sans DB locale ; hashes/ancrages vérifiés.
  Aucun SQLite, ledger ou .env publié. Les anciens corps jamais conservés
  restent manquants, explicitement déclarés dans les manifestes.
- Branche : `fix/p3-data-certification-and-durable-replay`, base main fusionné.
  Code testé : `de1e4b3d10b01a8bf9bd6003aaf8b8798a837ee5`.
  Suite finale : **1 342 réussis, 1 ignoré, 242 sous-tests**, warnings en erreur,
  stderr vide ; aucun réseau dans les tests, aucune dépendance ajoutée.
- Corrections ciblées : Token-2022 metadata-only 18/19, pins IDL indépendants/PDA
  publiques, contrôle de vente sur état ultérieur, entrées de replay et export
  portable. Profil historique conservé ; aucun seuil ou ledger modifié.
- Diagnostic postérieur : premier candidat lisible mais plateforme UNKNOWN ;
  second PDA complète mais supply mint/pool différente, contrôle conservé.
  Aucune estimation de sortie ultérieure qualifiée ; aucun résultat réétiqueté.
- **P3 économique : NO-GO / INSUFFICIENT DATA.** Couverture indépendante,
  temps source des devis, frais complets, réconciliation et sorties manquent.
- Rapport : [P3_V2_FINAL_VALIDATION.md](P3_V2_FINAL_VALIDATION.md).
  [Résultats v2](validation/P3_V2_DATA_RESULTS.json),
  [archives](evidence/p3/index.json),
  [restauration](validation/P3_EVIDENCE_RESTORE.json).
- Aucun ordre réel, dépense, souscription ou portefeuille activé. Pas de campagne
  prolongée ; droits/quotas et replay brut complet restent des préconditions.

## Résultats P3 antérieurs conservés

- Après PR #19 : main `966076c`, 880/1/242 reproduits ; P3_PR19_REVIEW.md.
- Primaire v1 : 19 requêtes, 185 événements, 0/2 créations ; diagnostics séparés :
  6 lectures, une création confirmée, second pool indisponible par timeout.
  Aucun réétiquetage des résultats primaires ou des performances historiques.
- Rapports historiques : P3_LAUNCHLAB_VALIDATION.md, P3_LAUNCHLAB_CAMPAIGN.md,
  P3_SOURCE_ALTERNATIVES.md ; preuves disponibles désormais archivées séparément.

## Livraison P1/P2 précédente

- Branche de livraison : `fix/p1-research-gates-and-synthetic-protocol`.
- Livraison : [PR #18](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/18).
- Commit audité code et artefacts : `fcfe41eb9abdda83d308cc17a2ef52910fc08e18` ;
  la mise à jour de suivi ajoute uniquement ces références de livraison.
- Référence P1 publiée et reproduite : `56294b4795390db14b1bc46205ab382eb4ac0f5d` (604/1/242).
- Commit du protocole figé avant expériences : `8530f2b982e657fe7cb3fe82c3d0ad5028edeffd`.
- Validation courante : **699 tests réussis, 1 ignoré, 242 sous-tests réussis**,
  warnings en erreur. Le skip concerne une base utilisateur volontairement absente.
- Validation effectuée dans le cloud ; aucun check CI GitHub n'est configuré
  sur cette branche. Revues indépendantes du nettoyage, des exclusions héritées,
  de la fidélité des artefacts et des conclusions économiques terminées.
- B01/B03/B04 conservés ; compléments B02, B05/B08/B09, motifs de refus et
  exclusions v25/v26 validés. Aucun critère de stratégie active modifié.
- Support P1 du périmètre synthétique : GO. P1 global tous CLI/données réelles :
  non certifié. Détails dans P1_CLOUD_VALIDATION.md.
- Sources validées et exécutées : `f1a1345f3a7c1871ef497c9d2ec1eb219c652a8a`.
- P2 synthétique : trois mondes exécutés, neuf candidats de développement et
  27 sensibilités finales ; trois relectures identiques. Aucun candidat positif
  en validation au stress fixé ; aucun modèle activé. Voir QUANT_VALIDATION_REPORT.md
  et benchmarks/p2_synthetic_v1/manifest.json.
- Avantage économique : **INSUFFICIENT DATA**. Aucun corpus réellement exécutable
  ni change entrée/sortie vérifié ; limites dans ECONOMIC_VIABILITY_AUDIT.md.
- Comparaison memecoins/BTC–SOL : INSUFFICIENT DATA pour les deux ; aucun second
  moteur construit ou réorientation justifiée (STRATEGY_COMPARISON.md).
- Réseau autorisé utilisé : GitHub et gestion Git/PR ; aucune API de marché,
  RPC/WS marché, portefeuille, clé privée ou nouvelle dépense.
- Trading réel : **interdit sans autorisation financière explicite**, aucune
  activation ni transaction effectuée.
- Prochain objectif mesurable : définir la devise et un corpus point-in-time
  avec rejets/absences, FX et quotes exécutables à taille effective. P3 attend
  ces données et les autorisations correspondantes ; aucune conclusion économique
  ni réorientation BTC/SOL n’est justifiée par les fixtures.
