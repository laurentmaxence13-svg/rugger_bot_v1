# Continuation après PR #22 — résultats vérifiés

27 octobre 2026, Europe/Paris. Aucun travail de récupération de conversation répété.
Orientation agressive et paramètres actifs conservés ; uniquement PAPER.

## Avancée sur les faits économiques

Le contrôle historique 006, préenregistré dans GitHub avant appel, visait les
21 corps manquants et l'autre transaction au slot de création. Dix nouveaux corps
ont été conservés ; le onzième appel a reçu HTTP 429 après 6,216 secondes.
Arrêt immédiat, sans retry ni bascule. Aucun appel marché après cette limitation.

Trois burns désormais prouvés totalisent **513119481705** unités atomiques ;
le résiduel passe de **950156230625** à **466423024095**. L'autre transaction au
slot de création est conservée et son ordre source est postérieur à la création.
Les 23 bilans entiers des transactions conservées concordent ; il manque encore
12 corps parmi les 35 connus. La page RPC n'est pas une couverture indépendante
et le garde supply n'est pas levé. Voir P3_MINT_HISTORY_006_RESULTS.md.

## Changements fonctionnels et comparaisons

| Limite avant | Capacité nouvelle prouvée | Validation et limite |
| --- | --- | --- |
| HTTP 429 conservé sans délai de reprise | Retry-After entier ou date HTTP relatif au Date serveur, état inconnu explicite si absent/invalide | 15 régressions causales ; aucune reprise automatique, aucun délai ajouté rétroactivement au reçu réel |
| Calcul comptable recevant acquis/vendu comme entiers libres | Bridge reliant corps vérifiés des devis, inventaire attendu/minimal, taille demandée/réelle, chronologie, provenance et frais | 13 tests ; quantité ajustée ou frais inconnus ne peuvent certifier une clôture |
| Collecte de banques vides et vente du produit d'un achat jamais exécuté | Protocole actif 007 : batch 20 comptes, jusqu'à trois graphes, stock réel positif, vente observée vérifiée, q fixe indépendant du buy1SOL | 8 tests ; état suivi invalide, stock réduit, même slot ou source429 refusés ; pas de live après quota |

Cas causal corrigé pendant la revue : la projection après achat hypothétique
peut réussir avec real_b=1, alors que la vente contre la banque observée échoue.
Le nouveau protocole contrôle donc `observed_sell_projection` avant chaque devis
et au suivi, sans confondre ces deux mécanismes. Le suivi garde q et n'adapte pas
la quantité pour obtenir une réponse positive.

## Application aux preuves existantes

`tools/qualify_p3_quote_pairs.py` relit sept couples archivés après vérification
des ancres. Cinq manquent de corps fournisseur ; deux ont des corps mais aucune
heure source qualifiable. **Zéro clôture complète vérifiée, P&L inconnu.** Ce sont
des diagnostics d'admission, pas sept opérations réalisées ou un backtest.
Aucune mise à l'échelle linéaire d'un devis vers une autre quantité n'est faite.

L'inspiration historique premier signal/confirmation est maintenant traduite
en instrumentation exécutable dans `active_exit_campaign.py` : même quantité
préfixée, banques à slots croissants, références 1SOL conservées aux deux horizons,
refus et changements d'état tracés. Le protocole est prêt mais non exécuté,
avec la preuve du quota fournisseur comme blocage effectif.

La rentabilité, l'identité initiale de plateforme et les coûts d'exécution complets
restent non validés. Aucun TP/SL, score, plafond de risque ou capital n'a changé.
Aucune amélioration de rendement réel n'est revendiquée sans données suffisantes.
