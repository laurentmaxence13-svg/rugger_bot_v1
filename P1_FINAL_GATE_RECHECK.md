# Réexamen des gates P1 / P2 après correctifs scanner et temporels

26 octobre 2026 — PAPER ONLY.
Référence : `1c6175aa33190dc82d442e105e72a77e85a3c78c`.
Branche : `fix/p1-final-scanner-temporal-gates`.
Worktree : `C:\Users\maxen\Downloads\rugger_bot_v1_p16h_workspace`.
Aucun commit, push, fusion, expérience P2 ou collecte de marché.

## Cinq verdicts séparés

| Objet | Verdict | Portée et raison |
|---|---|---|
| B01/B02 — garde et erreurs scanner | **VALIDEE** | Mode intégré supervisé : refus mémoire immédiat avant nettoyage, y compris publication SQL échouée, erreurs internes et transport, annulations et erreurs secondaires conservées. Les tests positifs passent. |
| B03/B04 — intégrité temporelle | **VALIDEE pour les trois voies principales et leurs grilles** | backtest, momentum_backtest et behavior_backtest : groupes signature/timestamp insécables, purge selon disponibilité réelle des labels, minima conservés. Ne concerne pas les voies héritées v25/v26 listées ci-dessous. |
| Clôture globale P1 | **NO-GO** | Des points d'entrée encore présents ne partagent pas toutes ces garanties : validations chronologiques héritées, voie PAPER standalone, dates fallback et sorties de recherche directes. Aucune clôture globale par analogie. |
| P2 synthétique hors réseau, GO global demandé | **NO-GO** | Des routes de recherche appelables continuent à afficher une validation OOS à partir d'un split non sécurisé. Elles ne sont pas corrigées ni formellement exclues du périmètre global. Les tests de cette mission sont des validations P1, pas un démarrage P2. |
| Backtests sur données réelles | **NO-GO** | En plus des routes héritées, provenance historique, disponibilité des prix, biais de sélection, holdout indépendant, coûts et exécutabilité restent non validés. Aucun corpus réel n'a été inspecté. |

Le correctif est terminé dans son périmètre déclaré. Un résultat de test, une
validité de découpage, une qualité de corpus, une couverture de marché et une
rentabilité démontrée ne sont pas interchangeables. Aucun de ces verdicts
n'autorise un ordre réel, une signature ou un portefeuille financé.

## Faits démontrés et reproduits

Contrôles initiaux conformes : racine, branche, HEAD et origin/main au SHA demandé,
origin laurentmaxence13-svg/rugger_bot_v1, inventaire suivi, statut propre ; stdout,
stderr et codes de retour vérifiés. Aucun avertissement ou Permission denied.
Les détails et commandes sont dans
[P1_FINAL_SCANNER_TEMPORAL_FIX.md](P1_FINAL_SCANNER_TEMPORAL_FIX.md).

| Contrôle | État après correction |
|---|---|
| Parent scanner vivant mais enfant en échec | Refus déjà mémorisé ; zéro entrée dans la fenêtre de cleanup. |
| Mise à jour SQLite en échec ou état artificiellement rafraîchi sain | Ne rouvre pas le canal défaillant ; cause de publication conservée. |
| Receiver/worker imbriqués | Panne signalée avant leur nettoyage ; watcher du superviseur réveillé sans attendre leur terminaison. |
| Erreur du flux/transport acquis | Signal synchrone avant fermeture asynchrone ; erreurs de notification chaînées sans remplacer la cause. |
| Reprise | Un nouveau canal + des tâches vivantes ne suffisent pas sans nouvel état SQLite vérifié ; l'ancien contexte reste refusé. |
| Annulations répétées et erreurs multiples | CancelledError reste annulation ; cause initiale et secondaires accessibles ; tous les handles possédés ont une tentative indépendante de sortie. |
| Supervision saine | Autorisation possible après vérification fraîche, entrée de 1 SOL sur 10 SOL conservée. |
| Position déjà ouverte quand un refus est mémorisé | TP/SL continuent ; +0,18/−0,22 SOL et capitaux 10,18/9,78 conservés dans les fixtures. |
| Signature ou timestamp à la frontière train/test | Groupes non séparés, y compris une signature incohérente réapparaissant à une autre date. |
| Labels train futurs | Purge si l'heure réelle de sortie est >= au début brut du test. Aucun transfert des purgés vers test. |
| Retard de prix / premier événement test incomplet | Purge basée sur la cotation effective et la frontière brute inchangée. |
| Tailles minimales | Toujours 30 train / 15 test par défaut, cinq signaux et toutes les règles existantes conservés. Insuffisance après purge → refus. |
| Historique de rendements créateur | Le champ non utilisé par les RULES ne reprend que des résultats déjà clos avant l'entrée observée. Correction temporelle de soutien, sans changement des prédicats. |
| P0 financier, rapports moteur, scanner parsing et exports | Fichiers ou fonctions correspondants inchangés ; régression complète et comparaisons de sorties. |

