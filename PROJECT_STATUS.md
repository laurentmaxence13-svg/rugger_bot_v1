# État du projet — candidat fonctionnel PAPER

## Suite prioritaire — tailles et coûts cohérents après008, 28 octobre2026

Code distant `249c7b6637d7c0cdf980b029474e4b0a576f237c`, arbre testé
`a5a4ccb99119ee38a6604f3f96cb0ba00c40f3ba`, local `6ce9906`.
Premier checkpoint `446d2623`. **1724 passed,1 skipped,242 subtests**,7,56s,
warnings en erreur, stderr0. Lire `POST008_POSITION_SIZES_RESULTS.md`.
Aucune collecte nouvelle, aucun ancien contrôle relancé, PR22 ouverte non fusionnée.

- Modèle P3 achat puis vente du même lot sur le bank après achat, entiers et
  réserves dépensables exacts, frais/bornes/uint64 contrôlés. Sensibilités aux
  achats tiers et ventes de50%/100% du stock préexistant; jamais notre propre lot.
- Huit banks archivés007/008, quatre mints/deux sessions,32cas mathématiques pour
  0,05/0,10/0,25/1SOL. Sixbanks avec identité qualifiée, sans indépendance revendiquée.
  Frictions relatives proches2,484% ou11,169% avant coûts supplémentaires UNKNOWN.
  À1SOL: pertes0,024843751 ou0,111693751SOL. Sous0,001SOL de coûts supposés,
  demande tierce minimale≈0,42SOL/2,10SOL selon la courbe;96seuils vérifiés au
  lamport précédent. Ni prévision de flux, ni fill, ni bénéfice de marché.
- Rapport complet compressé, manifeste et32lignesCSV dans
  `validation/position_size_study/`; résumé, seuils et sources ancrées sous
  `validation/P3_POSITION_*`. Ne pas assimiler8banks à8trades indépendants.
- Cohorte préparée/non exécutée: conserver100lignes, six SOL uniques examinés,
  deux au plus actifs/capacité de Q entier0,10SOL,20appels/60s globaux,15s/slot
  supérieur, créations/coûts/réponses inconnues explicites. Critères publiés avant
  toute collecte future. Application rétrospective008:100lignes gardées, zéro
  sélection;3inactifs et3snapshots manquants. Ne pas relancer ces pools.
- Trois variantes P4 consomment le supplément causal tailles/coûts/sorties.
 24intentions UNKNOWN sur ces données sans features,96associations variante/taille,
  aucun gagnant. Ancien rapport24bras synthétiques octet pour octet préservé.
- P5 raccordé aux vrais callbacks internes RPC/WS existants, horloges civile et
  monotone, panne non réinitialisable, couverture/rapport. Aucun trafic ajouté.
  Endurance interne1000cycles,83h20min virtuelles,1000jambes/doublons,10reprises,
  750refus+10préflights sans preuve source,4021invariants, reliquat0. Aucune
  disponibilité murale24h/24 ni performance de marché certifiée.

**P3 OUVERT,0cycle strictement qualifié, net de marché inconnu.** Manquent preuves
horaires/slots fournisseur, création/identité selon le cas, coûts propres/rent/cash,
sorties futures cohérentes avec notre entrée et corpus indépendant. P4/P5
PARTIELLEMENT VALIDÉS. Les modèles conditionnels ne remplacent pas ces preuves.
Prochaine acquisition: nouveaux cas à circulation/capacité suffisante et métadonnées
source/coûts utiles, protocole figé avant départ; ne pas refaire006/007/008.
Commandes hors réseau et reçus complets dans la livraison. Les titres suivants
conservent l'historique précédent, pas une nouvelle mission de récupération.

## Reprise prioritaire — P3 prospectif, P4 comparatif et P5, 28 octobre 2026

Dernier code distant `1fa75efedf0ee80009d8b5d7dcfbc493e3dd217d`, arbre exact
`31b87a6b2a0d56bf657d88ad9d048605d77eac62`, équivalent local `18e3570`.
**1647 passed, 1 skipped, 242 subtests**,7,04s, warnings en erreur, stderr vide.
Lire `P3_P4_P5_RELEASE_20261028.md`; PR22 ouverte, aucune fusion/transaction/dépense.

- Travail interrompu récupéré, testé et publié `cc38e546` puis `39fe7fd0`.
- Plan008 publié/relu `917a4541` AVANT sa collecte unique.20 appels toutes sources,
  24,825s,3 candidats figés/3 achats indicatifs1SOL/6full+3quarter refusés,0cycle
  qualifié, P&L net inconnu. Les neuf refus INSUFFICIENT_LIQUIDITY sont conservés.
  Journal fermé exporté dans `evidence/p3/prospective_008`,55 événements. Index total
  12bundles/1694événements; anciennes ancres intactes. Preuves publiées `28c3a08d`.
