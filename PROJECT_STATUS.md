# État du projet — préparation P3

## Mission courante

- Branche : `feat/p3-point-in-time-data` ; base main fusionnée
  `9e4b5a788bf955e0afb9ab96818f17042c448b66`.
- Sources P3 testées : `da99644413ec68593d1f97a6727513fb9246ef69`.
  PR vérifiable ouverte : [#19](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/19).
- Préparation livrée dans `bot/p3/` : journal séparé append-only/as-of,
  capture publique bornée, devis exact-size et conversions SOL/USD strictes.
- **875 tests réussis, 1 ignoré, 242 sous-tests réussis**, warnings en erreur ;
  176 nouveaux cas P3. Ledger et tests historiques conservés sans modification.
- Contrôle live borné : 6 requêtes / 14 observations ; 5 signatures dont
  4 échecs chaîne, aucune création vérifiée ; deux quotes USDC pour tester
  le transport à 1 SOL, pas une stratégie LaunchLab ni une position acquise.
- Réseau utilisé sur cette mission : documentation publique et lectures anonymes
  Solana/Raydium/DexScreener. Discovery FX Hermes HTTP200, latest-price HTTP401,
  sans retry authentifié. Aucun abonnement, paiement, clé ou portefeuille utilisé.
- Préparation logicielle : testée. **Évaluation économique P3 : NO-GO /
  INSUFFICIENT DATA** ; prix source/fraîcheur, frais complets, exécutabilité,
  univers indépendant et corpus réel suffisants restent à établir.
- Rapport : [P3_DATA_READINESS_REPORT.md](P3_DATA_READINESS_REPORT.md).
  Protocole : [P3_CAPTURE_PROTOCOL.md](P3_CAPTURE_PROTOCOL.md).
  Sources/droits : [P3_DATA_SOURCES.md](P3_DATA_SOURCES.md).
- La base de capture et les réponses brutes restent locales ; seuls le résumé
  qualité et les ancrages sont versionnés. Aucune performance passée n'est recalculée.
- Prochaine étape : obtenir une source utilisable de FX horodaté et d'états de pool,
  devis et frais à taille effective, définir une campagne limitée avec accès/droits
  et budget validés, puis mesurer sa couverture avant toute conclusion économique.

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
