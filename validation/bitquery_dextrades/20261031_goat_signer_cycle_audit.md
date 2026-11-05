# Bitquery GOAT / WSOL — audit indépendant du 31 octobre 2026

## Source et périmètre
- Source fournie par l'utilisateur : export de `Solana.DEXTrades`, JSON, SHA256 original `c95b85bf208b61441ac1258243111f497c62b306181f5ef7d7d067b1367078a0`.
- Token : `5AWBTmZzYZ3twtKQLe1eziWw9yMcUyUiR6iRnCpXPv7f` (symbole non certifié « GOAT »).
- Fenêtre **2026-10-31 19:41:08—19:46:53 UTC**, **345 secondes**, **un seul token**. **97 lignes**, **82 signatures uniques**.
- **15 lignes de protocoles emboîtés** ne doivent pas être additionnées deux fois : Jupiter, DFlow, dex_solana_v3 vs jambe sous-jacente LaunchLab. Garder **une exécution par signature** pour cet extrait particulier.
- 77 exécutions WSOL réconciliées (49 achats GOAT, 28 ventes GOAT). Cinq achats routés USDC sont exclus du P&L en SOL.

## Rapprochement des opérations signées
- Rapprochement FIFO des quantités GOAT par `Transaction.Signer` ; contrôle strict de la chronologie et séparation SOL/USDC.
- **12 signataires dont tous les achats vus dans la fenêtre sont compensés par des ventes vues dans la fenêtre** : 17 achats + 18 ventes.
- Six soldes positifs, six négatifs. **Total des montants dépensés : 10,073918371 SOL** ; **montants reçus : 10,834086615 SOL** ; différence brute observée **+0,760168244 SOL** (7,5459 % des dépenses de ces cas clos), avant frais de réseau, pourboires, transferts et éventuelles entrées hors du corpus.
- **25 signataires avec inventaire GOAT encore ouvert à la fin du corpus** ; résultat terminal inconnu et exclusion de la statistique des cas clos. L'échantillon clos est fortement censuré / non représentatif.
- Signataire `AMDEmVocLtN5ji2gBY7BrmSHEyM5vt6TGszBbg4crMXg` : 34 193 904,632554 GOAT achetés pour 1,000000000 SOL au slot 463809741, quantité identique vendue pour 1,548041260 SOL au slot 463809800 ; **+0,548041260 SOL brut**.
- Signataire `DF9MXmawYzbqskNxL1wTSYRcG2Gv25pqvVxVKD4kvkM4` : 24 674 510,560755 GOAT achetés pour 0,999112000 SOL, revendus en totalité pour 1,199651061 SOL ; **+0,200539061 SOL brut**.

## Ce que cela ne prouve PAS
- Les `Transaction.Signer` ne suffisent pas à établir la propriété effective des token accounts ; vérifier les soldes pré/post et les transferts.
- Aucun calcul de frais réseau/priorité/échec ; la métrique ci-dessus n'est pas un P&L net.
- Un extrait de swaps tiers ne fournit pas les signaux horodatés du Master ni du moteur de référence, les quotes exactes au moment de leur décision, ni un prix d'exécution réalisable pour un ticket PAPER de 1 SOL.
- **0 cycle de rentabilité Master certifié, 0 créateur indépendant qualifié par cet audit, `master_minus_reference_net_pnl_sol = null`**. Aucune promotion LIVE.
- Ces 12 signataires opèrent sur le même token : ils ne sont pas 12 créateurs indépendants et ne fournissent aucune preuve statistique d'un avantage réplicable.
- Le taux de 7,5459 % ne doit en aucun cas être présenté comme la rentabilité de Rugger Bot.

## Requête suivante
`validation/bitquery_dextrades/20261031_goat_next_from_slot_463811349.graphql` : reprendre à slot **≥463811349** (chevauchement volontaire) pour suivre les positions ouvertes, dédupliquer les signatures au jointure et récupérer `Trade.Buy.Account.Owner` et `Trade.Sell.Account.Owner`.

Audit source et données détaillées conservés dans un ZIP de recherche livré dans la conversation ; pas de publication de l'export brut dans cette PR.
