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

## Tarifs officiels vérifiés le 2026-11-06

Relevés par RUGGER 03 sur les pages publiques, avec l'empreinte SHA-256 de la page
téléchargée. Le relevé Helius recoupe celui de RUGGER 04 du même jour. Aucun appel
d'API ; ces pages ne sont pas des devis.

**Helius** (www.helius.dev/pricing, 2026-11-06T18:13Z, sha256 `b6794b16…`)

| Offre | Prix par mois | Crédits inclus | Crédit supplémentaire | Requêtes par seconde |
|---|---|---|---|---|
| Free | 0 $ | 1 M | — | 10 |
| Developer | 49 $ | 10 M | 5 $ par million | 50 |
| Business | 499 $ | 100 M | 5 $ par million | 200 |
| Professional | 999 $ | 200 M | 5 $ par million | 500 |

- Un appel RPC coûte 1 crédit. Les exceptions sont `getProgramAccounts` et
  `getTransfersByAddress` (10 crédits), et `getTransactionsForAddress` : 10
  crédits par tranche de 100 transactions complètes renvoyées, arrondi au
  supérieur, minimum 10 ; une réponse avec signatures seulement coûte 10 crédits.
- `getSignaturesForAddress` et `getTransaction` ne sont pas dans les exceptions :
  1 crédit chacun.
- La page annonce des limites d'« autoscaling » réglables, le suivi de la
  consommation en temps réel et des alertes.
- Le **tarif probable** des sections suivantes est donc le **tarif officiel**. Le
  tarif prudent reste celui de l'outil (préréglage `helius-conservative`) : il
  compte 10 fois trop, ce qui fait arrêter la collecte trop tôt mais jamais trop
  tard. Avec ce préréglage, `--max-credits 9500000` correspond à environ 0,95 M
  crédits réels. Pour utiliser les 10 M, il faut un préréglage aux valeurs
  officielles (1, 1 et 10) : c'est un changement de code, à faire dans une tâche
  dédiée auditée par RUGGER 02, pas dans ce document.

**Autres fournisseurs** (même jour ; « NC » = non confirmé sur la page publique)

| Fournisseur | Page, sha256 | Prix relevé | Ce que cela couvre pour L2 |
|---|---|---|---|
| Bitquery | bitquery.io/pricing, `924c64c6…` | Personal 29 $, Pro 69 $, Scale 199 $ par mois en facturation annuelle (100 k, 1 M et 5 M points) ; points en plus 35 $ par million (Personal) | offres en temps réel seulement (trades sur 30 jours glissants). L'historique Solana est un module séparé : trades (`DEXTradeByTokens`) 210 $ par mois, ou transferts et transactions 350 $ par mois, en tarif annuel (« 30 % de moins » qu'en mensuel, donc environ 300 et 500 $ par mois en mensuel, valeurs déduites). Données de trades déjà décodées, pas de transactions brutes : **ne remplace pas** la source L1, utile seulement en contrôle croisé. |
| Triton One | triton.one/pricing, `3a590510…` | paiement à l'usage : dépôt minimal de 125 $ (stablecoins), valable 12 mois ; RPC standard, gRPC unaire, comptes et requêtes de registre : 10 $ par million d'appels plus 0,08 $ par Go | `getSignaturesForAddress` et `getTransaction` standards. La facturation de l'historique (« How is historical data billed? ») n'est pas lisible dans la page statique : **NC**, à demander dans le devis. |
| Chainstack | chainstack.com/pricing, `0888edd5…` | Developer gratuit (3 M unités de requête) ; Growth 49 $ par mois (20 M unités, 15 $ par million en plus) ; Pro 199 $ par mois (80 M unités, 12,5 $ par million en plus). Une requête d'archive vaut 2 unités. | l'archive Solana est un « module » des offres payantes, sans prix affiché : **NC**. |
| Old Faithful | docs.old-faithful.net, `6623e6d5…` | logiciel libre, sans prix | archives CAR de tout l'historique Solana, servies par un serveur RPC/gRPC que l'on héberge. Le coût est le stockage et la machine, non chiffrés ici. |
| Dune | docs.dune.com (facturation de l'API), `3d7b0b10…` | l'API exige un essai actif ou une offre payante ; facturation en crédits selon le calcul consommé | la grille de prix (dune.com/pricing) reste bloquée par le réseau : **NC**. |
| Axiom | docs.axiom.trade (index `llms.txt` de 38 pages, `f1d30ff5…`) | frais de trading nets de 0,95 % (Wood) à 0,75 % (Champion), remise comprise (page « Axiom Fees », `4010e788…`) | aucune page d'API, de SDK, de WebSocket ou de point d'accès dans la documentation officielle : rien à intégrer, liens sortants seulement. Ces frais sont ceux d'un trade réel fait sur Axiom ; ils ne s'appliquent pas aux cycles PAPER. |

Coût en dollars d'une collecte de 30 jours du programme (1,3 à 19,4 M
transactions, hypothèse non mesurée), avec les tarifs relevés :

