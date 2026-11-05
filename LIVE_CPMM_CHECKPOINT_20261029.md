# Rugger LIVE — checkpoint de validation technique du 29/10/2026

## Code effectivement publié sur PR #34

Source validée : commit `7b7056aee671d857cfa83bde976439a21a37f5a8`.

**CI Github Actions réellement exécutée :** run `40930479254`, `isolated-tests`, conclusion **success**. Commande `python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error`. **2609 passed, 1 skipped, 242 subtests passed en 50.99 s** ; source/fixtures 263 fichiers isolés, aucune clé, .env, base utilisateur ni réseau. Le test ignoré dépend de la base utilisateur non fournie. Les logs détaillés sont disponibles dans GitHub Actions.

### Modules nouveaux
- `bot/live/unsigned_preflight.py` : pré-simulation pour commandes LaunchLab et CPMM immuablement reconstruites ; vérification de l'empreinte du message, RPC/génésis, bank slot, horloge, durée du blockhash et CU. Appelle `simulateTransaction` avec signatures nulles / `sigVerify=false` sans signer ni soumettre.
- `bot/live/cpmm_swap.py` : instruction réelle Raydium CPMM `swap_base_input` (13 comptes, arguments atomiques, PDA de config/vault/observation).
- `bot/live/cpmm_exit.py` : transaction complète **non signée** de sortie CPMM vers SOL, composée de compute budget, création WSOL temporaire, initialisation WSOL, swap exact-in, fermeture du WSOL ; identités/vaults/supply/fee config/observations et permissions décodés à partir des **comptes bruts de même banque**. Calcul exact-input selon source CPMM publiée : trade fee / creator fee sur input ou output, soldes vault nets des frais accumulés, sortie entière arrondie et minimum de sortie conservateur. Tests contre des structures construites au layout officiel, et cas adversariaux.
- `bot/live/migration_evidence.py` : correspondance structurelle exacte de l'instruction LaunchLab `migrate_to_cpswap` (28 comptes), liaison ancien pool / mint / vrai pool CPMM / vaults / LP / autorité / observation. Le pool CPMM **n'est pas nécessairement une PDA de pool canonique** ; le module n'invente aucune adresse.
- Tests : `test_live_unsigned_preflight.py`, `test_live_cpmm_swap.py`, `test_live_cpmm_exit.py`, `test_live_migration_evidence.py`.
- GitHub Actions `.github/workflows/rugger-isolated-ci.yml` épinglé aux actions officielles checkout/setup-python compatibles Node24.

IDL : `raydium-io/raydium-idl@e7e0c96fe77bcf6a020b84a44c47a722aac8e359`, `raydium_cpmm/raydium_cp_swap.json` et `raydium_launchpad/raydium_launchpad.json`.
Source calcul CPMM / layouts : `raydium-io/raydium-cp-swap@b3187ae53a1b95a201f855a59024a12ca8f5b51a`, modules `states/pool.rs`, `states/config.rs`; `curve/calculator.rs` et `curve/constant_product.rs` (algorithme constant-product).

## Délimitations de preuve, non facultatives

**Ces tests sont hors réseau avec des comptes synthétiques.** Ils ne certifient **PAS** qu'une transaction BUY ou SELL réelle a réussi sur mainnet. La sortie CPMM ne possède pas, à ce checkpoint, de livraison vers `ExecutionEngine`, ni d'adaptateur signer/ordre final CPMM autonome. Les comptes historiques ne sont pas des confirmations financières.

Le vérificateur `migrate_to_cpswap` fait une vérification de structure de transaction ; il ne prouve **pas** l'authenticité du transport RPC ni la cryptographie des signatures sur la transaction non disponible en bytes bruts. Un résultat `STRUCTURAL_MIGRATION_RECEIPT` ne vaut ni provenance RPC certifiée ni autorisation de vendre.

La création `PreparedCpmmExit` ne certifie pas la relation à une transaction LaunchLab historique : `migration_provenance_verified=False`, `live_execution_enabled=False`. Les tests du module protègent ces flags contre le changement manuel via le validateur. La source du programme LaunchLab déployé n'est pas publique; l'égalité bit-à-bit source compilée ↔ ELF n'est donc pas une preuve exigible. ABI IDL, identité ProgramData, upgrades et simulations doivent prendre le relais, avec risque résiduel explicite.

## Portes restantes avant une déclaration LIVE_READY_TO_ARM

1. Capturer et vérifier un ou plusieurs vrais `getTransaction` de `migrate_to_cpswap` depuis un transport RPC autorisé, puis sélectionner le pool CPMM ainsi lié ; fournir hashes et comptes bruts S1/S2, slots et latence avec timestamps source identifiés.
2. Réaliser `simulateTransaction` de véritables messages BUY et SELL sur comptes admissibles mainnet; conserver les réponses brutes, statut `err`, CU, slots et comptabilité simulée, sans confusion signature nulle / exécution.
3. Integrer le routage de liquidation CPMM au moteur LIVE avec admission/positions/ledger/kill-switch réellement compatibles, et rapprocher les soldes/frais et sorties d'après migration ; préserver la protection contre double soumission. AMM v4 non supporté sans voie distincte, Token-2022 non supporté.
4. Recontrôler l'empreinte et la version du programme CPMM et LaunchLab en banque fraîche, avec IDL, autorité d'upgrade et blocage automatique au changement.
5. Contre-revue adversariale indépendante et suite intégrale sur le **SHA final** du code assemblé, puis manifest publié/relu.

**LIVE_READY_TO_ARM = FALSE. LIVE_EXECUTION_VERIFIED = FALSE. ECONOMIC_EDGE_VALIDATED = FALSE.** P3-012 (12 requêtes, 159 événements, 25 états, zéro cycle économique strict) reste archivé sans relance.

Aucune transaction réelle, signature privée, activation de wallet, dépense, contournement de protection ou fusion de PR n'a eu lieu dans ce checkpoint.
