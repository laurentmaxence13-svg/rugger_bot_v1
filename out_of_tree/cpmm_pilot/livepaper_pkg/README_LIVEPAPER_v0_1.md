# livepaper 0.1 — test PAPER en direct de G2-3 : robot autonome, journal vérifiable (PAPER_LIVE_DEMO)

RUGGER 01, 25/11/2026. Décision R04-17 (14:46Z), selon le dossier T-R01-12 (v0.3 dans `DOSSIER_PAPER_DIRECT_T_R01_12_v0_3.md`).
- **Étiquette `PAPER_LIVE_DEMO`.**
  - Aucun ordre, aucune signature, aucun envoi.
  - Jamais un trade du Master, jamais compté pour 50/20.
  - Aucun pool pilote (`livesim.check_universe`).
- **Aucun appel réseau n'est possible depuis la 0.1.**
  - `LiveTransport` ne s'ouvre qu'avec un texte d'autorisation dont le sha est dans `AUTHORIZED_TEXT_SHA256`, VIDE ici.
  - Le texte du propriétaire (D-3 / D-7), ancré par R02, n'entre que par une version auditée.
- G2-3 et N1 gelés sont importés sans modification. Le paquet est séparé.
- Il suit les exigences de R02 (14:45Z et 14:50Z) et le **texte du propriétaire livepaper v2 (1366025b, projet non
  signé)** :
  - univers et b₃ tirés de l'ELIGIBLE livesim ancré, sans nouvel historique ;
  - vérification d'ordre avant le test ;
  - voie figée ;
  - un seul compteur de crédits, plafond 25 000, arrêt dur à 24 500.

## Boucle (une étape = une réception)

| Étape | Code |
|---|---|
| Réception | Les transactions nouvelles de chaque pool, puis `getSlot` APRÈS la collecte : c'est le slot de réception. Les pages brutes sont stockées (une page gz par pool et par étape) ; enregistrements `RECEIVED` avec le sha brut, les heures murale et monotone |
| Ligne et G-0 | `cpmmx.timeline` sur les transactions live. Variante B : cpmmrecon 0.1, règle de g23run 0.1.2. `cpmmcost.pool_gate` (0.3.1) sur la ligne tronquée à la réception (`livesim.truncated`). Un changement donne un enregistrement `G0` |
| Décision | Pool éligible (G-0 admis et b₃ > 0) : `cpmmgen2.decisions_g23` sur cette ligne tronquée. Un swap déclencheur postérieur au départ et jamais décidé donne une décision LIVE, à l'instant de la réception (`DECISION`, `ORDER` fictif de 0,1 SOL) |
| Témoin | Chaque décision programme UN ordre témoin sur le même pool, à la première réception après un délai de 60 à 1 800 s tiré de sha256(graine │ pool │ signature). Il faut que le pool soit éligible à ce moment |
| Atterrissage et sortie | Sur la vue RÉGLÉE du pool : swaps au plus au slot de réception − 150 et à l'heure − 60 s, c'est-à-dire des données confirmées qu'un sondage ultérieur ne complète plus. `LANDING` quand le slot d'atterrissage est réglé. `EXIT` quand le point de sortie l'est, valorisé par `fill.position`. Une erreur de coût donne la vente nulle K01 (`cpmmpilot.step1.zero_sale`), comme g23run |
| Attente et marques | `WAIT` quand un pool devient non éligible (motifs G-0, ou `b3_zero`) ou qu'un témoin ne peut pas entrer. `MARK` chaque heure, pour chaque position atterrie et encore ouverte : valeur de vente exacte de ses jetons sur l'état réglé, à titre DESCRIPTIF |
| Fin d'étape | `STEP` : réception, durée de traitement (horloge monotone), positions ouvertes |

**Règle nouvelle, déclarée : l'ancre de réception (`fill.py`).**
- Le code gelé fait atterrir l'achat 4 slots après le swap DÉCLENCHEUR. En direct, l'ordre ne part qu'à la réception
  des données.
- Dans `fill.exit_point` et `fill.position`, l'ancre est donc :
  - le slot de réception, pour l'atterrissage (4 slots × (1 + échecs d'achat)) ;
  - l'heure de réception, pour l'horloge de 30 min ;
  - le dernier swap connu à la réception, pour l'état de la garde d'achat.
- Tout le reste est l'arithmétique gelée, par les fonctions gelées : H-1, TP/SL ±2 % sur la valeur de vente exacte,
  pire état de vente, transactions, WSOL, nettoyage, décomposition à résidu nul.
