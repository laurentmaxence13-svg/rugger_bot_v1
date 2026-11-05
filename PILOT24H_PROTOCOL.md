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
