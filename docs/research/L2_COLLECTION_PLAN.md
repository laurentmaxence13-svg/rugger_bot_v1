# L2 — plan de collecte historique reproductible (RUGGER 03)

Statut : **plan, non exécuté.** Aucun appel fournisseur n'a eu lieu. Le lancement
revient au propriétaire, après :

1. la rotation de `HELIUS_API_KEY` ;
2. l'audit de l'outil par RUGGER 02 (T-0027, T-0028) ;
3. sa décision de paiement.

## Objectif

Viser environ **200 cycles qualifiés**, et 50 cycles et 50 créateurs dans
l'échantillon de contrôle (70 % des créateurs, seaux 0 à 6 sur 10). Les seuils
protégés de 50 cycles et 20 créateurs restent inchangés.

## Outil

- `tools/backfill_launchlab_window.py` ;
- modules `bot/market/backfill.py`, `bot/market/backfill_cli.py` et
  `bot/market/backfill_export.py`.

La sortie de `export` est lue telle quelle par le rejeu L1 de RUGGER 01
(`bot/p4/historical_research_replay.run_replay`). Sur les 3 pools certifiés,
le rejeu donne un résultat identique avec les archives exportées et avec les
fixtures d'origine.

## Phases

| Phase | Fenêtre | But | Plafond de crédits dans l'outil |
|---|---|---|---|
| P0, mesure | 1 jour (216 000 slots finalisés) | mesurer : transactions par slot, créations par jour, part SOL, créateurs, migrations, échecs, **crédits réels par page** | 1 000 000 |
| P1, cohorte | N jours continus, N calculé après P0 | ≥ 200 cycles qualifiés selon le taux mesuré par L1 sur P0 | 9 500 000 moins la consommation de P0 |

### P0 : commandes exactes

Choisir `S` = un slot finalisé, vieux d'au moins une heure, puis `slot_min = S − 215 999`
et `slot_max = S`.

```bash
python -B tools/backfill_launchlab_window.py plan --slot-min <slot_min> --slot-max <slot_max> --expected-tx-per-slot 3.0 --costs helius-conservative
```

```bash
RUGGER_BACKFILL_RPC_URL='<URL Helius avec la nouvelle clé>' python -B tools/backfill_launchlab_window.py run --network --endpoint-env RUGGER_BACKFILL_RPC_URL --slot-min <slot_min> --slot-max <slot_max> --max-requests 20000 --max-credits 1000000 --costs helius-conservative --out data/backfill/p0
```

```bash
python -B tools/backfill_launchlab_window.py verify --out data/backfill/p0
```

```bash
python -B tools/backfill_launchlab_window.py export --out data/backfill/p0 --pools-dir data/backfill/p0_pools
```

- La même commande `run` reprend après une interruption.
- `data/` est ignoré par git. L'archive se conserve hors du dépôt ; son
  `manifest.json` et son SHA-256 peuvent être commités.
- Tout de suite après P0, relever sur le tableau de bord Helius les crédits
  réellement consommés, puis les comparer à `budget.credits` du manifeste.
  Cette comparaison tranche le tarif : 10 crédits par page de 100 transactions,
  ou 100.

## Estimation prudente des crédits

L'outil compte avec le tarif le plus élevé trouvé dans les sources Helius :

- 100 crédits par page `getTransactionsForAddress`, soit 1 crédit par transaction ;
- 10 crédits par page `getSignaturesForAddress`, la seconde méthode de contrôle.

Volume du programme : **0,2 à 3,0 transactions par slot**. Ce chiffre vient
de 760 à 4 300 créations par jour et de 58 à 150 signatures par pool ; il n'a
pas encore été mesuré.

| Fenêtre | Transactions | Crédits au tarif prudent | Crédits au tarif probable (0,1 par tx) |
|---|---|---|---|
| 1 jour (P0) | 44 000 à 645 000 | 44 000 à 652 000 | 4 400 à 65 000 |
| 7 jours | 0,3 à 4,5 M | 0,3 à 4,6 M | 0,03 à 0,46 M |
| 30 jours | 1,3 à 19,4 M | 1,3 à 19,5 M | 0,13 à 1,95 M |

