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
| P0, mesure | 1 jour (216 000 slots finalisés) | mesurer : transactions par slot, créations par jour, part SOL, créateurs, migrations, échecs, **crédits réels par page** ; collecter **la source SOL/USD causale** de la même fenêtre | 1 000 000 (programme) + plafond séparé pour la source SOL/USD |
| P1, cohorte | N jours continus, N calculé après P0 | ≥ 200 cycles qualifiés selon le taux mesuré par L1 sur P0 | 9 500 000 moins la consommation de P0 |

### Critères d'acceptation de P0 (avant tout P1)

1. `verify` réussit et le manifeste est complet (rapprochement par deux méthodes).
2. `export` produit au moins un pool SOL. Les pools écartés sont comptés par
   raison : `quote_not_sol`, `creation_not_in_window`, `active_near_window_end`,
   `earliest_transaction_is_not_the_creation`.
3. **Le rejeu L1 sur l'export de P0 n'est plus bloqué par
   `sol_usd_rate_unavailable`.** Il faut pour cela la source SOL/USD causale
   ci-dessous, au format attendu par RUGGER 01.
4. Contre-vérification sur un échantillon d'environ 20 pools exportés : comparer
   `getSignaturesForAddress(pool)` aux signatures de l'archive. Cela écarte une
   transaction qui toucherait le pool sans passer par le programme LaunchLab.
5. Les crédits du tableau de bord Helius concordent avec `budget.credits`.

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

- `--before-signature` : sans ancre, `getSignaturesForAddress` part de la tête de
  chaîne. Avec une fenêtre finissant une heure plus tôt (environ 9 000 slots, au
  plus 27 000 transactions), cela ajoute au plus 27 pages, soit environ 270 crédits
  au tarif prudent. Pour une fenêtre plus ancienne, fournir une signature proche
  de `slot_max`.
- La même commande `run` reprend après une interruption ; `spend.json` garde la
  consommation, même après une panne.
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

Le rejeu L1 de RUGGER 01 (`f44a8be`) refusait les 113 décisions des fixtures pour
la raison `sol_usd_rate_unavailable`. Le format est désormais fixé par
`docs/research/SOL_USD_SERIES_SPEC.md` (T-0031 @ `1c28f76`, audit PASS de
RUGGER 02). La collecte doit donc fournir, sur la même
fenêtre de slots, un cours SOL/USD daté avec sa provenance, connu **avant**
chaque décision. La forme exacte (horodatage, provenance, tolérance d'âge) est
attendue de RUGGER 01. Les options, à chiffrer pendant P0 :

| Option | Coût Helius | Vérifiabilité | Remarque |
|---|---|---|---|
| Trades d'un pool SOL/USDC de référence (Raydium ou Orca), avec `run --address <pool>` puis `sol-usd-series` | 1 crédit par transaction au tarif prudent ; volume à mesurer | transactions signées sur la chaîne | **seule source sur la chaîne possible en historique** (`sol_usdc_pool_last_trade`) ; cours = variation des deux réserves dans la transaction |
| Compte de prix Pyth SOL/USD (`pyth_onchain_account`) | — | la preuve exigée est le compte brut à chaque mise à jour | **impossible en historique** : le RPC ne donne pas l'état passé d'un compte ; possible seulement en collecte continue (abonnement au compte) |
| Mises à jour Pyth signées historiques (service Hermes) | 0 crédit Helius ; service public distinct, à autoriser | signatures Wormhole vérifiables | ce n'est pas un appel Helius ; il faut l'accord du propriétaire |

Estimation pour P0 (1 jour), au tarif prudent de 1 crédit par transaction :
- **pool SOL/USDC** : de l'ordre de 0,5 à 5 transactions par slot, soit 108 000 à
  1 080 000 crédits. C'est une hypothèse, à mesurer : un plafond séparé
  (`--out` distinct, donc `spend.json` distinct) arrête la collecte.
- **Hermes** : 0 crédit Helius, si le propriétaire autorise ce service.

Densité exigée par la spécification : au moins un point toutes les 4 s pendant la
vie de chaque pool, un par seconde recommandé. `sol-usd-series` affiche l'écart
maximal entre deux points (`density.max_gap_s`).

Contrôle croisé hors ligne (T-0032, copie isolée, non commité), avec le code de
RUGGER 01 @ `1c28f76` et une série synthétique à 150 $ placée dans la seconde qui
précède chaque décision des fixtures :
- le chargeur de RUGGER 01 accepte la série ;
- le motif `sol_usd_rate_unavailable` disparaît des 113 décisions ;
- les décisions sont identiques à celles d'un cours déclaré de 150 $ (226 lignes de
  journal, 0 différence).

Le critère d'acceptation 3 de P0 est donc atteignable avec cette source.