Le mode explicite sans scanner et la voie CLI PAPER indépendante ne deviennent
pas des consommateurs du canal en mémoire par cette correction. Le canal est
intraprocessus, partagé par la supervision intégrée ; ce n'est pas un verrou global
SQLite ou interprocessus. Leurs limites ne sont pas dissimulées par le verdict B01.

## Audit des autres voies de backtest

Recherche textuelle des partitions train/test et revue ciblée des fonctions
utilisant ces partitions, sur bot/ actif uniquement. Les copies bot/bot, .bak et
.avant_correctif ne sont pas utilisées comme preuves de code actif.

| Voie | Constat | Corrigée ? |
|---|---|---|
| research_pipeline.backtest | Ancienne coupe par nombre d'événements ; labels issus d'une sortie future sans purge | Oui, temporal_partition partagé + heure réelle de sortie |
| research_pipeline.momentum_backtest | Même anomalie ; sortie déjà horodatée dans les observations | Oui |
| behavior_pipeline.behavior_backtest | Même anomalie ; champ de rendement créateur pouvait contenir un résultat encore futur | Oui, découpage et champ causal |
| backtest_grid, momentum_grid, behavior_grid | Appellent les fonctions ci-dessus | Héritent du contrôle ; leur sélection multi-horizons ne devient pas une validation statistique indépendante |
| creator_backtest_v25.run_v25_decision_engine, lignes 2451-2462 au SHA de référence | rows triées sur launch_time puis split=max(4,int(N*.65)), tranches positionnelles ; pas de regroupement ni purge démontrée avant la sélection | **Non** |
| creator_backtest_v26.run_v25_decision_engine, lignes 2456-2467 | Copie active du même schéma de séparation | **Non** |
| creator_backtest_v26.run_v26_launch_selector, lignes 2659-2678 | split=max(5,int(N*.65)), listes d'indices train/test ; aucune obligation de signature/date disjointe ou de label train connu avant le test | **Non** |
| Autres variantes creator_backtest_v6…v24 et variantes suffixées | Pas de garantie de partition causale commune démontrée par cet inventaire ; pas de migration ni audit exhaustif de chaque stratégie historique | Non certifiées |

v25/v26 sont encore appelables par leurs CLI. v26 est documenté dans README.md
et son main appelle les sélecteurs v25 et v26. L'absence d'activation automatique
comme modèle du PAPER intégré ne rend pas leurs déclarations OOS valides.
Les tests v26 existants sont rejoués, mais leur réussite ne corrige pas cette coupe.

Ces fichiers restent IDENTIQUES octet par octet à la référence. Ils ne sont pas
modifiés indirectement par le nouveau helper. Leur causalité doit être corrigée
avec leurs propres identités/labels, ou leur éligibilité doit être explicitement
retirée avant un GO global. Réécrire leurs stratégies ou seuils pour les faire
passer n'était ni nécessaire au pipeline principal ni autorisé par cette mission.