- **Identité testée** : avec l'ancre SUR le déclencheur, les deux fonctions égalent `cpmmprereg.exit_point` et
  `cpmmcost.position`. Le test porte sur au moins 20 décisions et quatre variantes : primaire, 1 échec, 10 slots,
  garde de 50 000.

## Journal, preuve et rejeu

- Une ligne JSON par enregistrement : numéro, sha du précédent, sha propre. L'écriture se fait **une étape à la
  fois** (une écriture + fsync) : un processus tué ne laisse jamais une demi-étape.
- `HEAD.json` (tête, numéro, heure) est réécrit à chaque étape ; l'enveloppe de R03 le commite et le pousse toutes les
  15 min.
- **Rejeu = reprise (S-2).** `engine.resume` relit le journal et les pages stockées (sha vérifiés). Chaque
  enregistrement est re-dérivé et doit être identique, sans les horloges de l'hôte. Ensuite, la boucle continue : un
  redémarrage reprend exactement où il s'était arrêté.
  - Un enregistrement en trop, une page altérée, une autre graine ou un autre code (`code_sha256` dans `START`) donnent
    une erreur.
- **Trous.** Une pause de plus de 2 × la période de sondage donne un enregistrement `GAP`.
  - Une décision dont le déclencheur précède la fin du trou est marquée `decided_after_gap`.
  - Les arrêts sont des enregistrements `STOP` : plafond de crédits à 98 %, 3 erreurs de suite, fin prévue du
    processus.
- **Comparaison** (`compare`). `livesim.g23_rows` (ancres gelées sur le déclencheur), sur les MÊMES pages, apparie
  chaque décision live par la signature de son déclencheur. Sont publiés :
  - délai de réception, statut et net live, statut et net a posteriori ;
  - décisions présentes d'un seul côté ;
  - trous, temps de traitement p50/p95/p99, délais de décision.
  - Ce n'est jamais un verdict (`verdict: null`).

## Vérification d'ordre et voie figée

- `getTransaction` ne renvoie pas `transactionIndex`, dont cpmmx a besoin pour l'ordre de la chaîne des réserves.
- **`collect-gsfa`** (R03, une fois, sur le même compteur que le test) : pages `getSignaturesForAddress` des pools
  éligibles, en remontant jusqu'au début de la fenêtre pré-départ de l'ELIGIBLE ancré.
- **`ordercheck`** (hors ligne) :
  - comparaison avec les pages GTFA ancrées de la fenêtre pré-départ (`SHA256SUMS` 951b8479), qui portent le
    `transactionIndex` du fournisseur ;
  - pour TOUTE paire de signatures d'un même slot présente des deux côtés, l'ordre doit être exact.
  - Verdict `a-ok` seulement avec au moins une paire comparée, zéro écart et zéro slot différent ; sinon `b`. Le
    nombre de paires est publié. R02 ancre `ORDERCHECK.json`.
- **La voie suit le verdict ancré, puis elle est FIGÉE** dans `START`. Une reprise avec une autre voie est refusée dès
  le premier enregistrement.

| Verdict | Voie | Appels | Indice dans le slot |
|---|---|---|---|
| `a-ok` | (i-a) `gsfa_rank`, sondage toutes les **30 s** | `getSignaturesForAddress` (1), puis `getTransaction` (1) par signature nouvelle, puis `getSlot` (1) | RANG dans le slot selon l'ordre vérifié (`index_source: gsfa_rank`) |
| `b` | (i-b) `gtfa`, sondage toutes les **150 s** | Sonde `getSignaturesForAddress` (limit 1, 1 crédit) ; GTFA (10 par appel) seulement s'il y a du nouveau ; puis `getSlot` | `transactionIndex` du fournisseur |

- **Un seul compteur** (`Budget`) pour la collecte de vérification et pour le test : plafond **25 000**, arrêt dur à
  **24 500**, autres valeurs refusées.
  - Il est débité et écrit AVANT chaque requête, sans reprise au-delà.
  - Estimation sur les 3 pools éligibles B, avec les débits de R03 : (i-a) ≈ 21 800 crédits par jour ; (i-b)
    ≈ 18 100 par jour ; vérification ≈ 100.
- Le transport est `cpmmpilot.rpc.LiveRpc` (gelé 0.2.8), avec son propre jeu d'autorisations et quatre méthodes de
  lecture seulement.
- `run` refuse de démarrer si une clé du fournisseur est visible dans l'environnement (le proxy l'injecte) ou si un
  module de signature est chargé (S-4).

## Commandes

