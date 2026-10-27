# État du projet — préparation P3

## Mission courante

- Dernier main récupéré : `966076c1a8b9a5d83bea74fe53fdad1056ade6dc`.
  [PR #19](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/19)
  **fusionnée**, après revue indépendante et correctif
  `a4b6685520862cbf8dd84949d872e08cd6715a56`.
- Référence main reproduite sur ses seuls fichiers suivis : **880 tests réussis,
  1 ignoré, 242 sous-tests réussis**, warnings en erreur, code 0, stderr vide.
  La précédente référence 875 appartient à la PR avant correctif de revue.
- Dernières corrections : suppression de l'authentification netrc implicite et
  des retries GET cachés ; reçus/digests pour les preuves quote/FX rejetées.
  Journal et calculs financiers revus indépendamment ; voir
  [P3_PR19_REVIEW.md](P3_PR19_REVIEW.md).
- Branche suivante : `feat/p3-native-launchlab-campaign`, issue de ce main.
  Priorité à l'API officielle Raydium `get/list`, `sort=new`, avec vérification
  RPC des créations et lecture cohérente des comptes, calculs natifs en SOL.
- Validation des composants avant collecte : **1 263 tests réussis, 1 ignoré,
  242 sous-tests réussis**, warnings en erreur, stderr vide ; 383 nouveaux cas
  natifs, temporels et de campagne, dont persistance avant analyse et refus réseau.
- Protocole fixé avant collecte :
  [P3_LAUNCHLAB_CAMPAIGN.md](P3_LAUNCHLAB_CAMPAIGN.md), deux candidats au plus,
  20 requêtes / 60 secondes, exclusions/échecs/gaps conservés. Les nouveaux
  composants sont isolés dans `bot/p3/` ; aucun seuil de stratégie n'est changé.
- **Évaluation économique P3 : NO-GO / INSUFFICIENT DATA.** L'index est une
  piste de découverte, les devis/projections ne sont pas des transactions.
  Couverture indépendante, fraîcheur vérifiable, identités/permissions complètes,
  coûts et sortie prospective restent nécessaires.
- Comparaison accès gratuits/déjà accessibles et coûts éventuels :
  [P3_SOURCE_ALTERNATIVES.md](P3_SOURCE_ALTERNATIVES.md).
  Aucun abonnement, dépense, clé ou portefeuille activé.
- Ledger, historique de performance et protections P1/P2 conservés. Les bases
  de capture et réponses brutes restent locales ; résumés et ancrages seulement
  sont destinés à la PR.

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