| Option | Calcul | Total |
|---|---|---|
| Helius Developer, `getTransactionsForAddress` | 0,13 à 1,95 M crédits, plus le contrôle `getSignaturesForAddress` (≤ 20 000 crédits), plus la série SOL/USD échantillonnée (environ 0,75 M) : de 0,85 à 2,7 M, sous les 10 M inclus | **49 $** |
| Triton, `getTransaction` une par une | 13 à 194 $ d'appels, plus 16 à 233 Go à 12 Ko par transaction, soit 1 à 19 $ | 14 à 213 $ (dépôt minimal 125 $) ; historique **NC** |
| Chainstack Growth, `getTransaction` en archive | 2,6 à 38,8 M unités, pour 20 M incluses | 49 à 331 $ (18,8 M unités en plus à 15 $ par million) ; module d'archive **NC** |

La recommandation ne change pas : Helius Developer, 1 mois, au plus 100 $ HT,
avec P0 d'abord et le relevé du tableau de bord comparé à `budget.credits`.

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

Qualité de chaque point (constat B1 de RUGGER 02 sur T-0032) :
- un point n'est retenu que si la transaction porte **exactement une** instruction de
  swap sur le pool, reconnue par le programme, le discriminateur et la position du
  compte du pool ;
- un aller-retour ou plusieurs passages par le même pool (`multi_swap`) laissent un
  petit résidu net, qui donnerait un prix absurde : ils sont rejetés ;
- un swap combiné à une autre instruction du programme du pool sur ce même pool,
  par exemple un dépôt ou un retrait, est rejeté (`other_pool_instruction`, T-0034).
  Un passage par un agrégateur, qui appelle le pool par CPI, reste accepté ;
- une variation nette inférieure à `--min-sol-lamports` (0,1 SOL par défaut) est
  rejetée comme poussière (`below_min_size`) ;
- chaque rejet est compté par motif dans `<série>.report.json`.

Le seul préréglage est `--pool-kind raydium-cpmm`, dont les discriminateurs sont
épinglés dans l'IDL Raydium (`bot/live/cpmm_swap.py`). Pour un pool d'un autre type
(Raydium AMM v4, CLMM, Orca), utiliser `--pool-kind custom` avec `--swap-program`,
`--swap-discriminator` et `--pool-account-index`, après vérification dans l'IDL de
ce programme.

Biais connu (O1) : le prix est un prix d'exécution, frais du pool et impact
compris, et non un prix médian. Préférer un pool à faibles frais.

### Choix du pool de référence SOL/USDC (proposition, à valider)

Seul le préréglage `raydium-cpmm` existe aujourd'hui. Or l'essentiel de la liquidité
SOL/USDC est probablement sur d'autres types de pools (Raydium AMM v4 ou CLMM, Orca
Whirlpool). Ce n'est pas vérifié : mon environnement n'a pas de réseau. Un pool CPMM
peu liquide donnerait un prix d'exécution décalé, et fausserait les décisions du
Master. Le pool se choisit donc sur des mesures de P0, avec des seuils fixés
**avant** la collecte.

