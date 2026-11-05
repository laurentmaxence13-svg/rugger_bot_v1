# P3 — sources alternatives et niveau de preuve

28 octobre 2026. Recherche documentaire officielle et lecture du code existant
uniquement : aucun appel de marché, secret, portefeuille ou transaction.

## Décision recommandée

Ne pas compléter les timestamps/slots d’un devis Raydium avec un RPC voisin.
Conserver la qualification fournisseur actuelle. Un **modèle sur un état RPC**
est une alternative utile mais doit garder un résultat distinct :
`MODEL_SNAPSHOT_CONDITIONAL`, sans fill, sans admission automatique du cycle
fournisseur et sans inclusion dans le nombre de cycles économiques stricts.

Un résultat net indicatif nécessite soit les coûts indispensables documentés,
soit un scénario de coûts explicitement estimés. Dans ce dernier cas, afficher
« projection sous hypothèses », pas P&L net mesuré. Une absence de devis reste
une donnée manquante/refus ; ce n’est ni une vente ni une perte totale.

## Preuves temporelles disponibles

- [getMultipleAccounts](https://solana.com/docs/rpc/http/getmultipleaccounts)
  retourne une réponse `context.slot` et jusqu’à 100 comptes dans l’ordre demandé.
  Cela permet un graphe cohérent de comptes par bank, y compris plusieurs pools
  en une lecture bornée. `minContextSlot` fixe une borne minimale, pas un slot
  exact ni le slot d’un autre fournisseur. Conserver les adresses ordonnées,
  données, commitment, receipt/availability et empreintes.
- [getBlockTime](https://solana.com/docs/rpc/http/getblocktime) retourne une
  estimation de production du bloc tirée des votes pondérés par stake. C’est
  une heure de chaîne estimée pour ce slot, pas l’instant exact de changement
  de chaque compte, ni une horloge du moteur de devis. Null reste inconnu.
- `bot/p3/launchlab.py` possède déjà `analyze_snapshot` et
  `observed_sell_projection`. La projection après achat du même bank est
  explicitement contrefactuelle sans activité intermédiaire ; la lecture future
  observée ne contient pas notre achat. Ne pas confondre ces deux scénarios ni
  prétendre qu’un refus du bank sans cet achat prouve une invendabilité réelle.
  Conserver les contrôles d’identité, permissions, supply et vaults existants.

## Frais légitimement observables, mais comparabilité limitée

- [Fees](https://solana.com/docs/core/fees) : base par signature (5 000 lamports
  dans la documentation courante), priorité calculée avec **CU limit**, et non
  simplement CU consommées : ceil(CU price × CU limit / 1 000 000).
  Le nombre de signatures, la limite CU, les comptes et le chemin d’une transaction
  hypothétique restent à établir. Une formule documentaire n’est pas son coût observé.
- [getRecentPrioritizationFees](https://solana.com/docs/rpc/http/getrecentprioritizationfees)
  fournit des échantillons récents par slot, éventuellement filtrés par comptes
  verrouillés en écriture. Un zéro observé dans le cache n’impose pas un coût nul
  à notre scénario ; ni SLA d’inclusion ni frais complets.
- [getTransaction](https://solana.com/docs/rpc/http/gettransaction) donne une
  transaction confirmée, slot/blockTime et métadonnées. `meta.fee` d’un swap
  comparable est un coût observé de **cet autre swap**. Vérifier programmes,
  instruction, signatures, version, comptes et éventuels setup/close avant de
  l’utiliser comme estimation pour notre modèle. Les frais de création du token
  ne sont pas les frais d’achat/vente du token.
- [getMinimumBalanceForRentExemption](https://solana.com/docs/rpc/http/getminimumbalanceforrentexemption)
  donne le dépôt requis pour une taille de compte. Les [comptes Solana](https://solana.com/docs/core/accounts)
  gardent un minimum de stockage remboursable : séparer cash immobilisé,
  création de compte, remboursement et frais définitivement consommés.
  Sans wallet ni état de ses ATA, la nécessité de création est inconnue ;
  Token-2022 peut exiger une autre taille que 165 octets. Pas de zéro inventé.

Ne pas appeler build/getFeeForMessage/simulate/sign/send pour combler ces inconnues
pendant ce contrôle. Les coûts non connus restent null ; les estimations comparables
portent provenance et hypothèse. Les frais de courbe déjà inclus dans le montant
sortant ne sont pas soustraits une deuxième fois.

## Autre fournisseur étudié : Jupiter quote-only

[Swap API](https://developers.jup.ag/docs/swap/index) documente désormais
`GET /swap/v2/order` sans `taker` : quote seulement, `transaction=null`, sans
wallet ni clé, à 0,5 requête/seconde. Cela constitue une option légitime de lecture,
mais son activation exige un adaptateur/protocole et une analyse de conservation
propres ; aucun appel n’a été effectué ici.

La [référence order](https://developers.jup.ag/docs/api-reference/swap/order)
présente montants, route, frais et temps de réponse. Aucun context slot n’est
annoncé dans le schéma consulté ; `totalTime` est une durée de réponse et
`expireAt` une expiration RFQ, pas la date du bank. Le rent est décrit comme estimé,
et les frais sans taker peuvent manquer. Cette alternative peut comparer routes
et disponibilité sans garantir de résoudre la preuve temporelle ou les coûts.
Ne pas réétiqueter ses données comme Raydium, ni traiter ses champs absents comme zéro.