Même contrôle avec la collecte échantillonnée (T-0033), sur un marché synthétique
sans trou de plus de 1 s : 13 transactions téléchargées sur 202 listées, série avec
un écart maximal de 4 s, aucun motif `sol_usd_*` dans le rejeu, et décisions
identiques à un cours déclaré de 150 $ (0 différence sur 226 lignes). Avec un
marché synthétique troué (jusqu'à 8 s sans trade), 14 décisions passent en
`sol_usd_stale`, comme prévu.

### P0 : série SOL/USD, commandes

Le propriétaire choisit un pool SOL/USDC de référence et relève, une seule fois,
l'adresse de ses deux réserves (WSOL et USDC) dans le compte du pool.

Collecte **échantillonnée** (T-0033) : la liste complète des signatures du pool,
puis `getTransaction` seulement pour le dernier trade réussi de chaque pas de grille
(4 s par défaut, 2 s en option), avec un repli borné si ce trade n'est pas un swap.
Plafond séparé de 300 000 crédits en P0 (dossier `--out` et `spend.json` distincts).

```bash
python -B tools/backfill_launchlab_window.py sample --pool <pool SOL/USDC> --sol-vault <réserve WSOL> --usdc-vault <réserve USDC> --slot-min <slot_min> --slot-max <slot_max> --grid-seconds 4 --costs helius-conservative --max-requests 30000 --max-credits 300000 --out data/backfill/p0_solusdc
```

Sans `--network`, cette commande affiche seulement l'estimation. Pour lancer la
collecte, ajouter `--network --endpoint-env RUGGER_BACKFILL_RPC_URL`, avec l'URL
Helius dans cette variable.

Coût par jour au tarif prudent (10 crédits par appel d'archive) : environ 239 000 à
248 000 crédits sur une grille de 4 s. Au tarif probable (1 crédit) : environ 24 000
à 25 000.

Limite réelle : si le pool SOL/USDC lui-même reste plus de 4 s sans trade, les
décisions concernées restent WAIT (`sol_usd_stale`), quelle que soit la grille. La
densité du pool choisi se vérifie avec `density.max_gap_s`.

```bash
python -B tools/backfill_launchlab_window.py sol-usd-series --out data/backfill/p0_solusdc --pool <pool SOL/USDC> --sol-vault <réserve WSOL> --usdc-vault <réserve USDC> --series-out data/backfill/p0_sol_usd.json.gz
```

```bash
python -B tools/backfill_launchlab_window.py export --out data/backfill/p0 --pools-dir data/backfill/p0_pools --sol-usd-series data/backfill/p0_sol_usd.json.gz
```

L'export écrit `entry_cutoff_slot` (`slot_max − 160` par défaut, minimum 79) et
`window_slot_max` (règle M1) et garde tous les pools SOL complets. Le rejeu L1 se
lance ensuite avec `--sol-usd-series`.

## Dépassement et renouvellement (point f)

1. **Dans l'outil (vérifié par test)** : `--max-requests` et `--max-credits` sont
   comptés avant chaque envoi, nouvelles tentatives comprises.
   - Le fichier `spend.json` est réécrit **avant** chaque requête : la
     consommation survit à toute panne ou interruption, et la reprise ne repart
     jamais d'un compteur plus bas.
   - La table de coûts y est figée, et chaque changement de plafond y est
     enregistré.
   - Ce point n'est vrai qu'à partir du commit `5fd0995`, qui corrige le défaut
     F1 de T-0027.
   - **Plafonds approuvés** : une reprise peut relever un plafond (chaque
     changement reste inscrit dans `spend.json`). Le propriétaire ne relance qu'avec
     les plafonds qu'il a approuvés (observation O-a de RUGGER 02).
   - Le registre de dépense est propre à chaque dossier `--out`. La vraie limite
     globale reste celle fixée chez le fournisseur (O-b).
2. **Chez Helius (CONDITIONNEL, non vérifié)** : les pages officielles sont
   bloquées dans mon environnement. Avant le paiement, le propriétaire confirme
   sur ces pages comment acheter des crédits prépayés ou couper la facturation
   automatique des dépassements. Sans cette confirmation, seul le plafond de
   l'outil protège.
3. **Renouvellement (CONDITIONNEL, à la charge du propriétaire)** :
   - le jour du paiement, le propriétaire inscrit la date d'échéance (J + 30) ;
   - il programme une annulation ou une rétrogradation à J + 27 ;
   - la procédure exacte est à relever sur la page officielle de Helius.
4. **Arrêts** : 10 M crédits consommés ; ou premier relevé montrant 100 crédits
   par page de 100 transactions alors que le plan supposait 10 ; ou échec de
   `verify` ou d'`export`.
