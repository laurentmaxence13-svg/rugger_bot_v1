# Mandat principal 29/10/2026 — Rugger Bot V1 orienté exécution RÉELLE

## Décision du propriétaire : l'objectif final n'est pas PAPER ONLY

Cette directive remplace, pour le **développement à venir**, les formulations historiques `PAPER ONLY` du dépôt lorsqu'elles interdisaient **de concevoir** des composants de trading réel. Le système actuellement installé reste en simulation, **sans autorisation d'envoyer des transactions financières au moment de ce mandat**.

**Objectif final** : bot autonome Solana/Raydium LaunchLab capable de détecter, choisir, acheter, surveiller, vendre et réconcilier des positions **réelles**, avec une stratégie agressive, une latence maîtrisée, des protections anti-rug et un contrôle strict du capital. La robustesse d'un avantage net est une exigence de validation économique ; le résultat positif n'est jamais garanti ni inventé.

**Autonomie autorisée** : architecture, codage du routeur et du signataire, tests, sandbox/devnet, PR et publication sur branches dédiées, analyses de marché en lecture seule dans les quotas préenregistrés. **Aucune autorisation actuelle de financer un wallet, révéler une clé, envoyer un swap réel sur mainnet, dépenser, activer des ordres ou contourner les permissions.** La mise en route et les limites de fonds requièrent l'accord explicite du propriétaire.

## Architecture cible, non négociable

Séparer physiquement et logiquement :
1. **RESEARCH** : données brutes, contrôle temporel/identité, corpus A/B, calibration, aucun ordre.
2. **SHADOW** : même stratégie que l'environnement d'exécution, décisions réelles horodatées, transactions uniquement simulées; conservation des refus et coûts de marché.
3. **LIVE_PREPARED** : moteur de construction, simulation de transactions, signature isolée, routeur, contrôle des ordres, réconciliation de confirmations, redémarrage, arrêt d'urgence — prêts et contre-vérifiés; **aucune transaction envoyée**.
4. **LIVE_ARMED** puis **LIVE_ENABLED** : activation uniquement sur action explicite avec plafond de capital, wallet autorisé, RPC/cluster et durée de validité; deux protections indépendantes et journal d'audit. Le bot peut ensuite prendre des décisions et exécuter de manière autonome dans ces contraintes. Le simple démarrage, la présence d'une clé ou un paramètre d'environnement ne suffisent jamais à armer le réel.

Une commande de décision du Master ne donne **pas** un ordre implicite au routeur : le validateur d'admission recontrôle **au moment exact de l'envoi** état du scanner, origine du devis, route/programme, liquidité et quantité, frais totaux, slippage, reste à payer, capacité d'exit, limites journalières et portefeuille disponible.

## Chemin critique — ordre d'exécution

### L0 — Corriger et certifier P3-012

Source actuelle : PR #29, corrections de contre-revue PR #30. Revoir les fichiers locaux et distants sans écrasement, rectifier sens des réserves, fenêtres S0/S1, représentation numérique S2, historique `CreatePlatformConfig`, tests et reprise. Développer le vrai collecteur borné S0→S1→S2 qui manque; suite complète sur SHA exact; statut `VERIFIED` seulement avec preuve.

### L1 — Données économiques et validation de stratégie

Obtenir des observations prospectives avec provenance, stocks, transactions et coûts. Aucune promotion d'un devis sans horloge à P&L de marché. Comparer Master vs référence aux tailles **exactes** et même informations as-of, inclure les pertes et cas non liquidés. Chercher activement un edge net sur développement, figer puis tester sur holdout indépendant par créateur, stress coûts/délai. Une stratégie agressive ne signifie pas ignorer les preuves défavorables.

### L2 — Routeur d'exécution mainnet conforme

