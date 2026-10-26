# Validation cloud P1 et accès au protocole synthétique

26 octobre 2026. Branche : `fix/p1-research-gates-and-synthetic-protocol`.
Référence publiée récupérée : `56294b4795390db14b1bc46205ab382eb4ac0f5d`.
Protocole expérimental figé avant expérience : `8530f2b982e657fe7cb3fe82c3d0ad5028edeffd`.

## Verdicts et périmètre

| Objet | Décision et portée |
|---|---|
| B01–B04 publiés | VALIDÉS dans leur périmètre synthétique ; référence 604/1/242 reproduite, revue positive scanner et temporalité. |
| Support P1 nécessaire à P2 synthétique | GO : supervision intégrée, ledger sous convention de simulation, exports de recherche retenus et helper de partition ; régressions complètes vertes. |
| v25/v26 | EXCLUS par code et métadonnées, même si diagnostics positifs. Leurs stratégies et partitions historiques ne deviennent pas causales. |
| P1 global couvrant tous les CLI et données réelles | NON CERTIFIÉ. Aucune garantie transférée aux variantes historiques ni à l'exécution de marché. |
| P2 synthétique v1 | GO limité au nouvel évaluateur natif SOL et au protocole préenregistré. Ce GO permet les trois expériences décrites, pas une qualification de stratégie de marché. |
| Backtests économiques sur données réelles / P3 | NO-GO : provenance, devises, exécutabilité, échantillon et coûts observés manquants. |
| Viabilité économique | INSUFFICIENT DATA ; aucune recommandation de trading réel. |

Le GO limité respecte les exclusions explicites prévues dans le réexamen précédent.
Le collecteur PAPER standalone, les grilles historiques à deux périodes et les
variantes v6…v26 ne servent pas d'évaluateurs économiques dans P2 v1. La garde
mémoire scanner est intraprocessus ; elle n'est pas une permission interprocessus.

## Corrections et preuves

| Sujet | Résultat vérifiable |
|---|---|
| B01 / B03 / B04 | Pas de réécriture. Verrou scanner, groupes transaction/timestamp et purge des labels revus et rejoués. Le helper temporel est identique à la référence publiée. |
| B02 complément transport | L'erreur du corps, de fermeture et de notification restent diagnostiquables ; fermeture protégée et arrêt explicite du générateur sans reconnexion. Neuf nouveaux cas échouaient avant correction. |
| B02 complément annulation | Une CancelledError levée par une ressource ne remplace plus l'erreur initiale. Le compteur de l'appelant distingue une véritable annulation pendant le nettoyage. Cinq cas supplémentaires échouaient avant correction ; l'annulation de l'appelant reste propagée. |
| B05 dates | Seul blockTime brut entier, positif et non futur date un événement de recherche. La date sauvegardée ne répare jamais un timestamp inconnu ; cache conservé intact. |
| v25/v26 | Les trois sélecteurs publient validated=false, model_eligible=false et eligible_for_p2=false sur tous les chemins. Aucun paper_candidate ni affirmation de validation OOS ; les calculs exploratoires restent disponibles. |
| B08 standalone | Fermetures HTTP et SQLite indépendantes, acquisitions partielles et erreurs multiples préservées. Douze cas échouaient initialement ; 17 cas lifecycle passent après correction partagée. La garde scanner ne lui est pas ajoutée par analogie. |
| B09 artefacts | CSV dataset/prices/historical-prices et JSON de research_pipeline publiés par remplacement atomique mono-fichier après flush/fsync. Échec d'écriture, de synchronisation et de remplacement conserve l'ancienne sortie. |
| Motifs de session | _session_summary lit risk_flags_json pour les refus, au lieu de compter des bonus positifs dans reasons_json. Un test reproduisait exactement la mauvaise attribution avant correction. |
| Unités économiques | valuation_scope rend explicites le change SOL/USD constant, l'absence de FX aux fills et l'absence de P&L/exécution économiquement vérifiés. Aucun ancien trade n'est converti ou réécrit. |

