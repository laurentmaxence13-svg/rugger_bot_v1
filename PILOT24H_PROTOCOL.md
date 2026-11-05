# Protocole pilote 24h — MASTER vs référence (issue #181)

Statut : **préparation hors ligne**. Aucune collecte lancée, aucun P&L, aucune rentabilité démontrée.

## Observables (cahier des champs, pour RUGGER 01)
Voir `bot.p3.pilot24h.OBSERVABLE_FIELDS` : signature, slot, block_time_utc, received_utc, venue (LAUNCHLAB|CPMM),
event (create|buy|sell|migrate|missed), mint, creator, creator_authenticated, supply_atomic, creation_signature,
migration_signature, side, sol_lamports, token_atomic, failed, et coûts en lamports entiers : network, priority,
pool, protocol, ATA rent, WSOL rent. Coût inconnu = `None` signalé, jamais 0. Pas de float. Dédup par (signature, event, mint).
Latence = received_utc − block_time_utc ; slots et UTC conservés.

## Préenregistrement
Décisions MASTER et référence par observation (action, cause) hachées SHA-256 (`freeze`) **avant** tout résultat ;
mêmes événements pour les deux moteurs ; sortie strictement postérieure à l'entrée (slot SELL > slot BUY), sans survie ni anticipation.
Aucun seuil, critère anti-rug ou TP/SL modifié ; aucun BUY forcé.

## Métriques non vacuantes
Créateurs indépendants authentifiés (≥50), cycles BUY+SELL exécutables, non échoués, tous coûts connus (≥20),
migrations prouvées, WAIT par cause (`wait_by_cause`), événements ratés. Net P&L = vente − achat − tous coûts.
`verdict()` renvoie **INSUFFICIENT DATA** si 0 preuve, provenance non live, <20 cycles ou <50 créateurs ;
sinon EVALUABLE avec estimation ponctuelle seulement (aucun test d'inférence : risque d'inférence signalé).

## Observation 24h
Autorisée seulement après validation audit/runtime/guardrails, Helius lecture seule sur quota gratuit existant.
Non démarrée par cette exécution. Bilan prévu le 08/11 à 12:00 CET, ou BLOCKED motivé.

## Adaptateur offline (issue #195)
`bot/p3/pilot24h_offline.py` : lecture SQLite en lecture seule de la table `events` de l'observateur (#184/#191, non importé, aucun réseau), validation (anti-lookahead recv<chain_time, causalité, slippage jamais 0 par défaut, entiers), mapping vers le vocabulaire du protocole, `check_decisions_causal`, `build_ledger` (refuse si le digest préenregistré ne correspond pas ; net = None si un coût est inconnu) et `recompute_ledger`.
**Constat prouvé par le code** : les lignes de l'observateur ne contiennent ni créateur, ni mint, ni jambe SOL, ni coûts → 0 cycle qualifiable, 0 créateur ; `qualification_report` le dit explicitement.
Moteurs (branche `integration/consolidation-20261103`) : MASTER = `bot/master_decision.py::MasterDecisionOrchestrator` ; référence = `bot/master_comparison.py` (« current_final_decision_engine_and_native_ledger », `bot/p4_experiment.py`). Absents de `main`. Non branchés ici.
