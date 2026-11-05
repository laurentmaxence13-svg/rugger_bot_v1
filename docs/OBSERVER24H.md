# Observer 24 h LaunchLab + CPMM (read-only)

Module : `bot/market/observer24h.py` — tests : `tests/test_observer24h.py` (45, offline).
Aucune signature, aucun `sendTransaction`, aucun import `bot.live`. Méthodes RPC autorisées (liste exacte, testée par AST) : `getSignaturesForAddress`, `getTransaction`. (`getSlot` retiré : inutilisé.)

## Commandes (aucune n'a été exécutée sur le réseau)
Linux / Render (shell) :
- Plan + modèle de couverture, sans I/O : `python -m bot.market.observer24h --mode dry-run`
- Rejeu fixtures : `python -m bot.market.observer24h --mode fixture --fixture-dir tests/fixtures/launchlab_trades --db /tmp/obs.db`
- Live (après audit RUGGER 02 + autorisation propriétaire uniquement) :
  `HELIUS_RPC_URL=<défini hors dépôt> python -m bot.market.observer24h --mode live-readonly --i-understand-this-uses-network --db data/observer24h.db --journal data/observer24h.jsonl --hours 24 --max-requests <quota réel> --poll-interval 20`

Windows PowerShell : `$env:HELIUS_RPC_URL = "<url>"` puis `python -m bot.market.observer24h ...` (mêmes options).
Les valeurs invalides (`--hours 0|nan|>24`, `--max-requests 0`, intervalle négatif) donnent le code retour 2 avec un message, sans traceback. Le mode live refuse (code 2) une cadence qui consomme plus de 50 % du quota rien qu'en requêtes d'en-tête.

## Budget de requêtes (B1)
Chaque **tentative HTTP** (essai initial et chaque retry 429/timeout de `JsonRpc`) est comptée dans `PersistentBudget` et écrite en SQLite **avant** la tentative : un crash ne peut que sur-compter. Jamais remis à zéro au redémarrage. Test : 429×3 + succès = 4.

## Modèle de coût / couverture 24 h (B2)
Coût fixe = 1 `getSignaturesForAddress` par programme (2) par poll. À 2 s : 86 400 requêtes/24 h (quota de 20 000 épuisé en < 6 h). Défaut désormais 20 s : 8 640 requêtes fixes ; le reste (11 360 pour 20 000) est un **pool partagé** entre pages d'énumération supplémentaires, `getTransaction` et retries (~473/h). `--dry-run` affiche `coverage`. Le quota Helius réel n'est **pas connu** : `--max-requests` doit être fixé par le propriétaire ; rien ne prouve que 24 h soient couvrables si le débit des programmes dépasse le pool partagé (alors `pending` grossit, gap `backlog_unprocessed_at_stop`). Retries pires cas non modélisés (jusqu'à ×5 par appel sous 429 continus).

## Énumération, équité, reprise (B3/B4/B5)
- Énumération paginée (`before` + `until=curseur`), signatures stockées dans `pending` ; le curseur n'avance que quand toute la plage jusqu'à l'ancien curseur a été parcourue (reprise possible entre pages après crash). Plus de saut silencieux au-delà de 1000.
- Traitement des transactions en rotation entre programmes (ordre tournant persistant) : un backlog LaunchLab ne peut pas affamer CPMM. Le plafond par poll termine le poll sans erreur.
- `getTransaction` → `None` : 3 tentatives max (une par poll), puis `dead_letter` (table `seen`) + gap explicite `transaction_unavailable_dead_letter` ; aucune donnée inventée, pas de blocage de tête de file. Les `RpcError` ne comptent pas comme tentative (une panne réseau ne dead-letter pas) : arrêt `network_unavailable` après 8 échecs consécutifs.

## Garanties
Durée max 24 h depuis le **premier** démarrage UTC (conservée au redémarrage) ; quota persistant fail-closed ; backoff borné ; arrêt SIGINT/SIGTERM ; chaque transaction traitée = événements + migrations + `seen` + retrait de `pending` en une seule transaction SQLite (rollback testé entre INSERT et COMMIT) ; idempotence sur (signature, slot, index, pool, kind) ; pas de backfill au premier démarrage (gap `start_anchor_no_backfill`) ; slippage inconnu = `NULL`/`unknown`, jamais 0 ; journal expurgé (URL/api-key). Schéma v2 : une base v1 est refusée.

## Migrations (B6/B11)
Clé `migrations` = (signature, instruction_index `oN`/`iM.N`, launchlab_pool). Statut **toujours `unproven`** (`DISCRIMINATORS_CONFIRMED = False`), `evidence` = `no_cpmm_init_in_same_tx` ou `cpmm_init_same_tx_ids_unconfirmed`. Aucun lien LaunchLab→CPMM n'est affirmé. Note : `initialize` Anchor est le même discriminateur pour LaunchLab-create et CPMM-init (distingués seulement par le programme).

## Limites connues
- Supprimer la base SQLite remet à zéro fenêtre 24 h **et** quota (aucune protection côté code) : ne jamais supprimer `observer24h.db` en cours de campagne.
- `MAX_TX_VERSION = 1` (valeur de `collector.py`) n'est pas démontré contre le RPC cible.
- Discriminateurs create/migrate/CPMM non confirmés sur mainnet ; aucun trade CPMM décodé (seuls les `init` bruts sont enregistrés). Aucune couverture CPMM qualifiée sans signatures mainnet et décodage vérifié.
- Les modules `helius_readonly_rpc.py` et `helius_prospective_campaign.py` n'existent pas dans la branche d'intégration.
- Suite complète non exécutable ici (`aiohttp` absent) ; tests ciblés seulement.