Les frais, scores, seuils, TP/SL/trailing, capital initial et allocations de production
ne sont pas modifiés. Comparaison AST identique pour record_quote/_record_quote,
model_risk, entry_allowed, paper_capital, ensure_paper_portfolio, collect_once,
_realized_metrics, run et run_with_scanner. Les fichiers de stratégie, courbe
LaunchLab, parser, détecteur, backfill, schéma de base et temporal_partition sont
identiques octet par octet à 56294b4.

## Validation exécutée

Linux x86_64, Python 3.12.14, pytest 9.1.1. Aucune exécution Windows/Python 3.13
supplémentaire n'est revendiquée. Copies temporaires sans Git, dotenv neutralisé,
réseau externe interdit par le harness existant, plugins automatiques et caches
désactivés. Aucun secret, corpus ou base utilisateur utilisé.

- Référence publiée : **604 passed, 1 skipped, 242 subtests passed**.
- Suite finale : **699 passed, 1 skipped, 242 subtests passed**, code 0,
  warnings en erreur, stderr vide.
- Groupe supervision/transport/standalone/nettoyage : **160 passed,
  5 subtests passed**, warnings en erreur.
- Protocole synthétique : **20 tests unitaires réussis** ; leur exécution est
  une vérification du logiciel, distincte des trois expériences préenregistrées.
- Seul skip : test historique `tests/test_research_pipeline.py:17`,
  « base utilisateur absente ».
- `git diff --check` passe.

Commande cloud exécutée :

```sh
/workspace/.cloud-env/rugger_bot_v1/venv/bin/python -B /workspace/.cloud-env/rugger_bot_v1/check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Le helper copie les sources et fixtures courantes puis appelle
`tests/p16h_isolated_runner.py`. Hors de cet environnement, créer une copie
jetable de `bot/` et `tests/` sans .git, .env ou données utilisateur, y lancer :

```sh
python -B tests/p16h_isolated_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Ne pas lancer pytest sans cible : un ancien outil Birdeye placé sous bot/ effectue
un appel réseau à l'import. Les copies historiques tests/tests sont exclues.

## Comparaison des six sessions PAPER

Vide, TP, SL, refus, garde fermée et lancement non daté ont été exécutés sur les
sources 56294b4 puis les sources corrigées, avec services/horloge synthétiques.
Tables, schémas, finances, décisions et octets des CSV sont identiques.
TP conserve +0,18 et 10,18 SOL de simulation ; SL −0,22 et 9,78 SOL.

Deux changements JSON sont intentionnels : ajout de valuation_scope aux rapports
périodique/session, et motifs de refus de session pris dans les risk flags.
La ligne console Top rejets change en conséquence ; les autres sorties sont
identiques. Il ne s'agit donc pas d'une identité brute des JSON.

Hash SHA256 de la comparaison normalisée :
`a8143f62948a4c30752d32e41ed21c27f95e7209fb7612330fb4f1626dc890d5`.
Preuve concise versionnée dans `validation/P1_CLOUD_RESULTS.json`.
Les logs et artefacts synthétiques complets de l'instance sont sous
`/workspace/.cloud-env/rugger_bot_v1/validation/`.

## Limites et retour arrière

Le remplacement atomique est mono-fichier ; aucune transaction multi-fichier ni
durabilité d'entrée de répertoire après coupure électrique n'est certifiée.
Les anciens CLI hors research_pipeline ne reçoivent pas cette garantie.
Les prix indicatifs, funding, permissions/holders partiels et métriques réalisées
ne démontrent pas liquidité de sortie, stop garanti, risque latent ou rendement SOL
exécutable. Voir ECONOMIC_VIABILITY_AUDIT.md.

Les corrections sont livrées sur une branche séparée, sans réinitialisation ni
suppression de données. Retour arrière par revert des commits de livraison,
après identification du commit dans git log ; 56294b4 reste la référence conservée.
Aucun reset, force push, nettoyage de données ou changement de portefeuille requis.
