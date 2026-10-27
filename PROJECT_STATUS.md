# État du projet — candidat fonctionnel PAPER

## Livraison courante — 27 octobre 2026

`python -B -m bot demo --output work/demo-001` exécute maintenant le cycle réel
des composants sur une fixture synthétique : recovery/parseur/cache → garde
scanner/backfill → features/scoring → entrée → suivi → TP → frais → portefeuille
→ tableau de bord. Reconnexion SQLite après l'entrée et déduplication vérifiées.
Modèle : 1 SOL engagé, brut 0,20 / coût supposé 0,02 / net 0,18 SOL, capital 10 → 10,18 SOL.
Ce résultat synthétique ne démontre ni inventaire acquis ni rentabilité de marché.

Correction causale : le coût réellement appliqué à la clôture est persisté
atomiquement, ce qui permet de rapprocher le rapport après redémarrage. Aucun
changement de seuil ou de TP/SL. Rapports en lecture seule et latences mesurées
avec horloge monotone, provenance et inconnus explicites.

Code distant `f50d226`, arbre testé `c343ad51f418c04e2d18e8d050877996e585a0f4`,
équivalent local `4da94d3`. **1 435 passed, 1 skipped, 242 subtests passed**,
warnings en erreur, stderr vide, 5,31 s. Preuves `8aeb6c8`, PR #22 ouverte.

RPC contrôlé par une lecture préenregistrée HTTP200 (1 requête / 1,087 s), puis 007
exécuté une fois (12 requêtes / 19,871 s). Deux petites ventes indicatives obtenues
aux deux horizons ; supply et PDA du nouveau cas cohérentes. Quantité seulement
0,05507 % du devis d’achat de 1 SOL indépendant, pas de sortie complète ni P&L certifié. Heure/slot
source fournisseur inconnus, création absente du préfixe borné. Pas de contournement
de quota, retry, ordre ou dépense. Les 12 transactions de l'ancien mint restent
un travail borné distinct, non bloquant pour l'intégration du moteur.

11 bundles / 1 639 événements conservés ; les deux nouveaux bundles ont été restaurés
effectivement depuis GitHub, quatre quotes et deux snapshots reproduits sans DB
ni réseau pendant replay. Lire `RUGGER_V1_FUNCTIONAL_RELEASE.md`,
`validation/RUGGER_FUNCTIONAL_RELEASE_VALIDATION.json` et
`validation/RUGGER_FUNCTIONAL_REMOTE_RESTORE.json`.

Prochaine intégration : inventaire atomique lié à l'entrée puis qualification
d'une sortie à cette même quantité, avec impact d'entrée, frais et chronologie.
Configuration agressive conservée ; comparaison de stratégies seulement sur
cycles interprétables. Les sections suivantes sont des références antérieures.

## Référence antérieure — sorties à inventaire fixe et historique006

Code `fb8584d`, arbre `b049d1ef153287bd9d9cd78c52e583e79e3bcf54`.
**1 415 passed, 1 skipped, 242 subtests passed**, warnings en erreur, stderr vide.
PR #22 ouverte, non fusionnée. Orientation agressive et paramètres conservés.

- Dix nouveaux corps historiques, autre transaction du slot de création résolue.
  Trois burns total513119481705 ; résiduel466423024095, 12 corps manquants.
- Arrêt réel HTTP429 au11eappel/6,216s ; aucune requête de marché après. Retry-After
  était perdu par l'ancien code ; correctif testé, aucun délai inventé pour006.
- Bridge d'inventaire et de frais qualifie les couples de devis ; les sept couples
  archivés restent non qualifiés, aucun P&L ou fill revendiqué.
- Nouveau contrôle007 prêt : banques actives, q observé fixe, deux horizons, stock/
  liquidité vérifiés. Non exécuté suitequota, aucun changement du moteur de stratégie.
- 9 archives/605 événements,006 restauré depuis GitHub et qualification identique.
- Reprise/commandes : CODEX_CONTINUATION.md ; preuves et limites :
  P3_CONTINUATION_006_RESULTS.md, P3_MINT_HISTORY_006_RESULTS.md.

