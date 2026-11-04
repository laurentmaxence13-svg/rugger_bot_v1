# Série SOL/USD causale : entrée du rejeu L1 (spécification)

Référence de code : `bot/p4/sol_usd_series.py`, branché sur `bot/p4/historical_research_replay.py`. Option de l'outil : `--sol-usd-series <fichier>`. Tests hors réseau : `tests/test_sol_usd_series.py`, sur des échantillons **synthétiques** étiquetés `SYNTHETIC_TEST_FIXTURE`.

La **collecte** revient à RUGGER 03 (plan L2). Ce document fixe seulement ce que le rejeu accepte. L'exigence n'est pas assouplie : sans point valide, la décision reste WAIT.

## 1. Point de prix (`rugger-sol-usd-point-v1`)

Les clés sont exactement les suivantes. Toute clé en plus ou en moins fait refuser la série entière.

| Clé | Type | Règle |
|---|---|---|
| `schema` | str | `rugger-sol-usd-point-v1` |
| `slot` | int > 0 | slot de l'observation : lecture du compte, mise à jour ou trade |
| `transaction_index` | int ≥ 0 ou `null` | position dans le bloc (trade) ; `null` est traité comme 0 |
| `block_time` | int (s) ou `null` | heure de bloc |
| `received_at_ms` | int ou `null` | horloge de réception du client, en prospectif ; `null` en rétrospectif |
| `publish_time` | int (s) ou `null` | **obligatoire** pour les sources Pyth |
| `price` | int > 0 | mantisse ; prix en USD = `price × 10^exponent` |
| `exponent` | int, de −18 à 18 | par exemple −8 pour Pyth |
| `confidence` | int ≥ 0 ou `null` | même exposant |
| `source_kind` | str | une des 3 sources du §2 |
| `source_ref` | str | compte de prix, identifiant de flux Hermes ou adresse du pool |
| `evidence_sha256` | 64 hex minuscules | sha256 de la preuve brute : données du compte, octets de la mise à jour signée ou transaction brute |
| `signature` | str ou `null` | **obligatoire** pour un trade de pool, `null` sinon |

## 2. Provenances acceptées

| `source_kind` | Statut dans le rejeu | Peut-il être certifié un jour ? |
|---|---|---|
| `pyth_onchain_account` | `NOT_VERIFIED_IN_REPLAY` | oui, par un vérificateur audité qui relit le compte brut : programme propriétaire, slot, `publish_time` |
| `pyth_hermes_signed_update` | `NOT_VERIFIED_IN_REPLAY` | oui, par un vérificateur audité des signatures de la mise à jour |
| `sol_usdc_pool_last_trade` | `NOT_VERIFIED_IN_REPLAY` | **non** : observation de marché, jamais certifiée |

Aucune autre source n'est acceptée, en particulier les API HTTP comme DexScreener.

## 3. Série (`rugger-sol-usd-series-v1`)

```json
{"schema": "rugger-sol-usd-series-v1", "label": "COLLECTED", "points": [ ... ]}
```

- `label` vaut `COLLECTED` pour des données réelles, ou `SYNTHETIC_TEST_FIXTURE` pour un test.
- `points` est trié **strictement** par `(slot, transaction_index ou 0)`.
- Le fichier est en JSON ou en `.json.gz`, référencé dans le `MANIFEST.json` de la collecte avec son sha256.
- Le bundle du rejeu enregistre le sha256 canonique de la série.

## 4. Règle à l'instant de décision et refus

À une décision de slot S, d'index de transaction T et d'instant D (en ms) :

1. Prendre le **dernier** point dont `(slot, transaction_index ou 0)` est inférieur ou égal à `(S, T)`. Jamais un point postérieur, jamais d'interpolation ni de moyenne.
2. Son horloge de référence est `publish_time × 1000` s'il existe, sinon `received_at_ms`, sinon `block_time × 1000`.
3. Motifs de refus, journalisés pour chaque décision :
   - aucun point → `sol_usd_rate_unavailable` ;
   - référence postérieure à D → `sol_usd_point_from_future` ;
   - D − référence > **5000 ms** → `sol_usd_stale`. Ce plafond correspond à celui de `native_asof_signal_bridge` et ne peut pas être relevé.
4. Les prix passés de chaque décision utilisent le point as-of de leur propre événement. Un événement sans point valide est omis.

**Densité requise** : au moins un point toutes les 5 s sur la vie de chaque pool. Sinon, les décisions concernées restent WAIT.

## 5. Ce que la série ne change pas

- Le rejeu reste `HISTORICAL_REPLAY`, avec `source_clock_verified=False` et `sol_usd_verified=False`.
- Il n'alimente ni le grand livre PAPER, ni `research_evidence`, ni le seuil du Master.
- Le bundle par défaut, sans série, reste identique à l'octet (`fa86f314…`).
- Une série constante à 150 donne exactement les décisions du taux déclaré à 150 (test de cohérence).

## 6. Fenêtre de collecte (règle M1, contre le biais de survie)

Le MANIFEST de la collecte peut fournir `entry_cutoff_slot` et `window_slot_max`, soit dans chaque entrée de pool, soit au premier niveau, mais toujours les deux ensemble.

- **Entrée** : aucune entrée de recherche après `entry_cutoff_slot`. Les décisions concernées restent journalisées en WAIT, avec le motif `after_entry_cutoff_slot`.
- **Sortie** : un cycle n'est clos que si sa sortie a lieu au plus tard au slot `window_slot_max`. Sinon, son résultat est `open_at_window_end` : il n'est jamais compté comme cycle clos, et sa valeur de marché est seulement indiquée dans `mark_pnl_lamports`.
- **Contrôle** : le rejeu exige que `window_slot_max − entry_cutoff_slot` soit au moins égal à `ceil(exit_horizon_ms / 400) + 2 × latency_slots`, soit 79 slots avec les paramètres actuels. Les pools encore actifs près de la fin de la fenêtre **doivent être gardés** dans l'export.
- **Compatibilité** : sans ces champs, le comportement est inchangé et les fixtures ne sont pas affectées.
