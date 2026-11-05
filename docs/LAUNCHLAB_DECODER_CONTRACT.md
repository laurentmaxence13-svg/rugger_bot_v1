# Contrat LaunchLab/CPMM decoder + backfill (issue #186) — offline, PAPER

Modules indépendants (aucun fichier de #184 touché) : `bot/market/launchlab_program_decoder.py`, `bot/market/signature_backfill.py`.

## (a) Inventaire — vérifié vs inconnu
| Élément | Valeur | Statut |
|---|---|---|
| Programme LaunchLab | `LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj` | vérifié fixture (8 tx) |
| `buy_exact_in` | `faea0d7bd59c13ec` | vérifié fixture (464541196) |
| `sell_exact_in` | `9527de9bd37c981a` | vérifié fixture (7 tx) |
| Tag événement CPI | `e445a52e51cb9a1d` | vérifié fixture |
| `TradeEvent` | `bddb7fd34ee661ee` | vérifié fixture |
| initialize / initialize_v2 / buy_exact_out / sell_exact_out / migrate_to_amm / migrate_to_cpswap | hash Anchor calculé | **dérivé, NON vérifié** (aucune fixture) → `unproven` |
| Programme CPMM | `CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C` | présent dans le code, **aucune fixture tx** → non vérifié |
| Discriminants CPMM (swap_*, initialize) | hash calculé | **non vérifié** |
| PoolCreateEvent | `97d7e20976a173ae` (hash) | **non vérifié**, non décodé |

Aucune source officielle (IDL) n'a été consultée : réseau interdit. Les noms dérivés restent des hypothèses.

## (d) Liens de cycle de vie
`link_evidence()` : `trade` = proven (fixtures) ; `creation`, `graduation`, `migration`, `cpmm_pool` = **unproven**. Aucun cycle complet n'est affirmé.

## (c) Backfill (`run_backfill`)
`fetch(address, before, until, limit)` injecté (newest-first). Page ≤1000, `max_pages`, curseur `before` sérialisable (`to_dict/from_dict`). Page pleine jusqu'au plafond ⇒ `complete=False`, `gap='page_cap_reached_before_until'` (une page de taille exactement 1000 exige une page suivante vide). Idempotent (clé signature). Ordre (slot, signature) ; `ambiguous_slots()` signale l'ordre intra-slot inconnu. Slot non monotone ⇒ `BackfillError`. Erreurs `err` séparées dans `failed`.

## (e) API pour #184 (après audit)
`decode_instruction(program, bytes) -> Decoded(kind, evidence, name, detail)` ; `classify_transaction(getTransaction) -> [(Decoded, loc, program)]` (levée `EventDecodeError` si structure inexploitable, `[]` si tx échouée) ; `link_evidence`. Les trades complets restent décodés par `launchlab_events.extract_trade_events`.

## Fixtures manquantes
Transactions signées de création, graduation/migration et tout swap CPMM. Tant qu'elles manquent, ces événements restent `unproven`.