**1. Critère de choix**, mesuré sur la liste de signatures de P0 (déjà payée par
`sample`, sans appel en plus) et sur les transactions échantillonnées :

| Mesure | Source | Seuil proposé |
|---|---|---|
| Swaps réussis par minute | liste `getSignaturesForAddress` (lignes sans `err`) | ≥ 30 |
| Secondes de grille servies par un point de moins de 4 s | `sample` + `density` | ≥ 99 % |
| Écart maximal entre deux swaps | `density.max_gap_s` | ≤ 4 s sur ≥ 99 % de la fenêtre |
| Liquidité des deux réserves, en dollars | `postTokenBalances` des transactions échantillonnées | ≥ 1 M$ |
| Frais du pool | configuration du pool, lue une fois par le propriétaire | ≤ 0,25 % |

Un pool qui manque un seuil n'est pas utilisé. On passe au candidat suivant, au
besoin d'un autre type de pool (point 3).

**2. Contrôle de cohérence**, arrêt si le seuil est dépassé :
- construire une **seconde série** sur un échantillon d'environ 1 000 secondes de
  grille de P0. Elle vient d'un second pool indépendant (autre pool, idéalement
  d'un autre type), ou d'Hermes si le propriétaire l'autorise ;
- à chaque seconde commune, comparer les deux prix « as-of » :
  `écart = |p1 − p2| / p2` ;
- seuils figés dans T-REG avant l'analyse (voir ci-dessous) ;
- en cas de dépassement, arrêter P1 et revoir le choix du pool. Aucun rejeu n'est
  compté sur une série qui échoue.

Outil (T-0034, complété par #212 pour les observations O1/O2 de RUGGER 02, hors
réseau) : `compare-series`. Il applique la règle de temps de la spécification :
décision à B × 1000 + 400 ms, point disponible à la fin de sa seconde, âge d'au plus
5 s. Le verdict est PASS seulement si **toutes** les conditions tiennent :

| Contrôle | Règle |
|---|---|
| Couverture (O1) | part des secondes de la fenêtre où l'une des séries n'a pas de point utilisable ≤ `max_missing_share` |
| Fenêtre | par défaut l'**union** des périodes utilisables des deux séries : une série qui commence tard, s'arrête tôt ou manque une seconde sur deux compte ses trous |
| Volume | secondes comparées ≥ `min_compared` |
| Écart | médiane ≤ `max_median` et 99ᵉ centile ≤ `max_p99` |
| Indépendance | aucune preuve de transaction (`evidence_sha256`) ni référence de source (`source_ref`) commune ; une série comparée à elle-même échoue |

Le rapport donne aussi les secondes manquantes par série, la plus longue suite de
secondes manquantes et le SHA-256 des deux séries. Code de sortie : 0 = PASS,
4 = tout le reste (FAIL, INSUFFICIENT, NOT_PREREGISTERED), 2 = refus.

**Pré-enregistrement (O2).** Les seuils ne viennent que d'un événement `create`
d'auteur OWNER du registre T-REG, clé de charge utile `compare_series_thresholds`,
schéma `rugger-compare-thresholds-v1` (toutes les clés obligatoires, décimaux en
chaînes) :

```json
{"schema": "rugger-compare-thresholds-v1", "max_median": "0.003", "max_p99": "0.01", "min_compared": 1000, "max_missing_share": "0.01", "step_seconds": 1, "window": null}
```

L'outil lit l'instantané écrit par `treg.py ingest`, recalcule l'empreinte de
l'événement et refuse : un événement absent ou en double, une empreinte fausse, un
auteur autre que OWNER, un type autre que `create`, un document invalide, et toute
valeur passée en ligne de commande qui diffère de la valeur enregistrée (une valeur
égale est acceptée). Sans pré-enregistrement, les statistiques sont calculées mais le
verdict est `NOT_PREREGISTERED` : jamais PASS. Le rapport cite l'événement
(identifiant, empreinte, date) ; l'auditeur vérifie qu'il est sur GitHub et antérieur
à l'exécution.

