# L1 → L2 : du rejeu historique aux premiers cycles PAPER de recherche prospectifs

Préparé le 2026-11-04 par RUGGER 01, sur la base `bed623d` (consolidation #101). Le
document est une conception : il ne crée aucune autorisation. Aucun appel fournisseur,
achat, déploiement ni trade réel n'a lieu sans accord explicite du propriétaire.

Seuils protégés inchangés : **50 cycles économiques qualifiés et 20 créateurs
indépendants** (`bot/master_decision.py:18`, `bot/p4/creator_disjoint_shadow_audit.py:20-21`).

## 0. Trois catégories séparées

| | `HISTORICAL_REPLAY` (L1) | `MASTER_RESEARCH_PAPER` prospectif (L2) | Master opérationnel |
|---|---|---|---|
| Source | fixtures commitées, rejouées hors ligne | observations Helius en temps réel, archivées | idem, après le seuil 50/20 |
| Horloges | **modélisées** (`block_time` + latence déclarée) | **réelles** : réception enregistrée par notre client, avec `context.slot` | réelles |
| `source_clock_verified`, `source_quote_clock_verified` | `False`, jamais forcés | `True` seulement avec les preuves du §4 | idem |
| Grand livre | journal du rejeu (`bot/market/replay.py`), **jamais** `PaperLedger` | `bot/p4/live_like_paper_ledger.py` | idem |
| Compteur du Master (`research_evidence`) | **jamais** | non ; toute prise en compte fera l'objet d'une proposition distincte, auditée et approuvée | seul cas autorisé, après qualification |

## 1. Données manquantes pour des décisions de recherche PAPER prospectives

| Donnée | Utilisée par | État dans le dépôt | Source prévue (L2) |
|---|---|---|---|
| Horloge de réception (`available_at_ms`, `slot_available_at_ms`, `features_available_at_ms`) | `MasterDecisionOrchestrator.evaluate`, `freeze_real_master_reference` | absente des données historiques ; `bot/live/helius_ws_forward_paper.py:258-259` enregistre déjà `received_utc_ns` et une horloge monotone | réception WebSocket et RPC horodatée par notre client, avec `context.slot`, dans un journal append-only haché |
| Transaction de création signée | `signed_creator_verified` | Ed25519 vérifié pour v0 et legacy (`bot/live/solana_signatures.py`) ; **v1 en JSON non vérifiable** (99 des 114 transactions des fixtures) | `getTransaction` en encodage base64, puis `bot/live/solana_v1_readonly.verify_v1_base64_receipt` |
| **SOL/USD certifié, au plus 5 s avant la décision** | `price_usd`, `liquidity_usd`, `native_asof_signal_bridge.py:112-120` | **aucun producteur** dans le dépôt | **nouveau composant** : lecture du compte de prix d'un oracle on-chain à un slot inférieur ou égal à celui de la décision (propriétaire du compte = programme de l'oracle, prix publié frais), qui produit `certified_onchain_SOL_USD_oracle` avec `source_chain_verified` seulement si ces contrôles passent |
| Soldes des détenteurs à l'instant de la décision | `holder_count`, `top_holder_share` | calculables depuis les transactions signées, mais le coffre LaunchLab est compté comme détenteur (§3) | transactions signées dont le slot et la réception sont antérieurs à la décision, coffre exclu |
| Historique du créateur (`prior_launches`, couverture complète) | `verified_full_asof_features` (`complete_prior_creation_coverage`) | non collecté | `getSignaturesForAddress(creator)` borné, couverture déclarée ; sinon la décision reste WAIT |
| Banque à 7 comptes au slot de la cotation (pool, config, plateforme, coffres, frais accumulés) | `bot/p4/launchlab_quote_adapter.asof_launchlab_quote` | absente des fixtures | `getMultipleAccounts` à un slot strictement postérieur à la décision |
| Frais propres | `PaperLedger.quote` (réseau et priorité, création de compte, tentatives échouées) | modèles seulement | réseau et priorité déclarés ; loyer de l'ATA déclaré (récupérable à la fermeture) ; taux d'échec déclaré (34 % des signatures des fixtures échouent, R03) |
| Règle de sortie | aucune dans l'intention de recherche ni dans le grand livre | — | pré-enregistrée et hachée : TP, SL et durée du plan du scoreur (`reference_exit_conditions`), plafond `exit_horizon_ms` de 30 s (`bot/p4_experiment.py`) |

## 2. Raccordement aux observations Helius en temps réel (sans appel non autorisé)

Le pipeline prospectif réutilise des modules existants, testés hors ligne avec un transport
enregistré :