## Référence précédente — conservation réelle vérifiée, #22 non fusionnée

27 octobre 2026. Code final validé `e2e2008`, arbre `fbcd7ff26d09734e5e8eec558ffcf554c418757c`.
**1 379 passed, 1 skipped, 242 subtests passed**, warnings en erreur, stderr vide.
PR #22 et branche de reprise inchangées ; aucune fusion autorisée/effectuée.

- Contrôle v3 préenregistré dans GitHub avant départ : **19 tentatives / 26,034 s**,
  deux créations, quatre snapshots et quatre corps de devis conservés.
- Deux refus de vente réels **INSUFFICIENT_LIQUIDITY**, aucune cotation positive forcée.
- Deux burns historiques prouvés : 29386275175 unités ; reste 950156230625 non
  réconcilié, garde supply maintenu. Contrôles 004/005 clos, preuves conservées.
- **Contenu partagé de Configurer rugger_bot_v1 retrouvé** : 10 tours, copie exacte
  et transcription sous `history/`. Derniers diffs P3_PR21_REVIEW/collect récupérés ; sélection RPC canonique
  complétée et testée, sans fallback ni modification des protocoles historiques.
  Cela ne désarchive pas la tâche ni ne restaure la VM. Orientation agressive
  documentée dans `AGGRESSIVE_STRATEGY_CONTEXT.md`, aucun seuil modifié.
- Export de 152 événements puis restauration effective depuis GitHub, sans DB
  source : quatre analyses et quatre normalisations reproduites.
- Total conservé : **8 bundles / 580 événements** ; anciens corps absents inchangés.
- Code : diagnostics HTTP bornés, statut conservé à annulation, replay sémantique,
  plan successeur/profil enregistré/arrêts sur erreurs et délai monotone.
- **Conservation instrumentale validée sur ce contrôle ; NO-GO économique.**
  Banque de vente observée vide, achat hypothétique absent, identité plateforme et
  données de frais/horodatages/validation indépendante encore incomplètes.
- Sources et preuves : `CODEX_CONTINUATION.md`, `P3_RETENTION_EXIT_RESULTS.md`,
  `P3_SHORT_CONTROL_ACCESS.md`, `validation/P3_RETENTION_REMOTE_RESTORE.json`.

## Livraison initiale de reprise #22 — historique

27 octobre 2026. Lire [CODEX_CONTINUATION.md](CODEX_CONTINUATION.md) pour reprendre
sans l’ancienne conversation. Dernier main vérifié : fusion #21 `7ddddb9`.
[PR #22](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/22) **non fusionnée**,
branche `fix/p3-exit-evidence-continuation`, code publié `4f0fec8`, arbre testé
`539f716e04666c126ee0c30b628d22417625951a`.

- Corrigé : montants de devis rejetés encore exposés, tentatives annulées absentes,
  timing perdu lors d’un refus de corps dangereux, faits supply masqués par rejet.
- Validation actuelle : **1 348 passed, 1 skipped, 242 subtests passed**, warnings
  en erreur, stderr vide ; six cas causaux échouent sur l’ancienne version.
- Replay : **5 archives / 397 événements**, quatre analyses v2 identiques ; dix
  anciens corps quote restent absents. Oracle indépendant : 1 000 cas synthétiques.
- Outils réutilisables et rapport : `tools/`, `P3_CONTINUATION_VALIDATION.md`,
  `validation/P3_CONTINUATION_TESTS.json`. Instructions AGENTS actualisées.
- Ancienne session et modifications non publiées **non récupérées**.
- **NO-GO économique / INSUFFICIENT DATA**. Plateforme UNKNOWN et divergence supply
  non réconciliée ; aucune vente qualifiée ni nouveau résultat économique.
- Prochaine dépendance : droits/quota gratuit et transport, puis contrôle court
  préenregistré de conservation réelle. Aucune collecte marché ni boucle PAPER
  exécutée ici ; aucun ledger utilisateur, seuil, portefeuille ou dépense modifié.

## Référence historique — v2 exécutée et preuves archivées

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
  [PR #21 fusionnée](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/21).
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