Le pire cas de 30 jours ne tient pas dans 10 M au tarif prudent. Le plafond
`--max-credits` arrête alors l'outil proprement, et la reprise se fait le mois
suivant ou après décision. La durée N de P1 se calcule après P0 :

```
N_jours_max = (9 500 000 − crédits_P0) / (transactions_par_jour × crédits_par_transaction)
```

## Taille de cohorte pour environ 200 cycles

```
pools SOL nécessaires = 200 / (e × q)
jours de collecte     = pools SOL nécessaires / (créations par jour × part SOL)
```

- `e` est le taux d'entrée et `q` la part des entrées qui donnent un cycle
  qualifié.
- Tous deux sont **inconnus**. L1 les mesurera sur P0 ; aucun n'est supposé ici.
- Grille de lecture seulement, pour 760 créations par jour et 35 % de pools SOL :

| e × q | Pools SOL | Jours |
|---|---|---|
| 1 % | 20 000 | 75 |
| 2,5 % | 8 000 | 30 |
| 5 % | 4 000 | 15 |
| 10 % | 2 000 | 7,5 |

Avec 4 300 créations par jour, ces durées sont divisées par 5,7.

## Données manquantes et risques

- **Pools créés avant la fenêtre** : comptés avec la raison
  `creation_not_in_window`, jamais exportés.
- **Pools actifs près de la fin de fenêtre** : signalés par
  `active_near_window_end`. Leur historique est coupé par la fenêtre, pas par
  la chaîne.
- **Pools CPMM après migration** : non couverts par la fenêtre du programme
  LaunchLab. Chaque adresse CPMM se télécharge avec `run --address <pool CPMM>`.
  La détection automatique des migrations n'est pas encore écrite.
- **Contrôle par deux méthodes** : les deux listes viennent du même fournisseur.
  Ce n'est pas une source indépendante ; la contre-vérification indépendante se
  fait sur un échantillon d'environ 20 pools, avec Old Faithful ou un autre RPC.
- **Format réel de `getTransactionsForAddress`** : il n'a été testé que sur les
  fixtures. Le premier lot P0 doit passer `export`, puis le rejeu L1, avant P1.

## Cours SOL/USD causal (bloquant pour L1)

Le rejeu L1 de RUGGER 01 (`f44a8be`) refuse les 113 décisions des fixtures pour
la raison `sol_usd_rate_unavailable`. La collecte doit donc fournir, sur la même
fenêtre de slots, un cours SOL/USD daté avec sa provenance, connu **avant**
chaque décision. La forme exacte (horodatage, provenance, tolérance d'âge) est
attendue de RUGGER 01. Les options, à chiffrer pendant P0 :

| Option | Coût Helius | Vérifiabilité | Remarque |
|---|---|---|---|
| Trades d'un pool SOL/USDC de référence (Raydium ou Orca), avec `run --address <pool>` | 1 crédit par transaction au tarif prudent ; volume à mesurer | transactions signées sur la chaîne | même outil ; cours = dernier trade avant la décision |
| Transactions de mise à jour du compte de prix Pyth SOL/USD | environ 1 transaction par slot, soit environ 216 000 crédits par jour au tarif prudent | signées sur la chaîne | volume élevé : à échantillonner |
| Mises à jour Pyth signées historiques (service Hermes) | 0 crédit Helius ; service public distinct, à autoriser | signatures Wormhole vérifiables | ce n'est pas un appel Helius ; il faut l'accord du propriétaire |

## Dépassement et renouvellement (point f)

1. **Dans l'outil** : `--max-requests` et `--max-credits` sont comptés avant
   chaque envoi. Le fichier `spend.json` est réécrit **avant** chaque requête : la
   consommation survit à toute panne ou interruption. La table de coûts y est
   figée, et chaque changement de plafond y est enregistré.
2. **Chez Helius**, à confirmer sur leurs pages officielles, bloquées dans mon
   environnement : préférer des crédits prépayés, ou couper la facturation
   automatique des dépassements avant le premier appel.
3. **Renouvellement** : noter la date d'échéance. Rétrograder ou annuler depuis
   le tableau de bord avant cette date, sauf décision explicite de continuer.
4. **Arrêts** : 10 M crédits consommés ; ou premier relevé montrant 100 crédits
   par page de 100 transactions alors que le plan supposait 10 ; ou échec de
   `verify` ou d'`export`.