1. **Détection** : `logsSubscribe` sur le programme LaunchLab (`helius_ws_forward_paper.py`), avec horodatage de réception et `context.slot`.
2. **Création** : `getTransaction` en base64, vérification Ed25519 (v0 ou v1), création dans une instruction externe, créateur signataire (logique de `helius_ws_signed_creation_probe.py`).
3. **Fil du pool** : trades suivants via les journaux, plus `getTransaction` signé. Chaque événement porte son slot et sa réception, et rien n'est postérieur à la décision.
4. **Points de décision pré-enregistrés** (par exemple 5 s, 15 s et 30 s après la création), pour borner les appels.
5. **À chaque point** :
   - lecture de l'oracle SOL/USD ;
   - construction causale des caractéristiques ;
   - `freeze_master_research_paper` (`bot/p4/master_research_paper_intent.py`), avec les indicateurs vrais seulement s'ils sont prouvés (§4).
6. **En cas d'ENTER** : banque à 7 comptes à un slot postérieur → `asof_launchlab_quote` (BUY) → `PaperLedger.quote`. Puis surveillance de la règle de sortie → banque → SELL du lot exact → `PaperLedger.quote`.
7. **Archivage** dans le dépôt d'un bundle vérifié avec sha256, car les artefacts Actions expirent.

**Budget d'appels**, à faire approuver avant tout lancement. Ordre de grandeur par pool suivi :
- 1 `getTransaction` pour la création ;
- 1 `getTransaction` par trade retenu jusqu'au dernier point de décision ;
- 1 lecture d'oracle par point ;
- 2 `getMultipleAccounts` par cycle.

Les plafonds existants s'appliquent : 15 RPC par tranche de 30 s, plafond par défaut de 3000 (`helius_signed_master_paper`).

**Avant tout lancement** :
- rotation de `HELIUS_API_KEY` ;
- budget approuvé ;
- workflow manuel adapté : les conditions `if:` actuelles rendent les lancements manuels inertes ;
- PR fusionnée avec accord.

## 3. Coffre LaunchLab et concentration des détenteurs

**Constat, vérifié sur les fixtures.**
- `bot/analyser/behavior_pipeline.wallet_graph_snapshot` compte tous les propriétaires de soldes, y compris le coffre de la courbe, dont le propriétaire est l'autorité LaunchLab `WLHv2UAZm6…`.
- Part du coffre à la création : **98,5 %** sur 5pZ, **97,7 %** sur DVP. Sur ces deux pools, `top_holder_share` atteint au moins 0,9, ce qui déclenche le veto critique `concentration_extreme` (`bot/analyser/final_decision_engine.py:297, 306`).
- Sur C7F9, le créateur a acheté 31,9 % dans la transaction de création : le coffre ne détient que **68,1 %**. À la dernière transaction stockée, il détient 577 208 727 jetons, contre 5 165 896 pour le premier détenteur hors créateur.
- Le comptage du coffre fausse donc la concentration sur tout pool LaunchLab avant migration. Il rend le veto systématique quand le créateur n'a pas acheté une grosse part.

**Justification du correctif.** Pendant la phase de courbe, le coffre est l'inventaire du contrat :
- il n'appartient à aucun participant ;
- il ne peut être vendu que par la courbe elle-même.

Le compter comme détenteur rend le veto systématique et masque la vraie concentration entre participants.

**Effet mesuré dans L1 (variante c contre b).**
- Exclure le coffre fait passer les blocages par concentration de 13 à 11 décisions par bras.
- Sur C7F9, le créateur devient alors le premier détenteur : le veto s'applique aux décisions 0 à 6.
- Sur 5pZ, le scoreur voudrait entrer sur 8 décisions sur 11. Seule la création non signée par le créateur les bloque.
- Le correctif rétablit un signal de risque réel, entre participants, sans ouvrir d'entrée injustifiée.

**Correctif proposé.**
- Exclure des statistiques de détenteurs les propriétaires des comptes de coffre du pool, **dérivés causalement de la transaction de création**, et non une adresse codée en dur.
- Le créateur et tous les autres détenteurs restent comptés.

Dans L1, le paramètre `excluded_owners` est **désactivé par défaut** : la production est inchangée, et le rejeu montre les deux variantes. L'activation en production change un veto de risque. Ce sera une modification distincte, auditée par RUGGER 02 et approuvée par le propriétaire.

## 4. Conditions exactes d'un premier cycle ENTER → BUY PAPER → EXIT → SELL PAPER sans auto-attestation

Le grand livre exige les trois indicateurs avant tout ENTER (`live_like_paper_ledger.py:109-113`). Chacun ne passe à `True` que sur preuve.

| Indicateur | Preuve exigée |
|---|---|
| `signed_creator_verified` | signatures Ed25519 valides (v0, legacy ou v1 base64) ; création dans une instruction externe ; créateur signataire |
| `asof_features_verified` | chaque entrée (transactions, soldes, oracle, historique du créateur) a un slot inférieur ou égal à celui de la décision **et** une réception enregistrée antérieure à l'instant de décision. SOL/USD certifié au plus 5 s avant. Caractéristiques valides (`bot/p4_experiment._features`). Aucune étiquette future (`_reject_future_labels`). Contrôle mécanique enregistré dans le bundle |
| `source_quote_clock_verified` | banque de cotation lue avec un `context.slot` RPC strictement postérieur au slot de décision ; réception au moins 250 ms après la décision ; âge de la source au plus 5 s (`live_like_paper_ledger.py:173-180`) |

