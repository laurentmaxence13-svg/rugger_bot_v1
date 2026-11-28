# Rapport d'acceptation — simulateur MASTER V4 (`v4sim` 0.2) — étape V4-2

- **Auteur :** RUGGER 03, 2026-11-10. À auditer et à ancrer par RUGGER 02.
- **Conclusion proposée :** le simulateur est « UTILISABLE » au sens du protocole (§8, étape 3), rien de plus.
- **Ce rapport ne fait pas :** il ne teste aucune stratégie, ne mesure aucune rentabilité, ne promeut rien et n'autorise aucun essai sur données réelles.

## 1. Références

| Élément | Valeur |
|---|---|
| Protocole | V4 v2, sha256 `00d9ccf97b47b16b511b80de75202da58aa1cfeec5c90ba4759793227a286533`, ancré par RUGGER 02 |
| Amendement | v2.1 : A-4′ (mise fixe de 1 000 lamports), accepté dans l'audit `08f9d44079e98261545d5ff5a2f9ba3630626c0ce8c569f95de0c2ad37fcbdec` |
| Audits du code | v4sim 0.1 : `08f9d440…` (PASS sous réserve de A-4′) ; diff v02 : `3a62f17a441aa58f301316a6686727bf3802d0ac79cf86c9c96f9981fd8c1fc9` (PASS, V4-1 close) |
| Version | `v4sim` 0.2. Seul `__init__.py` change par rapport à l'état v02 audité : numéro de version et mention de l'amendement |
| Empreinte du code | `2fe085a33c5604f30468e08e4c0ee096f9881d8efbf24fad0c5faf51af03db67` (`v4sim.batch.code_fingerprint()`, sur les 6 modules) |
| MANIFEST | `MANIFEST_v4sim_020.txt`, sha256 `a53d6c155f41ceaf81a6c9abeaeb1eb77ae115b1b13379027f8c7b552a496629` |
| Journal des tests | `out/tests_journal_v020.txt`, sha256 `eb9236cdf93e560921921d62e35df4c3220e3dab002164d628246405e705214b` |
| Arbre gelé | aff97638cd011bcc3dc2b2826d42a208eb855aed, worktree propre avant et après (git status : 0 ligne) |
| Interpréteur | CPython 3.12.3 x86_64, `-W error`, `unshare -rn` (aucun réseau), `RUGGER_NO_DOTENV=1` |

**Modules (sha256)**

| Fichier | sha256 |
|---|---|
| `v4sim/__init__.py` | `b565beeb1fa825a31fcff51858cde80f88858d57dd95037b9f23c43fd01e8b2a` |
| `v4sim/engine.py` | `8517c4115676a44edf8efae16fc32022cc8e3e526a0f18f3184a196e94389cd4` |
| `v4sim/ledger.py` | `3f6f484a8d4a204f5ebb424b0a72809a283e9d3011f7148b982fc5934726a30c` |
| `v4sim/valuation.py` | `bd17659ea97418acfa3cfd44f0551dbb680fe9c0463542b201ffc288ad6d3a69` |
| `v4sim/io.py` | `867e16a0fc51c4bf0834c4d3b2ccb958760e83e575ac79f1827f2953c9fe81c9` |
| `v4sim/batch.py` | `28b2afe7b9167551eeac6c82891c7e3d7c2b5bde2070911afe84a445991b2b54` |
| `v4sim/tests/test_acceptance.py` | `6b66de67334225a04dd7c25fcef8c30c5c9190bde21fcd4c914bface04146980` |
| `v4synth/gen_pack.py` (générateur, à part) | `7ae50b8804bdb76bebc4c43b6e9b3c98740ec3c72b51c378ba6697013e2c766e` |
| `tools/prep_a3.py` (préparation A-3, à part) | `43685e1af58a4f44a2953e0ea65b47f703c84fc90237ec5d73441ebbfa9043f9` |

## 2. Données utilisées

Aucune donnée réelle : ni P0 (visible ou holdout), ni W1, ni le pilote.

