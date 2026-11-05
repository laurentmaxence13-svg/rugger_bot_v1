# Verrouillage des workflows Helius avant la consolidation

Registre : T-REG T-0037, audit de RUGGER 02. Garde-fou : `tools/workflow_trigger_guard.py` (fonction `helius_violations`). Tests hors réseau : `tests/test_helius_workflow_lock.py`.

**Objectif.** La consolidation (#101) doit pouvoir être fusionnée dans `main` sans qu'aucun workflow Helius puisse démarrer une collecte sans autorisation. Rien dans ce document n'autorise une exécution.

## 1. État vérifié au départ (2026-11-05)

- **`main`** = `66c6c2ef3f4d`, qui ajoute **un seul fichier**, `.github/workflows/helius-p0-gethealth-once.yml`, identique à l'octet près à celui de la PR #145 (sha256 `62aa86d0…`). Parent : `d9b950e`.
- **Exécution unique** `42020226890` (`workflow_dispatch` sur `main`) : résultat `HELIUS_P0_GETHEALTH=PASS result=ok http=200 latency_ms=88 requests=1`. La clé est masquée (`***`) dans le journal.
- **Workflow** `408043244` : état `disabled_manually`. Le commit sur `main` a aussi lancé la CI hors ligne `paper-terminal-ci` (`42019812969`, succès).
- **Consolidation** : `integration/consolidation-20261103` = `bed623d`. Les 23 workflows Helius ci-dessous y figurent, mais aucun n'est sur `main`.

## 2. Audit des 23 workflows (phase A)

Constats communs aux 23 :
- **Déclencheurs** : `workflow_dispatch` seulement (décision D3), aucun `push`, `pull_request`, `schedule` ni `workflow_call`.
- **Permissions** : `contents: read`, plus `actions: read` pour `helius-historical-ed25519-replay.yml`.
- **Secret** : le seul secret nommé dans tout le dépôt est `HELIUS_API_KEY`, toujours dans l'`env:` d'une étape, jamais dans une commande. Aucun secret de wallet n'existe, donc aucune signature n'est possible depuis Actions.
- **Actions** : `checkout`, `setup-python` et `upload-artifact`, épinglées par SHA, avec `persist-credentials: false`.

« Avant » indique ce qu'un simple lancement manuel aurait fait avant le verrouillage :
- **exécute** : le job qui utilise la clé démarre ;
- **inerte** : la condition du job exige un événement `pull_request` étiqueté, qui ne peut plus se produire.

Les plafonds sont ceux déclarés dans les arguments ou dans le code du module. Ils ne sont pas vérifiés dynamiquement.

| # | Fichier (`.github/workflows/`) | Avant | Job(s) avec la clé | Module, plafond déclaré | Délai max | Artifacts |
|---|---|---|---|---|---|---|
| 1 | `cpmm-prospective-markout-readonly.yml` | exécute | `prospective-no-trade` | `cpmm_prospective_markout`, `max_calls=4` | 5 min | — |
| 2 | `cross-provider-migrations-readonly.yml` | exécute | `compare-finalized-migrations` | `cross_provider_migration_proof`, plafond non trouvé | 5 min | — |
| 3 | `helius-active-launchlab-cohort.yml` | exécute | `fixed-cohort-before-followup` | `helius_active_launchlab_cohort`, `max_calls=6` | 5 min | 30 j |
| 4 | `helius-active-launchlab-scan.yml` | exécute | `current-active-survivor-only` | `helius_active_launchlab_scan`, `max_calls=2` | 5 min | — |
| 5 | `helius-historical-ed25519-replay.yml` | exécute | `finalized-signed-creation-replay` | `finalized_campaign_replay`, `max_calls=1` | 5 min | 30 j |
| 6 | `helius-index-first-cohort.yml` | exécute | `frozen-index-selection-before-market-outcomes` | `helius_index_prospective_cohort`, `max_calls=5` | 5 min | — |
| 7 | `helius-launchlab-sampled-creations.yml` | exécute | `bounded-historical-sample` | `helius_launchlab_cohort_probe`, 1 page et 4 paires (`max_calls=10`) | 5 min | 30 j |
| 8 | `helius-legacy-hints-crypto.yml` | exécute | `finalized-hints` | `helius_legacy_hint_crypto_audit`, `max_calls=10` | 4 min | 14 j |
| 9 | `helius-pinned-index-creators.yml` | exécute | `exact-finalized-creation-proof` | `helius_pinned_index_creators`, `max_calls=5` | 4 min | 14 j |
| 10 | `helius-pinned-root-diagnostic.yml` | exécute | `current-root-only` | `helius_pinned_root_diagnostic`, `max_calls=2` | 4 min | 14 j |
| 11 | `helius-prospective-campaign.yml` | exécute | `bounded-campaign` | `helius_prospective_campaign`, 4 fenêtres × 60 s, 200 événements au plus | 9 min | 14 j |
| 12 | `helius-recent-signed-sol-trades.yml` | inerte | `bounded-signed-sol-trade-discovery` | `helius_recent_signed_trade_pools`, `max_calls=10` | 4 min | 30 j |
| 13 | `helius-rolling-signed-paper.yml` | inerte | `bounded-mainnet-rolling-pilot` | `helius_rolling_signed_paper`, 180 s, `--rpc-call-cap 90` | 6 min | 30 j |
| 14 | `helius-s1-capacity-s2.yml` | exécute | `fixed-s1-capacity-before-s2` | `helius_s1_capacity_then_s2`, `max_calls=10` | 5 min | 30 j |
| 15 | `helius-signed-master-paper.yml` | inerte | `integrated-signed-source` | `helius_signed_master_paper`, 30 s | 4 min | 30 j |
| 16 | `helius-sol-forward-paper-cycle.yml` | inerte | `prospectively-frozen-sol-market` (matrice × 4) | `helius_sol_forward_paper_probe`, `max_calls=6` par page | 5 min | 30 j |
| 17 | `helius-unsigned-cpmm-sell.yml` | exécute | `only-zero-signature-readonly` | `helius_unsigned_sell_probe`, `max_calls` 4 et 10 | 5 min | — |
| 18 | `helius-ws-forward-paper.yml` | exécute | `mainnet-no-orders-probe` | flux WebSocket de 25 s (100 événements), puis `helius_ws_signed_creation_probe` (`max_calls=10`) | 3 min | 30 j |
| 19 | `master-prospective-evidence.yml` | exécute | `bounded-public-mainnet-observation`, `independent-finalized-creation-discovery`, `early-confirmed-prospective-sensor` | WebSocket de 45 s, signatures (`max_calls=10`), banque (`max_calls=5`), sonde (`max_calls=10`), S1/S2 (`MAX_RPC=10`) | 5, 4 et 4 min | 30 j |
| 20 | `public-holder-readonly.yml` | exécute | `public-holder-observation` | `public_holder_probe`, `max_calls=4` | 5 min | — |
| 21 | `sample-Wsol-independent-legs-readonly.yml` | exécute | `prove-two-disconnected-public-Wsol-legs` | `public_sample_wsol_legs`, `max_calls=3` | 5 min | — |
| 22 | `sample-public-trade-receipts-readonly.yml` | exécute | `verify-four-receipts-without-wallet` | `public_sample_trade_receipts`, `max_calls=5` | 5 min | — |
| 23 | `solana-v1-pinned-mainnet.yml` | exécute | `exact-public-v1-mainnet` | `solana_v1_pinned_mainnet_probe`, `max_calls=3` | 3 min | — |
| + | `helius-p0-gethealth-once.yml` (sonde, sur `main`) | requête unique, avec phrase | `gethealth-once` | 1 requête `getHealth` | 2 min | — |

**19 workflows exécutaient leur collecte sur un simple lancement manuel** : les n° 1 à 11, 14, 17 à 23. Les n° 12, 13, 15 et 16 étaient inertes. Les deux jobs hors ligne `offline-contract` (n° 18) et `strict-offline-contract` (n° 19) s'exécutaient aussi, sans clé. Le job `official-four-table-vendor-sample` (n° 5) est inerte et sans clé.

**Risques relevés :**
1. un lancement manuel suffisait pour 19 workflows dès que leur fichier serait sur `main` ;
2. les artifacts sont publics sur un dépôt public, et aucun contrôle n'empêchait d'y publier la clé ;
3. plusieurs groupes de concurrence dépendaient de `github.event.pull_request.number`, vide lors d'un lancement manuel ;
4. 4 checkouts visaient `github.event.pull_request.head.sha`.

## 3. Verrouillage réalisé (phase B)

### 3.1 Dans le code, contrôlé par le garde-fou

Pour chacun des 24 workflows qui nomment `HELIUS_API_KEY`, les 23 et la sonde :

1. **Entrée obligatoire** `confirm`. Chaque job est conditionné par **exactement** :
   ```
   github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' &&
   github.repository == 'laurentmaxence13-svg/rugger_bot_v1' &&
   vars.HELIUS_COLLECTION_ENABLED == 'true' && inputs.confirm == 'RUN-<NOM DU FICHIER>'
   ```
   - La phrase est propre à chaque workflow, par exemple `RUN-HELIUS-SIGNED-MASTER-PAPER`.
   - Seuls `always()` et `needs.<job>.result == …` peuvent la précéder, jamais `||`.
2. **`environment: helius-collection`** sur chacun des 25 jobs qui utilisent la clé (§3.2).
3. **Concurrence unique** `helius-collection`, sans annulation : une seule collecte Helius à la fois, tous workflows confondus.
4. **Durée** : 10 min au plus par job, exécuteur `ubuntu-latest`, sans `container`, `services` ni workflow réutilisable.
5. **Clé** : seulement sous la forme `HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}` dans l'`env:` d'une étape. Elle n'apparaît jamais dans une commande, un `with:` ou l'`env:` d'un job ou du workflow. Aucun `inputs` n'est interpolé dans une commande, et `toJSON(secrets)`, `secrets[...]` et tout autre nom de secret sont refusés.
6. **Contrôle de la clé avant publication** : dans les 16 jobs qui publient des artifacts, une étape relue `helius_key_canary` refuse la publication si un fichier de `paper_artifacts` contient la clé dans son contenu ou dans son nom.
   - Elle tourne toujours (`if: always()`), après toute étape qui utilise la clé.
   - La publication n'a lieu que si ce contrôle a réussi.
   - Les chemins restent sous `paper_artifacts/`, et la rétention est de 30 jours au plus.
7. **Pas de LIVE** : aucun nom d'environnement évoquant un wallet (`PRIVATE`, `KEYPAIR`, `SEED`…), `RUGGER_LIVE_ENABLED` seulement à `'0'`, et ni `sendTransaction` ni `--live` dans une commande.
8. **Les 4 workflows auparavant inertes** (n° 12, 13, 15 et 16) suivent maintenant la même chaîne d'autorisation. Leur checkout n'utilise plus l'ancienne référence de PR.

Le garde-fou lit ces fichiers avec un lecteur YAML strict, qui refuse ancres, alias, étiquettes, mappings en flux, clés citées ou en double, et scalaires multi-lignes. Il donne exactement le même résultat que PyYAML sur les 56 workflows du dépôt, ce qui est testé. Une régression fait échouer la CI hors ligne.

### 3.2 Garde-fous techniques à poser par le propriétaire (Settings)

Une phrase de confirmation et une condition écrite dans le fichier ne protègent pas contre une personne qui a le droit d'écriture : elle peut pousser une branche avec une version modifiée du workflow et la lancer. La protection technique repose donc sur les **réglages du dépôt**, que seul le propriétaire peut modifier :

1. **Settings → Environments → New environment `helius-collection`** :
   - **Required reviewers** : le propriétaire. Chaque exécution d'un job qui utilise la clé attend alors son approbation.
   - **Deployment branches and tags** : *Selected branches*, `main` uniquement.
   - **Environment secrets** : `HELIUS_API_KEY`, avec la clé renouvelée.
2. **Settings → Secrets and variables → Actions → Repository secrets** : **supprimer** `HELIUS_API_KEY` au niveau du dépôt. La clé n'existe plus alors que dans l'environnement : un workflow modifié sans `environment: helius-collection`, ou lancé depuis une autre branche, ne reçoit **aucune** clé.
3. **Repository variable `HELIUS_COLLECTION_ENABLED`** : la laisser absente. Elle ne doit valoir `true` que pendant une fenêtre de collecte autorisée, puis être supprimée.

Après l'étape 2, la sonde actuellement sur `main` (non durcie, et désactivée) ne recevrait plus de clé : elle répondrait `FAIL key_missing_or_malformed requests=0`.

### 3.3 Lancer une collecte autorisée, après fusion et réglages

1. Le propriétaire décide d'exécuter un workflow précis.
2. Il crée temporairement `HELIUS_COLLECTION_ENABLED = true`.
3. Actions → workflow → **Run workflow** sur `main` → `confirm` = `RUN-<NOM DU FICHIER>`.
4. Il approuve chaque job en attente sur l'environnement `helius-collection`.
5. Il supprime la variable `HELIUS_COLLECTION_ENABLED`, puis lit les résultats.

## 4. Vérification et retour arrière

- **Contrôles hors ligne** :
  ```
  python -B tools/workflow_trigger_guard.py
  python -B tools/offline_check.py -q tests/test_helius_workflow_lock.py tests/test_workflow_trigger_guard.py -p no:cacheprovider -W error
  ```
- **Retour arrière** : annuler le commit de la PR sur la branche de travail. Il ne touche ni `main` ni les réglages. Les réglages du §3.2 se défont dans Settings ; remettre le secret au niveau du dépôt restaure l'état antérieur, moins sûr.

## 5. Risques résiduels

1. **Réglages non vérifiables par le code.** Le garde-fou ne peut pas lire les environnements, les secrets ni les variables. Tant que le §3.2 n'est pas fait, la protection repose sur les conditions des fichiers, qu'une personne ayant le droit d'écriture peut contourner depuis une branche.
2. **Administrateurs.** Un administrateur du dépôt peut modifier les réglages. Les jetons des agents ont aujourd'hui des droits d'administration (constat P-PRIV) : la règle de ne pas y toucher reste déclarative.
3. **Plafonds de requêtes.** Ce sont ceux du code de chaque module, non contraints par le garde-fou ; seule la durée est bornée techniquement (10 min par job, une collecte à la fois). La consommation exacte en crédits n'est pas mesurée.
4. **Contrôle de la clé.** Il détecte la clé en clair dans les contenus et les noms de fichiers. Il ne détecte pas une clé encodée (par exemple en base64) ni une fuite par le journal. GitHub masque la clé dans les journaux, ce qui a été vérifié lors de l'exécution P0.
5. **Fusion avec `main`.** La sonde existe dans les deux branches avec des contenus différents : la fusion de #101 provoquera un conflit d'ajout sur ce fichier. Il faut garder la version durcie de la consolidation.
6. **Autres workflows réseau.** Les workflows manuels sans secret (RPC public, Raydium, trawl.run, Bitquery sans clé) restent lançables manuellement une fois sur `main`, sans phrase ni environnement. Ils n'utilisent aucune clé, mais font des appels réseau : un verrouillage analogue est à décider séparément.
