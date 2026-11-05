# Série SOL/USD causale : entrée du rejeu L1 (spécification)

Référence de code : `bot/p4/sol_usd_series.py`, branché sur `bot/p4/historical_research_replay.py`. Option de l'outil : `--sol-usd-series <fichier>`. Tests hors réseau : `tests/test_sol_usd_series.py`, sur des échantillons **synthétiques** étiquetés `SYNTHETIC_TEST_FIXTURE`.

La **collecte** revient à RUGGER 03 (plan L2). Ce document fixe seulement ce que le rejeu accepte. L'exigence n'est pas assouplie : sans point valide, la décision reste WAIT.

## 1. Point de prix (`rugger-sol-usd-point-v1`)

Les clés sont exactement les suivantes. Toute clé en plus ou en moins fait refuser la série entière.

| Clé | Type | Règle |
|---|---|---|
| `schema` | str | `rugger-sol-usd-point-v1` |
| `slot` | int > 0, ou `null` pour Hermes | slot **Solana** de l'observation : mise à jour du compte Pyth ou trade ; **`null` obligatoire** pour `pyth_hermes_signed_update` (§2 bis) |
| `transaction_index` | int ≥ 0 ou `null` | position dans le bloc ; `null` = position inconnue dans le slot (§4) ; **`null` obligatoire** pour Hermes. À renseigner pour `pyth_onchain_account` (index de la transaction de mise à jour Pyth) et pour les trades |
| `block_time` | int (s) ou `null` | heure de bloc Solana ; **`null` obligatoire** pour Hermes |
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

## 2 bis. Mises à jour Hermes : hors chaîne, ordonnées par le temps

Une mise à jour Hermes porte un slot **Pythnet**, qui n'est pas un slot Solana. Elle n'a donc aucune position Solana :

- `slot`, `transaction_index` et `block_time` valent `null` ; le slot Pythnet reste dans les octets signés hachés par `evidence_sha256` ;
- son ordre et sa causalité reposent uniquement sur `publish_time` (et `received_at_ms` en prospectif) ;
- une série est soit entièrement sur chaîne (ordre `chain_position`), soit entièrement Hermes (ordre `publish_time`), jamais mélangée.

## 3. Série (`rugger-sol-usd-series-v1`)

```json
{"schema": "rugger-sol-usd-series-v1", "label": "COLLECTED", "points": [ ... ]}
```

- `label` vaut `COLLECTED` pour des données réelles, ou `SYNTHETIC_TEST_FIXTURE` pour un test.
- Série sur chaîne : `points` est trié **strictement** par `(slot, transaction_index ou 0)` ; deux points `(S, null)` et `(S, 0)` sont donc refusés.
- Série Hermes : `points` est trié **strictement** par `publish_time`, soit au plus une mise à jour par seconde (garder celle du slot Pythnet le plus récent).
- Le bundle indique l'ordre retenu (`ordering`).
- Le fichier est en JSON ou en `.json.gz`, référencé dans le `MANIFEST.json` de la collecte avec son sha256.
- Le bundle du rejeu enregistre le sha256 canonique de la série.

## 4. Règle à l'instant de décision et refus

À une décision de slot S, d'index de transaction T et d'instant D (en ms) :

1. **Position.**
   - Série sur chaîne : le point doit être à `(slot, transaction_index)` ≤ `(S, T)`. Un point dont `transaction_index` vaut `null` n'est utilisable que si son slot est **strictement** antérieur à S, car sa place dans le slot S est inconnue (correctif B1-a de T-0031).
   - Série Hermes : `publish_time × 1000` ≤ D ; le slot de la décision n'intervient pas.
2. **Disponibilité, sans donnée future.** Une horloge à la seconde (`publish_time`, `block_time`) dit seulement que l'événement a eu lieu pendant cette seconde. L'instant de disponibilité est donc le plus tardif de : `publish_time × 1000 + 999`, `block_time × 1000 + 999` et `received_at_ms`. Il doit être ≤ D (correctif B1-b). Une horloge de réception ne peut que retarder un point, jamais l'avancer.
3. **Choix.** Prendre le **dernier** point positionné qui est disponible. Jamais un point postérieur, jamais d'interpolation ni de moyenne.
4. **Âge.** D moins le **début** de la plus ancienne horloge du point (`publish_time × 1000`, `block_time × 1000` ou `received_at_ms`).
5. **Motifs de refus**, journalisés pour chaque décision :
   - aucun point positionné → `sol_usd_rate_unavailable` ;
   - des points positionnés, mais aucun disponible à D → `sol_usd_point_from_future` ;
   - âge > **5000 ms** → `sol_usd_stale`. Ce plafond correspond à celui de `native_asof_signal_bridge` et ne peut pas être relevé.
6. Les prix passés de chaque décision utilisent le point as-of de leur propre événement. Un événement sans point valide est omis.

Le journal de chaque décision indique le point retenu (avec sa mantisse `price` et son exposant `exponent`), son âge et son instant de disponibilité `available_ms`, toujours ≤ `modelled_receipt_ms`.

**Conséquence pratique.** En rejeu, D vaut `block_time × 1000 + 400`. Un point horodaté dans la même seconde que la décision est donc toujours refusé : l'âge minimal effectif est de 1400 ms, pour un point publié pendant la seconde précédente.

**Densité requise : au moins un point par seconde** sur la vie de chaque pool (observation O2 de T-0031). Une décision de la seconde B n'est servie que par un point publié pendant l'une des secondes B − 4 à B − 1, et le plus récent de ces points fixe l'âge : avec un point par seconde, l'âge reste de 1400 à 2399 ms. Au-delà de 4 s sans point, les décisions concernées restent WAIT (`sol_usd_stale`).

## 5. Ce que la série ne change pas

- Le rejeu reste `HISTORICAL_REPLAY`, avec `source_clock_verified=False` et `sol_usd_verified=False`.
- Il n'alimente ni le grand livre PAPER, ni `research_evidence`, ni le seuil du Master.
- Le bundle par défaut, sans série, reste identique à l'octet (`fa86f314…`).
- Une série constante à 150, publiée pendant la seconde qui précède chaque décision, donne exactement les décisions du taux déclaré à 150, en série sur chaîne comme en série Hermes (tests de cohérence).

## 6. Fenêtre de collecte (règle M1, contre le biais de survie)

Le MANIFEST de la collecte peut fournir `entry_cutoff_slot` et `window_slot_max`, soit dans chaque entrée de pool, soit au premier niveau, mais toujours les deux ensemble.

- **Entrée** : aucune entrée de recherche après `entry_cutoff_slot`. Les décisions concernées restent journalisées en WAIT, avec le motif `after_entry_cutoff_slot`.
- **Sortie** : un cycle n'est clos que si sa sortie a lieu au plus tard au slot `window_slot_max`. Sinon, son résultat est `open_at_window_end` : il n'est jamais compté comme cycle clos, et sa valeur de marché est seulement indiquée dans `mark_pnl_lamports`.
- **Contrôle** : le rejeu exige que `window_slot_max − entry_cutoff_slot` soit au moins égal à `ceil(exit_horizon_ms / 350) + 2 × latency_slots`, soit **90 slots** avec les paramètres actuels. 350 ms est une borne basse de la durée d'un slot (la moyenne est d'environ 400 ms) : des slots plus rapides demandent plus de slots pour couvrir l'horizon de sortie (observation O1 de T-0031). Les pools encore actifs près de la fin de la fenêtre **doivent être gardés** dans l'export.
- **Compatibilité** : sans ces champs, le comportement est inchangé et les fixtures ne sont pas affectées.