| Pack | Nature | Empreinte |
|---|---|---|
| `tests/fixtures/launchlab_sol_pools` | pack de test de l'arbre gelé (3 pools, 113 événements) | fourni par l'arbre aff97638 |
| `random500` | synthétique, 500 pools, graine 20261110, avec transferts (stock externe) | MANIFEST `a7720db3800679a6d986fa38251f0f75f1bb5ea477274c89431cfd77dc1b32e8` |
| `stress100` | synthétique, 100 pools, graine 20261110 : les autres rachètent après notre ordre, puis vendent tout | MANIFEST `60e051959a76b355f4b81aa1dd2304223da362dd582261f1a31fcf5ed80edbf1` |
| `a3/x40` | synthétique ×40 du pack gelé (`w1aux.synthetic`, préparé à part) | MANIFEST `d1d863daf227cd57363004ae89fe6aad99f3c921610904cb9369178ed0559ba1` ; série `e5d4d910279a876fbac3dfaf2cf3e9b79da10b00d02739bff73db202efe52a34` |

Les packs synthétiques sont générés par un processus distinct, hachés, puis lus comme fichiers. `v4sim` n'importe ni `w1aux`, ni `v3lab`, ni dayj.

## 3. Résultats des critères d'acceptation

Série complète du 2026-11-10 sur `v4sim` 0.2 : **26 tests réussis, 0 échec, 0 ignoré, en 434 s**.

| Id | Critère | Résultat | Mesure |
|---|---|---|---|
| A-1 | Rejeu d'identité, état égal à `event.state_after()` champ par champ | **PASS** | 17 892 événements par mode, dans les 4 modes ; pack gelé (acteurs par propriétaire et par payeur), random500, stress100 |
| A-2 | Invariants I-1, I-2, I-4 sur 10 000 flux d'ordres | **PASS** | 10 000 flux (500 pools × 20 ordres, tailles de la grille) × 4 modes ; 0 violation. Garde contrôlée : un registre corrompu lève bien I-1 |
| A-3 | Non-régression du mode M-L | **PASS** | (i) > 5 000 comparaisons directes avec `replay` gelé, sorties sur horloge comprises : identiques. (ii) `w1_run.run_trials` gelé avec `replay` remplacé : SUMS `4aee76a3…` (pack gelé) et `ba14a5db…` (synthétique ×40) |
| A-4′ | Continuité à mise fixe de 1 000 lamports (v2.1) | **PASS** | 500 positions, 0 pool sans token, 482 valorisées par M-L ; écart maximal M-P et M-C contre M-L : 0 ; 0 hors tolérance |
| A-5 | Artefact L1 supprimé, valeur calculée à la main | **PASS** | stress100 : M-L 100/100 `counterfactual_divergence` ; M-P, M-C et M-A 100/100 clôturées ; tokens et valeur égaux à un calcul entier indépendant écrit dans le test |
| A-6 | Valorisation, règles 1 à 4 | **PASS** | cas construits ; quantité vendue maximale vérifiée (brut(q) ≤ réserve < brut(q+1)) ; aucun −1 de convention |
| A-7 | Déterminisme | **PASS** | sorties identiques à l'octet sur 2 exécutions et avec 1, 2 et 4 processus ; empreinte du code dans chaque sortie |
| A-8 | Monotonie et traçabilité des échecs | **PASS** | tokens par lamport non croissants avec la taille ; échecs à p = 0,10 inclus dans ceux à p = 0,25 ; coûts tracés ; ordre « avant » dans le slot testé sur ≥ 50 pools (O-2) |
| A-9 | Échecs et frais, au lamport près | **PASS** | glissement : base + priorité = 105 000 lamports ; non-inclusion : 5 000 par tentative (règle prudente) ; règle « zéro » refusée sans référence archivée ; nouvelle tentative exacte |
| A-10 | Mutations | **PASS** | 6 défauts injectés, tous détectés : garde de conservation désactivée, frais ×0, latence 0, repli à 0, registre ignorant notre impact, valeur dépendant d'un événement futur |
| A-11 | Recalcul indépendant par RUGGER 02 | **PASS** (audits 08f9d440 et 3a62f17a) | stress100 : 300/300 identiques ; random500 avec les ordres de RUGGER 02 : 4 500/4 500 identiques, plafonnements et drapeau `tracked_sale_clipped` compris |
| A-12 | Module CPMM | **NON APPLICABLE** | aucune donnée CPMM n'existe (§5) |

**Sortie de référence pour A-11 (état 0.2)**
- Commande : `python -m v4sim.batch <stress100>`.
- sha256 : `99beb3fb0ea095543e1b67464143d76212e3f15f3baf44cf82d81f74bd2b8be0`.
- Les 400 positions sont identiques, champ par champ (compteurs compris), à celles de l'état v02 (`1547f63f…`). Seuls le numéro de version et l'empreinte du code changent dans le fichier.