**Valeurs proposées, NON figées** : elles attendent la validation du propriétaire.
L'événement de gel ne sera écrit qu'après cette validation.

| Seuil | Proposé | Motif |
|---|---|---|
| `max_median` | 0,003 (0,3 %) | ordre de grandeur des frais d'un pool de référence (≤ 0,25 %, critère du point 1) : deux pools denses ne s'écartent durablement que d'environ un frais |
| `max_p99` | 0,01 (1 %) | tolère les secondes de mouvement rapide, où les deux pools ne se mettent pas à jour à la même seconde ; un écart de 1 % sur le taux décale d'autant la valeur en dollars ; au plus 1 % des secondes comparées peuvent dépasser cet écart |
| `min_compared` | 1 000 secondes | taille de l'échantillon du contrôle prévue plus haut ; avec 1 000 valeurs, le 99ᵉ centile repose sur environ 10 secondes |
| `max_missing_share` | 0,01 (1 %) | même exigence que le critère du pool de référence (≥ 99 % des secondes de grille servies) |
| `step_seconds` | 1 | chaque seconde de décision de la spécification |
| `window` | null | union des deux séries ; une fenêtre fixe ne doit être enregistrée que si elle est choisie avant de voir les données |

```bash
python -B tools/backfill_launchlab_window.py compare-series --a data/backfill/p0_sol_usd.json.gz --b data/backfill/p0_sol_usd_second.json.gz --registry treg_snapshot.json --preregistration-event T-XXXX-OWNER-0001 --report-out data/backfill/p0_sol_usd_compare.json
```

**3. Préréglages supplémentaires** (Raydium AMM v4, CLMM, Orca Whirlpool), si P0
montre qu'aucun pool CPMM ne passe le point 1 :
- chaque préréglage est épinglé depuis l'IDL ou le code source officiel du
  programme, avec le dépôt, le commit et le chemin, comme `bot/live/cpmm_swap.py`
  l'est pour CPMM ;
- il est couvert par des tests hors réseau (aller-retour, passage multi-étapes,
  poussière) ;
- il passe par l'audit de RUGGER 02 avant usage ;
- aucun discriminateur n'est écrit de mémoire.

Couverture (O2) : la densité est seulement rapportée, pas imposée. En P0, mesurer la
part des décisions L1 en `sol_usd_stale` ou `sol_usd_rate_unavailable`, et la
consigner avec le rapport.

Index de transaction (O2 de RUGGER 02 sur T-0033) : `getTransaction` standard ne
donne pas toujours `transactionIndex`. Un point sans index ne sert que les décisions
d'un slot strictement postérieur. En P0, consigner la part des points sans index et
la part des décisions refusées pour cette raison. Avec Helius, `sample` recopie
l'index de la ligne de signatures quand le corps n'en a pas.

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
2. **Chez Helius (vérifié en partie le 2026-11-06)** : la page de tarifs annonce
   des limites d'« autoscaling » réglables, le suivi en temps réel et des alertes,
   et 5 $ par million de crédits au-delà des 10 M. Elle ne dit pas si la limite
   peut être mise à zéro, c'est-à-dire si le dépassement peut être coupé. Avant
   le paiement, le propriétaire le vérifie dans le tableau de bord. Sans cette
   confirmation, seul le plafond de l'outil protège.
3. **Renouvellement (CONDITIONNEL, à la charge du propriétaire)** :
   - le jour du paiement, le propriétaire inscrit la date d'échéance (J + 30) ;
   - il programme une annulation ou une rétrogradation à J + 27 ;
   - la procédure exacte est à relever sur la page officielle de Helius.
4. **Arrêts** : 10 M crédits consommés ; ou premier relevé montrant 100 crédits
   par page de 100 transactions alors que le plan supposait 10 ; ou échec de
   `verify` ou d'`export`.
