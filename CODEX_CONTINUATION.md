# Rugger Bot V1 — reprise autonome depuis Git

État du 28 octobre 2026, Europe/Paris. Lire `AGENTS.md`, ce fichier puis
`PROJECT_STATUS.md`. Continuer les objectifs accessibles sans relance ; ne jamais
présenter une PR ou un test comme validation économique. Aucune fusion automatique.

## Suite prioritaire — tailles et coûts cohérents après008, 28 octobre2026

Code distant `249c7b6637d7c0cdf980b029474e4b0a576f237c`, arbre testé
`a5a4ccb99119ee38a6604f3f96cb0ba00c40f3ba`, local `6ce9906`.
Premier checkpoint `446d2623`. Preuves publiées `12e164fb`, quatre artefacts
retéléchargés puis rapport558754octets/32lignesCSV reproduits à l’identique.
Reçu `validation/POSITION_SIZE_REMOTE_RESTORE.json`. **1724 passed,1 skipped,242 subtests**,7,56s,
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

## Reprise courante — inventaire atomique intégré

Mandat économique appliqué, sans refaire l'ancienne démo ni contrôle réseau.
Lire `P3_ATOMIC_INVENTORY_RELEASE.md` et
`validation/P3_ATOMIC_INVENTORY_VALIDATION.json`.

Preuves et reprise publiées `f29d39ee9612422f5695c9ae35fda255bbdebc3d` ; trois
artefacts retéléchargés depuis cette référence puis neuf quotes/quatre jambes/
quatre cas rapprochés sans DB ni réseau pendant replay. Reçu conservé dans
`validation/P3_ATOMIC_INVENTORY_REMOTE_RESTORE.json`.

- Code distant `82ce606ef0952154efb0d964e8cfea7befc20c37`, arbre validé
  `49d9ca058dce7a6b953b96d997cf20a7bb187735`, équivalent local `2edcd43`.
  **1 535 passed, 1 skipped, 242 subtests**, 5,88 s, warnings en erreur, stderr vide.
- Tables natives dans la même base PAPER et un seul portefeuille. Quantités,
  basis et jambes en entiers TEXT ; capital historique SOL rapproché des jambes.
  Réalisation partielle créditée une fois, perte journalière et drawdown inclus,
  coût restant réservé, agrégat final exclu du second crédit. Historiques UNKNOWN
  non reconstruits. Frais inconnus bloquent le cash libre et les nouvelles entrées.
- `economic-demo` exécute le vrai `collect_once/record_quote` : full TP,
  partiel 40 %/reconnexion/doublon ignoré / 60 %, refus de liquidité, SL. Nets simulés
  respectifs +0,199985 / +0,049975 / 0 réalisé avec position ouverte / −0,300015 SOL.
  Fixtures indépendantes, pas des statistiques de stratégie. Frais synthétiques
  explicites, pas des coûts mesurés. À coût identique 200 bps, ancien/nouveau
  calcul donnent tous deux +0,18 SOL : aucune amélioration de rentabilité déduite.
- Bridge P3 étendu pour conserver les lots projetés et qualifier les jambes.
  Replay désormais synchrone, utilisable dans la boucle async. Version, q exacte,
  actualInput, source, chronologie et disponibilité contrôlés. Ancien devis,
  survente, double crédit, annulation, savepoint et uint64 testés.
- Lecteur `NativeInventoryQuoteProvider` branché à `paper --inventory-quotes`
  avec journal neuf et session 1..60 s, plafond propre 20 quotes / 60 s et arrêt premier
  refus/erreur. Aucun appel réel exécuté dans cette session. Ne pas l'activer
  sans nouveau protocole d'observation borné ; les autres flux scanner/prix ont
  leurs propres ressources. Heures/frais/décimales absents ne sont pas inventés.
- Évaluation007 existant : Q projeté 34076309234009, q indicatif 18765447579,
  deux petites quotes disponibles ; aucune demande pour Q entier, disponibilité
  complète inconnue, source et frais inconnus, zéro règlement et zéro cycle qualifié.
  Aucun ancien contrôle répété, aucune donnée/fill/performance reconstituée.

Commandes nouvelles hors réseau :

```sh
python -B -m bot economic-demo --output work/atomic-demo-next
python -B tools/compare_native_inventory_costs.py
python -B tools/evaluate_atomic_market.py
```