**Mesures descriptives (pas des critères)**
- **A-4 à 100 000 lamports :** 500 positions, 482 valorisées par M-L, écart maximal 1 lamport, 0 hors tolérance.
- **A-2, issues sur les 10 000 flux :**
  - M-P, M-C et M-A : 5 512 clôturées, 4 486 ouvertes en fin de données (valorisées), 2 migrées non valorisées (avec `last_curve_value`).
  - M-L sur les mêmes flux : 256 `counterfactual_divergence`.
- **A-2, drapeaux :** `external_inventory_limited` sur 106 positions en M-P et 110 en M-C, sur environ 10 000 entrées. Le pack random500 contient des transferts à dessein.

## 4. Choix d'implémentation acceptés par RUGGER 02 (D-1 à D-7)

- **D-1.** Une vente de stock externe plus grande que ce que la courbe contrefactuelle peut reprendre est plafonnée et comptée. L'écart E_R − E_C est publié (`external_real_minus_cf`).
- **D-2.** I-4 ne lève une erreur que si le stock externe net du pool est ≤ 0. Sinon la vente suivie est plafonnée et comptée, et la position porte le drapeau `tracked_sale_clipped`, qui entre dans la garde des 5 %.
- **D-3.** Le stock externe net démarre à −`real_base_before` du premier événement.
- **D-4.** Après épuisement des tentatives de sortie, la position reste ouverte jusqu'à la fin des données et y est valorisée (drapeau `exit_retries_exhausted`).
- **D-5.** `max_curve_share` est testé sur l'état connu à la décision. Un refus n'envoie aucune transaction et ne coûte rien.
- **D-6.** Une liquidation partielle avec reliquat ajoute le loyer du compte de token (2 039 280 lamports) aux coûts.
- **D-7.** L'acteur est le propriétaire de l'unique compte de token non WSOL dont la variation égale le montant échangé ; sinon le payeur des frais.

## 5. Limites (à lire avant tout usage)

- **L-1, CPMM absent.** Aucune sortie après migration n'est valorisée. Une position ouverte à la migration reste `migrated_unpriced`, n'est pas créditée, et porte seulement `last_curve_value` à titre descriptif. Lever cette limite demande un décodeur CPMM et une collecte sur une fenêtre neuve (W2), avec un budget validé par le propriétaire (critère A-12).
- **L-2, C-1 en règle prudente.** Une transaction non incluse paie le frais de base. La règle visée (zéro frais) n'entrera en vigueur qu'une fois la référence de la documentation officielle Solana archivée dans le MANIFEST. Le code refuse la règle « zéro » sans cette référence.
- **L-3, D-7 mesuré seulement sur le pack gelé.** 113 événements, 113 propriétaires trouvés, 1 différent du payeur. À re-mesurer sur toute donnée future, puisque les packs synthétiques n'ont pas de soldes de tokens.
- **L-4, comportement d'autrui.** Les autres acteurs gardent leurs instants et leurs budgets. M-A est un scénario de stress, pas une borne. MEV, sandwich et copie ne sont pas modélisés (protocole, B-1 et B-3).
- **L-5, données synthétiques.** Les packs synthétiques ont la forme des courbes LaunchLab, mais pas leurs distributions réelles : tailles, rythmes, part de stock externe. Les taux de drapeaux mesurés ici ne préjugent pas de ceux d'une fenêtre réelle.
- **L-6, un outil, pas une preuve.** Les hypothèses V4 viennent de la lecture des résultats V3 sur P0 (B-5). Toute preuve économique exige une fenêtre neuve et un plan pré-enregistré, ancré par RUGGER 02 et autorisé par le propriétaire.

## 6. Ce que ce rapport n'autorise pas

- Aucun essai sur P0, sur W1 ou sur une donnée réservée.
- Aucune modification de l'arbre gelé, du protocole W1 v2.6.2 ou de la chaîne dayj. W1 reste évalué par le moteur gelé.
- Aucune promotion de stratégie, aucune exécution réelle, aucune dépense.
- Le compteur d'essais reste à N = 34.

## 7. Reproduction

Voir `README_V4SIM.md` : génération des packs, tests, préparation de A-3, batch A-11. Durée totale : environ 8 minutes sur 4 cœurs.
