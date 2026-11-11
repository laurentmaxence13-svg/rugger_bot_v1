# Politique Token-2022 — v1 (projet, à auditer par RUGGER 02)

RUGGER 01, 2026-11-11. Directive du propriétaire « GO COMPATIBILITÉ TOKEN-2022 » (option (a) de R02) :
prise en charge, hors ligne, des Token-2022 sans extension dangereuse, sans modifier ni activer la
chaîne réelle validée.

## 1. Règle (liste d'autorisation stricte, refus par défaut)
Un jeton lancé est **Token-2022 autorisé** si et seulement si :
1. son compte de mint appartient au programme Token-2022 et le lecteur gelé `bot.p3.token2022.decode_mint`
   l'accepte : extensions de mint **uniquement** `MetadataPointer` (18) et `TokenMetadata` (19), sans
   doublon, métadonnées structurellement valides, aucune queue non vide ;
2. **aucune autorité de frappe et aucune autorité de gel** (règle gelée de `launchlab.analyze_snapshot` :
   `base_mint_authority_present`, `freeze_authority_present`) ;
3. tout le reste du contrôle gelé du pool passe (identités, PDA, coffres, offre).
Tout autre type, tout type inconnu (≥ 29), tout compte illisible : **refusé**.
Côté de NOS comptes : seule `ImmutableOwner` (7) est acceptée, posée d'office par le programme des
comptes associés sur tout compte Token-2022 (taille 170 octets, loyer 2 074 080 lamports au lieu de
2 039 280).

Cette règle n'élargit pas le code gelé : c'est exactement le sous-ensemble que son lecteur accepte
déjà ; le refus actuel vient seulement du constructeur d'ordres (`route.py:126`, `route.py:143`).