**Prochaine étape utile** : protocole prospectif borné à quantité complète,
preuve d'horloge/slot source et de frais additionnels, effet propre de l'entrée
séparé des banques réellement observées. Ne pas coder des frais zéro pour faire
passer une sortie. Les contrôles 006/007 sont terminés ; ne pas les relancer.
P3 reste ouvert. `P4_ATOMIC_COMPARISON_PROTOCOL.md` prépare premier signal /
confirmation, sans tuning ni nouvelle collecte. PR #22 ouverte, non fusionnée.
Les paragraphes suivants sont les références précédentes.

## Référence précédente — candidat fonctionnel PAPER exécuté

Mandat de finalisation appliqué. Ne pas recommencer la récupération de session,
les anciens burns ou la baseline. Livraison : `RUGGER_V1_FUNCTIONAL_RELEASE.md`.

- Code distant `f50d226b9f437e9d0e3bccb171671f450fb7bd23`, arbre testé
  `c343ad51f418c04e2d18e8d050877996e585a0f4`, équivalent local `4da94d3`.
  **1 435 passed / 1 skipped / 242 subtests**, 5,31 s, warnings en erreur, stderr vide.
- Point d'entrée unique `python -B -m bot` : `demo`, `report`, `paper`.
  Démo exécutée dans un dossier neuf sans `.env`/réseau. Le vrai parseur,
  recovery/backfill, garde scanner, scoring et ledger réalisent entry/follow/TP.
  Reconnexion SQLite et reçu persisté vérifiés ; capital modèle10 → 10,18 SOL.
  Aucun inventaire atomique ni rendement de marché revendiqué.
- Coût de clôture persisté atomiquement avec le P&L, au lieu du coût d'entrée
  périmé. Régression200 → 1 000 bps : coût0,02 → 0,10 SOL correctement rapporté,
  brut reconstruit0,12 → 0,20 ; net0,10 SOL inchangé. Rollback/reconnexion testés.
- Dashboard branché au moteur ; reporter autonome en lecture seule, provenance,
  fiabilité, coûts pondérés, réservations, manques et latences bornées.
- Contrôle RPC public préenregistré `ce70a4b`,1 lecture / 1 087 ms / HTTP200 ; contrôle 007
  ensuite exécuté selon son plan source fb8584d,12 lectures / 19 871 ms. Deux cotations
  de vente q=18 765 447 579 à 519 914 lamports ; quatre corps rejoués, deux snapshots
  aux slots 462210629 / 462210706. Supply et PDA complètes pour ce nouveau cas.
  Q ne couvre que 0,05507 % de l'achat indépendant de 1 SOL. Création non trouvée,
  frais additionnels et heures source absents, aucun cycle économique qualifié.
- Preuves publiées `8aeb6c83ac10d73ba4901b287bf776bd729d879a` :11 bundles,
  1 639 événements. Deux bundles retéléchargés effectivement du GitHub privé,
  1 034 événements vérifiés et analyse identique sans DB/réseau pendant replay.
  Aucun SQLite utilisateur exporté, aucun ordre, signature ou dépense.
- Lire les JSON `validation/RUGGER_FUNCTIONAL_*` et `P3_ACTIVE_EXIT_007*`.
  Les sept anciennes paires restent inchangées : six LaunchLab + une référence,
  zéro cycle qualifié. Ne pas en faire sept trades indépendants.

Commandes hors réseau (nouveau dossier pour la démo) :

```sh
python -B -m bot demo --output work/demo-next
python -B -m bot report --db work/demo-next/paper.sqlite --output work/demo-next/dashboard.json --data-kind synthetic
python -B tools/analyze_p3_active_exit_007.py
python -B tools/evaluate_functional_market.py
```

**Prochaine action technique** : relier une entrée simulée à une quantité token
atomique persistée, puis brancher le bridge de qualification sur la même quantité
de sortie. Séparer état observé et effet contrefactuel de notre entrée. Ne pas
relâcher les gardes source/quantité/chronologie/frais ni changer les paramètres
sur cette fixture. Les 12 signatures anciennes restent listées sans priorité
sur ce travail d'intégration. Ne pas répéter les contrôles live terminés ; nouveau
protocole borné et chemins neufs avant toute autre collecte. PR #22 non fusionnée.
Les paragraphes suivants décrivent les phases antérieures.

## Référence antérieure après contrôle006

