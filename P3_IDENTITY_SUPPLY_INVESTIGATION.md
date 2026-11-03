# P3 — investigation historique des identités et supplies

Date : 27 octobre 2026 (Europe/Paris). Lecture des archives Git uniquement ;
aucune requête RPC ou cotation de marché lancée pour cette investigation.

## Preuves nouvelles extraites des archives

Bundle : `evidence/p3/launchlab_002`, ancre
`8932cf725770daba7a9deddd12d0e29805c1ed1eae22bc57d18fb1d001eb8790`.

- Candidat BNbNt…iTFm, événement 164, transaction
  `3umbNJxM9hFM6GAebVd6pj86q7Hj5ete5ygjVE6BcPpr73XWQQPQ5Ron5Nv9tw94XJdmoBBirs1d8fNFwVU4mADa`,
  slot **461979373** : succès, `mintTo` exactement **1000000000000000** unités
  atomiques vers le vault base, puis `setAuthority(mintTokens, newAuthority=null)`.
  Aucun burn dans cette transaction de création.
- Snapshots cohérents des slots **461982938** et **461983014** : supply mint
  **999020457494200**, supply pool **1000000000000000** ; différence
  **−979542505800**. Décimales base 6 ; aucune autorité mint active.
- Les deux seules transactions brutes du bundle v2 sont les créations des deux
  candidats. Les corps des transactions intermédiaires nécessaires à une
  réconciliation de burns ne sont pas présents. Les autres bundles ont quatre
  transactions brutes supplémentaires, aucune burn parsée du candidat.
- Les pages de création historiques recherchent le **pool**. Un burn autonome
  signé par un détenteur peut ne référencer que le mint et le compte token ;
  rechercher seulement les signatures du pool ne suffit donc pas.

## Plateforme du premier candidat

- Plateforme observée `4E876qZTE9FJMrBzgVtBrSrzz2TLivB5Y5QXPjB4gZL7` ; nom public
  décodé du compte : `StonkFun`. Aucun recours à ce nom comme preuve d'admin.
- Aucun match PDA en testant les candidats issus des champs publiés fee wallet,
  NFT wallet, vesting wallet, cp creator, transfer fee authority et les 22 comptes
  de la transaction de création du token.
- Aucun match après examen des **542 adresses publiques distinctes présentes
  dans les valeurs JSON des cinq archives** comme candidats seed. Cela exclut
  ce corpus fini ; ce n'est pas une preuve que l'administrateur n'existe pas.
- La recherche publique de l'adresse dans les dépôts de l'organisation Raydium
  a renvoyé zéro correspondance. Aucune seed historique n'est obtenue.

## Sources officielles consultées

- SDK Raydium, commit `f8549145afe75d4c486e30c43331c2c4da32b1eb`,
  `src/raydium/launchpad/pda.ts`, lignes 54–55 : PDA plateforme dérivée de
  `platform_config` et `platformAdminWallet`.
  https://github.com/raydium-io/raydium-sdk-V2/blob/f8549145afe75d4c486e30c43331c2c4da32b1eb/src/raydium/launchpad/pda.ts
- IDL officiel, commit `e7e0c96fe77bcf6a020b84a44c47a722aac8e359`,
  `raydium_launchpad/raydium_launchpad.json`, types `PlatformConfig` et `PoolState` :
  aucune adresse admin originale stockée dans le compte plateforme ; fee wallet
  distinct du rôle admin. Champ pool `supply` décrit comme supply base du pool.
  https://github.com/raydium-io/raydium-idl/blob/e7e0c96fe77bcf6a020b84a44c47a722aac8e359/raydium_launchpad/raydium_launchpad.json

## Conclusion et expérience suivante

Aucun défaut de parsing ou de formule démontré. Aucune protection modifiée.
Plateforme premier candidat : UNKNOWN. Supply second : divergence observée,
origine non réconciliée. Un burn intermédiaire est une hypothèse, pas un résultat.
Une lecture historique bornée des signatures du **mint** puis des transactions
correspondantes doit établir un montant de burn exact avant toute levée du guard.
La recherche historique de création de plateforme doit identifier une seed
candidate puis vérifier son hash PDA canonique ; le nom et le fee wallet ne
suffisent pas.