## Défauts résiduels et limites classées

| Priorité / point | Fait et preuve | Effet sur le gate |
|---|---|---|
| Bloquant OOS — routes v25/v26 | Découpes par indices constatées dans les sources actives ci-dessus ; pas de correction appliquée | Empêche la clôture et le GO P2 globaux couvrant ces routes |
| P1 données / B05 | verified_launches garde timestamp=tx.blockTime or saved_time ; une fixture legacy avec blockTime=NULL est exportée datée, alors que la provenance d'entrée la refuse | Toujours reproduit par le test legacy conservé ; pas validation d'un corpus réel |
| P1 lifecycle / B08 | paper_trader.run standalone ouvre une connexion avant sa boucle sans finally explicite de fermeture, contrairement au moteur intégré | Démontré par le code ; non corrigé ici, pas de garantie globale transférée depuis main.run |
| P1 artefacts / B09 | CSV et JSON de certaines CLI de recherche écrits directement, sans remplacement atomique commun | Contenu normal testé, résistance aux interruptions non corrigée ; rapports JSON PAPER restent atomiques et inchangés |
| P2 méthode / B07 | Plusieurs horizons/règles/coûts consultent le même test pour juger une éligibilité ; pas de dernier holdout indépendant démontré | Le nouveau contrôle temporel ne rend pas ces choix statistiquement indépendants |
| P2 unités / B07 | Equity composée du backtest de recherche n'est pas un portefeuille de 10 SOL alloué à 10 % avec positions simultanées | Ne pas présenter selected_max_drawdown/equity_multiple comme un drawdown SOL vérifié |
| Données de marché | Âge fournisseur des prix, exhaustivité des événements, absence non aléatoire de prix, profondeur/slippage/revente/latence et provenance historique non mesurés | NO-GO données réelles ; aucune de ces inconnues n'est remplacée par une métrique de fixture |

B06, le champ de rendement créateur non causal, est corrigé dans behavior_pipeline
pour ne pas laisser un résultat futur dans une observation utilisée à l'entraînement.
Les RULES actuelles ne consommaient pas ce champ ; aucun critère de sélection n'est
ajouté, supprimé ou retouché.

Les lectures de prix historiques supposent que le timestamp transmis décrit la
connaissance disponible à cet instant. Les tests imposent cette convention dans
leurs CSV synthétiques. Ils ne prouvent pas cette disponibilité pour une source
réelle ou pour des données rétroactivement reconstruites.

Une tâche ou une bibliothèque qui refuse de terminer ne peut pas être forcée à
libérer proprement une ressource par cette logique. Le délai d'arrêt de cinq
secondes hérité reste explicite, les erreurs tardives sont observées ; aucun
succès de fermeture n'est inventé. Les tests avec barrières sont coopératifs et
vérifient l'absence de tâches restantes après leur libération. Kill brutal/coupure
électrique et fournisseurs réels restent hors validation.

## Résultats et comparaisons retenus

- Baseline : **535 passed, 1 skipped, 242 subtests passed**, 29,94 s.
- Six caractérisations anciennes : **6 passed**, 0,62 s, défauts de référence.
- Assertions positives sur l'ancienne source : **5 failed, 2 deselected**, 0,53 s.
- Nouvelle sécurité scanner/temps + audit converti : **75 passed**, 1,61 s,
  warnings en erreur.
- Groupe large ciblé : **253 passed, 5 subtests passed**, 12,81 s,
  warnings en erreur.
- Suite finale : **604 passed, 1 skipped, 242 subtests passed**, 32,08 s,
  code 0 et stderr vide.

Le skip « base utilisateur absente » est conservé. Les tests tournent uniquement
sur copies isolées avec réseau externe bloqué et dotenv neutralisé, sans installation.
Les cinq anciennes assertions de défauts sont devenues des propriétés positives,
avec une variante supplémentaire d'échec de publication ; la caractérisation B05
legacy reste explicitement une anomalie, pas une preuve de correction.