Reprise depuis la branche existante, sans répéter récupération ou baseline.
Code publié `fb8584dcf4c0fbbcd7c936169b4f7d7301821098`, arbre testé
`b049d1ef153287bd9d9cd78c52e583e79e3bcf54`, équivalent local `d87e8e8`.
**1 415 passed, 1 skipped, 242 subtests passed**, warnings en erreur et stderr vide.
Rapport actuel : `P3_CONTINUATION_006_RESULTS.md` et
`validation/PR22_CONTINUATION_006_VALIDATION.json`.

- Contrôle006 préenregistré distant `57eef76`, exécuté une fois : 11 tentatives,
  6,216s, dix nouveaux corps. Dernier appel HTTP429, arrêt avant second sous-lot.
- Trois burns prouvés totalisent **513119481705** unités ; résiduel réduit à
  **466423024095**. Autre transaction au slot création récupérée (index91>50),
  bilan nul. **23 corps sur35, 12 manquants**, liste exacte conservée.
- 25 événements006 exportés puis fichiers récupérés effectivement depuis GitHub
  dans un répertoire neuf ; qualification reproduite sans DB source. Total
  **9 bundles / 605 événements**, anciennes ancres conservées.
- Correction causale RPC : Retry-After retenu exactement (entier ou date HTTP),
  référence inconnue explicite. Aucun sommeil/retry/fallback automatique. Le reçu
  réel006 ne contenait pas ces champs : son délai ne peut pas être reconstitué.
- Nouveau bridge `bot/p3/exit_qualification.py` : taille attendue/minimale, quantité
  effectivement annoncée par la quote, chronologie, corps/provenance et frais.
  Pas de clôture totale sur quantité partielle ou ajustée, pas de scaling fictif.
- Nouveau `bot/p3/active_exit_campaign.py` et plan007 versionné : screening groupé,
  q=floor(real_a/100) fixé avant quotes et indépendant du buy1SOL, vérification de
  vente observée avant chaque quote, suivi à slot strictement supérieur. Aucune
  admission si identité incomplète. Ce protocole est **TESTÉ SYNTHÉTIQUEMENT et
  NON EXÉCUTÉ** après le429 ; il ne change pas la stratégie active.
- Sept couples historiques passés au bridge : cinq corps manquants, deux heures
  source inconnues. Zéro clôture vérifiée et P&L inconnu, sans réécriture du ledger.

**Prochaine action** : après rétablissement établi du quota, re-préenregistrer les
12 signatures restantes depuis P3_MINT_HISTORY_006_REMAINING.json, sans répéter
les corps déjà conservés, avec cadence historique préfixée plus basse (par exemple
5 getTransaction au plus par10s, sans supposer un quota réservé), puis contrôle 007 depuis son code/plan figés et nouveaux
chemins. Le plan007 n'est pas une preuve d'exécution. Ne pas alterner d'endpoint
pour esquiver le429 ni engager de dépense. Plateforme, frais complets, fraîcheur
fournisseur et corpus indépendant restent non certifiés ; NO-GO économique.
Les anciens paragraphes ci-dessous sont des références datées, non l'état actuel.

## Autorisations et protections

Corrections, recherches techniques, tests isolés, replays, simulations PAPER,
branches/commits/PR et contrôles courts gratuits préenregistrés sont autorisés.
Aucun ordre, signature/envoi blockchain, portefeuille financé, passage au réel,
dépense, secret `.env`, export de DB privée ou modification du ledger utilisateur.
Aucune campagne prolongée, souscription ou augmentation payante. Capital configuré
conservé (historiquement 10 SOL). Aucun changement de seuil pour rendre un résultat
positif. Données de validation indépendantes ; inconnus jamais remplacés par zéro.

## Git et références validées

