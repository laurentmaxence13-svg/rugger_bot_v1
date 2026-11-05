# Compatibilité offline #184+#191 × #189 × PaperLedger (issue #202)

Preuve : `tests/test_integration_collector_decoder_ledger.py` (offline, fixtures signées réelles `tests/fixtures/launchlab_trades`, aucune fusion de PR existante). Aucune mainnet, aucun secret, aucun ordre.

Branche de test = `#191` (head `bdea6d9`, empilée sur `#184` `2a00b03`) + merge de `#189` (head `0998090`). Fusion sans conflit (fichiers disjoints).

## Matrice
| Chaîne | Résultat | Preuve |
|---|---|---|
| Événement signé → décodeur #189 → collecteur #184/#191 : mêmes trades, même côté | OK (7/7 tx) | test 1 |
| Stockage idempotent, cursor, checkpoint, redémarrage sans doublon ni refetch | OK | test 1 |
| Deux paginations (observateur `until/before` vs `run_backfill`) : mêmes 7 signatures, sans doublon | OK | test 2 |
| Plafond de pages backfill = gap, jamais « complete » | OK | test 3 |
| No-lookahead : `recv < blockTime` ⇒ `violation_recv_before_chain`, rejeté par l'adaptateur | OK | test 4 |
| `blockTime=None` ⇒ `chain_time_unknown` ; `getTransaction=None` ⇒ retry puis dead-letter + gaps | OK | test 5 |
| Quota total persistant et non réinitialisable au redémarrage ; méthodes hors allowlist refusées | OK | test 6 |
| Création / migration / CPMM : `unproven` des deux côtés, pool `unknown` | OK (instructions **synthétiques**, pas de tx réelle) | test 7 |
| Contrat ledger : écart explicite | voir ci-dessous | test 8 |

## Différences de pagination (à connaître)
- Observateur : `until=cursor`, page 1000, max 3 pages/poll ; le cursor n'avance qu'une fois la plage entièrement parcourue (vérifié : avec PAGE=2, 6 sig. au 1er poll, cursor inchangé, la 7e au 2e poll). Ignore les tx `err`.
- Backfill : `before` seul, `max_pages` configurable, gap si plafond atteint, tx `err` séparées, abandon si slot non monotone. L'observateur n'a pas ce contrôle de monotonie.
- Risque de doublon si les deux écrivent : clés différentes (`seen`/`pending` vs `BackfillState.seen`) → **ne pas brancher les deux sur la même table sans clé commune** (signature) ; non fait ici.

## Champs manquants (rien n'est inventé)
| Champ | État |
|---|---|
| mint | **absent** de `TradeEvent` et de la table `events` (colonnes pool/kind/payload uniquement) |
| créateur | **absent** (seul `creator_fee` montant et `fee_payer` = clé 0, ≠ créateur prouvé) |
| jambe SOL | quote token/mint **non identifié** dans l'événement ; `amount_in/out` en unités atomiques sans mint quote prouvé |
| frais | protocole/plateforme/créateur/partage présents ; frais réseau/priorité/ATA **non lus** (meta.fee non exploité) |
| création, graduation/migration, pool CPMM | `unproven` (aucune fixture signée) ; `DISCRIMINATORS_CONFIRMED=False` |
| ordre intra-slot | inconnu (`ambiguous_slots`) |
| Adaptateur R03 | **impossible** : aucune spécification R03 dans le dépôt. Seul le contrat `PaperLedger.source_quote` est testé : 6 clés obligatoires non fournissables (mint, 3 frais lamports, provenance, migration_proof) ⇒ `exact_quote_evidence_required` (fail-closed). |

## Ordre d'intégration proposé
1. #184 → `integration/consolidation-20261103` (après ré-audit R02 de #191).
2. #191 retargetée puis fusionnée (empilée).
3. #189 (indépendante, base déjà `integration/…`) ; vérifier d'abord le doublon `launchlab_tx.json` racine/`tests/fixtures`.
4. Ensuite seulement : mint/créateur/frais depuis `meta` + fixtures signées de création/migration, puis adaptateur ledger/R03.
Reste BLOQUÉ (hors périmètre) : B2 quota Helius réel, B11 discriminateurs mainnet, runtime 24 h.
