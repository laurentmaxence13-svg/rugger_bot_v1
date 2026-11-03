# CODEX — Mandat de reprise, intégration CPMM et essais mainnet contrôlés

**Date de référence : 29 octobre 2026.** À lire **avant de toucher au workspace Cloud Codex**. Ce document est un mandat d'intégration, pas un certificat d'activation ni une autorisation de trading.

## 0. État vérifié / source de vérité

- Dépôt : `laurentmaxence13-svg/rugger_bot_v1`.
- PR **#34** : `feat/live-real-preflight-20261029`, head publié **`fec74b04d29b7850c2f1bff87525fca707e0ec6f`** ; ouverte, draft, **aucun merge**.
- PR **#35** : `review/live-program-pinning-20261029`, basée sur PR #34, head **AVANT ce présent document** : `a5b854ce41c8a93fde20f665f1815fec900dcadf`. Le SHA **final** après ce document doit être relu depuis GitHub, jamais deviné.
- CI PR35 sur `a5b854c` : [suite isolée 40953415185](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/40953415185) **2801 passed, 242 subtests passed, 1 skipped** ; [rejeu ProgramData 40953415293](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/40953415293) SUCCESS ; [CLI hors réseau 40953415303](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/40953415303) SUCCESS. **Ces chiffres ne certifient pas les changements locaux Codex ni le présent futur commit.**
- Dans la dernière session Cloud Codex, l'utilisateur a vu **20 fichiers modifiés / +2451 -1** avant suspension par quota. **Les modifications locales ne sont pas visibles par cette assistance via GitHub**. Certaines peuvent être des fichiers importés de PR34, et non 20 nouveaux changements ; vérifier l'écart réel avec `fec74b0`.
- `LIVE_READY_TO_ARM=false`, `LIVE_EXECUTION_VERIFIED=false`, `ECONOMIC_EDGE_VALIDATED=false`. Aucune transaction mainnet financière autorisée. Les preuves P3-012 restent historiques et **ne doivent pas être relancées**.

## 1. Priorité 0 — Sauver le travail local Codex sans aucun écrasement

**Même workspace Cloud Codex qu'avant le quota**, pas une nouvelle réinstallation.

1. Inspecter l'état **avant de changer de branche** :

```bash
git status --porcelain=v1
git branch --show-current
git rev-parse HEAD
git remote -v
git diff --stat
git diff --cached --stat
git diff --stat fec74b04d29b7850c2f1bff87525fca707e0ec6f
git ls-files --others --exclude-standard
```

2. Conserver, sous un chemin de sauvegarde privé, `git diff --binary`, `git diff --cached --binary`, `git status --porcelain=v1`, les fichiers non suivis pertinents et les logs de `/workspace/work/cpmm-integration-20261029/`. **Ne jamais publier** des `.env`, clés privées, tokens, seeds, wallets réels, DB utilisateur ou captures de compte/activité sensibles.
3. Créer **une branche de récupération dédiée depuis l'état actuel** sans checkout/reset destructif. Si le HEAD n'est pas descendant de `fec74b0`, arrêter et reconstruire le graphe des commits ; ne pas supposer son origine. Ne pas effacer le worktree.
4. Examiner le diff, staged files explicites (jamais `git add -A` sans revue), commit/push dans une branche **nouvelle**, puis ouvrir une **PR draft vers `feat/live-real-preflight-20261029`**. Relire la branche distante et lister les fichiers réellement publiés.
5. **Tant que la sauvegarde GitHub n'est pas confirmée, ne pas merger/cherry-pick PR35 ni réécrire la branche Codex.**

## 2. Priorité 1 — Fusion contrôlée de la PR #35 après sauvegarde