## 2. Les mécanismes demandés par le propriétaire
| Mécanisme | Extension ou champ | Effet sur nos achats / ventes | Décision |
|---|---|---|---|
| Gel d'un compte, reprise (dégel) | `freeze_authority` du mint | le titulaire de l'autorité peut geler notre compte : vente impossible | refus si présente (SPL et Token-2022) |
| État par défaut gelé | `DefaultAccountState` (6) | notre compte naîtrait gelé | refus |
| Pause globale | `Pausable` (26) | tous les transferts arrêtés | refus |
| Frais de transfert, et leur modification | `TransferFeeConfig` (1) | frais prélevé à l'achat et à la vente ; l'autorité peut le relever (effet après deux époques, jusqu'au maximum configuré) | refus |
| Délégué permanent | `PermanentDelegate` (12) | un tiers peut déplacer ou brûler nos jetons | refus |
| Crochet de transfert | `TransferHook` (14) | un programme arbitraire peut faire échouer la vente | refus |
| Jeton non transférable | `NonTransferable` (9) | aucune vente possible | refus |
| Montants confidentiels | 4, 5, 16, 17, 24 | soldes hors du montant public | refus |
| Montant affiché ≠ montant brut | `InterestBearingConfig` (10), `ScaledUiAmount` (25) | risque d'erreur d'unité | refus |
| Nouvelle frappe | `mint_authority` | dilution | refus si présente |

## 3. Table complète (source officielle `interface/src/extension/mod.rs`, sha256 d273a876…, identique à l'épingle gelée)
| Valeur | Extension | Porte sur | Décision | Raison |
|---|---|---|---|---|
| 0 | Uninitialized | - | IGNORE | padding marker, carries nothing |
| 1 | TransferFeeConfig | mint | REFUSE | a fee is withheld on every transfer, including our buy and our sale; its authority can raise it up to the configured maximum after two epochs |
| 2 | TransferFeeAmount | account | REFUSE | exists only with TransferFeeConfig |
| 3 | MintCloseAuthority | mint | REFUSE | not needed by any launch seen; refused until shown harmless on data |
| 4 | ConfidentialTransferMint | mint | REFUSE | balances may move outside the public amount |
| 5 | ConfidentialTransferAccount | account | REFUSE | confidential balances |
| 6 | DefaultAccountState | mint | REFUSE | new accounts may start frozen: a buy would land in a frozen account |
| 7 | ImmutableOwner | account | ALLOW_ON_OUR_ACCOUNT | added by the associated token account program on every Token-2022 ATA; it only forbids changing the owner |
| 8 | MemoTransfer | account | REFUSE | requires a memo on incoming transfers; never on our accounts |
| 9 | NonTransferable | mint | REFUSE | the token cannot be transferred: no sale is possible |
| 10 | InterestBearingConfig | mint | REFUSE | display amount differs from the raw amount |
| 11 | CpiGuard | account | REFUSE | restricts calls through programs; never on our accounts |
| 12 | PermanentDelegate | mint | REFUSE | a third party can transfer or burn our tokens at any time |
| 13 | NonTransferableAccount | account | REFUSE | exists only with NonTransferable |
| 14 | TransferHook | mint | REFUSE | an arbitrary program runs on every transfer and can make the sale fail |
| 15 | TransferHookAccount | account | REFUSE | exists only with TransferHook |
| 16 | ConfidentialTransferFeeConfig | mint | REFUSE | confidential fees |
| 17 | ConfidentialTransferFeeAmount | account | REFUSE | confidential fees |
| 18 | MetadataPointer | mint | ALLOW | points to metadata; no effect on amounts, transfers or holders |
| 19 | TokenMetadata | mint | ALLOW | name, symbol, URI; no effect on amounts, transfers or holders |
| 20 | GroupPointer | mint | REFUSE | neutral by design but not accepted by the frozen reader; not seen yet |
| 21 | TokenGroup | mint | REFUSE | same |
| 22 | GroupMemberPointer | mint | REFUSE | same |
| 23 | TokenGroupMember | mint | REFUSE | same |
| 24 | ConfidentialMintBurn | mint | REFUSE | supply may change confidentially |
| 25 | ScaledUiAmount | mint | REFUSE | display amount scaled by an authority-set multiplier |
| 26 | Pausable | mint | REFUSE | an authority can pause every transfer: the sale would be blocked |
| 27 | PausableAccount | account | REFUSE | exists only with Pausable |
| 28 | PermissionedBurn | mint | REFUSE | burn controlled by an authority; not analysed |

## 4. Ce qui reste à établir
- Que les mints observés ne peuvent pas recevoir d'extension après leur initialisation (lecture de la
  source à faire auditer par R02) ; sinon l'état du mint doit être relu juste avant chaque ordre.
- Frais et contraintes réellement applicables aux jetons autorisés : aucun frais de transfert par
  construction ; coûts propres = loyer du compte associé (2 074 080 lamports) et unités de calcul.
- La chaîne d'exécution Token-2022 (constructeur, comptes associés, nettoyage) : travail hors ligne
  sur une branche dédiée, jamais branchée sur la chaîne réelle sans audit et GO.

## 5. Outils
- `t22pol.census` : classe de chaque jeton d'un ensemble de pools, raisons de refus, contrôle croisé
  avec le lecteur gelé (`--frozen-check`). Descriptif.
- `t22pol.trace` : même recensement lu dans la transaction de CRÉATION du pool (les archives P0 ne
  contiennent aucun compte de mint) : programme du jeton, extensions initialisées avant le mint, option
  d'autorité de gel, révocation de l'autorité de frappe, taux de frais de transfert. Limite : l'état à
  la création seulement ; pas de contrôle croisé avec le lecteur gelé.
- `v3lab.scenarios` : deux vues des mêmes résultats enregistrés — `executable_now` (jetons SPL) et
  `experimental` (+ Token-2022 autorisés) — avec le loyer de notre compte compté comme coût.

48 tests t22pol (la table concorde avec le lecteur gelé sur les 28 types ; 14 tests de la lecture de trace) ; 7 tests v3lab (scenarios + tables).