```
python -B -m livepaper.cli prepare --eligible ELIGIBLE.json --eligible-sha <ancré R02> --list-l LIST_L.json --variant B --start T --out POOLS.json
python -B -m livepaper.cli collect-gsfa --pools POOLS.json --out GSFA --ledger L.json --calls C.jsonl --authorization <texte ancré> --endpoint https://mainnet.helius-rpc.com/
python -B -m livepaper.cli ordercheck --pools POOLS.json --gsfa GSFA --gtfa <pages pré-départ 951b8479> --out ORDERCHECK.json
python -B -m livepaper.cli run --pools POOLS.json --ordercheck ORDERCHECK.json --journal J.jsonl --store PAGES --seed-sha <graine déclarée> --ledger L.json --calls C.jsonl --authorization <texte ancré> --endpoint https://mainnet.helius-rpc.com/ --max-minutes 110
python -B -m livepaper.cli replay --pools POOLS.json --journal J.jsonl --store PAGES --seed-sha <graine>
python -B -m livepaper.cli verify --journal J.jsonl
python -B -m livepaper.cli compare --pools POOLS.json --journal J.jsonl --store PAGES --now T --out COMPARE.json
```

- `prepare` contrôle l'ELIGIBLE ancré :
  - son sha, et un schéma qui correspond à la variante (A : livesim 0.3.1, B : livesim 0.3.2) ;
  - la LIST_L ancrée, et un départ postérieur au `t_start` de l'historique ;
  - pour chaque pool, la config recalculée par `livesim.pool_config`, qui doit avoir le sha enregistré ;
  - l'absence de pool pilote.
- Il reprend les b₃ de l'ELIGIBLE tels quels : aucun nouvel historique n'est collecté.

## Limites déclarées

- G2-3 seulement. Les marques N1 ne sont pas dans la 0.1.
- Le temps de traitement croît avec la ligne, puisque chaque étape recalcule la ligne entière. Il est publié (`STEP`),
  mais NON MESURÉ sur le volume réel.
- Le délai de sondage (jusqu'à P secondes) s'ajoute au délai de décision : il est publié (`delay_s`), jamais masqué.
- Le règlement à 150 slots / 60 s retarde la valorisation, pas la décision.

## Validation

- 23 tests sur des pools synthétiques (`test_livepaper.py`, `test_source.py`) :
  - identité de l'ancre avec le code gelé ; déplacement de l'ancre ;
  - chaîne du journal : altération, ligne illisible, rejeu ;
  - boucle complète : décisions, ordres, atterrissages, sorties, témoin, règlement, unicité, G0 seulement sur un
    changement ;
  - **causalité** : deux flux identiques jusqu'à un krach donnent des enregistrements identiques avant la première
    réception qui le contient ;
  - rejeu et reprise : une reprise suivie de la suite égale une exécution d'un seul tenant ; page altérée ; autre
    graine ; enregistrement non reproduit ;
  - trou et décisions rattrapées ; b₃ = 0 ; données pré-départ ; variante B (cpmmrecon appelé, transaction gardée non
    décodée et donc refusée par G-0) ;
  - source : deux modes, rang dans le slot, restauration après redémarrage ; budget à 98 % ; boucle sur horloge
    simulée (trou de 90 s, arrêt sur crédits, arrêt sur erreurs, fin prévue) ;
  - transport refusé, méthodes refusées, S-4, clé visible ;
  - commandes `prepare`, `run` (refus, puis une exécution hors ligne sur `FakeChain`), `verify`, `replay`, `compare`.
- Tests ajoutés pour les exigences de R02 :
  - vérification d'ordre : paires exactes, une inversion, un slot différent, aucune paire, convention « le plus récent
    d'abord » ;
  - voie figée dans `START` (reprise refusée) et voie déterminée par le verdict ;
  - plafond 25 000 et arrêt à 24 500 sur un seul compteur ; `prepare` depuis l'ELIGIBLE et ses refus ;
  - `collect-gsfa` sur le même compteur ;
  - `WAIT` et `MARK`.
- Mutants : 70/71 détectés (`MUTATIONS_livepaper_v0_1.json`), sur fill, journal, engine, source, ordercheck et cli.
  - Le survivant `tp_strict` (« ≥ » devient « > » sur TP) est déclaré ÉQUIVALENT EN PRATIQUE : il ne change le résultat
    que si la valeur de vente vaut exactement 102 000 000 lamports.
  - Les campagnes intermédiaires (56/71, puis 69/71) ont conduit aux tests ciblés : pool construit, exclusion par G-0,
    déclencheur tardif, rafale pré-départ, krach sur une position ouverte, règlement jamais atteint, sortie à
    l'instant de réception.
