# Rugger — Prévalidation CPMM sur mainnet (LECTURE SEULE)

Ce dossier documente la prochaine acquisition réseau, distincte de P3-012. Aucun portefeuille ne doit être financé ou activé pour ce protocole. **Ne jamais publier le fichier de résultats brut dans GitHub sans inspection et suppression des informations publiques sensibles (adresses, soldes, liens d'activité).**

## Avant toute opération

1. Confirmer que la PR #35 a été intégrée après sauvegarde des fichiers locaux de Codex.
2. Inspecter `bot/live/{program_pin,migration_rpc_receipt,solana_signatures,cpmm_bank,cpmm_readiness}.py`, `bot/live/readonly_plan.py` et `tools/run_readonly_cpmm_preflight.py` sur le SHA effectivement utilisé. Ces fichiers ont leurs propres tests, sans clés.
3. Constituer une **signature historique réelle** `migrate_to_cpswap`, l'ancien pool LaunchLab, le nouveau pool CPMM, le token SPL et un wallet public disposant des tokens à vendre. Le protocole refuse toute valeur inventée. N'utiliser que des adresses publiques, jamais de phrase de récupération, clé privée, secret de service ou fichier `.env`.
4. Épingler indépendamment les empreintes ProgramData/ELF, le slot de déploiement et l'autorité de mise à jour **actuels** de LaunchLab et CPMM. La capture historique LaunchLab du 29/10/2026 n'autorise pas automatiquement les programmes.
5. Définir le `min_context_slot` après la migration finalisée et un budget d'appels RPC : exactement **18 appels au plus**, aucun retry, arrêt au premier échec, délai maximum 60 secondes.

La commande exige un plan JSON rempli avec **exactement** les champs de `bot/live/readonly_plan.py`. Le gabarit `mainnet_plan_template.json` comporte volontairement des valeurs interdites : il ne peut pas être exécuté sans configuration explicite.

## Commandes

Valider le plan localement, **zéro réseau** :

```bash
python -B tools/run_readonly_cpmm_preflight.py --plan /private/validated_plan.json --validate-only
```

Une fois le plan inspecté et validé, lancer **une seule** tentative lecture seule (pas de boucle) :

```bash
python -B tools/run_readonly_cpmm_preflight.py --plan /private/validated_plan.json --out /private/new_readonly_receipt.json --run-readonly
```

Le script utilise l'endpoint public `https://api.mainnet.solana.com`, le proxy explicitement géré par l'environnement, un budget fixe et **aucune autorisation de `sendTransaction`**. Il ne lit aucun portefeuille ni clé. Il peut échouer si le wallet public ne détient pas les tokens nécessaires, si le pool n'est plus admissible, si le réseau renvoie `null` pour le temps du bloc, si les programmes ont changé ou si la latence dépasse 5 secondes. Ces échecs sont des **résultats de sécurité corrects**, pas des prétextes à répéter ou assouplir le protocole.

Le rapport JSON est créé en mode privé 0600 sans écraser de fichier existant. La ligne standard affiche seulement le statut, des empreintes et le nombre d'appels. La capture privée comprend des adresses publiques, l'historique de migration et les comptes source utiles pour une contre-revue ; elle ne contient pas de clé de signature. **Ne pas transmettre publiquement un rapport brut lié à un wallet personnel.**

## Ce qu'une réussite prouve réellement

- Les ProgramData fournis par un RPC épinglé correspondent aux empreintes **externes explicitement indiquées**.
- La transaction historique de migration a une structure reconnue et ses signatures Ed25519 sont vérifiées sur les octets compilés legacy/v0.
- Les comptes CPMM nécessaires à la sortie appartiennent à une même banque RPC, avec comptes/mint/vaults/PDA/frais contrôlés.
- Le message SELL exact, non signé, est simulé via `simulateTransaction(sigVerify=false)`, sous les limites de fraîcheur, blockhash, prix et frais.

**Ce que cela ne prouve pas :** consensus RPC indépendant, sûreté du code source privé LaunchLab, exécution d'une transaction réelle, vente effectivement confirmée, disponibilité du moteur comptable après migration, rentabilité ou autorisation d'engager des fonds. Les statuts `LIVE_READY_TO_ARM`, `LIVE_EXECUTION_VERIFIED` et `ECONOMIC_EDGE_VALIDATED` restent faux jusqu'aux audits séparés.

## À remettre à Codex

Conserver le SHA exact du code et les journaux de tests, importer le module d'acquisition dans l'intégration `ExecutionEngine` + `ExecutionJournal` une fois son propre travail local publié, revalider les pins immédiatement avant tout envoi éventuel, tester le redémarrage après soumission ambiguë, puis organiser une première transaction à montant plafonné seulement après autorisation financière spécifique. **Ne jamais transformer une simulation en feu vert automatique.**