Identité exacte des six scénarios PAPER normaux : finances, transactions, TP/SL,
décisions, audits, tables, schémas, JSON et CSV avec leurs octets. Seule la ligne
console contenant le chemin temporaire est exclue de la comparaison console.
SHA256 commun :
`677fe804066dafa634e585419e5dc2d80e3d706debbb711d2cb0e5f23d469f10`.

Trois backtests sur observations suffisamment espacées : résultats et outcomes
identiques après retrait de la seule métadonnée temporal_split, SHA256 :
`eff212635d7bb3bf97def910dac7bf1581b21e3b79519715322ac8960e06c7f6`.
Les seules différences attendues ailleurs proviennent des cohortes groupées/purgées
et des validations temporelles décrites dans le rapport de correctif.

Capital 10 SOL, allocation 10 %, TP/SL/trailing, coûts, scores, limites financières,
parser/détecteur, backfill et exports de données ne sont pas modifiés. Aucun
fichier de base ni historique de trade utilisateur n'est touché.

## Conditions de réexamen des verdicts globaux

1. Corriger les partitions des routes héritées encore éligibles, avec identités
   de transaction et heures de disponibilité de labels, ou les exclure explicitement
   des routes/rapports validés. Le GO global ne doit pas continuer à couvrir une
   route présentant encore les défauts B03/B04.
2. Définir le périmètre d'exécution P2 hors réseau : points d'entrée retenus,
   politique pour la voie standalone, fichiers d'entrée et garanties d'intégrité,
   provenance et traitement des dates inconnues. Résoudre les écarts B05/B08/B09
   correspondants ou les exclure explicitement du périmètre déclaré.
3. Figer un protocole d'expérience synthétique reproductible : générateurs/seeds,
   hypothèses de disponibilité des données, unité de capital/coûts, périodes et
   jeu final indépendant après sélection. Ce n'est pas une autorisation de modifier
   les seuils de stratégie dans la mission actuelle.
4. Rejouer les assertions positives de sécurité, les régressions financières et
   les tests propres à toutes les routes déclarées éligibles. Publier les résultats
   et le rollback, puis réémettre les cinq verdicts sans GO automatique.
5. Pour un GO sur données réelles, ajouter un audit autorisé de snapshots sans
   secrets : provenance, disponibilité des prix, dates, biais/missingness, univers
   étudié et coûts/exécutabilité. Ne jamais assimiler couverture des mints connus
   et couverture du marché ou rentabilité économique.

Ces conditions ne demandent ni réseau réel ni trading réel dans cette mission.
Aucune expérimentation P2 n'est lancée pour compenser un NO-GO.

## Fichiers, traces et rollback

La liste exhaustive est donnée dans P1_FINAL_SCANNER_TEMPORAL_FIX.md : huit fichiers
production (dont deux nouveaux modules), six fichiers de tests (dont deux nouveaux),
et les deux rapports nouveaux. Les anciens rapports et stratégies sont conservés.

Les traces, sources originales/corrigées et comparaisons sont dans :
`C:\Users\maxen\AppData\Local\Temp\rugger_p1final_04fb2cdeb78c4965812c836ec166f0a8`.
Logs finaux : final-suite.stdout.log, final-suite.stderr.log vide, final-suite.exit.txt=0.
Python 3.13.15/Windows est l'environnement réellement exécuté ; la syntaxe des
fichiers modifiés a été analysée en mode Python 3.10 sans prétendre à un test runtime
sur cette version.

Rollback NON exécuté : sauvegarder le diff et les six ajouts ; restaurer les dix
fichiers suivis au SHA 1c6175aa33190dc82d442e105e72a77e85a3c78c avec la commande exacte
du rapport de correctif, puis déplacer hors worktree les deux nouveaux modules,
les deux nouveaux tests et les deux rapports. Aucun git clean, remplacement de
dossier, suppression de base, changement d'ACL ou commit.

Arrêt après correctifs, tests et rapports. Aucun GO global P1/P2 n'est accordé.