Implémenter dans un **module séparé** et testable :
- Adaptateur LaunchLab/Raydium dont programme, IDL et comptes sont explicitement épinglés et vérifiés contre le réseau cible. Construire les instructions compatibles achat, vente, WSOL et comptes associés ; ne pas supposer qu'une API de devis est une API d'exécution.
- Quote → route → simulation RPC → message → signature isolée → envoi → confirmation/expiration → vérification de balances et frais → clôture/réconciliation. Aucune étape fictive ou silencieuse.
- `min_out` et contraintes en unités atomiques, frais base/priority/compute/rent/échecs, slippage, impact de marché, disponibilité réelle et refus de route; prendre en compte Token-2022 et éventuelles migrations de courbe.
- Signataire fourni par une interface spécialisée (secret externalisé hors dépôt; matériel/HSM ou gestion de clés sécurisée si disponible); jamais logguer clé/seed, jamais livrer de secret à Codex ou aux tests.
- Protection contre duplication : ID décision stable, stockage durable pré-soumission, reprise après crash, signature unique, `already_submitted`, retries seulement après état de chaîne réconcilié. Contrôles de blockhash, timeouts, slots, finalité, transactions partiellement réussies ou annulées.
- Supervision et arrêt d'urgence : perte RPC/WS, dérive de l'horloge, données stale, dérive de frais, pool qui migre, invalidité de quote, risque anti-rug, perte réalisée journalière, dépenses maximales, transactions consécutivement échouées, ordres en vol.
- Capital engagé/réservé et SOL libre y compris frais; ne jamais engager plus de fonds que disponibles; respecter tailles et plafonds. **La première activation est toujours limitée à un montant explicitement autorisé par le propriétaire**, pas 10 SOL par défaut.

### L3 — Validation pré-réel technique

Test suite entière, couverture de refus/délais/réorgs/duplication, simulations de transactions (RPC `simulateTransaction`) en lecture, transactions simulées devnet seulement si autorisées, tests de bout en bout avec un signataire factice isolé, exercices de crash/reprise et rollback, trace des versions programme/IDL et build reproducible. Chaque mode utilise **le même moteur de décision et la même comptabilité**, avec adaptateurs de sortie clairement séparés.

**Livrable `LIVE_READY_TO_ARM`** seulement si tous les tests pertinents, protections, simulateurs, commandes d'arrêt d'urgence et métriques de flux sont prouvés. Ce statut **n'est pas** une preuve de P&L live, et ne donne aucun droit de dépenser.

### L4 — Activation réelle conditionnée à l'accord du propriétaire

Avant toute commande mainnet financière, demander l'autorisation explicite sur :
- wallet/cluster autorisé, capital maximal engagé et perte journalière maximum;
- limite par position, exposition simultanée, slippage/frais absolus, durée de l'armement;
- taille du premier test réel et règle de rollback/arrêt;
- conséquence : pertes financières possibles jusqu'au capital autorisé; aucune garantie de profit.

Après accord, commencer par une quantité minimale et observer de vraies confirmations achat/vente, rent/ATA, écarts quote/fill et réconciliation. Cela est nécessaire pour établir un statut `LIVE_EXECUTION_VERIFIED`, **distinct** de `LIVE_READY_TO_ARM`. Le bot peut ensuite agir automatiquement tant que son armement borné reste valide; ne pas multiplier les clés ni réémettre des ordres non réconciliés.

## Validation, communication et autonomie

L'objectif d'une session Codex est d'**exécuter et corriger**, pas de produire un bilan à chaque étape. Ne pas interrompre la session pour demander des consignes déjà autorisées. N'annoncer **terminé** qu'avec tests + preuve + commit + revue distante. Poursuivre les autres tâches indépendantes lorsqu'un fournisseur est indisponible.

**Une session Codex ne se poursuit pas après l'épuisement du quota ni sans invocation active.** Avant interruption, enregistrer état, erreurs et commandes de reprise exacts. Ne jamais inventer un travail effectué en arrière-plan. Limiter les messages intermédiaires, mais ne jamais masquer un obstacle exigeant accès, dépense, risque non accepté ou données externes. La livraison finale doit expliciter `LIVE_READY_TO_ARM`, `LIVE_EXECUTION_VERIFIED` et `ECONOMIC_EDGE_VALIDATED` séparément.

La politique de stratégie peut rester **agressive** sur la détection et la prise de risque **dans les plafonds autorisés** ; pas d'augmentation automatique et illimitée des fonds, pas de contournement des critères de risque pour obtenir plus d'entrées.

**Référence :** ce document prévaut sur les interdictions historiques de *développement* de modules réels dans le dépôt, mais **pas** sur les règles de confidentialité, de budget, de validation et d'autorisation d'opérations financières.

