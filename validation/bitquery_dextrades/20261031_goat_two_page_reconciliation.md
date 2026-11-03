# Rugger Bot — GOAT, audit consolidé des deux exports Bitquery (31/10/2026)

**Verdict : transactions de tiers rentables observées, rentabilité Master Trader non démontrée.**

## Source
- 2026-10-31, 19:41:08–19:54:06 UTC, slots 463809741–463813363.
- Token `5AWBTmZzYZ3twtKQLe1eziWw9yMcUyUiR6iRnCpXPv7f` ; pool `EwZxoy5QpQBxo13AHp9fvh11f49CanyFJXXmpSjVtpbP`.
- Export #1 : **97 lignes**, SHA-256 `c95b85bf208b61441ac1258243111f497c62b306181f5ef7d7d067b1367078a0`.
- Export #2 : **45 lignes**, SHA-256 `466e7f7a1ca2c64bc1d9422d1b69898b2f88bf4d8374cfc36d07fbf8f6a85c69`.
- Total **142 lignes**, **121 signatures uniques**, **21 doublons de pages/routeurs**, dont **2 signatures de chevauchement entre les pages**.

## Marché observé
- **76 achats GOAT/WSOL**, **39 ventes GOAT/WSOL**, **6 exécutions en USDC exclues des comptes SOL**.
- Sur les signataires avec inventaire GOAT acheté/revendu entièrement dans l'extrait : **18 signataires**, **9 positifs/9 négatifs**, **19,203461244 SOL dépensés**, **21,869414761 SOL récupérés**, donc **+2,665953517 SOL brut**, soit **+13,8827 % sur ces seuls cas soldés** (fort biais de sélection).
- **32 signataires avec inventaire encore ouvert** ; coût historique de leurs positions non liquidées **33,59864795 SOL** ; résultat terminal inconnu et non imputé.
- Sur 121 signatures, 39 évènements ont un propriétaire de compte GOAT identique au signataire, 1 propriétaire différent (route USDC) et **81 sans propriétaire renseigné**. **Seulement 3 des 18 cas soldés ont des propriétaires token vérifiés sur la totalité des transactions observées**.
- Précision FIFO : +1,410496214 SOL brut pour la transaction signée `A97aQUCpjPhaKzUCAQTQ7oJzNAScmK16xfVHC1gi4Mdj` (31 941 554,433492 GOAT, 2 SOL à l'achat, 3,410496214 SOL à la vente), avant les coûts non observés.
- Entre les deux exports, **7 nouveaux signataires entièrement soldés**, **11 des 12 signataires précédemment soldés sont restés soldés**, **1 a rouvert une position**. Ne pas additionner naïvement les deux profits publiés : le sous-ensemble de signataires soldés change.

## Risques d'interprétation
- Reconstructions par signataire : la première page ne fournit pas les propriétaires des comptes token. Les flux du signataire ne prouvent pas tous la propriété économique réelle.
- Les coûts supplémentaires (priorité, réseau, pourboires, transferts et échecs) ne sont pas entièrement observés.
- Les positions ouvertes **ne sont ni des gains nuls ni des pertes nulles**. Un ratio calculé seulement sur les gagnants/perdants soldés n'est pas un rendement de cohorte.
- Un seul token, pas 50 créateurs indépendants, pas d'achats PAPER exécutés du Master, pas de décision horodatée Master/référence ni de liquidation exacte.

**Master PAPER vérifié : 0 cycles ; P&L net Master : null ; avantage net Master/référence : null ; LIVE : NON.**

## Prochaine collecte
Repartir du slot **463813363 inclus** (chevauchement voulu) pour poursuivre les inventaires non soldés, en demandant `Account.Owner`. Mais l'effort principal doit se déplacer vers **la sélection de nouvelles créations indépendantes et le gel prospectif des décisions Master/référence avant les résultats**, sinon des pages supplémentaires d'un seul token ne prouveront pas l'edge.

Les exports JSON, le script à précision décimale, les CSV et les 9 tests de réconciliation sont conservés dans l'archive ZIP de la conversation, non inclus dans cette PR.