- Replay local et restauration réellement téléchargée depuis ce commit identiques,
  sockets/SQLite/.env interdits:12corps de devis,2banks,6analyses,1référence de frais.
  Les six banks real_a=0 expliquent les refus sans notre achat. Le modèle propre
  buy/reverse donne pertes de courbe0,111693751/0,024843751/0,111693751SOL avant
  coûts additionnels inconnus. Aucun P&L net observé. La plateforme du deuxième
  candidat reste UNKNOWN (seed admin original absent), les deux autres passent.
- P4: `bot experiment` réutilise ledger/inventaire existants pour trois variantes
  figées early_sniping/confirmed_momentum/adaptive_hybrid, décisions as-of, split
  chronologique et exclusion des créateurs communs.24bras synthétiques vérifiés,
  sensibilités frais×1/×2 et délai0/250ms, refus/reliquats explicites. Aucun vainqueur
  ni activation. Le corpus008 manque de features permettant une comparaison réelle.
- P5: `bot operations health|backup|serve`, état en lecture seule, snapshot WAL
  cohérent, garde collect_once, urgence sans bloquer les clôtures, sauvegarde
  committed-only/restauration testée, API limitée127.0.0.1.31tests ciblés. Aucun
  serveur permanent lancé; heartbeats de production et endurance restent ouverts.

**Prochaine action utile**: acquisition admissible des preuves temporelles et des
coûts/bornes propres, puis cohorte prospective préenregistrée ayant une circulation
observée suffisante avant les résultats, avec entrées/sorties liées à chaque lot.
Ne pas relancer008/007/006 ni répéter les mêmes refus sur ces trois pools à vide.
`P3_SOURCE_ACCESS_METHOD.md` décrit les sources légitimes et leurs limites; ne pas
substituer blockTime à l'heure du fournisseur ni meta.fee d'autrui à nos coûts.
L'effet contrefactuel de notre entrée reste séparé des banks futurs observés.
Commandes de replay/comparaison/supervision dans la livraison; aucun réseau implicite.
P3 OUVERT; P4/P5 PARTIELLEMENT VALIDÉS logiciellement, pas économiquement.

## Livraison courante — inventaire économique, 27 octobre 2026

Code `82ce606`, arbre `49d9ca058dce7a6b953b96d997cf20a7bb187735`, local `2edcd43`.
**1 535 tests et 242 sous-tests réussis, 1 ignoré**, warnings en erreur, stderr vide.
Configuration agressive conservée, un seul portefeuille PAPER, aucune dépense.

Inventaire atomique projeté attaché aux positions, jambes partielles entières,
reliquats et frais conservés, pertes partielles incluses dans les contrôles.
Clôture native par simple ratio de prix interdite ; aucun deuxième crédit à la fin.
Reconnexion/doublons/annulation/triggers ignorés/version/survente testés. L'ancien
historique garde ses quantités UNKNOWN. Le reporting distingue P&L SOL natif,
ancien modèle USD/SOL constant et métriques impossibles faute de données.

Nouvelle démo `python -B -m bot economic-demo --output work/atomic-demo-next` :
full +0,199985 SOL ; partiel 40 %/60% après reprise +0,049975 ; refus ouvert sans
réalisation ; SL −0,300015. Ce sont quatre fixtures distinctes, pas un rendement
de stratégie. Comparaison à coûts identiques : ancien/nouveau +0,18 SOL, sans
gain artificiel lié au changement d'hypothèse de frais.

Lecteur de nouvelles quotes connecté au moteur, tailles entières exactes,
plafond propre 20 / 60 s, sans retry/fallback, journal neuf et arrêt premier refus.
Seulement testé hors réseau ; aucune nouvelle collecte ni contrôle répété.
007 déjà conservé fournit Q projeté et deux petites sorties indicatives, mais
aucune demande pour Q entier, aucune horloge/frais complets, zéro cycle qualifié.

Rapport `P3_ATOMIC_INVENTORY_RELEASE.md`, preuves `validation/P3_ATOMIC_*`,
comparaison `validation/P3_MATCHED_INVENTORY_COSTS.json`. P3 non terminé ; prochaine
étape : observation prospective complète avec quantités, source et coûts prouvés.
Préparation P4 documentée, aucune stratégie promue. PR #22 ouverte, non fusionnée.

## Référence précédente — première livraison fonctionnelle

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
- Nouveau contrôle 007 prêt : banques actives, q observé fixe, deux horizons, stock/
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
