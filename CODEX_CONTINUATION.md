# Rugger Bot V1 — reprise autonome depuis Git

État du 27 octobre 2026, Europe/Paris. Lire `AGENTS.md`, ce fichier puis
`PROJECT_STATUS.md`. Continuer les objectifs accessibles sans relance ; ne jamais
présenter une PR ou un test comme validation économique. Aucune fusion automatique.

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