- Dernier main fusionné vérifié : #21 `7ddddb9f73339242fbcb5b9bf10fa329c82fa700`.
- [PR #22](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/22) ouverte,
  non fusionnée, branche `fix/p3-exit-evidence-continuation`.
- Code final validé : `e2e200889da3deaf4117ceb60109a46469c385da`, arbre
  `fbcd7ff26d09734e5e8eec558ffcf554c418757c`, équivalent local `55d58f1`.
  **1 379 passed, 1 skipped, 242 subtests passed**, warnings en erreur, stderr vide.
- Code du contrôle réel : `455defdbe6ec388e245e188476716452b82a47c6`, arbre testé
  `294289227071b849133e476446152c5772bbec5b`. Commit local équivalent `06a7755`.
- Préenregistrement distant **avant appel** : `4436f04315f1c9ab130c0a0c8617fb6c76a1a8e5`,
  plan `benchmarks/p3_retention_control_v3/plan.json`, SHA256 canonique
  `6a1fcd9fda45c7bafa38c1367703e81797d6dceaca77c7225f5eaea612fa8d28`.
- Preuves réelles publiées : `b0eef8e464c3dfec1c28cd998b41bd3d66d0dad2`.
  Les documents de résultat/reprise suivent ce commit. Ne pas rejouer le plan live.
- Publication via connecteur GitHub : commits locaux/distants différents mais
  arbres comparés identiques. L'ancienne référence locale origin/main est périmée.
- Nouveau lien propriétaire : https://chatgpt.com/s/cx_6ae0e7ea3e348191b141166aafd561d9.
  Contenu partagé récupéré effectivement : **Configurer rugger_bot_v1**, 10 tours,
  8 messages propriétaire, 48 messages agent et 51 événements fileChange.
  Copie exacte 239430 octets : `history/CONFIGURER_RUGGER_BOT_V1_SHARED_SNAPSHOT.json`,
  manifeste SHA256 `history/RECOVERY_MANIFEST.json`, transcription Markdown à côté.
  Derniers diffs non publiés retrouvés : P3_PR21_REVIEW.md et collect.py.
  VM Cloud non restaurée, tâche originale non désarchivée ; exhaustivité du partage
  par rapport à toute la session originale inconnue. Ne pas confondre ces états.

## Capacités et validation

Corrections initiales #22 : quote rejetée sans montants utilisables ; annulation
achat/vente persistée ; métadonnées des corps refusés conservées ; diagnostic
supply visible avant blocage. Compléments : corps JSON d'erreurs HTTP bornés à
65 536 octets, statut HTTP conservé même si lecture annulée, replay sémantique des
devis, profil de snapshot enregistré, successeur v3 avec arrêt après erreur et
délai monotone. Le patch non publié retrouvé de collect.py a été complété :
sélection explicite de l'endpoint public canonique ou de l'alias historique,
transport cohérent et reçu endpoint_kind. Défaut historique préservé ; aucune
bascule automatique ni retry après refus. Ce complément est testé synthétiquement,
non essayé sur le réseau. Les anciens protocoles n'ont pas été changés.
Aucun garde d'identité/supply/finances relâché.

Validation avant contrôles réels sur copie isolée : **1 366 passed, 1 skipped,
242 subtests passed**, warnings en erreur, stderr vide, Python 3.12.14/pytest 9.1.1.
Le skip concerne la base utilisateur volontairement absente. Baseline précédente
1 348/1/242 historique distincte. Revues ciblées indépendantes effectuées ; un
arrêt manquant après erreur quote détecté et corrigé avant le contrôle réel.
Oracle comptable précédent 1 000 cas synthétiques ; oracle nouveau de quatre
projections réelles par invariant rationnel indépendant (aucune exécution).

## Observation réelle de conservation v3 — terminée

**19 tentatives / 26,034 s**, 100 lignes reçues, 2 candidats, 2 créations vérifiées,
4 snapshots cohérents. Deux achats indicatifs à 1 SOL et deux refus de vente
**HTTP200 / INSUFFICIENT_LIQUIDITY**, corps conservés. Aucun montant/slippage
adapté à la réponse. 152 événements nouveaux, export fermé sans SQLite.

Bundle `evidence/p3/retention_003`, ancre
`914901e885fa97c87e7e81f0bd2750d0092a4cfb7a12f709c5402c993ed75fce`.
Récupération effective des deux blobs depuis GitHub dans un répertoire neuf :
152 événements, quatre analyses et quatre normalisations quote reproduits, avec
accès DB et réseau interdits pendant replay. Total après investigations historiques : **8 archives / 580 événements**,
8 analyses de snapshots reproduites ; dix anciens corps restent manquants.

Qualification : conservation instrumentale **OBSERVÉE EN RÉEL puis VALIDÉE SUR REPLAY**.
Gardes HTTP/annulation **TESTÉES SYNTHÉTIQUEMENT** ; fonctionnement PAPER continu,
inventaire acquis, fills, frais complets et rentabilité **NON VALIDÉS**.

## Conclusion économique et investigations

**NO-GO / INSUFFICIENT DATA.** Les banques observées ont real_a=0 et seulement
0 ou 1 lamport disponible après retrait des frais accumulés. Un refus de vente
contre ces banques ne démontre pas l'impossibilité après notre achat hypothétique.
Après sa propre entrée de 1 SOL, le modèle conditionnel sans autre activité donne
975156249 lamports, soit un écart de 24843751 avant coûts additionnels. Ce n'est
ni un devis futur ni un P&L réalisé. Timestamp/slot fournisseur inconnus ; égalité
du calcul d'achat et du devis ne prouve pas l'identité des banques source.

Ancien BNbNt : mintTo 1e15 puis autorité mint révoquée prouvés à la création ;
différence ultérieure -979542505800. Contrôle 004 : page mint de 37 signatures,
7 transactions fixées, 8 requêtes / 4,695 s. Contrôle 005 : 5 références mint seules
fixées avant lecture, 5 requêtes / 3,852 s. Deux burns réels confirmés aussi par
les soldes de comptes : 14960820821 + 14425454354 = 29386275175 unités.
**Reste 950156230625 non expliqué**, 21 autres corps éligibles et une transaction
au slot de création manquent encore. Garde strict maintenu. Les trois contrôles
sont terminés ; aucun budget de marché supplémentaire dans cette session. Ancienne plateforme StonkFun : aucune seed admin
prouvée dans les 542 adresses archivées ; UNKNOWN maintenu, aucun garde contourné.
Détails : `P3_IDENTITY_SUPPLY_INVESTIGATION.md`, `P3_RETENTION_EXIT_RESULTS.md`,
`P3_MINT_HISTORY_004_RESULTS.md` et `P3_MINT_HISTORY_005_RESULTS.md`.

## Commandes de reprise hors réseau

Utiliser un Python avec requirements.txt et pytest ; aucun secret nécessaire.

```sh
git status --short
git log -4 --oneline
python -B tools/offline_check.py
python -B tools/verify_p3_evidence.py
python -B tools/analyze_p3_retention_exits.py
python -B tools/verify_p3_accounting.py
python -B tools/verify_p3_historical_burns.py
python -B tools/verify_p3_history_006.py
python -B tools/qualify_p3_quote_pairs.py
```

Ici : `/workspace/.cloud-env/rugger_bot_v1/venv/bin/python`.
Résultats : `validation/P3_RETENTION_CONTROL_RESULT.json`,
`P3_RETENTION_REMOTE_RESTORE.json`, `P3_RETENTION_ALL_REPLAY.json`,
`P3_RETENTION_EXIT_ANALYSIS.json`, `P3_V3_TESTS.json`,
`P3_MINT_HISTORY_004.json`, `P3_MINT_HISTORY_005_QUALIFICATION.json`,
`PR22_FINAL_VALIDATION.json`.
Les rapports de la première livraison sont conservés comme historiques.

## Orientation stratégique actuelle

Le nouveau mandat conserve une orientation **agressive**, précoce et rapide.
Ne pas réduire arbitrairement l'agressivité ni retoucher les seuils sans comparaison
crédible. Les protections, coûts et sorties doivent rester qualifiés. Paramètres
historiques effectifs et hypothèses récupérés : `AGGRESSIVE_STRATEGY_CONTEXT.md`.
FomoIsBack n'est qu'une piste citée ; aucune stratégie privée/performance démontrée
retrouvée. Le meilleur résultat P2 synthétique négatif ne justifie aucun changement
de configuration active. Le capital réel reste interdit sans autorisation distincte.

## Suite et limites

Les conditions API publiques et le transport ont été vérifiés pour le contrôle
court, voir `P3_SHORT_CONTROL_ACCESS.md` ; ne plus présenter l'absence d'une licence
explicite comme une interdiction démontrée de replay interne minimal. Aucun droit
de redistribution générale ou de collecte prolongée n'en est déduit.

Ne pas répéter une découverte de banques vides pour gonfler le corpus. Expériences
utiles : historique borné du mint ancien pour un burn exact ; preuve admin par
création de plateforme ; pool aux identités qualifiées et net vendu/réserves
positifs pour vente indicative à quantité préenregistrée. Pas de nouvelle stratégie
ou optimisation avant données économiquement interprétables. Les règles complètes,
coûts et couverture indépendante restent à établir. Mettre la reprise à jour après
chaque livraison. Aucune tâche de fond ne continue après la fin de session.
