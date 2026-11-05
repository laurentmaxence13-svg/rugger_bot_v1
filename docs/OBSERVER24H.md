# Observer 24 h LaunchLab + CPMM (read-only)

Module : `bot/market/observer24h.py` — tests : `tests/test_observer24h.py` (17, offline).
Aucune signature, aucun `sendTransaction`, aucun import `bot.live`. Méthodes RPC autorisées : `getSignaturesForAddress`, `getTransaction`, `getSlot`.

## Commandes (aucune n'a été exécutée sur le réseau)
Linux / Render (shell) :
- Plan sans I/O : `python -m bot.market.observer24h --mode dry-run`
- Rejeu fixtures : `python -m bot.market.observer24h --mode fixture --fixture-dir tests/fixtures/launchlab_trades --db /tmp/obs.db`
- Live (après audit RUGGER 02 + autorisation propriétaire uniquement) :
  `HELIUS_RPC_URL=<défini hors dépôt> python -m bot.market.observer24h --mode live-readonly --i-understand-this-uses-network --db data/observer24h.db --journal data/observer24h.jsonl --hours 24 --max-requests 20000`

Windows PowerShell : remplacer la ligne d'env par `$env:HELIUS_RPC_URL = "<url>"` puis `python -m bot.market.observer24h ...` (mêmes options).

## Garanties
Durée max 24 h depuis le **premier** démarrage UTC (conservée au redémarrage) ; quota total de requêtes persistant (fail-closed) ; backoff borné ; arrêt par SIGINT/SIGTERM ; événements + curseur dans une seule transaction SQLite (idempotence sur signature, slot, index, pool, kind) ; pas de backfill historique au premier démarrage (gap `start_anchor_no_backfill`) ; slippage inconnu = `NULL`/`unknown`, jamais 0 ; journal expurgé (URL/api-key).

## Limites connues (à auditer)
- Les modules `helius_readonly_rpc.py` et `helius_prospective_campaign.py` n'existent pas dans la branche d'intégration : seuls `bot/market/collector.py` (JsonRpc, Budget) et `launchlab_events.py` sont réutilisés.
- Création / migration / init CPMM : discriminateurs Anchor `sha256("global:<nom>")` **non confirmés sur mainnet** ; ces événements ne sont pas décodés (`decoded=0`, pool `unknown`) et toute migration reste `unproven` tant que les identifiants ne sont pas liés. Aucun événement CPMM de trade n'est décodé.
- `getSignaturesForAddress` d'un programme très actif peut dépasser une page de 1000 : perte possible, tracée dans `gaps` (`page_full_possible_loss`), non comblée.
- Le budget Helius réel (crédits/jour) n'est pas connu du code : `--max-requests` est à fixer par le propriétaire.
- Suite complète non exécutable ici (dépendance `aiohttp` absente) ; seuls les tests ciblés ont tourné.
