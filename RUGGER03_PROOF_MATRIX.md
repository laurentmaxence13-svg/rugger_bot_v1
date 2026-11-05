# RUGGER 03 — matrice de preuves (issue #152)

Offline, sans réseau. Preuve : `tests/test_rugger03_evidence_inventory.py` (11 tests, voir #163).

| Objectif | Exigé | Disponible (démontré par archives `evidence/p3`) | Statut |
|---|---|---|---|
| Créateurs indépendants vérifiés | ≥ 50 | 3 créations LaunchLab observées (3 `launch`) | MANQUANT |
| Cycles PAPER BUY/SELL réels | ≥ 20 | 0 ; 7 devis « quoted » non exécutables, 2 devis de vente (1 LaunchLab, 1 sonde USDC) | MANQUANT |
| P&L net (frais, slippage, échecs, latence) | oui | frais réseau/priorité `null` ; temps source des devis inconnu | NON CALCULABLE |
| MASTER vs référence, mêmes observations | oui | aucun moteur « MASTER » dans le code actif ; seuls `paper_engine`/`final_decision_engine` (calibration v2) et mentions dashboard | NON IMPLÉMENTÉ |
| Causes de WAIT | oui | 214 `candidate_decision` : 129 hors périmètre SOL natif, 67 hors échantillon préenregistré, 8 observation seule, 4 sélectionnés, 3 non évalués, 3 sans instruction de création. Ce ne sont pas des WAIT de stratégie. | PARTIEL |
| Migrations LaunchLab→CPMM | oui | aucun événement de migration observé ; 16 devis `unsupported_or_unverified_state` (états migration/limites non gérés par `bot/p3/launchlab.py`) | NON OBSERVÉ |

Nature des données : réelles (lectures publiques archivées, 397 événements, non-rejouables complets) ; historiques (docs, DB PAPER legacy USD non vérifiée) ; synthétiques (benchmarks P2) ; manquantes (ventes, FX horodaté, frais, flux de migration).

**Rentabilité : NON DÉMONTRÉE (INSUFFICIENT DATA).**

## Prochaine mission
Définir et figer (avant résultats) un protocole de capture LaunchLab+CPMM avec : création signée, transactions de migration, pool CPMM, quotes buy/sell horodatés, frais complets ; puis implémenter un moteur MASTER et une référence sur un même journal rejoué.
Alternative gratuite : RPC public Solana en lecture à débit borné + quotes Raydium publiques (déjà utilisés, limités : quota, rétention, pas de replay complet). Abonnement (ex. flux/historique payant) seulement si le quota gratuit empêche d'atteindre 50 créateurs ; coût non estimé ici, à demander au fournisseur — aucune autorisation demandée/utilisée.

## Correctifs #163 (suite à l'audit #160)
- Transactions : **81 enregistrements** (pas 80), **79 signatures uniques** (2 signatures présentes dans deux bundles).
- 397 = enregistrements bruts ; entités : 3 mints `launch`, 135 mints distincts dans 214 `candidate_decision` (+3 décisions sans mint), 79 signatures.
- « 0 cycle » est mesuré sur les devis réels (`quote_side`, `executable_confirmed`) ; absence de migration vérifiée par un test ; contrôles positifs SYNTHÉTIQUES en mémoire uniquement.