Ensuite :
- ENTER uniquement si l'intention de recherche des scoreurs réels le décide ; aucune entrée forcée ;
- BUY par `asof_launchlab_quote`, sortie selon la règle pré-enregistrée, SELL du lot exact ;
- frais : réseau et priorité, création de compte, tentatives échouées ;
- P&L en lamports calculé par le grand livre ;
- bundle archivé avec sha256, catégorie `MASTER_RESEARCH_PAPER` ;
- **non compté** dans le seuil du Master.

## 5. Plan de livraison L2 (chaque étape = une PR courte, testée hors ligne, auditée)

1. **Lecteur d'oracle SOL/USD on-chain** : analyse du compte de prix et contrôles (propriétaire, fraîcheur, slot), testés sur un compte enregistré.
2. **Vérification v1 base64** dans le pipeline signé.
3. **Constructeur causal de caractéristiques** à partir des réceptions horodatées, avec le correctif du coffre en option.
4. **Récupération de la banque à 7 comptes** et adaptateur de cotation, avec un transport simulé.
5. **Coureur prospectif** branché sur `PaperLedger`, avec un transport enregistré de bout en bout, qui produit un cycle complet hors ligne à partir d'une session enregistrée.
6. **Workflow manuel** adapté, sans déclencheur automatique, garde-fou vert.
7. **Premier lancement borné**, après rotation de clé et budget approuvé.

## 6. Résultats L1 : rejeu historique (`HISTORICAL_REPLAY`)

**Code.**
- `bot/p4/historical_research_replay.py` et l'outil `tools/historical_research_replay.py` ;
- 12 tests dans `tests/test_historical_research_replay.py` ;
- paramètre `excluded_owners` (désactivé par défaut) dans `wallet_graph_snapshot` et `build_features`.

**Commande** (déterministe, hors réseau) :
`python -B tools/historical_research_replay.py --fixtures tests/fixtures/launchlab_sol_pools`.

**Preuves.**
- `validation/historical_replay_l1/bundle_default.json`, de `bundle_sha256` `fa86f314f015277f…` ; identique d'une exécution à l'autre ;
- `validation/historical_replay_l1/RESULTS.json`, qui donne les 4 variantes, leurs paramètres et leurs empreintes.

| Variante | Entrées par bras | Principaux motifs de blocage (sur 113 décisions par bras) |
|---|---|---|
| a. Par défaut, sans SOL/USD (fidèle à la production) | 0 | `sol_usd_rate_unavailable` 113, `signed_creator_unverified` 11 |
| b. SOL/USD 150, **supposé et déclaré** | 0 | refus de score ou de risque 113, dont `score_below_minimum` 59, `vente_developpeur` 42, `concentration_extreme` 13 ; `signed_creator_unverified` 11 |
| c. b + coffre exclu | 0 | refus de score ou de risque 105, dont `score_below_minimum` 52, `vente_developpeur` 42, `concentration_extreme` 11 ; `signed_creator_unverified` 11 |
| d. SOL/USD 250, supposé + coffre exclu | 0 | identique à c : les bandes de financement plafonnent dès 150 |

**Par pool.**
- **5pZ** : création par appel interne, créateur non signataire, donc `signed_creator_verified=False`. Avec le coffre exclu, le scoreur voudrait entrer sur 8 décisions sur 11.
- **C7F9** : créateur signataire vérifié.
  - Scores de 43, 36, 27, 25 et 28 sur les décisions 0 à 4, puis 33 sur les décisions 5 à 58, sous le minimum de 45.
  - À partir de la décision 59, le créateur vend : veto `vente_developpeur`.
- **DVP** : concentration, puis vente du créateur.

**Diagnostic.** Aucun cycle n'est possible sur ces fixtures sans entorse aux règles. La conclusion s'appuie sur des décisions réelles et leurs motifs ; aucun indicateur n'a été forcé.

**Limites.**
- **Horloges modélisées** : `block_time` + 400 ms, avec `source_clock_verified=False`.
- **SOL/USD** : absent ou supposé.
- **Historique du créateur** : inconnu, `prior_launches=0`.
- **Tentatives échouées** : non modélisées (0 par défaut, 34 % mesuré dans les fixtures).
- **Bras identiques** : le bras Master et le bras de référence sont identiques par construction, car `early_sniping` figure dans toutes les priorités figées.
- **Fenêtre courte** : 16 à 31 s par pool, sans élan à 60 s.
- **Chemin ENTER** : couvert seulement par un test d'entrée forcée, qui n'est pas un résultat.
- **Statut** : aucune donnée de rejeu n'est comptée comme cycle qualifié. Ces résultats restent en attente de qualification par RUGGER 02.

**Ressource nécessaire pour un premier cycle réel** : les étapes 1 à 5 du §5 (oracle SOL/USD certifié, vérification v1, réceptions horodatées, banque à 7 comptes, coureur prospectif). Le premier lancement borné exige la rotation de `HELIUS_API_KEY` et un budget approuvé par le propriétaire.