Importer le diff **actuel** de [PR #35](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/35) dans la branche d'intégration Codex, **pas directement sur main**, pas en écrasant une autre branche. Les principaux risques de conflits sont :

- `bot/live/rpc.py` et `bot/live/unsigned_preflight.py` : préserver le budget RPC, le suivi des frais `getFeeForMessage` avec `minContextSlot`, le slot causal, les traces sans données privées, l'enveloppe de simulation exacte et les garde-fous de submission.
- `bot/live/cpmm_exit.py` : corriger manuellement si le constructeur de Codex diverge du constructeur testé PR35. Ne pas conserver deux chemins concurrents de sortie.
- `bot/live/engine.py`, `journal.py`, `runtime.py` : faire primer les modifications **réellement inspectées** de Codex ; PR35 n'y apporte normalement pas de modifications.

**Modules de PR35 à reprendre** : `program_pin`, `solana_signatures`, `migration_rpc_json`, `migration_rpc_receipt`, `cpmm_bank`, `cpmm_readiness`, `readonly_plan`, `readonly_report`, `readonly_diagnostics`, `readonly_cli`, `tools/run_readonly_cpmm_preflight.py`, `validation/live_readonly/README.md` et leurs tests.

Après résolution des conflits, exécuter les tests sur le **SHA intégré** (ne pas recycler les résultats d'un ancêtre) :

```bash
python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Exiger CI GitHub sur le même SHA, avec dépôt isolé, aucune `.env`, base utilisateur, secret ou wallet financé.

## 3. Priorité 2 — Vrai moteur comptable LaunchLab → CPMM

**Défaut structurel prouvé dans le checkpoint PR34** :

- `ExecutionJournal.positions` a un inventaire `(mint, original_launchlab_pool)`.
- `ExecutionJournal.reserve` cherche actuellement en SELL `(mint, order.pool)`.
- `ExecutionJournal.finalize` modifie également `(mint, order.pool)`.
- `evaluate_admission` cherche un `InventoryPosition` par `(mint, request.pool)`.
- Une vente après graduation vise `migrated_cpmm_pool != original_launchlab_pool`. Le token détenu reste le **même mint** ; la destination de vente n'est pas un deuxième inventaire.

**Invariants obligatoires**, tous couverts par tests SQLite transactionnels :

1. Créer un lien immuable `(mint, original_pool, cpmm_pool, migration_signature, migration_slot)` lié à une transaction finalisée signée et vérifiée ; refuser toute substitution de mint, pair, wallet, pool ou source.
2. Le registre de propriété reste **une position source unique** `(mint, original_pool)` ; **le pool de sortie est une route**, non une position nouvelle. Conserver le coût d'achat, les loyers, frais et P&L d'origine.
3. Lors de `reserve`, repérer **atomiquement** la source propriétaire, autoriser la vente CPMM uniquement si migration vérifiée, et compter toutes les réservations `ACTIVE` par **mint propriétaire**, quel que soit le pool de sortie. Refuser double SELL LaunchLab + CPMM et deux sorties CPMM simultanées sur le même token.
4. Les états `PREPARED → SIMULATED → RESERVED → SIGNED → SUBMITTING → SUBMITTED/UNCERTAIN → RECONCILED` doivent conserver même `decision_id`, même message signé, même stock et même somme réservée, même après crash.
5. Avant signature, vérifier pin ELF/ProgramData **actuel** de tous les programmes exécutés, admissibilité de pool, quote, banque source, prix d'exécution, frais, slippage, coût de sortie, rent et kill switch. Une simulation unsigned ne fournit **aucun droit d'armement**.
6. Aucun second `sendTransaction` pour une signature/décision incertaine. `SUBMITTING` enregistré **avant** l'unique envoi ; après crash/timeout, rechercher l'historique et conserver blocage en absence de certitude.
7. Après vente CPMM, réconcilier **signature, transaction, slot finalisé, programme, message exact, mint, quantité vendue, compte ATA, WSOL temporaire créé/fermé, native SOL reçus, rent récupéré, frais**, et prix net avant toute mise à jour de stock ou P&L. Aucun P&L synthétique basé seulement sur une quote.
8. En cas d'erreur de transaction finale, débiter **uniquement les frais réellement consommés**, ne pas détruire l'inventaire, et conserver l'état d'audit.
9. Le mécanisme de migration doit survivre à réouverture SQLite, rollback transactionnel, replay identique, tentative de double décision, et absence d'information (fail-closed).
10. Le journal d'audit doit détecter modification des anciennes lignes, altération du coût, incohérence de réservations ou sortie fictive ; `verify_audit()` avant/après chaque scénario.

**Ne pas faire** : inventer une deuxième position, mettre à jour les positions sans transaction, transférer la quantité entre pools simplement parce qu'une migration a été observée, modifier `PROGRAM` globalement en CPMM, ou permettre `Mode.LIVE_ENABLED` sans enveloppe de programme explicitement autorisée.

## 4. Priorité 3 — Tests adversariaux du moteur réel

Définir des fixtures **déterministes**, comprenant au minimum :

- BUY LaunchLab finalisé avec les chiffres ledger réels ; migration plus tardive, preuve Ed25519 exacte, bonne cible CPMM ; SELL complet et partiel.
- Réservations concurrentes (`SELL` source + `SELL` migré, deux décisions CPMM) ; état observé identique avant/après refus.
- Wallet sans balance suffisante SOL, mint erroné, mauvaise token-program authority, faux pool, gel ou Token-2022 non supporté, slippage, blockhash expiré, changement de binaire ProgramData ou autorité upgrade.
- RPC `null`, HTTP 429, timeout pendant signature, juste après `SUBMITTING`, pendant submission, après finalisation avant commit SQLite, reorg et redémarrage.
- Vérification des changements ATA/WSOL/natif et absence de rent résiduelle à la clôture, frais actualisés et P&L calculés sur mouvements observés.
- Aucune vraie signature de wallet, fonds, `sendTransaction` mainnet, base utilisateur ou secret dans CI. Signatures Ed25519 uniquement avec clé **publique de test déterministe, non financée**.

## 5. Priorité 4 — Une vraie simulation mainnet, sans argent

Après intégration, utiliser `validation/live_readonly/README.md` et le lanceur `tools/run_readonly_cpmm_preflight.py` sur **une migration réelle qualifiée et des comptes publics réels**, avec tous les pins ProgramData/ELF/upgrade **approuvés indépendamment**. Le gabarit `mainnet_plan_template.json` est volontairement non exécutable. Il faut une position publique disposant réellement du token pour un SELL ; sinon enregistrer `REFUSED`, pas un faux succès.

**Périmètre** : max 18 appels RPC, pas de retry, max 60 s, source de banque fraîche, `getBlockTime`, prix/frais `getFeeForMessage` causal, `simulateTransaction(sigVerify=false)`, rapport privé 0600. Aucune clé, achat, signature ou `sendTransaction`. Conserver SHA du plan, RPC, résultats, logs et les erreurs ; **ne pas publier les données de wallets personnels** sans inspection.

Ne pas relancer P3-012 ni changer ses constats d'origine : 12 requêtes, 25 states, 159 events, zéro cycle économique strict qualifié, hypothèses de prix aller-retour négatives aux deux tailles observées. Ne pas baptiser `ECONOMIC_EDGE_VALIDATED` avec des tests logiciels.

## 6. Priorité 5 — Première transaction financière : uniquement après une nouvelle autorisation humaine

C'est une étape ultérieure, séparée et **NON AUTORISÉE par ce mandat**. Une fois le logiciel validé, demander l'accord explicite sur wallet isolé, budget maximal, achat minimum, frais, slippage, perte quotidienne, plafond de positions, programme autorisé, périmètre et kill switch. Ne jamais choisir le montant à la place du propriétaire, n'utiliser aucun wallet principal et ne pas activer par défaut.

L'essai réel initial devra être un seul cycle observé, montant minimal autorisé, avec preuve de confirmation et réconciliation indépendante ; ne pas extrapoler une rentabilité ni promettre un résultat positif.

## 7. Définition de « terminé »

**Une livraison est complète uniquement si** :

- Travail local précédent récupéré, sauvegardé, publié en branche, aucune perte.
- PR35 intégrée de façon contrôlée, conflits résolus et check suite totale vert sur le SHA **final**, avec logs/CI attachés.
- Un seul ledger pour un mint migré, réservations atomiques, entrée/sortie idempotente, tests de crash/restart/double send/double sell validés.
- Cotation et frais réels connus, preuve de migration + programme adéquats, exit checks et santé scanner/master, historique de message lié à une preuve.
- Au moins une preuve valide de simulation mainnet non signée sur un scénario admissible, ou refus justifié avec limites précises (ne pas inventer de disponibilité).
- Revue de sécurité contradictoire : si un invariant échoue, `LIVE_READY_TO_ARM=false`.
- `ECONOMIC_EDGE_VALIDATED` évalué **séparément** avec observations représentatives, coûts, net P&L et échantillon hors entraînement.

**Rapport Codex attendu :** liens GitHub PR/commits, résultats CI sourcés au SHA, fichier par fichier modifié, invariants réussis/refusés, captures RPC privées non exposées, dépenses réelles = 0, état des trois indicateurs `LIVE_READY_TO_ARM`, `LIVE_EXECUTION_VERIFIED`, `ECONOMIC_EDGE_VALIDATED`, et précisément le prochain verrou non résolu.

**Consigne d'autonomie :** développer/corriger/tester tant que c'est possible, ne pas solliciter d'arbitrages sur des détails d'implémentation ; en revanche, ne jamais franchir les barrières de fonds/signature/merge ou masquer un échec pour satisfaire l'objectif « full success ». Une validation positive n'a de valeur que si elle est démontrée.
