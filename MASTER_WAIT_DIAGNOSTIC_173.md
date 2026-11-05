# RUGGER 03 — Diagnostic WAIT MASTER hors réseau (issue #173)

Méthode : `python -I -m bot.master_wait_diagnostic evidence/p3` (lecture seule, sans réseau, sans modification de stratégie). Base : 16 archives `evidence/p3/*/events.jsonl.gz`, 2046 événements, 265 mints distincts cités.

## Résultats (démontrés par le code, reproductibles)
| Blocage WAIT | Exigé par `bot/master_decision.py` | Réellement présent | Manquant |
|---|---|---|---|
| `additional_costs_unknown` | frais entrée+sortie+tentatives échouées, drapeaux « hors frais de pool » | 35 tx observées avec `meta.fee` ; 2 frais de création (`creation_matched`) | aucune sortie (SELL) exécutée → `exit_extra_lamports` ; 745 tx `chain_failed` sans frais ni propriétaire ; drapeau `quote_amounts_net_of_pool_fees` |
| `qualified_past_edge_evidence_unavailable` | ≥50 cycles économiques qualifiés, ≥20 groupes de créateurs, hash de politique | 0 cycle ; 5 créateurs distincts (launch + creation_matched) | tout cycle BUY/SELL complet ; 15 créateurs de plus |
| `source_identity_supply_creation_unqualified` | `identity_qualified`, `supply_verified`, `creation_verified` = True | 4 `creation_matched`, 5 `launch` ; champ `creation_verified` présent sur 45 candidats | `creation_verified=True` : **0/45** ; aucune preuve de supply/identité |

- Taux d'éligibilité MASTER sur les archives : **0 trame éligible** (aucune trame ne peut satisfaire les 3 portes ; `entry_permitted=True` : 0/364 décisions candidates).
- 28 cotations « quoted » existent, mais sans SELL complet ni horloge de source commune elles ne suffisent pas.
- Les trois motifs sont donc des **champs réellement absents**, pas un bug de la porte : aucune remédiation de code n'est justifiée sans collecte.

## Remédiations vérifiables (sans toucher à la stratégie)
1. Collecte de cycles complets (≥20 BUY/SELL PAPER, ≥50 créateurs) — nécessite une mission de collecte autorisée (hors périmètre ici).
2. Enregistrer `meta.fee`/priority fee pour les tentatives échouées avec leur propriétaire, et le drapeau de frais de pool.
3. Ajouter une vérification supply/identité à l'étape `creation_matched`.

## Limites
Archives = échantillon instrumental (gaps ouverts : `universe_bootstrap_no_independent_creation_reference`). Aucune rentabilité n'est démontrée ni revendiquée. Pas de comparaison MASTER vs référence sur données réelles : 0 cycle.
